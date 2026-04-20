#!/usr/bin/env python3
"""
One-time migration: load public/data/jobs.json -> Supabase `jobs` table.

Rules (per user decisions):
  Q1: Drop X/Twitter feed entries (category == 'X_Feed' or company starts with 'X: @')
  Q2: Cross-source dedup using normalized (title, company)
  Q3: Migrate everything else as-is; null out obviously broken salaries

Source tier mapping for dedup tie-breaking (higher = better, kept on conflict):
  3 = direct ATS / company careers page
  2 = major aggregator (CryptoJobsList, Web3.career, CryptocurrencyJobs)
  1 = broad remote board (WeWorkRemotely, RemoteLeaf)
"""
import json
import os
import re
import sys
import hashlib
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AGGREGATOR_COMPANIES = {
    "cryptojobslist", "web3.career", "cryptocurrencyjobs",
    "we work remotely", "remoteleaf", "remotive",
}

BROAD_BOARD_CATEGORIES = {"Remote_Board", "Board"}

# Vertical categories (real sector classifications, not source types)
VERTICAL_CATEGORIES = {
    "L1", "L2", "DeFi", "CEX", "DevTools", "Storage", "Bridge", "Payments",
    "Forensics", "Custody", "Mining", "FinTech", "Oracle", "Bot", "Identity",
    "Gaming", "RWA", "Stablecoin"
}

BATCH_SIZE = 500  # Supabase client-side batching


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_for_dedup(s: str) -> str:
    """Aggressive normalization for cross-source dedup."""
    if not s:
        return ""
    s = s.lower().strip()
    # Strip common company suffixes that vary across sources
    s = re.sub(r"\s*(inc|llc|ltd|gmbh|corp|co|labs|foundation)\.?$", "", s)
    # Collapse whitespace and drop punctuation
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def make_dedup_key(title: str, company: str) -> str:
    """Cross-source dedup key: normalized(title) + normalized(company)."""
    t = normalize_for_dedup(title)
    c = normalize_for_dedup(company)
    return f"{t}|{c}"


def is_x_feed(job: dict) -> bool:
    if job.get("category") == "X_Feed":
        return True
    company = (job.get("company") or "").lower()
    if company.startswith("x: @") or company.startswith("x:@"):
        return True
    return False


# Markers that reliably identify sidebar/promotional content on aggregator sites
# (WeWorkRemotely, RemoteLeaf, Web3.career). These are not real job listings.
JUNK_MARKERS = (
    "promoted",
    "curated marches",
    "find flexible remote roles",
    "curated by",
    "hiring talent from",
    "browse jobs",
    "post a job",
    "see all jobs",
    "view all openings",
    "featured jobs",
    "top remote companies",
)


def is_junk_listing(job: dict) -> bool:
    """
    Detect aggregator sidebar ads and promotional modules that got scraped
    as if they were job listings. Conservative: only drops rows matching
    explicit markers. Real roles should never match these phrases verbatim.
    """
    title = (job.get("title") or "").lower()
    # Only apply length gate + marker match — keeps the filter conservative
    if len(title) < 80:
        return False
    return any(marker in title for marker in JUNK_MARKERS)


# ---------------------------------------------------------------------------
# Aggregator title unmashers
# ---------------------------------------------------------------------------
# WeWorkRemotely (and similar aggregators) concatenate HTML elements without
# separators: "<title><age><company><type><location><salary?>" all jammed.
# We reverse-engineer the original fields.

WWR_SPLIT = re.compile(
    r"^(?P<title>.+?)"                                         # real job title
    r"(?P<age>\d+[dmhw]|\d+mo|Featured|Top\s*\d+)"            # age/badge token
    r"(?P<company>.+?)"                                        # company + maybe location
    r"(?P<emp>Full-Time|Part-Time|Contract|Freelance|Internship)"
    r"(?P<tail>.*)$"                                           # location + maybe salary
)


def _split_company_location(s: str) -> tuple[str, str | None]:
    """Split 'VantaSan Francisco' -> ('Vanta', 'San Francisco')."""
    s = re.sub(r"(Featured|Top\s*\d+)+$", "", s).strip()
    m = re.search(r"([a-z])([A-Z])", s)
    if m:
        return (s[: m.start() + 1].strip(), s[m.start() + 1 :].strip())
    return (s, None)


def _split_location_salary(s: str) -> tuple[str, tuple[int, int] | None]:
    """Pull a USD salary range out of the location tail if present."""
    # Pattern A: "$10,000 - $25,000 USD"
    m = re.search(r"\$?([\d,]+)\s*[-–]\s*\$?([\d,]+)\s*USD", s)
    if m:
        lo = int(m.group(1).replace(",", ""))
        hi = int(m.group(2).replace(",", ""))
        loc = re.sub(r"\$?[\d,]+\s*[-–]\s*\$?[\d,]+\s*USD\s*", "", s).strip() or "Anywhere in the World"
        if 10_000 <= lo <= hi <= 1_000_000:
            return (loc, (lo, hi))
    # Pattern B: "$100,000 or more USD"
    m = re.search(r"\$([\d,]+)\s*or\s*more\s*USD?", s)
    if m:
        lo = int(m.group(1).replace(",", ""))
        loc = re.sub(r"\$[\d,]+\s*or\s*more\s*USD?\s*", "", s).strip() or "Anywhere in the World"
        if 10_000 <= lo <= 1_000_000:
            return (loc, (lo, lo))
    return (s, None)


