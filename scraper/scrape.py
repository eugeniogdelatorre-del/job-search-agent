#!/usr/bin/env python3
"""
Job Search Scraper v2.1 - Staggered Career Page Scanner (dual-write)

Changes vs v2.0:
  - Drops X/Twitter feed sources at group-load time (they are hiring signals,
    not job listings — see DECISIONS_LOG.md).
  - Applies shared cleanup from jobs_cleanup.py: junk/sidebar filter,
    WWR-style aggregator title unmasher.
  - Dual-writes: still writes public/data/jobs.json AS THE FALLBACK PATH,
    also upserts cleaned rows into the Supabase `jobs` table (fail-soft —
    Supabase errors never break the jobs.json write).
  - Logs per-source health to Supabase `sources_health` table.

Usage:
  python scrape.py --group 1        # Scrape group 1 only
  python scrape.py --group all      # Scrape every group
  python scrape.py --group 1 --dry  # Don't write anywhere
"""

import json
import os
import sys
import re
import hashlib
import argparse
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# Allow both "python scraper/scrape.py" (from repo root) and
# "python -m scraper.scrape" invocation styles.
if __package__ in (None, ""):
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

# Local imports (shared with migrate_to_supabase.py)
from scraper import jobs_cleanup as cleanup
from scraper import supabase_sink as sink


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
SOURCES_FILE = SCRIPT_DIR / "career_sources.json"
CONFIG_FILE = PROJECT_ROOT / "config.json"
OUTPUT_FILE = PROJECT_ROOT / "public" / "data" / "jobs.json"
CACHE_DIR = SCRIPT_DIR / ".cache"

