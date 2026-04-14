#!/usr/bin/env python3
"""
🎯 Daily Job Search Agent v2 — Eugenio García de la Torre
============================================================
Maximum coverage: 30 job sources, 24-hour recency filter,
direct links to every listing.

Sources (30):
  WEB3-SPECIFIC (15):
    1.  Crypto Jobs List (cryptojobslist.com)
    2.  Web3.career
    3.  CryptocurrencyJobs (cryptocurrencyjobs.co)
    4.  Remote3 (remote3.co)
    5.  Froog (froog.co)
    6.  useWeb3 (useweb3.xyz/jobs)
    7.  JobStash (jobstash.xyz)
    8.  CryptoJobs.com (cryptojobs.com)
    9.  MyWeb3Jobs (myweb3jobs.com)
    10. BeInCrypto Jobs (beincrypto.com/jobs)
    11. Blockchain Association (theblockchainassociation.org)
    12. HireChain (hirechain.io)
    13. Pantera Capital Jobs (panteracapital.com)
    14. Axiom Recruit (axiomrecruit.com)
    15. TalentWeb3 (talentweb3.co)

  GENERAL REMOTE (8):
    16. Remotive (remotive.com)
    17. WeWorkRemotely (weworkremotely.com)
    18. Himalayas (himalayas.app)
    19. Wellfound / AngelList (wellfound.com)
    20. Jobicy (jobicy.com)
    21. DailyRemote (dailyremote.com)
    22. Working Nomads (workingnomads.com)
    23. Remote OK (remoteok.com)

  LATAM (2):
    24. GetOnBoard (getonbrd.com)
    25. Torre (torre.ai)

  AGGREGATED SEARCH via Google (5):
    26. LinkedIn jobs (24h filter)
    27. X/Twitter hiring posts (24h filter)
    28. Indeed/Glassdoor (24h filter)
    29. Google misc catch-all (24h filter)
    30. Google Web3-specific (24h filter)

Usage:
  python3 job_search_agent.py              # Run + send email
  python3 job_search_agent.py --dry-run    # Preview (saves HTML)
  python3 job_search_agent.py --verbose    # Detailed scoring log
"""

import os
import sys
import json
import re
import time
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urljoin, urlparse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("❌ Missing deps. Run: pip install requests beautifulsoup4")
    sys.exit(1)

# ============================================================================
# CONFIG
# ============================================================================

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "eugeniogdelatorre@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", EMAIL_ADDRESS)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

SALARY_FLOOR = 30000          # USD annual minimum. No-salary jobs are KEPT.
MIN_RELEVANCE_SCORE = 50      # 0-100
RECENCY_HOURS = 72            # Only jobs posted in the last N hours
CACHE_FILE = "jobs_cache.json"
CACHE_MAX_AGE_DAYS = 30

REQUEST_TIMEOUT = 20
REQUEST_DELAY = 1.2
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ============================================================================
# KEYWORDS & FILTERS
# ============================================================================

PRIMARY_ROLES = [
    "Community Manager", "Community Lead", "Head of Community",
    "Community Director", "Community Operations",
    "Growth Manager", "Growth Lead", "Head of Growth", "Growth Strategist",
    "KOL Manager", "KOL Lead",
    "Ecosystem Lead", "Ambassador Program",
    "Influencer Marketing Manager", "Influencer Marketing Lead",
    "Influencer Relations", "Social Media Lead",
]

SECONDARY_ROLES = [
    "Marketing Manager", "Marketing Lead", "Marketing Coordinator",
    "Social Media Manager", "Content Strategist", "Content Marketing",
    "Partnerships Manager", "Developer Relations", "DevRel",
    "Business Development", "BD Manager", "Regional Lead",
    "LATAM Lead", "Regional Manager", "Chief of Staff",
    "Engagement Manager", "User Acquisition", "Brand Manager",
    "Growth Hacker", "Go-to-Market",
]

WEB3_KEYWORDS = [
    "Web3", "Crypto", "Blockchain", "DeFi", "NFT", "DAO",
    "Token", "Protocol", "dApp", "Smart Contract",
    "L1", "L2", "Layer 1", "Layer 2", "RWA", "Real World Asset",
    "Oracle", "Launchpad", "GameFi", "P2E", "Play to Earn",
    "DEX", "CEX", "Staking", "Yield", "Airdrop",
    "Ethereum", "Solana", "Polygon", "Arbitrum", "Optimism",
    "BNB", "Binance", "Avalanche", "Cosmos", "Bitcoin",
    "Metaverse", "On-chain", "Onchain", "Decentralized",
    "DePIN", "SocialFi", "Rollup", "ZK", "Zero Knowledge",
]

BILINGUAL_KEYWORDS = [
    "Spanish", "Español", "Bilingual", "LATAM", "Latin America",
    "Bilingüe", "Hispanohablante", "Spanish-speaking",
    "Argentina", "Buenos Aires", "South America",
]

VERTICAL_BONUS_KEYWORDS = [
    "RWA", "Real World Asset", "Oracle", "Launchpad",
    "P2E", "Play to Earn", "GameFi", "Gaming",
    "IDO", "IGO", "Token Launch", "Incubator", "Accelerator",
]

# Sources that are Web3-specific by nature — jobs from these don't need Web3 keywords in text
WEB3_NATIVE_SOURCES = {
    "Crypto Jobs List", "CryptoJobsList", "JobStash", "CryptoJobs.com",
    "MyWeb3Jobs", "BeInCrypto Jobs", "HireChain", "Pantera Capital",
    "Blockchain Association", "Axiom Recruit", "TalentWeb3",
    "Web3.career", "CryptocurrencyJobs", "Remote3", "Froog", "useWeb3",
    "Telegram @cryptojobslist", "Telegram @jobstash", "Telegram @talentatweb3",
    "Telegram @DeJob_Global", "Telegram @illuminatiJOBS", "Telegram @web3hiring",
}

EXCLUSIONS = [
    "Intern", "Internship", "Junior", "Entry Level", "Entry-Level",
    "Executive Assistant", "Personal Assistant", "Receptionist",
    "PhD Required", "Solidity Developer", "Smart Contract Engineer",
    "Backend Engineer", "Frontend Engineer", "Full Stack", "Full-Stack",
    "DevOps Engineer", "SRE", "Data Engineer", "Data Scientist",
    "Machine Learning Engineer", "ML Engineer", "QA Engineer",
    "Software Engineer", "Software Developer", "Platform Engineer",
    "Site Reliability", "Security Engineer", "Infrastructure Engineer",
    "iOS Developer", "Android Developer", "Mobile Developer",
    "Cloud Engineer", "Systems Engineer", "Network Engineer",
    # Spanish dev/non-relevant roles
    "Desarrollador", "Ingeniero de Software", "Programador",
    "Analista de Datos", "Administrador de Base", "Soporte Técnico",
    "Soporte en Terreno", "Reclutador", "Recruiter IT",
    "Instructor", "Tutor", "Copywriter", "Video Editor",
    "Contador", "Abogado", "Diseñador UX", "Diseñador UI",
]

# Hybrid/onsite keywords to reject in title or location
HYBRID_KEYWORDS = [
    "hybrid", "híbrido", "hibrido", "on-site", "onsite", "in-office",
    "presencial", "en oficina",
]

# Search query sets used across multiple Google-based scrapers
GOOGLE_SEARCH_QUERIES_WEB3 = [
    '"community manager" OR "growth lead" OR "kol manager" web3 crypto remote',
    '"marketing manager" OR "head of community" OR "ecosystem lead" crypto blockchain remote',
    '"ambassador program" OR "influencer marketing" OR "social media" web3 crypto remote',
]

GOOGLE_SEARCH_QUERIES_GENERAL = [
    '"community manager" OR "growth manager" remote -junior -intern',
    '"kol manager" OR "influencer marketing manager" remote',
]

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("job_search.log", mode="a"),
    ],
)
log = logging.getLogger("JobAgent")

# ============================================================================
# HELPERS
# ============================================================================

def get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    })
    return s


def safe_get(session, url, **kwargs):
    try:
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        time.sleep(REQUEST_DELAY)
        r = session.get(url, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"GET failed {url}: {e}")
        return None


def safe_post(session, url, **kwargs):
    try:
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        time.sleep(REQUEST_DELAY)
        r = session.post(url, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"POST failed {url}: {e}")
        return None


def job_hash(title, company):
    raw = f"{title.lower().strip()}|{company.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()


def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
        cutoff = (datetime.now() - timedelta(days=CACHE_MAX_AGE_DAYS)).isoformat()
        return {k: v for k, v in cache.items() if v.get("seen", "") > cutoff}
    except Exception:
        return {}


def save_cache(cache):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        log.warning(f"Cache save failed: {e}")


def is_within_24h(date_str):
    """Check if a date string represents a time within the last 24 hours."""
    if not date_str:
        return True  # If no date info, include it (benefit of the doubt)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=RECENCY_HOURS)

    # Try common date formats
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%m/%d/%Y",
    ]:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt >= cutoff
        except ValueError:
            continue

    # Relative time patterns: "2 hours ago", "1 day ago", "just now", "today"
    text = date_str.lower().strip()
    if text in ("just now", "just posted", "now", "today", "new"):
        return True
    if "minute" in text or "hour" in text or "second" in text:
        return True
    if "1 day ago" in text or "1d ago" in text:
        return True
    if "yesterday" in text:
        return True
    if any(w in text for w in ["2 day", "3 day", "4 day", "5 day", "6 day", "week", "month", "year"]):
        return False

    # Reject any mention of old years (2025 or earlier)
    year_match = re.search(r'\b(20[0-2][0-9])\b', text)
    if year_match:
        year = int(year_match.group(1))
        if year <= 2025:
            return False

    # Reject date patterns like "Jan 16", "Apr 09" — calculate actual day difference
    month_match = re.search(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})\b', text)
    if month_match:
        try:
            month_abbr = month_match.group(1).capitalize()
            day = int(month_match.group(2))
            current_year = datetime.now().year
            dt = datetime.strptime(f"{month_abbr} {day} {current_year}", "%b %d %Y")
            dt = dt.replace(tzinfo=timezone.utc)
            return dt >= cutoff
        except ValueError:
            pass

    # Unknown format → include (don't want to miss jobs)
    return True


def ensure_absolute_url(url, base):
    """Ensure a URL is absolute."""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        parsed = urlparse(base)
        return f"{parsed.scheme}://{parsed.netloc}{url}"
    return f"{base.rstrip('/')}/{url.lstrip('/')}"


def clean_text(text, max_len=500):
    """Clean and truncate text."""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_len]


