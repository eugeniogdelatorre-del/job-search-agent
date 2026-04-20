"""
Shared cleanup and transform logic for scraped job listings.

Used by:
  - scrape.py (applied at scrape time, so jobs.json is clean too)
  - migrate_to_supabase.py (the one-shot historical migration)

Rules (per DECISIONS_LOG.md):
  - X/Twitter feeds are hiring signals, not jobs. Drop them.
  - Aggregator sidebars ("promoted", "see all jobs", etc.) are not listings. Drop them.
  - WeWorkRemotely-style aggregators mash title+company+location+salary into one
    string with no separators. Unmash with regex.
  - Cross-source dedup uses normalized(title) + normalized(company).
  - Source tier for dedup tie-breaking:
      3 = direct company / ATS (Greenhouse, Lever, Ashby)
      2 = Web3-focused aggregator (CryptoJobsList, Web3.career, CryptocurrencyJobs)
      1 = broad remote board (WeWorkRemotely, RemoteLeaf, Remotive)
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Reference sets
# ---------------------------------------------------------------------------

AGGREGATOR_COMPANIES = {
    "cryptojobslist", "web3.career", "cryptocurrencyjobs",
    "we work remotely", "remoteleaf", "remotive",
}

WEB3_AGGREGATORS = {"cryptojobslist", "web3.career", "cryptocurrencyjobs"}

BROAD_BOARD_CATEGORIES = {"Remote_Board", "Board"}

VERTICAL_CATEGORIES = {
    "L1", "L2", "DeFi", "CEX", "DevTools", "Storage", "Bridge", "Payments",
    "Forensics", "Custody", "Mining", "FinTech", "Oracle", "Bot", "Identity",
    "Gaming", "RWA", "Stablecoin",
}

# Phrases that reliably identify sidebar/promotional modules on aggregator sites.
# Conservative: only matched when the title is long (>= 80 chars), since a real
# short job title should never contain these phrases.
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

# WWR/aggregator mashed-title pattern:
#   "<real title><age badge><company><employment type><location/salary tail>"
# e.g. "Senior Backend Engineer3dVantaFull-TimeSan Francisco$120,000 - $160,000 USD"
WWR_SPLIT = re.compile(
    r"^(?P<title>.+?)"
    r"(?P<age>\d+[dmhw]|\d+mo|Featured|Top\s*\d+)"
    r"(?P<company>.+?)"
    r"(?P<emp>Full-Time|Part-Time|Contract|Freelance|Internship)"
    r"(?P<tail>.*)$"
)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def normalize_for_dedup(s: str) -> str:
    """Aggressive normalization used to build dedup keys across sources."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"\s*(inc|llc|ltd|gmbh|corp|co|labs|foundation)\.?$", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def make_dedup_key(title: str, company: str) -> str:
    """Cross-source dedup key: normalized(title)|normalized(company)."""
    return f"{normalize_for_dedup(title)}|{normalize_for_dedup(company)}"


def is_x_feed(job: dict) -> bool:
    if job.get("category") == "X_Feed":
        return True
    company = (job.get("company") or "").lower()
    return company.startswith("x: @") or company.startswith("x:@")


def is_junk_listing(job: dict) -> bool:
    title = (job.get("title") or "").lower()
    if len(title) < 80:
        return False
    return any(marker in title for marker in JUNK_MARKERS)


# ---------------------------------------------------------------------------
# Aggregator title unmasher
# ---------------------------------------------------------------------------

def _split_company_location(s: str) -> tuple[str, str | None]:
    """Split 'VantaSan Francisco' -> ('Vanta', 'San Francisco')."""
    s = re.sub(r"(Featured|Top\s*\d+)+$", "", s).strip()
    m = re.search(r"([a-z])([A-Z])", s)
    if m:
        return (s[: m.start() + 1].strip(), s[m.start() + 1 :].strip())
    return (s, None)


def _split_location_salary(s: str) -> tuple[str, tuple[int, int] | None]:
    """Pull a USD salary range out of the location tail if present."""
    m = re.search(r"\$?([\d,]+)\s*[-\u2013]\s*\$?([\d,]+)\s*USD", s)
    if m:
        lo = int(m.group(1).replace(",", ""))
        hi = int(m.group(2).replace(",", ""))
        loc = re.sub(r"\$?[\d,]+\s*[-\u2013]\s*\$?[\d,]+\s*USD\s*", "", s).strip() or "Anywhere in the World"
        if 10_000 <= lo <= hi <= 1_000_000:
            return (loc, (lo, hi))
    m = re.search(r"\$([\d,]+)\s*or\s*more\s*USD?", s)
    if m:
        lo = int(m.group(1).replace(",", ""))
        loc = re.sub(r"\$[\d,]+\s*or\s*more\s*USD?\s*", "", s).strip() or "Anywhere in the World"
        if 10_000 <= lo <= 1_000_000:
            return (loc, (lo, lo))
    return (s, None)