REQUEST_TIMEOUT = 15  # seconds per request
DELAY_BETWEEN_REQUESTS = 2  # seconds between requests (polite scraping)
MAX_RETRIES = 2
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def job_id(title: str, company: str, url: str) -> str:
    """Deterministic ID for jobs.json dedup (NOT the Supabase dedup_key)."""
    raw = f"{title.lower().strip()}|{company.lower().strip()}|{url.strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def clean_title(raw: str) -> str:
    """Normalize job title: strip emojis, extra whitespace, location tags."""
    cleaned = re.sub(r"[\U00010000-\U0010ffff]", "", raw)  # strip emojis
    cleaned = re.sub(r"\s*[\(\[].*(remote|hybrid|onsite|location).*[\)\]]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_salary_range(text: str) -> dict | None:
    """Try to extract salary from job description text."""
    patterns = [
        r"\$\s?([\d,]+)\s*[-\u2013]\s*\$\s?([\d,]+)",  # $80,000 - $120,000
        r"([\d,]+)\s*[-\u2013]\s*([\d,]+)\s*(?:USD|usd)",  # 80000 - 120000 USD
        r"\$\s?([\d]+)k\s*[-\u2013]\s*\$?\s?([\d]+)k",  # $80k - $120k
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            low = int(match.group(1).replace(",", "").replace("k", "000") if "k" not in match.group(1) else match.group(1).replace("k", "") + "000")
            high = int(match.group(2).replace(",", "").replace("k", "000") if "k" not in match.group(2) else match.group(2).replace("k", "") + "000")
            return {"min": low, "max": high, "currency": "USD"}
    return None


def is_relevant_link(href: str, text: str) -> bool:
    """Determine if a link likely points to a job listing."""
    if not href:
        return False
    job_signals = [
        "/job/", "/position/", "/role/", "/opening/",
        "/apply/", "/careers/", "lever.co/", "greenhouse.io/",
        "boards.greenhouse", "jobs.lever", "workday"
    ]
    text_lower = text.lower()
    href_lower = href.lower()
    has_signal = any(s in href_lower for s in job_signals)
    has_text_signal = any(
        kw in text_lower
        for kw in ["manager", "engineer", "lead", "director", "analyst",
                    "designer", "developer", "specialist", "coordinator",
                    "head of", "vp of", "community", "growth", "marketing",
                    "content", "social", "kol", "ambassador"]
    )
    return has_signal or has_text_signal


# ---------------------------------------------------------------------------
# Scraping Engine
# ---------------------------------------------------------------------------

def fetch_page(url: str, retries: int = MAX_RETRIES) -> str | None:
    """Fetch a page with retries and polite delays."""
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9,es;q=0.8"}
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 429:
                wait = min(30, 2 ** (attempt + 2))
                print(f"  [429] Rate limited on {url}, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  [{resp.status_code}] Failed: {url}")
                return None
        except requests.RequestException as e:
            print(f"  [ERR] {url}: {e}")
            if attempt < retries:
                time.sleep(2)
    return None


# ---------------------------------------------------------------------------
# X feed scraper (DEAD CODE — kept per DECISIONS_LOG "revisit as hiring signals"
# feature later). Not invoked in v2.1: X_Feed sources are filtered out at
# group-load time. Left in place so re-enabling is a one-line change.
# ---------------------------------------------------------------------------

NITTER_INSTANCES = [
    "nitter.net",
    "nitter.privacydev.net",
    "nitter.poast.org",
    "nitter.tiekoetter.com",
]


def scrape_x_handle(source: dict) -> list[dict]:
    """[DEAD CODE in v2.1] Scrape an X handle via Nitter RSS."""
    handle = source.get("handle", "")
    company = source["name"]
    category = source.get("category", "X_Feed")
    print(f"  Scraping X handle @{handle}")

    rss_xml = None
    used_instance = None
    for instance in NITTER_INSTANCES:
        url = f"https://{instance}/{handle}/rss"
        rss_xml = fetch_page(url, retries=0)
        if rss_xml and "<item>" in rss_xml:
            used_instance = instance
            break

    if not rss_xml:
        print(f"    All Nitter instances failed for @{handle}")
        return []

    try:
        soup = BeautifulSoup(rss_xml, "xml")
    except Exception:
        soup = BeautifulSoup(rss_xml, "html.parser")

    jobs = []
    seen = set()
    items = soup.find_all("item")[:30]

    for item in items:
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        if not title_el:
            continue
        raw_text = title_el.get_text(strip=True)
        if not raw_text or len(raw_text) < 10:
            continue
        text_lower = raw_text.lower()
        job_signals = ["hiring", "job", "career", "position", "role", "opening",
                       "apply", "join us", "we're looking", "we are looking",
                       "manager", "lead", "director", "growth", "marketing",
                       "community", "kol", "developer", "engineer"]
        if not any(s in text_lower for s in job_signals):
            continue
        title = clean_title(raw_text[:200])
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        tweet_url = link_el.get_text(strip=True) if link_el else f"https://x.com/{handle}"
        if "nitter" in tweet_url:
            tweet_url = tweet_url.replace(f"https://{used_instance}", "https://x.com").replace(f"http://{used_instance}", "https://x.com")
        description = ""
        if desc_el:
            desc_html = desc_el.get_text(strip=True)
            desc_soup = BeautifulSoup(desc_html, "html.parser")
            description = desc_soup.get_text(strip=True)[:500]
        salary = extract_salary_range(description)
        jobs.append({
            "id": job_id(title, company, tweet_url),
            "title": title,
            "company": company,
            "category": category,
            "url": tweet_url,
            "source_url": f"https://x.com/{handle}",
            "location": "Remote",
            "salary": salary,
            "description": description,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "raw_score": None,
        })
    return jobs


def scrape_career_page(source: dict) -> list[dict]:
    """Scrape a single career page and extract job listings."""
    url = source["url"]
    company = source["name"]
    category = source.get("category", "Unknown")
    print(f"  Scraping {company}: {url}")

    html = fetch_page(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen_titles = set()

    # Strategy 1: Look for job links in the page
    for link in soup.find_all("a", href=True):
        text = link.get_text(strip=True)
        href = link["href"]

        if not text or len(text) < 5 or len(text) > 200:
            continue
        if not is_relevant_link(href, text):
            continue

        title = clean_title(text)
        if not title or title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())

        if href.startswith("/"):
            parsed = urlparse(url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        elif not href.startswith("http"):
            href = url.rstrip("/") + "/" + href

        parent = link.parent
        description = ""
        if parent:
            desc_el = parent.find(["p", "span", "div"], class_=re.compile(r"desc|summary|subtitle|location", re.I))
            if desc_el:
                description = desc_el.get_text(strip=True)[:500]

        location = "Remote"
        location_el = parent.find(string=re.compile(r"remote|on-?site|hybrid|buenos aires|latam|americas|global", re.I)) if parent else None
        if location_el:
            location = location_el.strip()[:100]

        salary = extract_salary_range(description)

        jobs.append({
            "id": job_id(title, company, href),
            "title": title,
            "company": company,
            "category": category,
            "url": href,
            "source_url": url,
            "location": location,
            "salary": salary,
            "description": description,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "raw_score": None
        })

    # Strategy 2: structured containers if no links found
    if not jobs:
        job_containers = soup.find_all(["div", "li", "article"], class_=re.compile(
            r"job|position|opening|career|role|listing|vacancy", re.I
        ))
        for container in job_containers[:50]:
            title_el = container.find(["h2", "h3", "h4", "a", "strong", "span"],
                                       class_=re.compile(r"title|name|role|position", re.I))
            if not title_el:
                title_el = container.find(["h2", "h3", "h4"])
            if not title_el:
                continue

            title = clean_title(title_el.get_text(strip=True))
            if not title or title.lower() in seen_titles:
                continue
            seen_titles.add(title.lower())

            link_el = container.find("a", href=True)
            href = link_el["href"] if link_el else url
            if href.startswith("/"):
                parsed = urlparse(url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"

            jobs.append({
                "id": job_id(title, company, href),
                "title": title,
                "company": company,
                "category": category,
                "url": href,
                "source_url": url,
                "location": "Remote",
                "salary": None,
                "description": "",
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "raw_score": None
            })

    print(f"    Found {len(jobs)} listings")
    return jobs


def scrape_source_with_health(source: dict, supabase_client) -> list[dict]:
    """Wrap a single-source scrape with timing + sources_health logging."""
    company = source["name"]
    start = time.time()
    error_message: str | None = None
    jobs: list[dict] = []
    success = False
    try:
        jobs = scrape_career_page(source)
        success = True
    except Exception as e:
        error_message = str(e)[:500]
        print(f"  [ERR] scrape failed for {company}: {e}", file=sys.stderr)
    duration_ms = int((time.time() - start) * 1000)
    sink.log_source_health(
        supabase_client,
        source=company,
        jobs_found=len(jobs),
        success=success,
        duration_ms=duration_ms,
        error_message=error_message,
    )
    return jobs


def scrape_group(group_key: str, sources: dict, supabase_client) -> list[dict]:
    """Scrape all active (non-X_Feed) sources in a group."""
    group = sources["groups"].get(group_key)
    if not group:
        print(f"Group {group_key} not found!")
        return []

    # Drop X_Feed sources at load time (hiring signals, not job listings)
    active_sources = [s for s in group["sources"] if s.get("category") != "X_Feed"]
    skipped_x = len(group["sources"]) - len(active_sources)

    print(f"\n{'='*60}")
    print(f"GROUP: {group['name']}")
    print(f"Sources: {len(active_sources)} active ({skipped_x} X_Feed skipped)")
    print(f"{'='*60}")

    all_jobs = []
    for source in active_sources:
        jobs = scrape_source_with_health(source, supabase_client)
        all_jobs.extend(jobs)
        time.sleep(DELAY_BETWEEN_REQUESTS)

    return all_jobs


# ---------------------------------------------------------------------------
# Merging & Deduplication (jobs.json — Supabase has its own via dedup_key)
# ---------------------------------------------------------------------------

def merge_with_existing(new_jobs: list[dict], existing_path: Path, max_age_days: int = 7) -> dict:
    """Merge cleaned new jobs with existing data, dedup by `id`, age out stale."""
    existing = {}
    if existing_path.exists():
        try:
            data = load_json(existing_path)
            for job in data.get("jobs", []):
                existing[job["id"]] = job
        except (json.JSONDecodeError, KeyError):
            pass

    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_days * 86400)
    fresh = {}
    for jid, job in existing.items():
        try:
            scraped = datetime.fromisoformat(job["scraped_at"]).timestamp()
            if scraped > cutoff:
                fresh[jid] = job
        except (ValueError, KeyError):
            fresh[jid] = job  # keep if unparseable

    for job in new_jobs:
        # Recompute id after cleanup (title/company may have changed via unmash)
        new_id = job_id(job.get("title", ""), job.get("company", ""), job.get("url", ""))
        job["id"] = new_id
        fresh[new_id] = job

    return {
        "metadata": {
            "total_jobs": len(fresh),
            "last_scrape": datetime.now(timezone.utc).isoformat(),
            "sources_scraped": len(set(j.get("source_url", "") for j in fresh.values())),
            "version": "2.1.0",
        },
        "jobs": sorted(fresh.values(), key=lambda j: j.get("scraped_at", ""), reverse=True),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Staggered Career Page Scraper")
    parser.add_argument("--group", required=True, help="Group to scrape (1-5 or 'all')")
    parser.add_argument("--dry", action="store_true", help="Dry run: don't write output")
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="Output JSON path")
    parser.add_argument("--no-supabase", action="store_true",
                        help="Skip Supabase dual-write (jobs.json only)")
    args = parser.parse_args()

    sources = load_json(SOURCES_FILE)
    output_path = Path(args.output)

    print(f"Job Search Scraper v2.1")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    # Supabase client (fail-soft: None means json-only mode)
    supabase_client = None
    if not args.no_supabase:
        supabase_client = sink.get_client()
        if supabase_client is None:
            print("  [supabase] no credentials — running in jobs.json-only mode")
        else:
            print("  [supabase] client ready — dual-write enabled")

    all_new_jobs: list[dict] = []
    if args.group == "all":
        for gkey in sources["groups"]:
            all_new_jobs.extend(scrape_group(gkey, sources, supabase_client))
    else:
        group_key = f"group_{args.group}"
        all_new_jobs.extend(scrape_group(group_key, sources, supabase_client))

    print(f"\n{'='*60}")
    print(f"RAW LISTINGS SCRAPED: {len(all_new_jobs)}")

    # Apply cleanup pipeline (drop X (belt-and-suspenders), drop junk, unmash titles)
    cleaned, stats = cleanup.clean_scraped_jobs(all_new_jobs)
    print(
        f"[cleanup] input={stats['input']} "
        f"dropped_x_feeds={stats['dropped_x_feeds']} "
        f"dropped_junk={stats['dropped_junk']} "
        f"unmashed={stats['unmashed']} "
        f"dropped_empty={stats['dropped_empty']} "
        f"output={stats['output']}"
    )

    if args.dry:
        print("[DRY RUN] No files written, no Supabase writes")
        print(f"{'='*60}")
        return 0

    # Write 1: jobs.json (fallback path — always runs, always authoritative for UI)
    merged = merge_with_existing(cleaned, output_path)
    save_json(output_path, merged)
    print(f"OUTPUT: {output_path} ({merged['metadata']['total_jobs']} total jobs)")

    # Write 2: Supabase upsert (best-effort, fail-soft)
    if supabase_client is not None and cleaned:
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = [cleanup.job_to_supabase_row(j, now_iso) for j in cleaned]
        written, errors = sink.upsert_jobs(supabase_client, rows)
        print(f"  [supabase] {written}/{len(rows)} rows written, {errors} batch errors")

    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