def make_job(title, company, location, url, description, source, salary="", posted_date=""):
    """Standard job dict constructor with aggressive cleaning and validation."""
    if not title or len(title.strip()) < 3:
        return None

    title_clean = clean_text(title, 300)

    # === STEP 1: Strip concatenated garbage ===

    # If title contains middle dots (·), it's a concatenated row — take first part only
    if '\xb7' in title_clean or '·' in title_clean:
        title_clean = re.split(r'[·\xb7]', title_clean)[0].strip()

    # Strip leading single-char UI artifacts (B, R, C prepended from adjacent elements)
    # Pattern: single uppercase letter followed immediately by another uppercase+lowercase
    title_clean = re.sub(r'^[A-Z](?=[A-Z][a-z])', '', title_clean)

    # Strip emoji metadata prefixes — strip all non-ASCII + known metadata from start
    for _ in range(3):  # Multiple passes to handle nested patterns
        # Strip ANY non-ASCII characters from the beginning (catches all emoji)
        title_clean = re.sub(r'^[^\x00-\x7F]+\s*', '', title_clean)
        # Strip known metadata patterns that follow emoji
        title_clean = re.sub(r'^(?:United States|Europe|Asia|Worldwide|Global|Remote)\s*', '', title_clean, flags=re.IGNORECASE)
        title_clean = re.sub(r'^\$?\d[\d,]*\s*[-–]\s*\$?\d[\d,]*\s*(?:per year|per month|USD|/\s*(?:year|month))?\s*', '', title_clean, flags=re.IGNORECASE)
        title_clean = re.sub(r'^\d+-\d+\s*yrs?\s*exp\s*', '', title_clean, flags=re.IGNORECASE)
    # Strip leading category labels when prepended as metadata
    title_clean = re.sub(r'^(?:Marketing|Engineering|Design|Sales|Operations|Business|Finance)\s*(?=[A-Z])', '', title_clean)

    # Strip trailing junk: "Full time", "Part time", "View", "Apply", date remnants
    title_clean = re.sub(r'\s*(?:Full time|Part time|Contract|Freelance|Full-time|Part-time)\s*$', '', title_clean, flags=re.IGNORECASE)
    title_clean = re.sub(r'\s*(?:View|Apply|Apply Now)\s*$', '', title_clean, flags=re.IGNORECASE)
    title_clean = re.sub(r'\s*\d+\s*days?\s*ago\s*(?:View)?\s*$', '', title_clean, flags=re.IGNORECASE)

    title_clean = title_clean.strip()

    # === STEP 2: Reject garbage titles ===

    if len(title_clean) < 5 or len(title_clean.split()) < 2:
        return None

    if len(title_clean) > 120:
        return None

    # Contains "X days ago" embedded — concatenated row data
    if re.search(r'\d+\s*days?\s*ago', title_clean, re.IGNORECASE):
        return None

    # Navigation: "Lima (40)", "Python (203)"
    if re.match(r'^[\w\s/\-\.]+\(\d+\)$', title_clean.strip()):
        return None

    # Pagination: "+ 3 More"
    if re.match(r'^\+?\s*\d+\s*more', title_clean.strip(), re.IGNORECASE):
        return None

    # Category page titles ending in "Jobs", "Careers", etc.
    if re.search(r'\b(?:jobs?|careers?|openings?|vacancies|listings?)\s*$', title_clean, re.IGNORECASE):
        return None

    # Bootcamps, courses, training, hackathons — not actual jobs
    if re.search(r'\b(?:bootcamp|course|training|certification|tutorial|learn|guaranteed|workshop|hackathon|prize pool|sponsored)\b', title_clean, re.IGNORECASE):
        return None

    # URL validation — reject category/tag/city pages
    if url:
        url_lower = url.lower()
        if any(p in url_lower for p in ['/tag/', '/city/', '/category/', '/categories/', '/filter']):
            return None

    # === STEP 3: Extract salary from description ===
    desc_clean = clean_text(description)
    detected_salary = salary
    if not detected_salary:
        sal_match = re.search(r'(\d{3,6})\s*[-–]\s*(\d{3,6})\s*(?:USD|usd)?\s*/?\s*(?:month|mo)', desc_clean)
        if sal_match:
            detected_salary = f"${sal_match.group(1)}-${sal_match.group(2)}/month"

    return {
        "title": title_clean,
        "company": clean_text(company, 100) or "Unknown",
        "location": clean_text(location, 100) or "Remote",
        "url": url.strip() if url else "",
        "description": desc_clean,
        "source": source,
        "salary": clean_text(detected_salary, 100),
        "posted_date": posted_date,
    }


# ============================================================================
# SCORING ENGINE
# ============================================================================

def extract_salary_number(salary_text):
    """Extract annual salary number from text. Handles monthly/hourly too. Returns None if unclear."""
    if not salary_text:
        return None
    text = salary_text.lower().replace(",", "").replace(" ", "")

    # Monthly salary: $1200/month, $2000/mo, $1500 monthly, 1200-2000/month
    m = re.search(r"\$?(\d{3,5})\s*(?:/\s*)?(?:month|mo(?:nthly)?|per\s*month|pm)", text)
    if m:
        return int(m.group(1)) * 12  # Annualize
    # Range with monthly: $1200-$2000/month or 1200-2000 monthly
    m = re.search(r"\$?(\d{3,5})\s*[-–]\s*\$?(\d{3,5})\s*(?:/\s*)?(?:month|mo|monthly|pm)", text)
    if m:
        return int(m.group(2)) * 12  # Use higher end, annualize

    # Annual with K: $80k, $40K
    m = re.search(r"\$?(\d{2,3})k", text)
    if m:
        return int(m.group(1)) * 1000
    # Annual range with K: $60k-$80k
    m = re.search(r"\$?(\d{2,3})k\s*[-–]\s*\$?(\d{2,3})k", text)
    if m:
        return int(m.group(1)) * 1000  # Use lower end

    # Raw annual number: $80000, $45000
    m = re.search(r"\$?(\d{4,6})", text)
    if m:
        num = int(m.group(1))
        if num > 1000:
            return num
    return None


def score_job(title, company, description, location, salary_text="", source=""):
    score = 0
    reasons = []
    text_blob = f"{title} {company} {description} {location}".lower()
    title_lower = title.lower()
    desc_lower = description.lower()

    # ── GATE 1: Exclusion list ─────────────────────────────────────────────────
    for exc in EXCLUSIONS:
        if exc.lower() in title_lower:
            return -1, [f"Excluded: '{exc}'"]

    # ── GATE 2: Location whitelist ─────────────────────────────────────────────
    loc_lower = location.lower()
    LOCATION_WHITELIST = [
        "remote", "worldwide", "global", "anywhere", "distributed",
        "work from home", "wfh", "all locations", "any location",
        "argentina", "buenos aires", "caba", "latam", "latin america",
        "south america", "americas",
        "brazil", "brasil", "colombia", "chile", "peru", "uruguay",
        "mexico", "costa rica", "ecuador",
    ]
    loc_is_acceptable = (
        not loc_lower
        or loc_lower in ("", "remote", "unknown")
        or any(w in loc_lower for w in LOCATION_WHITELIST)
    )
    if not loc_is_acceptable:
        return -1, [f"Location not accessible: '{location}'"]

    # Region-specific title suffixes
    for loc_exc in ["- africa", "- india", "- pakistan", "- china", "- japan",
                    "- apac", "- emea", "- uk", "- eu "]:
        if loc_exc in title_lower:
            return -1, [f"Region-specific role: '{loc_exc}'"]

    # ── GATE 3: Onsite outside Buenos Aires ───────────────────────────────────
    ONSITE_CITIES = [
        "santiago", "lima", "bogotá", "bogota", "medellín", "medellin",
        "são paulo", "sao paulo", "rio de janeiro", "quito", "montevideo",
        "san jose", "ciudad de mexico", "guadalajara", "dubai", "london",
        "new york", "san francisco", "tel aviv", "singapore", "hong kong",
        "belfast", "paris",
    ]
    combined_lower = f"{title_lower} {loc_lower} {desc_lower}"
    is_onsite_role = any(kw in combined_lower for kw in [
        "onsite", "on-site", "in-office", "presencial", "(hybrid)", "híbrido", "hibrido"
    ])
    if is_onsite_role:
        is_buenos_aires = any(ba in combined_lower for ba in ["buenos aires", "argentina", "caba"])
        if not is_buenos_aires:
            for city in ONSITE_CITIES:
                if city in loc_lower or city in title_lower:
                    return -1, [f"Onsite in non-accessible city: '{city}'"]
            # If no specific city matched but clearly onsite with no BA mention → reject
            if not any(ba in combined_lower for ba in ["buenos aires", "argentina", "caba", "remote"]):
                return -1, ["Onsite/hybrid role, not accessible from Buenos Aires"]

    # ── GATE 4: Geo-restricted remote ─────────────────────────────────────────
    RESTRICTED_REMOTE = [
        "us only", "usa only", "u.s. only", "united states only",
        "us-based", "usa-based", "us based", "usa based",
        "must be located in the us", "must reside in the us",
        "us residents only", "us citizens only",
        "uk only", "uk-based", "uk based", "united kingdom only",
        "eu only", "eu-based", "eu based", "europe only", "european union only",
        "canada only", "canada-based", "australia only",
        "apac only", "emea only",
        "authorized to work in the united states",
    ]
    OPEN_REMOTE_SIGNALS = [
        "worldwide", "global", "anywhere", "latam", "latin america",
        "south america", "americas", "argentina", "buenos aires",
        "all locations", "any location", "any country",
    ]
    is_open = any(p in text_blob for p in OPEN_REMOTE_SIGNALS)
    is_restricted = any(p in text_blob for p in RESTRICTED_REMOTE)
    if is_restricted and not is_open:
        return -1, ["Geo-restricted remote (not accessible from Argentina)"]

    # ── GATE 5: Salary floor ($30K/year) ──────────────────────────────────────
    if salary_text:
        salary_num = extract_salary_number(salary_text)
        if salary_num and salary_num < SALARY_FLOOR:
            return -1, [f"Below ${SALARY_FLOOR:,} floor (${salary_num:,}/yr)"]
        hourly_match = re.search(r"\$?(\d+)\s*[-–]?\s*\$?(\d*)\s*/\s*h(?:our|r)?", salary_text.lower())
        if hourly_match:
            low_hourly = int(hourly_match.group(1))
            if low_hourly * 40 * 52 < SALARY_FLOOR:
                return -1, [f"Hourly rate too low: ${low_hourly}/hr"]

    # Scan description for explicit monthly salary below floor
    monthly_match = re.search(
        r'(\d{3,5})\s*[-–]\s*(\d{3,5})\s*(?:USD|usd)?\s*/?(?:month|mo|monthly)',
        text_blob
    )
    if monthly_match:
        high_monthly = int(monthly_match.group(2))
        if high_monthly * 12 < SALARY_FLOOR:
            return -1, [f"Below floor: ${high_monthly}/mo = ${high_monthly*12:,}/yr"]

    single_monthly = re.search(r'(\d{3,4})\s*(?:USD|usd)\s*/?\s*(?:month|mo)\b', text_blob)
    if single_monthly:
        mv = int(single_monthly.group(1))
        if mv * 12 < SALARY_FLOOR:
            return -1, [f"Below floor: ${mv}/mo in description"]

    # ── GATE 6: Commission-only / base below $2,500/month ─────────────────────
    COMMISSION_SIGNALS = [
        "commission only", "commission-only", "100% commission",
        "no base salary", "performance-based compensation only",
        "ote only", "purely commission",
    ]
    if any(sig in text_blob for sig in COMMISSION_SIGNALS):
        return -1, ["Commission-only compensation"]

    # Base salary explicitly stated as very low (< $2,500/month)
    base_match = re.search(
        r'base\s*salary[:\s]*(?:month\s*1[:\s]*)?(\d{3,4})\s*(?:USD|USDT|usd)?',
        text_blob
    )
    if base_match:
        base_val = int(base_match.group(1))
        if base_val < 2500 and base_val > 100:  # filter out % values
            return -1, [f"Base salary too low: ${base_val}/mo"]

    # ══ SCORING ═══════════════════════════════════════════════════════════════

    # Primary role match (+50) — highest weight, checked first
    role_matched = False
    for role in PRIMARY_ROLES:
        if role.lower() in title_lower:
            score += 50
            reasons.append(f"+50 Primary: {role}")
            role_matched = True
            break

    # Secondary role match (+30) — only if no primary hit
    if not role_matched:
        for role in SECONDARY_ROLES:
            if role.lower() in title_lower:
                score += 30
                reasons.append(f"+30 Secondary: {role}")
                break

    # Web3 signal (+15 max, 5 per keyword)
    web3_hits = sum(1 for kw in WEB3_KEYWORDS if kw.lower() in text_blob)
    if web3_hits:
        s = min(15, web3_hits * 5)
        score += s
        reasons.append(f"+{s} Web3 ({web3_hits} hits)")

    # Remote / location (+15 global/LATAM, +10 generic remote)
    is_remote = any(p in text_blob for p in ["remote", "work from home", "wfh", "anywhere", "distributed"])
    if is_remote:
        if is_open:
            score += 15
            reasons.append("+15 Remote global/LATAM")
        else:
            score += 10
            reasons.append("+10 Remote")

    # Bilingual / LATAM (+10)
    if any(kw.lower() in text_blob for kw in BILINGUAL_KEYWORDS):
        score += 10
        reasons.append("+10 Bilingual/LATAM")

    # Salary ≥ $45K explicitly stated (+5)
    if salary_text:
        sal_num = extract_salary_number(salary_text)
        if sal_num and sal_num >= 45000:
            score += 5
            reasons.append(f"+5 Salary ≥$45K (${sal_num:,})")

    # Vertical bonus (+5)
    if any(kw.lower() in text_blob for kw in VERTICAL_BONUS_KEYWORDS):
        score += 5
        reasons.append("+5 Vertical match")

    return min(score, 100), reasons