def unmash_aggregator_title(job: dict) -> dict:
    """
    If this job came from an aggregator that mashes fields (WWR-style),
    try to recover real title/company/location/salary. No-op on failure.
    Preserves the aggregator name in _discovery_channel for source-tier logic.
    """
    title_raw = job.get("title") or ""
    if len(title_raw) < 80:
        return job
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
        out["_discovery_channel"] = job["company"]
        out["company"] = real_company
    out["title"] = real_title
    out["location"] = location_clean or job.get("location")
    if salary_range:
        out["salary"] = {"min": salary_range[0], "max": salary_range[1], "currency": "USD"}
    return out


# ---------------------------------------------------------------------------
# Transforms for Supabase schema
# ---------------------------------------------------------------------------

def infer_source_tier(company: str, category: str | None) -> int:
    """Higher tier wins during cross-source dedup."""
    company_lower = (company or "").lower()
    if company_lower in AGGREGATOR_COMPANIES:
        return 2
    if category in BROAD_BOARD_CATEGORIES:
        return 1
    return 3  # direct company / ATS


def split_category(raw_category: str | None) -> tuple[str | None, str | None]:
    """Legacy `category` mixes verticals and source types — split them."""
    if raw_category in VERTICAL_CATEGORIES:
        return (raw_category, None)
    if raw_category in BROAD_BOARD_CATEGORIES:
        return (None, raw_category)
    return (None, None)


def clean_salary(raw_salary) -> tuple[int | None, int | None]:
    """Return (min_usd, max_usd) or (None, None) if the range is garbage."""
    if not raw_salary or not isinstance(raw_salary, dict):
        return (None, None)
    try:
        lo = int(raw_salary.get("min", 0))
        hi = int(raw_salary.get("max", 0))
    except (TypeError, ValueError):
        return (None, None)
    # "90k-140k" style: scale up
    if 0 < lo < 1000 and 0 < hi < 1000:
        lo *= 1000
        hi *= 1000
    if lo <= 0 or hi <= 0:
        return (None, None)
    if lo > hi:
        return (None, None)
    if hi < 10_000 or hi > 2_000_000:
        return (None, None)
    return (lo, hi)


def infer_remote_status(location: str | None) -> str | None:
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


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def clean_scraped_jobs(raw_jobs: list[dict]) -> tuple[list[dict], dict]:
    """Apply the full cleanup pipeline. Returns (cleaned_jobs, stats)."""
    stats: dict = {"input": len(raw_jobs)}

    step1 = [j for j in raw_jobs if not is_x_feed(j)]
    stats["dropped_x_feeds"] = len(raw_jobs) - len(step1)

    step2 = [j for j in step1 if not is_junk_listing(j)]
    stats["dropped_junk"] = len(step1) - len(step2)

    step3 = [unmash_aggregator_title(j) for j in step2]
    stats["unmashed"] = sum(
        1
        for before, after in zip(step2, step3)
        if before.get("title") != after.get("title")
    )

    step4 = [
        j
        for j in step3
        if (j.get("title") or "").strip() and (j.get("company") or "").strip()
    ]
    stats["dropped_empty"] = len(step3) - len(step4)
    stats["output"] = len(step4)
    return step4, stats


def job_to_supabase_row(job: dict, last_seen_iso: str) -> dict:
    """
    Transform a cleaned scraper job dict into a Supabase `jobs` row.

    IMPORTANT: this payload is used with on_conflict=dedup_key upsert.
    Fields deliberately omitted from the payload are preserved on conflict:
      - first_seen_at    (preserves original sighting; uses DB default on insert)
      - function_category, function_confidence, seniority (AI-filled — don't clobber)
      - score_total, score_breakdown (AI-filled — don't clobber)
    """
    title = (job.get("title") or "").strip()
    company = (job.get("company") or "").strip()
    location = job.get("location")
    raw_category = job.get("category")

    vertical, _ = split_category(raw_category)
    sal_min, sal_max = clean_salary(job.get("salary"))

    # If unmashed, the original "company" was actually the aggregator name.
    # Use it as source + derive tier; real employer lives in `company`.
    discovery = job.get("_discovery_channel")
    if discovery:
        source = discovery
        tier = 2 if discovery.lower() in WEB3_AGGREGATORS else 1
    else:
        source = company
        tier = infer_source_tier(company, raw_category)

    return {
        "dedup_key": make_dedup_key(title, company),
        "title": title[:500],
        "company": company[:200],
        "location": ((location or "")[:200]) or None,
        "remote_status": infer_remote_status(location),
        "salary_min_usd": sal_min,
        "salary_max_usd": sal_max,
        "description": ((job.get("description") or "")[:5000]) or None,
        "apply_url": ((job.get("url") or "")[:1000]) or None,
        "source": source[:100],
        "source_tier": tier,
        "source_url": ((job.get("source_url") or "")[:1000]) or None,
        "vertical": vertical,
        "last_seen_at": last_seen_iso,
        "is_active": True,
    }