def unmash_aggregator_title(job: dict) -> dict:
    """
    If the job comes from an aggregator that mashes title/company/location
    together (WWR, RemoteLeaf pattern), attempt to extract real fields.
    Returns a modified copy of the job dict. No-op on failure.

    Preserves the aggregator name in a separate '_discovery_channel' field
    so downstream transform knows which source found the job.
    """
    title_raw = job.get("title") or ""
    if len(title_raw) < 80:
        return job  # short titles are already fine
    m = WWR_SPLIT.match(title_raw)
    if not m:
        return job

    real_title = m.group("title").strip()
    company_raw = m.group("company").strip()
    tail = m.group("tail").strip()

    real_company, bled_location = _split_company_location(company_raw)
    location_clean, salary_range = _split_location_salary(tail)

    if bled_location and (not location_clean or location_clean == "Anywhere in the World"):
        location_clean = bled_location

    out = dict(job)
    original_company = (job.get("company") or "").lower()
    if original_company in AGGREGATOR_COMPANIES and real_company:
        # Keep the aggregator name as discovery channel, use real company for company field
        out["_discovery_channel"] = job["company"]
        out["company"] = real_company
    out["title"] = real_title
    out["location"] = location_clean or job.get("location")
    if salary_range:
        out["salary"] = {"min": salary_range[0], "max": salary_range[1], "currency": "USD"}
    return out


def infer_source_tier(company: str, category: str) -> int:
    """Higher tier = prefer this source when deduplicating."""
    company_lower = (company or "").lower()
    if company_lower in AGGREGATOR_COMPANIES:
        return 2
    if category in BROAD_BOARD_CATEGORIES:
        return 1
    # Everything else is a direct company careers page or ATS scrape
    return 3


def split_category(raw_category: str) -> tuple[str | None, str | None]:
    """
    The legacy `category` field mixes verticals and source types.
    Returns (vertical, source_type_hint).
    """
    if raw_category in VERTICAL_CATEGORIES:
        return (raw_category, None)
    if raw_category in BROAD_BOARD_CATEGORIES:
        return (None, raw_category)
    return (None, None)


def clean_salary(raw_salary) -> tuple[int | None, int | None]:
    """
    Legacy salary field is often corrupt (min > max, or absurdly small).
    Returns (min_usd, max_usd) or (None, None) if the range looks broken.
    """
    if not raw_salary or not isinstance(raw_salary, dict):
        return (None, None)
    try:
        lo = int(raw_salary.get("min", 0))
        hi = int(raw_salary.get("max", 0))
    except (TypeError, ValueError):
        return (None, None)

    # If values are tiny (< 1000), assume they're in thousands (e.g. "90k-140k")
    if 0 < lo < 1000 and 0 < hi < 1000:
        lo *= 1000
        hi *= 1000

    # Sanity checks
    if lo <= 0 or hi <= 0:
        return (None, None)
    if lo > hi:
        return (None, None)  # "min 270 max 62" garbage
    if hi < 10_000:
        return (None, None)  # too small to be an annual salary
    if hi > 2_000_000:
        return (None, None)  # too large, probably parsed garbage
    return (lo, hi)


def infer_remote_status(location: str) -> str | None:
    if not location:
        return None
    l = location.lower()
    if "hybrid" in l:
        return "hybrid"
    if "remote" in l or "anywhere" in l:
        return "remote"
    if "on-site" in l or "onsite" in l or "office" in l:
        return "onsite"
    return None


def transform_job(raw: dict) -> dict:
    """Map legacy job record -> new Supabase schema row."""
    title = (raw.get("title") or "").strip()
    company = (raw.get("company") or "").strip()
    location = raw.get("location")
    raw_category = raw.get("category")

    vertical, _ = split_category(raw_category)
    sal_min, sal_max = clean_salary(raw.get("salary"))

    # If we unmashed this from an aggregator, the discovery channel is the aggregator
    # (e.g. "We Work Remotely") and company is the real employer.
    # Otherwise the scraper hit the company directly (tier 3).
    discovery = raw.get("_discovery_channel")
    if discovery:
        source = discovery
        # Aggregator tier: 2 for Web3-focused (CryptoJobsList, Web3.career), 1 for broad
        tier = 2 if discovery.lower() in {"cryptojobslist", "web3.career", "cryptocurrencyjobs"} else 1
    else:
        source = company
        tier = infer_source_tier(company, raw_category)

    return {
        "dedup_key": make_dedup_key(title, company),
        "title": title[:500],
        "company": company[:200],
        "location": (location or "")[:200] or None,
        "remote_status": infer_remote_status(location or ""),
        "salary_min_usd": sal_min,
        "salary_max_usd": sal_max,
        "description": (raw.get("description") or "")[:5000] or None,
        "apply_url": (raw.get("url") or "")[:1000] or None,
        "source": source[:100],
        "source_tier": tier,
        "source_url": (raw.get("source_url") or "")[:1000] or None,
        "function_category": None,  # filled by AI classifier later
        "function_confidence": None,
        "vertical": vertical,
        "seniority": None,  # filled by AI classifier later
        "score_total": None,
        "score_breakdown": None,
        "first_seen_at": raw.get("scraped_at"),
        "last_seen_at": raw.get("scraped_at"),
        "is_active": True,
    }