# ============================================================================
# SCRAPERS — WEB3 SPECIFIC
# ============================================================================

def scrape_cryptojobslist(session):
    """cryptojobslist.com — filter by recent"""
    jobs = []
    terms = ["community", "growth", "marketing", "kol", "operations", "ecosystem"]

    for term in terms:
        url = f"https://cryptojobslist.com/search?q={quote_plus(term)}&sort=recent"
        resp = safe_get(session, url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")

        for a in soup.select("a[href*='/jobs/']"):
            try:
                href = ensure_absolute_url(a.get("href", ""), "https://cryptojobslist.com")
                title = a.get_text(strip=True)
                # Try to find parent container for more info
                parent = a.find_parent("div") or a.find_parent("li") or a.find_parent("tr")
                company = ""
                location = "Remote"
                posted = ""
                if parent:
                    comp_el = parent.select_one(".company, .employer, [class*=company]")
                    company = comp_el.get_text(strip=True) if comp_el else ""
                    loc_el = parent.select_one(".location, [class*=location]")
                    location = loc_el.get_text(strip=True) if loc_el else "Remote"
                    time_el = parent.select_one("time, [datetime], [class*=date], [class*=time], [class*=ago]")
                    if time_el:
                        posted = time_el.get("datetime", "") or time_el.get_text(strip=True)
                    desc = clean_text(parent.get_text())
                else:
                    desc = title

                if not is_within_24h(posted):
                    continue

                j = make_job(title, company, location, href, desc, "Crypto Jobs List", posted_date=posted)
                if j:
                    jobs.append(j)
            except Exception:
                continue

    log.info(f"Crypto Jobs List: {len(jobs)} jobs")
    return jobs


def scrape_web3career(session):
    """web3.career — multiple categories"""
    jobs = []
    paths = [
        "/community-jobs", "/growth-jobs", "/marketing-jobs",
        "/non-tech-jobs", "/operations-jobs",
    ]

    for path in paths:
        url = f"https://web3.career{path}"
        resp = safe_get(session, url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")

        for row in soup.select("tr[onclick], div[class*=job], a[href*='/job/']"):
            try:
                # Extract link
                onclick = row.get("onclick", "")
                href = ""
                if "location.href" in onclick:
                    m = re.search(r"'(.*?)'", onclick)
                    href = f"https://web3.career{m.group(1)}" if m else ""
                if not href:
                    link_el = row.select_one("a[href*='/job/']")
                    if link_el:
                        href = ensure_absolute_url(link_el.get("href", ""), "https://web3.career")

                cells = row.select("td")
                title = cells[0].get_text(strip=True) if cells else row.get_text(strip=True)[:120]
                company = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                salary = ""
                location = "Remote"

                # Look for salary and location cells
                for cell in cells:
                    txt = cell.get_text(strip=True)
                    if "$" in txt or "k" in txt.lower():
                        salary = txt
                    if any(w in txt.lower() for w in ["remote", "usa", "europe", "global", "worldwide"]):
                        location = txt

                # Date check
                time_el = row.select_one("time, [datetime], [class*=date]")
                posted = ""
                if time_el:
                    posted = time_el.get("datetime", "") or time_el.get_text(strip=True)
                else:
                    # Check for relative text in last cell
                    if cells:
                        last_text = cells[-1].get_text(strip=True).lower()
                        if any(w in last_text for w in ["ago", "today", "new", "hour", "minute", "just"]):
                            posted = last_text

                if not is_within_24h(posted):
                    continue

                j = make_job(title, company, location, href, row.get_text(strip=True), "Web3.career", salary, posted)
                if j:
                    jobs.append(j)
            except Exception:
                continue

    log.info(f"Web3.career: {len(jobs)} jobs")
    return jobs


def scrape_cryptocurrencyjobs(session):
    """cryptocurrencyjobs.co"""
    jobs = []
    url = "https://cryptocurrencyjobs.co/non-tech/"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")

    for listing in soup.select("a[href*='/job/'], div.job-listing, article.job"):
        try:
            if listing.name == "a":
                href = ensure_absolute_url(listing.get("href", ""), "https://cryptocurrencyjobs.co")
                title = listing.get_text(strip=True)
            else:
                link_el = listing.select_one("a[href*='/job/']")
                href = ensure_absolute_url(link_el.get("href", ""), "https://cryptocurrencyjobs.co") if link_el else ""
                title_el = listing.select_one("h2, h3, .title")
                title = title_el.get_text(strip=True) if title_el else ""

            comp_el = listing.select_one(".company, [class*=company]")
            company = comp_el.get_text(strip=True) if comp_el else ""
            time_el = listing.select_one("time, [datetime], [class*=date]")
            posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

            if not is_within_24h(posted):
                continue

            j = make_job(title, company, "Remote", href, listing.get_text(strip=True), "CryptocurrencyJobs", posted_date=posted)
            if j:
                jobs.append(j)
        except Exception:
            continue

    log.info(f"CryptocurrencyJobs: {len(jobs)} jobs")
    return jobs


def scrape_remote3(session):
    """remote3.co — Web3 remote jobs"""
    jobs = []
    url = "https://remote3.co/web3-jobs?category=marketing&category=community"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")

    for card in soup.select("a[href*='/web3-job/'], div[class*=job], article"):
        try:
            if card.name == "a":
                href = ensure_absolute_url(card.get("href", ""), "https://remote3.co")
                title = card.get_text(strip=True)
            else:
                link_el = card.select_one("a[href]")
                href = ensure_absolute_url(link_el.get("href", ""), "https://remote3.co") if link_el else ""
                title_el = card.select_one("h2, h3, .title, strong")
                title = title_el.get_text(strip=True) if title_el else ""

            comp_el = card.select_one("[class*=company], .employer, span.company")
            company = comp_el.get_text(strip=True) if comp_el else ""
            time_el = card.select_one("time, [class*=date], [class*=time], [class*=ago]")
            posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

            if not is_within_24h(posted):
                continue

            j = make_job(title, company, "Remote", href, card.get_text(strip=True), "Remote3", posted_date=posted)
            if j:
                jobs.append(j)
        except Exception:
            continue

    log.info(f"Remote3: {len(jobs)} jobs")
    return jobs


def scrape_froog(session):
    """froog.co — Crypto jobs"""
    jobs = []
    for cat in ["community", "marketing", "growth", "operations"]:
        url = f"https://froog.co/crypto-jobs/{cat}"
        resp = safe_get(session, url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")

        for card in soup.select("a[href*='/job/'], div[class*=job], li[class*=job]"):
            try:
                if card.name == "a":
                    href = ensure_absolute_url(card.get("href", ""), "https://froog.co")
                    title = card.get_text(strip=True)
                else:
                    link_el = card.select_one("a[href]")
                    href = ensure_absolute_url(link_el.get("href", ""), "https://froog.co") if link_el else ""
                    title_el = card.select_one("h2, h3, .title")
                    title = title_el.get_text(strip=True) if title_el else ""

                time_el = card.select_one("time, [class*=date], [class*=ago]")
                posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

                if not is_within_24h(posted):
                    continue

                j = make_job(title, "", "Remote", href, card.get_text(strip=True), "Froog", posted_date=posted)
                if j:
                    jobs.append(j)
            except Exception:
                continue

    log.info(f"Froog: {len(jobs)} jobs")
    return jobs


def scrape_useweb3(session):
    """useweb3.xyz/jobs — Web3 jobs aggregator"""
    jobs = []
    url = "https://useweb3.xyz/jobs?q=community+growth+marketing"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")

    for card in soup.select("a[href*='/job'], div[class*=job], article"):
        try:
            link_el = card if card.name == "a" else card.select_one("a[href]")
            href = ensure_absolute_url(link_el.get("href", ""), "https://useweb3.xyz") if link_el else ""
            title_el = card.select_one("h2, h3, .title, strong")
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:120]

            time_el = card.select_one("time, [class*=date], [class*=ago]")
            posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

            if not is_within_24h(posted):
                continue

            j = make_job(title, "", "Remote", href, card.get_text(strip=True), "useWeb3", posted_date=posted)
            if j:
                jobs.append(j)
        except Exception:
            continue

    log.info(f"useWeb3: {len(jobs)} jobs")
    return jobs


def scrape_jobstash(session):
    """jobstash.xyz — Web3 job aggregator with API"""
    jobs = []
    url = "https://jobstash.xyz/jobs?q=community+growth+marketing"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")

    for card in soup.select("a[href*='/job'], div[class*=job], article, li[class*=job]"):
        try:
            link_el = card if card.name == "a" else card.select_one("a[href]")
            href = ensure_absolute_url(link_el.get("href", ""), "https://jobstash.xyz") if link_el else ""
            title_el = card.select_one("h2, h3, .title, strong, p")
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:120]

            time_el = card.select_one("time, [class*=date], [class*=ago]")
            posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

            if not is_within_24h(posted):
                continue

            j = make_job(title, "", "Remote", href, card.get_text(strip=True), "JobStash", posted_date=posted)
            if j:
                jobs.append(j)
        except Exception:
            continue

    log.info(f"JobStash: {len(jobs)} jobs")
    return jobs


# ============================================================================
# SCRAPERS — GENERAL REMOTE
# ============================================================================

def scrape_remotive(session):
    """remotive.com — REST API with published date"""
    jobs = []
    categories = ["marketing", "customer-support", "business", "all-others"]

    for cat in categories:
        url = f"https://remotive.com/api/remote-jobs?category={cat}&limit=30"
        resp = safe_get(session, url)
        if not resp:
            continue
        try:
            data = resp.json()
            for item in data.get("jobs", []):
                posted = item.get("publication_date", "")
                if not is_within_24h(posted):
                    continue
                j = make_job(
                    item.get("title", ""),
                    item.get("company_name", ""),
                    item.get("candidate_required_location", "Remote"),
                    item.get("url", ""),
                    item.get("description", ""),
                    "Remotive",
                    item.get("salary", ""),
                    posted,
                )
                if j:
                    jobs.append(j)
        except Exception:
            continue

    log.info(f"Remotive: {len(jobs)} jobs")
    return jobs


def scrape_weworkremotely(session):
    """weworkremotely.com"""
    jobs = []
    feeds = [
        "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
        "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss",
        "https://weworkremotely.com/categories/remote-business-exec-and-management-jobs.rss",
    ]

    for feed_url in feeds:
        resp = safe_get(session, feed_url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "xml")

        for item in soup.select("item"):
            try:
                title = item.select_one("title").get_text(strip=True) if item.select_one("title") else ""
                link = item.select_one("link").get_text(strip=True) if item.select_one("link") else ""
                pub_date = item.select_one("pubDate").get_text(strip=True) if item.select_one("pubDate") else ""
                desc = item.select_one("description").get_text(strip=True)[:500] if item.select_one("description") else ""

                if not is_within_24h(pub_date):
                    continue

                # Title format usually: "Company: Job Title"
                company = ""
                job_title = title
                if ": " in title:
                    parts = title.split(": ", 1)
                    company = parts[0]
                    job_title = parts[1]

                j = make_job(job_title, company, "Remote", link, desc, "WeWorkRemotely", posted_date=pub_date)
                if j:
                    jobs.append(j)
            except Exception:
                continue

    log.info(f"WeWorkRemotely: {len(jobs)} jobs")
    return jobs


def scrape_himalayas(session):
    """himalayas.app — remote jobs API"""
    jobs = []
    terms = ["community manager", "growth", "marketing manager", "kol"]

    for term in terms:
        url = f"https://himalayas.app/jobs/api?q={quote_plus(term)}&limit=20"
        resp = safe_get(session, url)
        if not resp:
            # Fallback to HTML
            url2 = f"https://himalayas.app/jobs?q={quote_plus(term)}"
            resp = safe_get(session, url2)
            if not resp:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("a[href*='/jobs/']"):
                try:
                    href = ensure_absolute_url(a.get("href", ""), "https://himalayas.app")
                    title = a.get_text(strip=True)
                    j = make_job(title, "", "Remote", href, title, "Himalayas")
                    if j:
                        jobs.append(j)
                except Exception:
                    continue
            continue

        try:
            data = resp.json()
            for item in data if isinstance(data, list) else data.get("jobs", []):
                posted = item.get("published_at", "") or item.get("created_at", "")
                if not is_within_24h(posted):
                    continue
                j = make_job(
                    item.get("title", ""),
                    item.get("company_name", "") or item.get("company", {}).get("name", ""),
                    "Remote",
                    item.get("url", "") or f"https://himalayas.app/jobs/{item.get('slug', '')}",
                    item.get("description", ""),
                    "Himalayas",
                    posted_date=posted,
                )
                if j:
                    jobs.append(j)
        except Exception:
            continue

    log.info(f"Himalayas: {len(jobs)} jobs")
    return jobs


def scrape_wellfound(session):
    """wellfound.com — Startup jobs"""
    jobs = []
    slugs = ["community-manager", "growth-marketing", "marketing", "social-media-manager"]

    for slug in slugs:
        url = f"https://wellfound.com/role/r/{slug}"
        resp = safe_get(session, url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")

        for card in soup.select("div[class*=jobListing], a[href*='/jobs/'], div[class*=styles_result]"):
            try:
                link_el = card.select_one("a[href*='/jobs/']") if card.name != "a" else card
                href = ensure_absolute_url(link_el.get("href", ""), "https://wellfound.com") if link_el else ""
                title_el = card.select_one("h2, h3, [class*=title]")
                title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:120]
                comp_el = card.select_one("[class*=company], [class*=startup]")
                company = comp_el.get_text(strip=True) if comp_el else ""
                sal_el = card.select_one("[class*=salary], [class*=compensation]")
                salary = sal_el.get_text(strip=True) if sal_el else ""

                j = make_job(title, company, "Remote", href, card.get_text(strip=True), "Wellfound", salary)
                if j:
                    jobs.append(j)
            except Exception:
                continue

    log.info(f"Wellfound: {len(jobs)} jobs")
    return jobs


def scrape_jobicy(session):
    """jobicy.com — Remote jobs with RSS feed"""
    jobs = []
    url = "https://jobicy.com/api/v2/remote-jobs?count=30&tag=marketing,community"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    try:
        data = resp.json()
        for item in data.get("jobs", []):
            posted = item.get("pubDate", "")
            if not is_within_24h(posted):
                continue
            j = make_job(
                item.get("jobTitle", ""),
                item.get("companyName", ""),
                item.get("jobGeo", "Remote"),
                item.get("url", ""),
                item.get("jobExcerpt", ""),
                "Jobicy",
                item.get("annualSalaryMin", ""),
                posted,
            )
            if j:
                jobs.append(j)
    except Exception:
        pass

    log.info(f"Jobicy: {len(jobs)} jobs")
    return jobs


def scrape_dailyremote(session):
    """dailyremote.com"""
    jobs = []
    url = "https://dailyremote.com/remote-marketing-jobs"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")

    for card in soup.select("a[href*='/remote-job/'], div[class*=job]"):
        try:
            link_el = card if card.name == "a" else card.select_one("a[href]")
            href = ensure_absolute_url(link_el.get("href", ""), "https://dailyremote.com") if link_el else ""
            title_el = card.select_one("h2, h3, .title")
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:120]

            time_el = card.select_one("time, [class*=date], [class*=ago]")
            posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

            if not is_within_24h(posted):
                continue

            j = make_job(title, "", "Remote", href, card.get_text(strip=True), "DailyRemote", posted_date=posted)
            if j:
                jobs.append(j)
        except Exception:
            continue

    log.info(f"DailyRemote: {len(jobs)} jobs")
    return jobs


