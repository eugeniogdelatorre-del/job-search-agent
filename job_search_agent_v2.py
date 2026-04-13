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

SALARY_FLOOR = 40000          # USD annual minimum. No-salary jobs are KEPT.
MIN_RELEVANCE_SCORE = 35      # 0-100
RECENCY_HOURS = 24            # Only jobs posted in the last N hours
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
    "Community Director", "Growth Manager", "Growth Lead",
    "Head of Growth", "Growth Strategist", "Marketing Manager",
    "KOL Manager", "KOL Lead", "Influencer Marketing",
    "Influencer Relations", "Ambassador Program", "Ecosystem Lead",
    "Community Operations", "Social Media Lead",
]

SECONDARY_ROLES = [
    "Operations Manager", "Social Media Manager", "Content Strategist",
    "Partnerships Manager", "Developer Relations", "DevRel",
    "Business Development", "BD Manager", "Regional Lead",
    "LATAM Lead", "Regional Manager", "Chief of Staff",
    "Engagement Manager", "User Acquisition", "Brand Manager",
    "Content Marketing", "Growth Hacker", "Go-to-Market",
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

EXCLUSIONS = [
    "Intern", "Internship", "Junior", "Entry Level", "Entry-Level",
    "Executive Assistant", "Personal Assistant", "Receptionist",
    "PhD Required", "Solidity Developer", "Smart Contract Engineer",
    "Backend Engineer", "Frontend Engineer", "Full Stack",
    "DevOps Engineer", "SRE", "Data Engineer",
    "Machine Learning Engineer", "ML Engineer", "QA Engineer",
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

    # Reject date patterns like "Jan 16", "Apr 09" without year (check if month is far from current)
    month_match = re.search(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}\b', text)
    if month_match:
        month_abbr = month_match.group(1)
        current_month = datetime.now().strftime('%b').lower()
        # If the month doesn't match current month, likely old
        if month_abbr != current_month:
            return False

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


def score_job(title, company, description, location, salary_text=""):
    score = 0
    reasons = []
    text_blob = f"{title} {company} {description} {location}".lower()
    title_lower = title.lower()

    # Exclusion check
    for exc in EXCLUSIONS:
        if exc.lower() in title_lower:
            return -1, [f"Excluded: '{exc}'"]

    # Location exclusion — reject roles tied to specific non-remote locations
    LOCATION_EXCLUSIONS = [
        # Regions
        "africa", "nigeria", "kenya", "cape town", "lagos", "nairobi",
        "india only", "china only", "japan only",
        "on-site only", "onsite only", "in-office only",
        # Major cities (only excluded when "remote" is NOT also mentioned)
        "san francisco", "new york", "los angeles", "chicago", "seattle",
        "london", "berlin", "paris", "tokyo", "singapore", "hong kong",
        "sydney", "toronto", "dubai", "mumbai", "bangalore",
    ]
    loc_lower = location.lower()
    for loc_exc in LOCATION_EXCLUSIONS:
        if loc_exc in loc_lower and "remote" not in loc_lower and "hybrid" not in loc_lower:
            return -1, [f"Location excluded: '{loc_exc}'"]
    # Also check title for region-specific roles
    for loc_exc in ["- africa", "- india", "- nigeria", "- kenya", "- china", "- japan", "- apac", "- emea"]:
        if loc_exc in title_lower:
            return -1, [f"Region-specific role: '{loc_exc}'"]

    # Also scan description for non-remote city mentions when location says "Remote"
    if loc_lower in ("remote", ""):
        desc_lower = description.lower()
        onsite_signals = ["must be based in", "office in", "on-site", "onsite", "in-person", "relocate to"]
        for signal in onsite_signals:
            if signal in desc_lower:
                score_penalty = True
                break

    # Salary floor — check explicit salary field
    if salary_text:
        salary_num = extract_salary_number(salary_text)
        if salary_num and salary_num < SALARY_FLOOR:
            return -1, [f"Below ${SALARY_FLOOR:,} floor (${salary_num:,}/yr)"]

    # Salary floor — also scan description for monthly salary mentions
    monthly_match = re.search(
        r'(\d{3,5})\s*[-–]\s*(\d{3,5})\s*(?:USD|usd)?\s*/?(?:month|mo|monthly|pm)',
        text_blob
    )
    if monthly_match:
        high_monthly = int(monthly_match.group(2))
        annual = high_monthly * 12
        if annual < SALARY_FLOOR:
            return -1, [f"Below floor: ${high_monthly}/mo = ${annual:,}/yr"]

    # Primary role (+30)
    for role in PRIMARY_ROLES:
        if role.lower() in title_lower:
            score += 30
            reasons.append(f"+30 Primary: {role}")
            break

    # Secondary role (+15)
    if score < 30:
        for role in SECONDARY_ROLES:
            if role.lower() in title_lower:
                score += 15
                reasons.append(f"+15 Secondary: {role}")
                break

    # Web3 keywords (+25 max)
    web3_hits = sum(1 for kw in WEB3_KEYWORDS if kw.lower() in text_blob)
    if web3_hits:
        s = min(25, web3_hits * 5)
        score += s
        reasons.append(f"+{s} Web3 ({web3_hits} hits)")

    # Bilingual (+10)
    if any(kw.lower() in text_blob for kw in BILINGUAL_KEYWORDS):
        score += 10
        reasons.append("+10 Bilingual/LATAM")

    # Vertical (+10)
    if any(kw.lower() in text_blob for kw in VERTICAL_BONUS_KEYWORDS):
        score += 10
        reasons.append("+10 Vertical match")

    # Remote eligibility — smart detection for Argentina-based applicant
    is_remote = any(p in text_blob for p in ["remote", "work from home", "wfh", "anywhere", "distributed"])

    if is_remote:
        # Check if "remote" is restricted to a region the user CAN'T access
        RESTRICTED_REMOTE = [
            "us only", "usa only", "u.s. only", "united states only",
            "us-based", "usa-based", "us based", "usa based",
            "must be located in the us", "must reside in the us",
            "us residents only", "us citizens",
            "uk only", "uk-based", "uk based", "united kingdom only",
            "eu only", "eu-based", "eu based", "europe only", "european union only",
            "canada only", "canada-based", "australia only",
            "apac only", "emea only",
            "must be authorized to work in the u", "work authorization required",
        ]
        # Check if open to LATAM / global (overrides restriction)
        OPEN_REMOTE = [
            "worldwide", "global", "anywhere", "latam", "latin america",
            "south america", "americas", "argentina", "buenos aires",
            "all locations", "any location", "any country",
        ]

        is_open = any(p in text_blob for p in OPEN_REMOTE)
        is_restricted = any(p in text_blob for p in RESTRICTED_REMOTE)

        if is_open:
            score += 15
            reasons.append("+15 Remote (global/LATAM)")
        elif is_restricted:
            return -1, ["Remote but geo-restricted (not accessible from Argentina)"]
        else:
            score += 10
            reasons.append("+10 Remote")
    elif any(p in text_blob for p in ["onsite", "on-site", "in-office"]):
        score -= 5
        reasons.append("-5 Non-remote")

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

    log.info(f"Crypto Jobs List: {len(jobs)} jobs (24h)")
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

    log.info(f"Web3.career: {len(jobs)} jobs (24h)")
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

    log.info(f"CryptocurrencyJobs: {len(jobs)} jobs (24h)")
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

    log.info(f"Remote3: {len(jobs)} jobs (24h)")
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

    log.info(f"Froog: {len(jobs)} jobs (24h)")
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

    log.info(f"useWeb3: {len(jobs)} jobs (24h)")
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

    log.info(f"JobStash: {len(jobs)} jobs (24h)")
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

    log.info(f"Remotive: {len(jobs)} jobs (24h)")
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

    log.info(f"WeWorkRemotely: {len(jobs)} jobs (24h)")
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

    log.info(f"Himalayas: {len(jobs)} jobs (24h)")
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

    log.info(f"Jobicy: {len(jobs)} jobs (24h)")
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

    log.info(f"DailyRemote: {len(jobs)} jobs (24h)")
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

    log.info(f"Working Nomads: {len(jobs)} jobs (24h)")
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

    log.info(f"RemoteOK: {len(jobs)} jobs (24h)")
    return jobs


# ============================================================================
# SCRAPERS — LATAM
# ============================================================================

def scrape_getonboard(session):
    """getonbrd.com — LATAM remote jobs. Only scrape actual job detail links."""
    jobs = []
    terms = ["community", "growth", "marketing", "crypto"]

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
            except Exception:
                continue

    log.info(f"GetOnBoard: {len(jobs)} jobs (24h)")
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

    log.info(f"Torre: {len(jobs)} jobs (24h)")
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

    log.info(f"CryptoJobs.com: {len(jobs)} jobs (24h)")
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

    log.info(f"MyWeb3Jobs: {len(jobs)} jobs (24h)")
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

    log.info(f"BeInCrypto Jobs: {len(jobs)} jobs (24h)")
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

    log.info(f"Blockchain Association: {len(jobs)} jobs (24h)")
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

    log.info(f"HireChain: {len(jobs)} jobs (24h)")
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

    log.info(f"Pantera Capital: {len(jobs)} jobs (24h)")
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

    log.info(f"Axiom Recruit: {len(jobs)} jobs (24h)")
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

    log.info(f"TalentWeb3: {len(jobs)} jobs (24h)")
    return jobs


# ============================================================================
# SCRAPERS — GOOGLE DORKING (LinkedIn, X/Twitter, Indeed)
# ============================================================================

def _scrape_google(session, query, source_label, domain_filter=""):
    """Generic Google search scraper with 24h time filter."""
    jobs = []
    # tbs=qdr:d → last 24 hours
    full_query = f"{query} {domain_filter}".strip()
    url = f"https://www.google.com/search?q={quote_plus(full_query)}&tbs=qdr:d&num=10"
    # Longer delay for Google to avoid 429 rate limits
    time.sleep(3)
    resp = safe_get(session, url)
    if not resp:
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")

    for result in soup.select("div.g, div[data-sokoban-container], div.tF2Cxc"):
        try:
            title_el = result.select_one("h3")
            title = title_el.get_text(strip=True) if title_el else ""

            link_el = result.select_one("a[href^='http']")
            href = link_el.get("href", "") if link_el else ""

            snippet_el = result.select_one("div.VwiC3b, span.aCOpRe, div[data-sncf]")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            # Parse company from title
            company = ""
            clean_title = title
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                clean_title = parts[0].strip()
                company = parts[1].replace("| LinkedIn", "").replace("| Indeed", "").replace("(@", "").strip()
            if " | " in clean_title:
                parts = clean_title.split(" | ", 1)
                clean_title = parts[0].strip()

            if clean_title and href:
                j = make_job(clean_title, company, "Remote", href, snippet, source_label, posted_date="today")
                if j:
                    jobs.append(j)
        except Exception:
            continue

    return jobs


def scrape_google_linkedin(session):
    """LinkedIn jobs via Google (last 24h)."""
    jobs = []
    for q in GOOGLE_SEARCH_QUERIES_WEB3:
        results = _scrape_google(session, q, "LinkedIn (via Google)", "site:linkedin.com/jobs")
        jobs.extend(results)
    log.info(f"LinkedIn (Google): {len(jobs)} jobs (24h)")
    return jobs


def scrape_google_twitter(session):
    """X/Twitter hiring posts via Google (last 24h)."""
    jobs = []
    twitter_queries = [
        '(hiring OR "we\'re hiring") (community OR growth OR marketing OR kol) (web3 OR crypto)',
        '("community lead" OR "growth lead" OR "community manager") crypto hiring',
    ]
    for q in twitter_queries:
        results = _scrape_google(session, q, "X/Twitter (via Google)", "site:twitter.com OR site:x.com")
        jobs.extend(results)
    log.info(f"X/Twitter (Google): {len(jobs)} jobs (24h)")
    return jobs


def scrape_google_indeed(session):
    """Indeed + Glassdoor via Google (last 24h)."""
    jobs = []
    for q in GOOGLE_SEARCH_QUERIES_GENERAL[:1]:
        results = _scrape_google(session, q, "Indeed (via Google)", "site:indeed.com OR site:glassdoor.com")
        jobs.extend(results)
    log.info(f"Indeed/Glassdoor (Google): {len(jobs)} jobs (24h)")
    return jobs


def scrape_google_misc(session):
    """Catch-all Google search for Web3 jobs posted in last 24h on any site."""
    jobs = []
    queries = [
        '"community manager" OR "kol manager" web3 crypto remote hiring',
        '"growth lead" OR "head of community" crypto web3 remote hiring',
    ]
    for q in queries:
        results = _scrape_google(session, q, "Google (misc)")
        jobs.extend(results)
    log.info(f"Google (misc): {len(jobs)} jobs (24h)")
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
    # Google-based (4 active — reduced queries to avoid rate limits)
    ("LinkedIn (Google)", scrape_google_linkedin),
    ("X/Twitter (Google)", scrape_google_twitter),
    ("Indeed/Glassdoor (Google)", scrape_google_indeed),
    ("Google (misc)", scrape_google_misc),
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
    log.info(f"✅ {len(scored)} jobs passed (score ≥ {MIN_RELEVANCE_SCORE}, 24h, with links)")
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

    jobs_html = ""
    for i, job in enumerate(jobs, 1):
        score = job.get("score", 0)

        # Score color
        if score >= 70:
            sc, sl = "#10b981", "Excellent"
        elif score >= 50:
            sc, sl = "#f59e0b", "Good"
        else:
            sc, sl = "#6b7280", "Moderate"

        # Badges
        badges = ""
        if job.get("salary"):
            badges += f'<span class="badge badge-salary">{job["salary"]}</span>'
        blob = f"{job['title']} {job['description']} {job['location']}".lower()
        if any(kw.lower() in blob for kw in BILINGUAL_KEYWORDS):
            badges += '<span class="badge badge-latam">LATAM/ES</span>'
        if any(kw.lower() in blob for kw in WEB3_KEYWORDS[:10]):
            badges += '<span class="badge badge-web3">Web3</span>'

        desc = job["description"][:220].replace("<", "&lt;").replace(">", "&gt;")
        loc = job["location"].replace("<", "&lt;")
        company = job["company"].replace("<", "&lt;")
        title = job["title"].replace("<", "&lt;")
        link = job["url"]

        jobs_html += f"""
      <div class="job-card">
        <div class="job-header">
          <div class="job-info">
            <h3 class="job-title"><a href="{link}" target="_blank" rel="noopener">{title}</a></h3>
            <div class="job-meta">
              <span class="meta-item"><span class="meta-icon">◆</span> {company}</span>
              <span class="meta-item"><span class="meta-icon">◇</span> {loc}</span>
              <span class="meta-item source">{job['source']}</span>
            </div>
          </div>
          <div class="score" style="--sc: {sc}">
            <span class="score-num">{score}</span>
            <span class="score-label">{sl}</span>
          </div>
        </div>
        <p class="job-desc">{desc}</p>
        <div class="job-footer">
          <div class="badges">{badges}</div>
          <a href="{link}" target="_blank" rel="noopener" class="apply-btn">View Role →</a>
        </div>
      </div>"""

    if not jobs:
        jobs_html = """
      <div class="empty-state">
        <div class="empty-icon">○</div>
        <h3>No new matches today</h3>
        <p>The market varies day to day. New roles will appear tomorrow.</p>
      </div>"""

    source_tags = "".join(
        f'<span class="source-tag">{k} <strong>{v}</strong></span>'
        for k, v in sorted(sources.items(), key=lambda x: -x[1])
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Job Digest — {today}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0a0a0b;
    --surface: #141416;
    --surface2: #1c1c1f;
    --border: #2a2a2e;
    --text: #e4e4e7;
    --text2: #a1a1aa;
    --text3: #71717a;
    --accent: #6366f1;
    --green: #10b981;
    --amber: #f59e0b;
    --blue: #3b82f6;
    --radius: 12px;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: 'DM Sans', -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    min-height: 100vh;
  }}
  .container {{ max-width: 760px; margin: 0 auto; padding: 40px 20px 80px; }}

  /* Header */
  .header {{
    text-align: center;
    padding: 48px 0 40px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 32px;
  }}
  .header-eyebrow {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 12px;
  }}
  .header h1 {{
    font-size: 28px;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.5px;
  }}
  .header-date {{
    color: var(--text3);
    font-size: 14px;
    margin-top: 8px;
  }}
  .stats-row {{
    display: flex;
    justify-content: center;
    gap: 32px;
    margin-top: 24px;
  }}
  .stat {{
    text-align: center;
  }}
  .stat-num {{
    font-size: 28px;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    color: var(--text);
  }}
  .stat-label {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--text3);
    margin-top: 2px;
  }}

  /* Source tags */
  .sources {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: center;
    margin-bottom: 32px;
  }}
  .source-tag {{
    font-size: 11px;
    padding: 4px 10px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 20px;
    color: var(--text3);
    font-family: 'JetBrains Mono', monospace;
  }}
  .source-tag strong {{ color: var(--text2); }}

  /* Job cards */
  .job-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    margin-bottom: 12px;
    transition: border-color 0.2s;
  }}
  .job-card:hover {{
    border-color: #3a3a40;
  }}
  .job-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
  }}
  .job-info {{ flex: 1; }}
  .job-title {{
    font-size: 16px;
    font-weight: 600;
    line-height: 1.4;
    margin-bottom: 6px;
  }}
  .job-title a {{
    color: var(--text);
    text-decoration: none;
  }}
  .job-title a:hover {{
    color: var(--accent);
  }}
  .job-meta {{
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    font-size: 13px;
    color: var(--text3);
  }}
  .meta-item {{ display: flex; align-items: center; gap: 4px; }}
  .meta-icon {{ font-size: 8px; color: var(--text3); opacity: 0.5; }}
  .source {{ color: var(--accent); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .score {{
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 52px;
    padding: 8px 12px;
    background: var(--surface2);
    border-radius: 10px;
    border: 1px solid var(--border);
  }}
  .score-num {{
    font-size: 20px;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    color: var(--sc);
  }}
  .score-label {{
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--text3);
    margin-top: 1px;
  }}
  .job-desc {{
    font-size: 13px;
    color: var(--text3);
    margin: 12px 0;
    line-height: 1.5;
  }}
  .job-footer {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 12px;
  }}
  .badges {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .badge {{
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 6px;
    font-weight: 500;
    font-family: 'JetBrains Mono', monospace;
  }}
  .badge-salary {{ background: #1e3a2f; color: #34d399; border: 1px solid #065f46; }}
  .badge-latam {{ background: #2d2006; color: #fbbf24; border: 1px solid #78350f; }}
  .badge-web3 {{ background: #1e1b4b; color: #818cf8; border: 1px solid #3730a3; }}
  .apply-btn {{
    font-size: 13px;
    padding: 8px 20px;
    background: var(--accent);
    color: white;
    text-decoration: none;
    border-radius: 8px;
    font-weight: 500;
    transition: opacity 0.2s;
    white-space: nowrap;
  }}
  .apply-btn:hover {{ opacity: 0.85; }}

  /* Empty state */
  .empty-state {{
    text-align: center;
    padding: 60px 20px;
    color: var(--text3);
  }}
  .empty-icon {{ font-size: 48px; margin-bottom: 16px; opacity: 0.3; }}
  .empty-state h3 {{ color: var(--text2); margin-bottom: 8px; }}

  /* Footer */
  .footer {{
    text-align: center;
    padding: 32px 0;
    border-top: 1px solid var(--border);
    margin-top: 40px;
    color: var(--text3);
    font-size: 12px;
  }}
  .footer p {{ margin: 4px 0; }}
  .footer strong {{ color: var(--text2); }}

  @media (max-width: 600px) {{
    .container {{ padding: 20px 16px 60px; }}
    .header h1 {{ font-size: 22px; }}
    .stats-row {{ gap: 20px; }}
    .job-header {{ flex-direction: column; }}
    .score {{ flex-direction: row; gap: 8px; align-self: flex-start; }}
    .job-footer {{ flex-direction: column; gap: 12px; align-items: flex-start; }}
    .apply-btn {{ width: 100%; text-align: center; }}
  }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <div class="header-eyebrow">Job Search Agent</div>
    <h1>Daily Digest</h1>
    <p class="header-date">{today} · Updated {time_str} · Last 24 hours</p>
    <div class="stats-row">
      <div class="stat">
        <div class="stat-num">{len(jobs)}</div>
        <div class="stat-label">Matches</div>
      </div>
      <div class="stat">
        <div class="stat-num">{len(sources)}</div>
        <div class="stat-label">Sources</div>
      </div>
      <div class="stat">
        <div class="stat-num">{max((j.get('score',0) for j in jobs), default=0)}</div>
        <div class="stat-label">Top Score</div>
      </div>
    </div>
  </div>

  <div class="sources">
    {source_tags}
  </div>

  {jobs_html}

  <div class="footer">
    <p><strong>Eugenio García de la Torre</strong> · Job Search Agent v2</p>
    <p>20 sources · Remote only · $40K+ · 24h recency · Argentina-eligible</p>
    <p>Next update: {(datetime.now() + timedelta(days=1)).strftime('%A, %B %d · 8:00 AM ART')}</p>
  </div>

</div>
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