def dedup_jobs(transformed: list[dict]) -> tuple[list[dict], dict]:
    """
    Cross-source dedup: keep highest-tier source per dedup_key.
    Returns (deduped_list, stats_dict).
    """
    by_key: dict[str, dict] = {}
    collisions = 0
    for job in transformed:
        key = job["dedup_key"]
        if not key or key == "|":
            continue  # skip entries with empty title/company
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = job
        else:
            collisions += 1
            # Keep the higher tier; on tie, keep whichever was scraped more recently
            if job["source_tier"] > existing["source_tier"]:
                by_key[key] = job
            elif job["source_tier"] == existing["source_tier"]:
                if (job["first_seen_at"] or "") > (existing["first_seen_at"] or ""):
                    by_key[key] = job
    return list(by_key.values()), {"collisions": collisions, "unique": len(by_key)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(jobs_json_path: Path, dry_run: bool = False) -> int:
    print(f"[migrate] loading {jobs_json_path}")
    with open(jobs_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_jobs = data.get("jobs", [])
    print(f"[migrate] loaded {len(raw_jobs)} raw jobs")

    # Q1: drop X feeds
    after_xfilter = [j for j in raw_jobs if not is_x_feed(j)]
    print(f"[migrate] dropped X feeds: {len(raw_jobs) - len(after_xfilter)} removed, {len(after_xfilter)} remaining")

    # Option C: drop aggregator sidebar ads / promotional modules
    after_junk = [j for j in after_xfilter if not is_junk_listing(j)]
    print(f"[migrate] dropped junk/sidebar ads: {len(after_xfilter) - len(after_junk)} removed, {len(after_junk)} remaining")

    # Unmash aggregator titles (WWR and similar concatenate fields)
    unmashed = [unmash_aggregator_title(j) for j in after_junk]
    recovered = sum(
        1
        for before, after in zip(after_junk, unmashed)
        if before.get("title") != after.get("title")
    )
    print(f"[migrate] unmashed aggregator titles: {recovered} jobs had fields recovered")

    # Transform
    transformed = [transform_job(j) for j in unmashed]
    # Filter rows with empty title or company
    transformed = [j for j in transformed if j["title"] and j["company"]]
    print(f"[migrate] transformed: {len(transformed)} valid")

    # Q2: cross-source dedup
    deduped, stats = dedup_jobs(transformed)
    print(f"[migrate] dedup: {stats['collisions']} collisions merged, {stats['unique']} unique jobs")

    # Salary coverage sanity check
    with_salary = sum(1 for j in deduped if j["salary_min_usd"])
    print(f"[migrate] salary coverage after cleanup: {with_salary}/{len(deduped)}")

    # Vertical coverage
    with_vert = sum(1 for j in deduped if j["vertical"])
    print(f"[migrate] vertical populated: {with_vert}/{len(deduped)} (rest will be classified by AI later)")

    if dry_run:
        print("[migrate] DRY RUN — not inserting")
        print("[migrate] sample transformed job:")
        print(json.dumps(deduped[0], indent=2)[:1500])
        return 0

    # ------------------------------------------------------------------
    # Insert to Supabase
    # ------------------------------------------------------------------
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    sb = create_client(url, key)

    print(f"[migrate] inserting in batches of {BATCH_SIZE}...")
    inserted = 0
    errors = 0
    for i in range(0, len(deduped), BATCH_SIZE):
        batch = deduped[i : i + BATCH_SIZE]
        try:
            # upsert on dedup_key in case the migration runs twice
            resp = sb.table("jobs").upsert(batch, on_conflict="dedup_key").execute()
            inserted += len(resp.data) if hasattr(resp, "data") and resp.data else len(batch)
            print(f"[migrate]  batch {i // BATCH_SIZE + 1}: +{len(batch)} rows")
        except Exception as e:
            errors += 1
            print(f"[migrate]  batch {i // BATCH_SIZE + 1} FAILED: {e}")

    print(f"[migrate] done. inserted≈{inserted}, errors={errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="public/data/jobs.json")
    ap.add_argument("--dry", action="store_true", help="Transform and report, don't insert")
    args = ap.parse_args()
    sys.exit(run(Path(args.input), dry_run=args.dry))