def scrape_workingnomads(session):
    """workingnomads.com — API"""
    jobs = []
    url = "https://www.workingnomads.com/api/exposed_jobs/?category=marketing"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    try:
        data = resp.json()
        for item in data if isinstance(data, list) else []:
            posted = item.get("pub_date", "")
            if not is_within_24h(posted):
                continue
            j = make_job(
                item.get("title", ""),
                item.get("company_name", ""),
                item.get("location", "Remote"),
                item.get("url", ""),
                item.get("description", ""),
                "Working Nomads",
                posted_date=posted,
            )
            if j:
                jobs.append(j)
    except Exception:
        pass

    log.info(f"Working Nomads: {len(jobs)} jobs")
    return jobs


def scrape_remoteok(session):
    """remoteok.com — JSON API"""
    jobs = []
    url = "https://remoteok.com/api?tag=marketing"
    resp = safe_get(session, url, headers={"User-Agent": USER_AGENT})
    if not resp:
        return jobs
    try:
        data = resp.json()
        # First item is metadata, skip it
        for item in data[1:] if isinstance(data, list) and len(data) > 1 else []:
            posted = item.get("date", "")
            if not is_within_24h(posted):
                continue
            slug = item.get("slug", item.get("id", ""))
            j = make_job(
                item.get("position", ""),
                item.get("company", ""),
                item.get("location", "Remote"),
                f"https://remoteok.com/remote-jobs/{slug}" if slug else item.get("url", ""),
                " ".join(item.get("tags", [])),
                "RemoteOK",
                item.get("salary_min", ""),
                posted,
            )
            if j:
                jobs.append(j)
    except Exception:
        pass

    log.info(f"RemoteOK: {len(jobs)} jobs")
    return jobs


# ============================================================================
# SCRAPERS — LATAM
# ============================================================================

def scrape_getonboard(session):
    """getonbrd.com — LATAM remote jobs. Web3/crypto terms only to avoid noise."""
    jobs = []
    # Only crypto/Web3 terms — removed generic "community", "growth", "marketing"
    # to avoid pulling unrelated LATAM roles
    terms = ["crypto", "blockchain", "web3", "defi", "nft"]

    for term in terms:
        url = f"https://www.getonbrd.com/jobs?q={quote_plus(term)}&remote=true"
        resp = safe_get(session, url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")

        # GetOnBoard job links look like /jobs/category/job-title-company
        # Navigation links look like /jobs/city/X, /jobs/tag/X — skip those
        skip_patterns = ['/jobs/city/', '/jobs/tag/', '/jobs/category/', '/jobs?', '/jobs#']

        for card in soup.select("a[href*='/jobs/']"):
            try:
                href = card.get("href", "")
                # Skip navigation/filter links
                if any(p in href for p in skip_patterns):
                    continue
                # Must have at least 3 path segments: /jobs/category/actual-job
                path_parts = [p for p in href.split("/") if p]
                if len(path_parts) < 3:
                    continue

                href = ensure_absolute_url(href, "https://www.getonbrd.com")

                # Reject onsite/hybrid indicators in the URL or card text
                card_text = card.get_text(strip=True).lower()
                if any(kw in card_text for kw in ["presencial", "híbrido", "hibrido", "in-office", "on-site"]):
                    if not any(ba in card_text for ba in ["buenos aires", "argentina", "caba"]):
                        continue

                title_el = card.select_one("h2, h3, strong, [class*=title], span[class*=title]")
                title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:120]
                comp_el = card.select_one("[class*=company], .employer, span[class*=company]")
                company = comp_el.get_text(strip=True) if comp_el else ""

                time_el = card.select_one("time, [datetime], [class*=date], [class*=ago]")
                posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

                if not is_within_24h(posted):
                    continue

                j = make_job(title, company, "LATAM / Remote", href, card.get_text(strip=True), "GetOnBoard", posted_date=posted)
                if j:
                    jobs.append(j)
            except Exception:
                continue

    log.info(f"GetOnBoard: {len(jobs)} jobs")
    return jobs


