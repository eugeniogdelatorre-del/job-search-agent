#!/usr/bin/env python3
"""
Job Search Scraper v2.0 - Staggered Career Page Scanner
Scrapes career pages in groups, extracts job listings, scores them,
and outputs consolidated JSON for the scoring configurator artifact.

Usage:
  python scrape.py --group 1        # Scrape group 1 only
  python scrape.py --group all      # Scrape all groups (manual full run)
  python scrape.py --group 1 --dry  # Dry run, no file writes
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
    """Generate a deterministic ID for deduplication."""
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
    # Must have a job-like signal in URL or text
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
        
        # Build full URL
        if href.startswith("/"):
            parsed = urlparse(url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        elif not href.startswith("http"):
            href = url.rstrip("/") + "/" + href
        
        # Try to find nearby description text
        parent = link.parent
        description = ""
        if parent:
            desc_el = parent.find(["p", "span", "div"], class_=re.compile(r"desc|summary|subtitle|location", re.I))
            if desc_el:
                description = desc_el.get_text(strip=True)[:500]
        
        # Extract location hints
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
            "raw_score": None  # Scored by the configurator artifact
        })
    
    # Strategy 2: If no links found, look for structured job listings (divs, lis)
    if not jobs:
        job_containers = soup.find_all(["div", "li", "article"], class_=re.compile(
            r"job|position|opening|career|role|listing|vacancy", re.I
        ))
        for container in job_containers[:50]:  # Cap at 50 to avoid noise
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


def scrape_group(group_key: str, sources: dict) -> list[dict]:
    """Scrape all sources in a group."""
    group = sources["groups"].get(group_key)
    if not group:
        print(f"Group {group_key} not found!")
        return []
    
    print(f"\n{'='*60}")
    print(f"GROUP: {group['name']}")
    print(f"Sources: {len(group['sources'])}")
    print(f"{'='*60}")
    
    all_jobs = []
    for source in group["sources"]:
        jobs = scrape_career_page(source)
        all_jobs.extend(jobs)
        time.sleep(DELAY_BETWEEN_REQUESTS)
    
    return all_jobs


# ---------------------------------------------------------------------------
# Merging & Deduplication
# ---------------------------------------------------------------------------

def merge_with_existing(new_jobs: list[dict], existing_path: Path, max_age_days: int = 7) -> dict:
    """Merge new scraped jobs with existing data, deduplicating by ID."""
    existing = {}
    if existing_path.exists():
        try:
            data = load_json(existing_path)
            for job in data.get("jobs", []):
                existing[job["id"]] = job
        except (json.JSONDecodeError, KeyError):
            pass
    
    # Remove stale jobs (older than max_age_days)
    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_days * 86400)
    fresh = {}
    for jid, job in existing.items():
        try:
            scraped = datetime.fromisoformat(job["scraped_at"]).timestamp()
            if scraped > cutoff:
                fresh[jid] = job
        except (ValueError, KeyError):
            fresh[jid] = job  # Keep if we can't parse date
    
    # Merge: new jobs override existing by ID
    for job in new_jobs:
        fresh[job["id"]] = job
    
    return {
        "metadata": {
            "total_jobs": len(fresh),
            "last_scrape": datetime.now(timezone.utc).isoformat(),
            "sources_scraped": len(set(j.get("source_url", "") for j in fresh.values())),
            "version": "2.0.0"
        },
        "jobs": sorted(fresh.values(), key=lambda j: j.get("scraped_at", ""), reverse=True)
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Staggered Career Page Scraper")
    parser.add_argument("--group", required=True, help="Group to scrape (1-5 or 'all')")
    parser.add_argument("--dry", action="store_true", help="Dry run: don't write output")
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="Output JSON path")
    args = parser.parse_args()
    
    sources = load_json(SOURCES_FILE)
    output_path = Path(args.output)
    
    print(f"Job Search Scraper v2.0")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    
    all_new_jobs = []
    
    if args.group == "all":
        for gkey in sources["groups"]:
            jobs = scrape_group(gkey, sources)
            all_new_jobs.extend(jobs)
    else:
        group_key = f"group_{args.group}"
        jobs = scrape_group(group_key, sources)
        all_new_jobs.extend(jobs)
    
    print(f"\n{'='*60}")
    print(f"TOTAL NEW LISTINGS: {len(all_new_jobs)}")
    
    if not args.dry:
        merged = merge_with_existing(all_new_jobs, output_path)
        save_json(output_path, merged)
        print(f"OUTPUT: {output_path} ({merged['metadata']['total_jobs']} total jobs)")
    else:
        print("[DRY RUN] No files written")
    
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