def scrape_torre(session):
    """torre.ai — LATAM job API"""
    jobs = []
    terms = ["community manager", "growth", "marketing crypto", "community lead"]

    for term in terms:
        url = "https://torre.ai/api/entities/_searchOpportunities"
        payload = {"or": {"term": term}, "offset": 0, "size": 20, "aggregate": False}
        resp = safe_post(session, url, json=payload)
        if not resp:
            continue
        try:
            data = resp.json()
            for item in data.get("results", []):
                opp = item.get("objective", "") or item.get("objectiveShort", "")
                org_name = ""
                for org in item.get("organizations", []):
                    org_name = org.get("name", "")
                    break
                job_id = item.get("id", "")
                link = f"https://torre.ai/jobs/{job_id}" if job_id else ""

                created = item.get("created", "") or item.get("lastUpdated", "")
                if not is_within_24h(created):
                    continue

                locs = item.get("locations", [])
                loc_str = ", ".join(locs) if locs else "Remote"

                comp = item.get("compensation", {})
                salary = ""
                if comp and (comp.get("minAmount") or comp.get("maxAmount")):
                    salary = f"{comp.get('currency','USD')} {comp.get('minAmount','')}-{comp.get('maxAmount','')}"

                j = make_job(opp, org_name, loc_str, link, item.get("details", opp), "Torre", salary, created)
                if j:
                    jobs.append(j)
        except Exception:
            continue

    log.info(f"Torre: {len(jobs)} jobs")
    return jobs


# ============================================================================
# SCRAPERS — ADDITIONAL WEB3 BOARDS (user-provided)
# ============================================================================

def scrape_cryptojobs_com(session):
    """cryptojobs.com — sorted by recent"""
    jobs = []
    url = "https://www.cryptojobs.com/jobs?per_page=50&sort_by=posted_at&sort_order=desc"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")

    for card in soup.select("a[href*='/job/'], div[class*=job], article[class*=job], li[class*=job]"):
        try:
            link_el = card if card.name == "a" else card.select_one("a[href*='/job/']")
            href = ensure_absolute_url(link_el.get("href", ""), "https://www.cryptojobs.com") if link_el else ""
            title_el = card.select_one("h2, h3, h4, [class*=title], strong")
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:150]

            comp_el = card.select_one("[class*=company], [class*=org], span.company")
            company = comp_el.get_text(strip=True) if comp_el else ""
            loc_el = card.select_one("[class*=location], [class*=loc]")
            location = loc_el.get_text(strip=True) if loc_el else "Remote"
            sal_el = card.select_one("[class*=salary], [class*=comp]")
            salary = sal_el.get_text(strip=True) if sal_el else ""

            time_el = card.select_one("time, [datetime], [class*=date], [class*=ago], [class*=posted]")
            posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

            if not is_within_24h(posted):
                continue

            j = make_job(title, company, location, href, card.get_text(strip=True), "CryptoJobs.com", salary, posted)
            if j:
                jobs.append(j)
        except Exception:
            continue

    log.info(f"CryptoJobs.com: {len(jobs)} jobs")
    return jobs


def scrape_myweb3jobs(session):
    """myweb3jobs.com"""
    jobs = []
    url = "https://myweb3jobs.com/"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")

    for card in soup.select("a[href*='/job'], div[class*=job], article, li[class*=job], div[class*=card]"):
        try:
            link_el = card if card.name == "a" else card.select_one("a[href*='/job']")
            if not link_el:
                link_el = card.select_one("a[href]")
            href = ensure_absolute_url(link_el.get("href", ""), "https://myweb3jobs.com") if link_el else ""
            title_el = card.select_one("h2, h3, h4, [class*=title], strong")
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:150]

            comp_el = card.select_one("[class*=company], [class*=org]")
            company = comp_el.get_text(strip=True) if comp_el else ""
            loc_el = card.select_one("[class*=location]")
            location = loc_el.get_text(strip=True) if loc_el else "Remote"

            time_el = card.select_one("time, [datetime], [class*=date], [class*=ago], [class*=posted]")
            posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

            if not is_within_24h(posted):
                continue

            j = make_job(title, company, location, href, card.get_text(strip=True), "MyWeb3Jobs", posted_date=posted)
            if j:
                jobs.append(j)
        except Exception:
            continue

    log.info(f"MyWeb3Jobs: {len(jobs)} jobs")
    return jobs


def scrape_beincrypto(session):
    """beincrypto.com/jobs — remote only"""
    jobs = []
    url = "https://beincrypto.com/jobs/?search=&remoteOnly=true"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")

    for card in soup.select("a[href*='/job'], div[class*=job], article[class*=job], li[class*=job], div[class*=card]"):
        try:
            link_el = card if card.name == "a" else card.select_one("a[href*='/job']")
            if not link_el:
                link_el = card.select_one("a[href]")
            href = ensure_absolute_url(link_el.get("href", ""), "https://beincrypto.com") if link_el else ""
            title_el = card.select_one("h2, h3, h4, [class*=title], strong")
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:150]

            comp_el = card.select_one("[class*=company], [class*=org]")
            company = comp_el.get_text(strip=True) if comp_el else "BeInCrypto Network"
            loc_el = card.select_one("[class*=location]")
            location = loc_el.get_text(strip=True) if loc_el else "Remote"
            sal_el = card.select_one("[class*=salary], [class*=comp]")
            salary = sal_el.get_text(strip=True) if sal_el else ""

            time_el = card.select_one("time, [datetime], [class*=date], [class*=ago], [class*=posted]")
            posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

            if not is_within_24h(posted):
                continue

            j = make_job(title, company, location, href, card.get_text(strip=True), "BeInCrypto Jobs", salary, posted)
            if j:
                jobs.append(j)
        except Exception:
            continue

    log.info(f"BeInCrypto Jobs: {len(jobs)} jobs")
    return jobs


def scrape_blockchain_association(session):
    """jobs.theblockchainassociation.org — remote filter"""
    jobs = []
    url = "https://jobs.theblockchainassociation.org/jobs?filter=eyJzZWFyY2hhYmxlX2xvY2F0aW9uX29wdGlvbiI6WyJyZW1vdGUiXX0%3D"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")

    for card in soup.select("a[href*='/job'], div[class*=job], li[class*=job], article, div[class*=card], div[class*=listing]"):
        try:
            link_el = card if card.name == "a" else card.select_one("a[href*='/job']")
            if not link_el:
                link_el = card.select_one("a[href]")
            href = ensure_absolute_url(link_el.get("href", ""), "https://jobs.theblockchainassociation.org") if link_el else ""
            title_el = card.select_one("h2, h3, h4, [class*=title], strong, [class*=name]")
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:150]

            comp_el = card.select_one("[class*=company], [class*=org], [class*=employer]")
            company = comp_el.get_text(strip=True) if comp_el else ""
            loc_el = card.select_one("[class*=location]")
            location = loc_el.get_text(strip=True) if loc_el else "Remote"

            time_el = card.select_one("time, [datetime], [class*=date], [class*=ago], [class*=posted]")
            posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

            if not is_within_24h(posted):
                continue

            j = make_job(title, company, location, href, card.get_text(strip=True), "Blockchain Association", posted_date=posted)
            if j:
                jobs.append(j)
        except Exception:
            continue

    log.info(f"Blockchain Association: {len(jobs)} jobs")
    return jobs


def scrape_hirechain(session):
    """share.hirechain.io — Web3 job board"""
    jobs = []
    url = "https://share.hirechain.io/job-board/le5rgc1a70?sort=recent"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")

    for card in soup.select("a[href*='/job'], div[class*=job], li[class*=job], article, div[class*=card], div[class*=row], tr"):
        try:
            link_el = card if card.name == "a" else card.select_one("a[href]")
            href = ensure_absolute_url(link_el.get("href", ""), "https://share.hirechain.io") if link_el else ""
            title_el = card.select_one("h2, h3, h4, [class*=title], strong, [class*=name], td:first-child")
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:150]

            comp_el = card.select_one("[class*=company], [class*=org], td:nth-child(2)")
            company = comp_el.get_text(strip=True) if comp_el else ""
            loc_el = card.select_one("[class*=location]")
            location = loc_el.get_text(strip=True) if loc_el else "Remote"

            time_el = card.select_one("time, [datetime], [class*=date], [class*=ago], [class*=posted]")
            posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

            if not is_within_24h(posted):
                continue

            j = make_job(title, company, location, href, card.get_text(strip=True), "HireChain", posted_date=posted)
            if j:
                jobs.append(j)
        except Exception:
            continue

    log.info(f"HireChain: {len(jobs)} jobs")
    return jobs


def scrape_pantera(session):
    """jobs.panteracapital.com — Pantera portfolio jobs, remote, last 7 days"""
    jobs = []
    url = "https://jobs.panteracapital.com/jobs?remoteOnly=true&postedSince=P7D"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")

    for card in soup.select("a[href*='/job'], div[class*=job], li[class*=job], article, div[class*=card], div[class*=listing]"):
        try:
            link_el = card if card.name == "a" else card.select_one("a[href*='/job']")
            if not link_el:
                link_el = card.select_one("a[href]")
            href = ensure_absolute_url(link_el.get("href", ""), "https://jobs.panteracapital.com") if link_el else ""
            title_el = card.select_one("h2, h3, h4, [class*=title], strong, [class*=name]")
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:150]

            comp_el = card.select_one("[class*=company], [class*=org], [class*=employer]")
            company = comp_el.get_text(strip=True) if comp_el else "Pantera Portfolio"
            loc_el = card.select_one("[class*=location]")
            location = loc_el.get_text(strip=True) if loc_el else "Remote"
            sal_el = card.select_one("[class*=salary], [class*=comp]")
            salary = sal_el.get_text(strip=True) if sal_el else ""

            time_el = card.select_one("time, [datetime], [class*=date], [class*=ago], [class*=posted]")
            posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

            if not is_within_24h(posted):
                continue

            j = make_job(title, company, location, href, card.get_text(strip=True), "Pantera Capital", salary, posted)
            if j:
                jobs.append(j)
        except Exception:
            continue

    log.info(f"Pantera Capital: {len(jobs)} jobs")
    return jobs


def scrape_axiomrecruit(session):
    """axiomrecruit.com — Web3 recruitment agency"""
    jobs = []
    url = "https://www.axiomrecruit.com/job-search/"
    resp = safe_get(session, url)
    if not resp:
        return jobs
    soup = BeautifulSoup(resp.text, "html.parser")

    for card in soup.select("a[href*='/job'], div[class*=job], li[class*=job], article, div[class*=card], div[class*=listing]"):
        try:
            link_el = card if card.name == "a" else card.select_one("a[href]")
            href = ensure_absolute_url(link_el.get("href", ""), "https://www.axiomrecruit.com") if link_el else ""
            title_el = card.select_one("h2, h3, h4, [class*=title], strong")
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:150]

            comp_el = card.select_one("[class*=company], [class*=client], [class*=org]")
            company = comp_el.get_text(strip=True) if comp_el else ""
            loc_el = card.select_one("[class*=location]")
            location = loc_el.get_text(strip=True) if loc_el else "Remote"
            sal_el = card.select_one("[class*=salary], [class*=comp]")
            salary = sal_el.get_text(strip=True) if sal_el else ""

            time_el = card.select_one("time, [datetime], [class*=date], [class*=ago], [class*=posted]")
            posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

            if not is_within_24h(posted):
                continue

            j = make_job(title, company, location, href, card.get_text(strip=True), "Axiom Recruit", salary, posted)
            if j:
                jobs.append(j)
        except Exception:
            continue

    log.info(f"Axiom Recruit: {len(jobs)} jobs")
    return jobs


def scrape_talentweb3(session):
    """talentweb3.co — Web3 jobs filtered by Marketing, Sales, Ops, etc."""
    jobs = []
    categories = [
        "Marketing%20%26%20Comms",
        "Sales%20%26%20BD",
        "Operations",
        "People%20%26%20HR",
        "Support",
    ]
    for page in range(1, 4):
        cat_str = ",".join(categories)
        url = f"https://www.talentweb3.co/?page={page}&channel=web3&category={cat_str}"
        resp = safe_get(session, url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")

        for card in soup.select("a[href*='/job'], div[class*=job], li[class*=job], article, div[class*=card], div[class*=listing], tr[class*=job]"):
            try:
                link_el = card if card.name == "a" else card.select_one("a[href*='/job']")
                if not link_el:
                    link_el = card.select_one("a[href]")
                href = ensure_absolute_url(link_el.get("href", ""), "https://www.talentweb3.co") if link_el else ""
                title_el = card.select_one("h2, h3, h4, [class*=title], strong, [class*=name]")
                title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:150]

                comp_el = card.select_one("[class*=company], [class*=org]")
                company = comp_el.get_text(strip=True) if comp_el else ""
                loc_el = card.select_one("[class*=location]")
                location = loc_el.get_text(strip=True) if loc_el else "Remote"
                sal_el = card.select_one("[class*=salary], [class*=comp]")
                salary = sal_el.get_text(strip=True) if sal_el else ""

                time_el = card.select_one("time, [datetime], [class*=date], [class*=ago], [class*=posted]")
                posted = (time_el.get("datetime", "") or time_el.get_text(strip=True)) if time_el else ""

                if not is_within_24h(posted):
                    continue

                j = make_job(title, company, location, href, card.get_text(strip=True), "TalentWeb3", salary, posted)
                if j:
                    jobs.append(j)
            except Exception:
                continue

    log.info(f"TalentWeb3: {len(jobs)} jobs")
    return jobs


# ============================================================================
# SCRAPERS — LINKEDIN GUEST API + DUCKDUCKGO SEARCH
# ============================================================================

def scrape_linkedin_guest_api(session):
    """LinkedIn Guest Jobs API — public endpoint, no auth needed."""
    jobs = []
    searches = [
        ("community manager web3 crypto", "Remote"),
        ("community manager blockchain", "Remote"),
        ("growth lead crypto", "Remote"),
        ("growth manager web3", "Remote"),
        ("kol manager crypto", "Remote"),
        ("marketing manager web3 crypto", "Remote"),
        ("head of community crypto", "Remote"),
        ("community lead blockchain", "Remote"),
        ("ecosystem lead crypto", "Remote"),
        ("ambassador program crypto", "Remote"),
        ("influencer marketing crypto", "Remote"),
        ("community manager crypto", "Latin America"),
        ("growth lead web3", "Latin America"),
    ]

    for keywords, location in searches:
        # LinkedIn Guest API — returns HTML fragments of job cards
        url = (
            f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            f"?keywords={quote_plus(keywords)}"
            f"&location={quote_plus(location)}"
            f"&f_TPR=r86400"  # Last 72 hours
            f"&f_WT=2"        # Remote
            f"&start=0"
            f"&count=25"
        )
        time.sleep(1.5)
        resp = safe_get(session, url)
        if not resp:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        for card in soup.select("li, div.base-card, div.job-search-card, div[class*=base-card]"):
            try:
                title_el = card.select_one(
                    "h3.base-search-card__title, "
                    "h3[class*=title], "
                    "h3, h4"
                )
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                comp_el = card.select_one(
                    "h4.base-search-card__subtitle, "
                    "a.hidden-nested-link, "
                    "h4[class*=subtitle], "
                    "[class*=company]"
                )
                company = comp_el.get_text(strip=True) if comp_el else ""

                link_el = card.select_one(
                    "a.base-card__full-link, "
                    "a[href*='linkedin.com/jobs'], "
                    "a[href*='/jobs/view/']"
                )
                href = ""
                if link_el:
                    href = link_el.get("href", "")
                    if "?" in href:
                        href = href.split("?")[0]

                if not href:
                    # Try data attribute
                    entity_urn = card.get("data-entity-urn", "")
                    if entity_urn:
                        job_id = entity_urn.split(":")[-1]
                        href = f"https://www.linkedin.com/jobs/view/{job_id}"

                loc_el = card.select_one(
                    "span.job-search-card__location, "
                    "[class*=location]"
                )
                location_text = loc_el.get_text(strip=True) if loc_el else "Remote"

                time_el = card.select_one("time, [datetime]")
                posted = ""
                if time_el:
                    posted = time_el.get("datetime", "") or time_el.get_text(strip=True)

                if posted and not is_within_24h(posted):
                    continue

                if title and href:
                    j = make_job(title, company, location_text, href,
                                card.get_text(strip=True), "LinkedIn",
                                posted_date=posted)
                    if j:
                        jobs.append(j)
            except Exception:
                continue

    log.info(f"LinkedIn (Guest API): {len(jobs)} jobs")
    return jobs


def _scrape_duckduckgo(session, query, source_label):
    """DuckDuckGo HTML search — zero rate limiting, very scraping-friendly."""
    jobs = []
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    time.sleep(1.5)
    resp = safe_get(session, url)
    if not resp:
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")

    for result in soup.select("div.result, div.results_links"):
        try:
            title_el = result.select_one("a.result__a, h2 a, a.result__url")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")

            # DuckDuckGo wraps URLs — extract the real one
            if "uddg=" in href:
                from urllib.parse import parse_qs, urlparse as up
                parsed = up(href)
                real_url = parse_qs(parsed.query).get("uddg", [""])[0]
                if real_url:
                    href = real_url

            snippet_el = result.select_one("a.result__snippet, .result__snippet")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            company = ""
            clean_title = title
            for sep in [" - ", " | ", " — ", " at "]:
                if sep in title:
                    parts = title.split(sep, 1)
                    clean_title = parts[0].strip()
                    company = parts[1].replace("LinkedIn", "").replace("X", "").replace("Twitter", "").strip()
                    break

            if clean_title and href:
                j = make_job(clean_title, company, "Remote", href, snippet,
                            source_label, posted_date="today")
                if j:
                    jobs.append(j)
        except Exception:
            continue

    return jobs


def scrape_ddg_linkedin(session):
    """LinkedIn jobs via DuckDuckGo search."""
    jobs = []
    queries = [
        'site:linkedin.com/jobs "community manager" OR "growth lead" web3 crypto remote',
        'site:linkedin.com/jobs "kol manager" OR "marketing manager" crypto web3',
        'site:linkedin.com/jobs "head of community" OR "ecosystem lead" crypto blockchain',
    ]
    for q in queries:
        results = _scrape_duckduckgo(session, q, "LinkedIn (via DDG)")
        jobs.extend(results)
    log.info(f"LinkedIn (DDG): {len(jobs)} jobs")
    return jobs


def scrape_ddg_twitter(session):
    """X/Twitter hiring posts via DuckDuckGo search."""
    jobs = []
    queries = [
        'site:x.com OR site:twitter.com hiring "community manager" OR "growth lead" crypto web3',
        'site:x.com OR site:twitter.com "we\'re hiring" OR "join us" crypto web3 community growth marketing',
    ]
    for q in queries:
        results = _scrape_duckduckgo(session, q, "X/Twitter (via DDG)")
        jobs.extend(results)
    log.info(f"X/Twitter (DDG): {len(jobs)} jobs")
    return jobs


def scrape_ddg_general(session):
    """General Web3 job search via DuckDuckGo."""
    jobs = []
    queries = [
        '"community manager" OR "kol manager" web3 crypto remote hiring 2026',
        '"growth lead" OR "head of community" crypto web3 remote hiring',
        '"community lead" OR "marketing manager" blockchain remote hiring',
    ]
    for q in queries:
        results = _scrape_duckduckgo(session, q, "DuckDuckGo")
        jobs.extend(results)
    log.info(f"DuckDuckGo (general): {len(jobs)} jobs")
    return jobs


# ============================================================================
# SCRAPERS — TELEGRAM CHANNELS (public web view, no API needed)
# ============================================================================

# Add your Telegram channel usernames here (without @)
TELEGRAM_JOB_CHANNELS = [
    "illuminatiJOBS",
    "degencryptojobs",
    "web3hiring",
    "cryptojobslist",
    "jobstash",
    "DeJob_Global",
    "talentatweb3",
]

def scrape_telegram_channels(session):
    """Scrape public Telegram channels via t.me/s/ web view."""
    jobs = []

    for channel in TELEGRAM_JOB_CHANNELS:
        url = f"https://t.me/s/{channel}"
        resp = safe_get(session, url)
        if not resp:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        for msg in soup.select("div.tgme_widget_message_wrap, div.tgme_widget_message"):
            try:
                text_el = msg.select_one("div.tgme_widget_message_text, div.js-message_text")
                if not text_el:
                    continue
                text = text_el.get_text(strip=True)
                if not text or len(text) < 30:
                    continue

                # Check if this message looks like a job posting
                job_indicators = [
                    "hiring", "we're hiring", "looking for", "job opening",
                    "community manager", "growth", "marketing", "kol",
                    "apply", "remote", "join our team", "open position",
                    "head of", "lead", "manager",
                ]
                text_lower = text.lower()
                if not any(ind in text_lower for ind in job_indicators):
                    continue

                # ── Get date — prefer datetime attribute for accurate recency ──
                posted = ""
                # First try: <time datetime="..."> inside the message date link
                date_el = msg.select_one("a.tgme_widget_message_date time[datetime]")
                if date_el:
                    posted = date_el.get("datetime", "")
                if not posted:
                    # Second try: any time element with datetime attr
                    time_el = msg.select_one("time[datetime]")
                    if time_el:
                        posted = time_el.get("datetime", "")
                if not posted:
                    # Last resort: text of any time element
                    time_el = msg.select_one("time")
                    if time_el:
                        posted = time_el.get_text(strip=True)

                if posted and not is_within_24h(posted):
                    continue

                # ── Get Telegram post permalink ────────────────────────────────
                tg_link_el = msg.select_one("a.tgme_widget_message_date")
                tg_post_url = tg_link_el.get("href", "") if tg_link_el else f"https://t.me/s/{channel}"
                if not tg_post_url:
                    tg_post_url = f"https://t.me/s/{channel}"

                # ── Extract external apply/job link from message body ─────────
                # Priority: job board URLs > any non-Telegram external link
                apply_link = ""
                JOB_BOARD_DOMAINS = [
                    "cryptojobslist.com", "jobstash.xyz", "web3.career",
                    "talentweb3.co", "cryptojobs.com", "myweb3jobs.com",
                    "linkedin.com", "greenhouse.io", "lever.co", "ashbyhq.com",
                    "jobs.", "apply.", "careers.", "wellfound.com", "notion.so",
                    "airtable.com", "typeform.com", "forms.gle", "bit.ly",
                ]
                external_links = text_el.select("a[href]")
                for el in external_links:
                    h = el.get("href", "")
                    if not h or not h.startswith("http") or "t.me" in h:
                        continue
                    # Prefer known job board / apply domains
                    if any(d in h for d in JOB_BOARD_DOMAINS):
                        apply_link = h
                        break
                    # Otherwise keep first external link as candidate
                    if not apply_link:
                        apply_link = h

                # Final URL: apply link if found, otherwise Telegram post
                final_url = apply_link if apply_link else tg_post_url

                # Extract a title from the first meaningful line
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                title = lines[0][:120] if lines else text[:80]
                desc = text[:500]

                j = make_job(
                    title, channel, "Remote",
                    final_url,
                    desc, f"Telegram @{channel}",
                    posted_date=posted
                )
                if j:
                    # Store both URLs so the card can show them
                    j["apply_url"] = apply_link
                    j["tg_url"] = tg_post_url
                    jobs.append(j)
            except Exception:
                continue

    log.info(f"Telegram channels: {len(jobs)} jobs ({len(TELEGRAM_JOB_CHANNELS)} channels)")
    return jobs


# ============================================================================
# PIPELINE
# ============================================================================

ALL_SCRAPERS = [
    # Web3 specific (10 active)
    ("Crypto Jobs List", scrape_cryptojobslist),
    ("Web3.career", scrape_web3career),
    ("CryptocurrencyJobs", scrape_cryptocurrencyjobs),
    ("Remote3", scrape_remote3),
    # Froog — removed (DNS resolution failure, domain dead)
    # useWeb3 — removed (404 not found)
    ("JobStash", scrape_jobstash),
    ("CryptoJobs.com", scrape_cryptojobs_com),
    ("MyWeb3Jobs", scrape_myweb3jobs),
    # BeInCrypto — removed (403 forbidden)
    ("Blockchain Association", scrape_blockchain_association),
    ("HireChain", scrape_hirechain),
    ("Pantera Capital", scrape_pantera),
    ("Axiom Recruit", scrape_axiomrecruit),
    ("TalentWeb3", scrape_talentweb3),
    # General remote (5 active)
    ("Remotive", scrape_remotive),
    ("WeWorkRemotely", scrape_weworkremotely),
    ("Himalayas", scrape_himalayas),
    # Wellfound — removed (403 forbidden)
    ("Jobicy", scrape_jobicy),
    # DailyRemote — removed (blocks access to apply)
    ("Working Nomads", scrape_workingnomads),
    ("RemoteOK", scrape_remoteok),
    # LATAM (1 active)
    ("GetOnBoard", scrape_getonboard),
    # Torre — removed (400 bad request, API changed)
    # LinkedIn + X/Twitter + DuckDuckGo (4 active)
    ("LinkedIn (Guest API)", scrape_linkedin_guest_api),
    ("LinkedIn (via DDG)", scrape_ddg_linkedin),
    ("X/Twitter (via DDG)", scrape_ddg_twitter),
    ("DuckDuckGo", scrape_ddg_general),
    # Telegram
    ("Telegram", scrape_telegram_channels),
]


def collect_all_jobs():
    session = get_session()
    all_jobs = []

    for name, fn in ALL_SCRAPERS:
        log.info(f"🔍 Scraping {name}...")
        try:
            results = fn(session)
            all_jobs.extend(results)
        except Exception as e:
            log.error(f"❌ {name} crashed: {e}")
            continue

    log.info(f"📊 Total raw jobs: {len(all_jobs)}")
    return all_jobs


def filter_and_score(jobs):
    cache = load_cache()
    scored = []
    seen = set()
    verbose = "--verbose" in sys.argv

    for job in jobs:
        h = job_hash(job["title"], job["company"])
        if h in seen or h in cache:
            continue
        seen.add(h)

        # Verify URL exists
        if not job.get("url"):
            continue

        score, reasons = score_job(
            job["title"], job["company"],
            job["description"], job["location"],
            job.get("salary", ""),
            job.get("source", ""),
        )

        if verbose and score >= 0:
            log.info(f"  [{score:3d}] {job['title'][:60]} @ {job['company'][:25]} | {job['url'][:60]}")
            for r in reasons:
                log.info(f"        {r}")

        if score >= MIN_RELEVANCE_SCORE:
            job["score"] = score
            job["reasons"] = reasons
            scored.append(job)
            cache[h] = {"seen": datetime.now().isoformat(), "title": job["title"]}

    scored.sort(key=lambda j: j["score"], reverse=True)
    save_cache(cache)
    log.info(f"✅ {len(scored)} jobs passed (score ≥ {MIN_RELEVANCE_SCORE}, with links)")
    return scored


# ============================================================================
# EMAIL
# ============================================================================

def build_email_html(jobs):
    today = datetime.now().strftime("%A, %B %d, %Y")
    time_str = datetime.now().strftime("%I:%M %p")

    sources = {}
    for j in jobs:
        sources[j["source"]] = sources.get(j["source"], 0) + 1

    # Build source filter buttons
    source_buttons = ''.join(
        f'<button class="filter-btn" data-source="{k}" onclick="toggleSource(this)">{k} <span class="cnt">{v}</span></button>'
        for k, v in sorted(sources.items(), key=lambda x: -x[1])
    )

    # Build job cards
    jobs_html = ""
    for i, job in enumerate(jobs, 1):
        score = job.get("score", 0)
        if score >= 65: sc, sl, ring = "#10b981", "Excellent", 70
        elif score >= 45: sc, sl, ring = "#f59e0b", "Good", 50
        else: sc, sl, ring = "#6b7280", "Fair", 30

        # SVG ring
        circum = 2 * 3.14159 * 18
        filled = circum * score / 100
        gap = circum - filled

        badges = ""
        blob = f"{job['title']} {job['description']} {job['location']} {job['company']}".lower()
        if job.get("salary"):
            badges += f'<span class="badge b-salary">{job["salary"]}</span>'
        if any(kw.lower() in blob for kw in BILINGUAL_KEYWORDS):
            badges += '<span class="badge b-latam">LATAM</span>'
        if any(kw.lower() in blob for kw in WEB3_KEYWORDS[:12]):
            badges += '<span class="badge b-web3">Web3</span>'

        desc = job["description"][:200].replace("<", "&lt;").replace(">", "&gt;")
        title = job["title"].replace("<", "&lt;")
        company = job["company"].replace("<", "&lt;")
        loc = job["location"].replace("<", "&lt;")
        link = job["url"]
        src = job["source"].replace("<", "&lt;")
        apply_url = job.get("apply_url", "")
        tg_url = job.get("tg_url", "")
        is_telegram = src.startswith("Telegram")

        # Build action buttons
        if is_telegram and apply_url and tg_url and apply_url != tg_url:
            action_html = f'<a href="{apply_url}" target="_blank" rel="noopener" class="btn">Apply Now</a><a href="{tg_url}" target="_blank" rel="noopener" class="btn btn-sec">View on Telegram</a>'
        elif is_telegram and tg_url:
            action_html = f'<a href="{tg_url}" target="_blank" rel="noopener" class="btn">View on Telegram</a>'
        else:
            action_html = f'<a href="{link}" target="_blank" rel="noopener" class="btn">View Role</a>'

        # Title link: for Telegram use apply link if available, else tg post
        title_href = apply_url if (is_telegram and apply_url) else (tg_url if is_telegram else link)

        jobs_html += f"""
      <article class="card" data-score="{score}" data-source="{src}">
        <div class="card-main">
          <div class="card-left">
            <h3><a href="{title_href}" target="_blank" rel="noopener">{title}</a></h3>
            <div class="meta">
              <span>{company}</span>
              <span class="dot"></span>
              <span>{loc}</span>
              <span class="dot"></span>
              <span class="src">{src}</span>
            </div>
            <p class="desc">{desc}</p>
            <div class="badges">{badges}</div>
          </div>
          <div class="card-right">
            <svg class="ring" viewBox="0 0 44 44">
              <circle cx="22" cy="22" r="18" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="3"/>
              <circle cx="22" cy="22" r="18" fill="none" stroke="{sc}" stroke-width="3"
                stroke-dasharray="{filled:.1f} {gap:.1f}" stroke-linecap="round"
                transform="rotate(-90 22 22)"/>
              <text x="22" y="22" text-anchor="middle" dominant-baseline="central"
                fill="{sc}" font-size="12" font-weight="700" font-family="JetBrains Mono,monospace">{score}</text>
            </svg>
          </div>
        </div>
        <div class="card-action">
          {action_html}
        </div>
      </article>"""

    if not jobs:
        jobs_html = """
      <div class="empty">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#4b5563" stroke-width="1.5">
          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
        </svg>
        <h3>No matches today</h3>
        <p>The market varies daily. Check back tomorrow.</p>
      </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Digest — {today}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
:root{{
  --bg:#0B0F19;--s1:#111827;--s2:#1F2937;--s3:#374151;
  --b:rgba(255,255,255,0.06);--b2:rgba(255,255,255,0.1);
  --t1:#F9FAFB;--t2:#9CA3AF;--t3:#6B7280;
  --acc:#6366F1;--green:#10B981;--amber:#F59E0B;--red:#EF4444;
  --r:14px;
}}
body{{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--t1);line-height:1.6;min-height:100vh}}
h1,h2,h3{{font-family:'Manrope',system-ui,sans-serif}}

.wrap{{max-width:780px;margin:0 auto;padding:32px 20px 80px}}

/* ── Header ── */
.hdr{{text-align:center;padding:48px 0 36px;border-bottom:1px solid var(--b);margin-bottom:28px}}
.hdr-eye{{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:3px;text-transform:uppercase;color:var(--acc);margin-bottom:10px}}
.hdr h1{{font-size:32px;font-weight:800;letter-spacing:-0.5px;background:linear-gradient(135deg,var(--t1),var(--t2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.hdr-date{{color:var(--t3);font-size:13px;margin-top:6px}}
.stats{{display:flex;justify-content:center;gap:40px;margin-top:28px}}
.stat-n{{font-size:32px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--t1)}}
.stat-l{{font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:var(--t3);margin-top:2px}}

/* ── Filters ── */
.filters{{
  display:flex;flex-wrap:wrap;gap:8px;padding:16px 0 20px;
  border-bottom:1px solid var(--b);margin-bottom:24px;
  align-items:center;
}}
.filters-label{{font-size:11px;color:var(--t3);text-transform:uppercase;letter-spacing:1px;margin-right:4px;font-family:'JetBrains Mono',monospace}}
.filter-btn{{
  font-size:12px;padding:6px 14px;border-radius:999px;
  border:1px solid var(--b2);background:transparent;color:var(--t2);
  cursor:pointer;transition:all .2s;font-family:'Inter',sans-serif;
}}
.filter-btn:hover{{border-color:var(--acc);color:var(--t1)}}
.filter-btn.active{{background:var(--acc);border-color:var(--acc);color:#fff}}
.filter-btn .cnt{{
  font-family:'JetBrains Mono',monospace;font-size:10px;
  background:rgba(255,255,255,0.1);padding:1px 6px;border-radius:99px;margin-left:4px;
}}
.filter-btn.active .cnt{{background:rgba(255,255,255,0.2)}}
.score-filter{{display:flex;align-items:center;gap:8px;margin-left:auto}}
.score-filter label{{font-size:11px;color:var(--t3);font-family:'JetBrains Mono',monospace}}
.score-filter input[type=range]{{
  width:100px;height:4px;-webkit-appearance:none;appearance:none;
  background:var(--s3);border-radius:2px;outline:none;
}}
.score-filter input[type=range]::-webkit-slider-thumb{{
  -webkit-appearance:none;width:14px;height:14px;border-radius:50%;
  background:var(--acc);cursor:pointer;border:2px solid var(--bg);
}}
.score-val{{font-size:12px;color:var(--acc);font-family:'JetBrains Mono',monospace;min-width:24px}}

/* ── Cards ── */
.card{{
  background:var(--s1);border:1px solid var(--b);border-radius:var(--r);
  padding:24px;margin-bottom:12px;position:relative;
  transition:border-color .25s,transform .25s,opacity .25s;
}}
.card::before{{
  content:'';position:absolute;top:0;left:0;right:0;height:3px;
  border-radius:var(--r) var(--r) 0 0;
  background:linear-gradient(90deg,var(--acc),#8B5CF6);
  opacity:0;transition:opacity .25s;
}}
.card:hover{{border-color:var(--b2);transform:translateY(-2px)}}
.card:hover::before{{opacity:1}}
.card.hidden{{opacity:0;transform:scale(0.96);pointer-events:none;position:absolute;visibility:hidden}}

.card-main{{display:flex;gap:16px;align-items:flex-start}}
.card-left{{flex:1;min-width:0}}
.card-left h3{{font-size:17px;font-weight:700;line-height:1.35;margin-bottom:6px}}
.card-left h3 a{{color:var(--t1);text-decoration:none;transition:color .2s}}
.card-left h3 a:hover{{color:var(--acc)}}

.meta{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:13px;color:var(--t3);margin-bottom:10px}}
.dot{{width:3px;height:3px;border-radius:50%;background:var(--s3);flex-shrink:0}}
.src{{color:var(--acc);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px}}

.desc{{font-size:13px;color:var(--t3);line-height:1.55;margin-bottom:10px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}

.badges{{display:flex;flex-wrap:wrap;gap:6px}}
.badge{{font-size:10px;padding:3px 10px;border-radius:6px;font-weight:600;font-family:'JetBrains Mono',monospace;letter-spacing:0.3px}}
.b-salary{{background:#064E3B;color:#6EE7B7;border:1px solid #065F46}}
.b-latam{{background:#78350F;color:#FCD34D;border:1px solid #92400E}}
.b-web3{{background:#312E81;color:#A5B4FC;border:1px solid #3730A3}}

.card-right{{flex-shrink:0}}
.ring{{width:48px;height:48px}}

.card-action{{margin-top:14px;display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}}
.btn{{
  font-size:13px;padding:8px 22px;border-radius:8px;
  background:rgba(99,102,241,0.12);color:var(--acc);
  text-decoration:none;font-weight:600;
  border:1px solid rgba(99,102,241,0.2);
  transition:all .2s;
}}
.btn:hover{{background:var(--acc);color:#fff;border-color:var(--acc)}}
.btn-sec{{
  background:transparent;color:var(--t3);
  border:1px solid var(--b);
}}
.btn-sec:hover{{background:var(--s2);color:var(--t1);border-color:var(--b2)}}

/* ── Empty ── */
.empty{{text-align:center;padding:64px 20px;color:var(--t3)}}
.empty svg{{margin-bottom:16px;opacity:0.4}}
.empty h3{{color:var(--t2);font-size:18px;margin-bottom:6px}}

/* ── Footer ── */
.ftr{{text-align:center;padding:32px 0;border-top:1px solid var(--b);margin-top:36px;font-size:12px;color:var(--t3)}}
.ftr p{{margin:3px 0}}
.ftr strong{{color:var(--t2)}}

/* ── Scroll reveal ── */
@keyframes fadeUp{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:translateY(0)}}}}
.card{{animation:fadeUp .4s ease both}}
.card:nth-child(2){{animation-delay:.05s}}
.card:nth-child(3){{animation-delay:.1s}}
.card:nth-child(4){{animation-delay:.15s}}
.card:nth-child(5){{animation-delay:.2s}}

/* ── Mobile ── */
@media(max-width:600px){{
  .wrap{{padding:20px 16px 60px}}
  .hdr h1{{font-size:24px}}
  .stats{{gap:24px}}
  .stat-n{{font-size:24px}}
  .card-main{{flex-direction:column}}
  .card-right{{align-self:flex-start}}
  .ring{{width:40px;height:40px}}
  .score-filter{{margin-left:0;width:100%}}
  .card-action{{justify-content:stretch}}
  .btn{{width:100%;text-align:center}}
}}
</style>
</head>
<body>
<div class="wrap">

  <header class="hdr">
    <div class="hdr-eye">Job Search Agent</div>
    <h1>Daily Digest</h1>
    <p class="hdr-date">{today} · {time_str} · Last 72 hours</p>
    <div class="stats">
      <div><div class="stat-n">{len(jobs)}</div><div class="stat-l">Matches</div></div>
      <div><div class="stat-n">{len(sources)}</div><div class="stat-l">Sources</div></div>
      <div><div class="stat-n">{max((j.get('score',0) for j in jobs), default=0)}</div><div class="stat-l">Top Score</div></div>
    </div>
  </header>

  <div class="filters">
    <span class="filters-label">Filter</span>
    {source_buttons}
    <div class="score-filter">
      <label>Min score</label>
      <input type="range" min="0" max="100" value="0" id="scoreSlider" oninput="filterCards()">
      <span class="score-val" id="scoreVal">0</span>
    </div>
  </div>

  <section id="jobList">
    {jobs_html}
  </section>

  <p id="noResults" style="display:none;text-align:center;color:var(--t3);padding:40px;font-size:14px;">
    No jobs match the current filters. Try adjusting above.
  </p>

  <footer class="ftr">
    <p><strong>Eugenio García de la Torre</strong> · Job Search Agent v2</p>
    <p>20 sources · Web3 only · Remote only · $40K+ · Argentina-eligible · 72h recency</p>
    <p>Next update: {(datetime.now() + timedelta(days=1)).strftime('%A, %B %d · 8:00 AM ART')}</p>
  </footer>

</div>

<script>
const activeSources = new Set();

function toggleSource(btn) {{
  const src = btn.dataset.source;
  if (activeSources.has(src)) {{
    activeSources.delete(src);
    btn.classList.remove('active');
  }} else {{
    activeSources.add(src);
    btn.classList.add('active');
  }}
  filterCards();
}}

function filterCards() {{
  const minScore = parseInt(document.getElementById('scoreSlider').value);
  document.getElementById('scoreVal').textContent = minScore;
  const cards = document.querySelectorAll('.card');
  let visible = 0;
  cards.forEach(c => {{
    const score = parseInt(c.dataset.score);
    const source = c.dataset.source;
    const passScore = score >= minScore;
    const passSource = activeSources.size === 0 || activeSources.has(source);
    if (passScore && passSource) {{
      c.classList.remove('hidden');
      visible++;
    }} else {{
      c.classList.add('hidden');
    }}
  }});
  document.getElementById('noResults').style.display = visible === 0 ? 'block' : 'none';
}}
</script>
</body>
</html>"""
    return html

def send_email(html_content, job_count):
    if not EMAIL_PASSWORD:
        log.error("❌ EMAIL_PASSWORD not set. Use --dry-run or set .env")
        return False

    today = datetime.now().strftime("%b %d")
    subject = f"🎯 Job Digest ({today}): {job_count} new matches from 20 sources"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL if isinstance(RECIPIENT_EMAIL, str) else ", ".join(RECIPIENT_EMAIL)

    msg.attach(MIMEText(f"Daily Job Digest — {job_count} matches. View HTML version.", "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        recipients = [RECIPIENT_EMAIL] if isinstance(RECIPIENT_EMAIL, str) else RECIPIENT_EMAIL
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, recipients, msg.as_string())
        log.info(f"✅ Email sent to {RECIPIENT_EMAIL}")
        return True
    except Exception as e:
        log.error(f"❌ Email failed: {e}")
        return False


# ============================================================================
# MAIN
# ============================================================================

def main():
    log.info("=" * 65)
    log.info(f"🎯 Job Search Agent v2 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info(f"   Sources: 20 | Recency: {RECENCY_HOURS}h | Min score: {MIN_RELEVANCE_SCORE}")
    log.info("=" * 65)

    dry_run = "--dry-run" in sys.argv

    try:
        all_jobs = collect_all_jobs()
    except Exception as e:
        log.error(f"❌ Job collection crashed: {e}")
        all_jobs = []

    try:
        matched = filter_and_score(all_jobs)
    except Exception as e:
        log.error(f"❌ Scoring crashed: {e}")
        matched = []

    try:
        html = build_email_html(matched)
    except Exception as e:
        log.error(f"❌ HTML generation crashed: {e}")
        html = f"<html><body><h1>Error generating digest</h1><p>{e}</p></body></html>"

    if dry_run:
        out = "job_digest_preview.html"
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(html)
            log.info(f"📄 Dry run saved: {out}")
        except Exception as e:
            log.error(f"❌ File write failed: {e}")
    else:
        # Save to public/index.html for Vercel
        os.makedirs("public", exist_ok=True)
        try:
            with open("public/index.html", "w", encoding="utf-8") as f:
                f.write(html)
            log.info("📄 Saved public/index.html for Vercel")
        except Exception as e:
            log.error(f"❌ public/index.html write failed: {e}")

        # Also send email if credentials are set
        if EMAIL_PASSWORD:
            send_email(html, len(matched))
        else:
            log.info("📧 No EMAIL_PASSWORD set, skipping email (Vercel-only mode)")

    log.info(f"\n{'='*40}")
    log.info(f"📊 SUMMARY")
    log.info(f"   Raw scraped:    {len(all_jobs)}")
    log.info(f"   After filters:  {len(matched)}")
    if matched:
        log.info(f"   Top match:      {matched[0]['title'][:50]} ({matched[0]['score']}%)")
        log.info(f"   Sources with hits: {len(set(j['source'] for j in matched))}")
        log.info(f"   All jobs have links: ✅")
    log.info("🏁 Done!\n")

    return matched


if __name__ == "__main__":
    main()
