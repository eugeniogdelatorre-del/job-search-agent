"""
Smoke tests for scraper.jobs_cleanup. Runs with plain asserts (no pytest).

  cd <repo_root>
  python -m scraper.test_jobs_cleanup
"""
from __future__ import annotations

from scraper import jobs_cleanup as c


def test_is_x_feed():
    assert c.is_x_feed({"category": "X_Feed", "company": "Foo"}) is True
    assert c.is_x_feed({"company": "X: @someonehiring"}) is True
    assert c.is_x_feed({"company": "x:@other", "category": "L2"}) is True
    assert c.is_x_feed({"company": "Uniswap", "category": "DeFi"}) is False


def test_is_junk_listing():
    short_ad = {"title": "Promoted: Remote Jobs"}  # under 80 chars
    assert c.is_junk_listing(short_ad) is False
    long_ad = {
        "title": (
            "Browse jobs from 200+ remote companies — find flexible remote roles"
            " curated by us for senior engineers"
        )
    }
    assert c.is_junk_listing(long_ad) is True
    real_long_title = {
        "title": (
            "Senior Growth Marketing Manager (Web3, DeFi, Community-Led) - Remote,"
            " Americas Timezone, $120k-$160k"
        )
    }
    assert c.is_junk_listing(real_long_title) is False


def test_normalize_and_dedup_key():
    assert c.normalize_for_dedup("Senior Engineer!") == "senior engineer"
    assert c.normalize_for_dedup("Vanta, Inc.") == "vanta"
    k1 = c.make_dedup_key("Community Manager", "Uniswap Labs")
    k2 = c.make_dedup_key("community manager", "uniswap")
    assert k1 == k2, (k1, k2)





def test_unmash_wwr_title():
    # Must be >= 80 chars for the unmash path to engage
    mashed = {
        "title": "Senior Backend Engineer - Platform Infrastructure3dVantaSan FranciscoFull-Time$120,000 - $160,000 USD",
        "company": "We Work Remotely",
        "category": "Remote_Board",
    }
    out = c.unmash_aggregator_title(mashed)
    assert out["title"] == "Senior Backend Engineer - Platform Infrastructure", out["title"]
    assert out["company"] == "Vanta", out["company"]
    assert out["_discovery_channel"] == "We Work Remotely"
    assert out.get("salary") == {"min": 120_000, "max": 160_000, "currency": "USD"}


def test_unmash_noop_on_short_title():
    short = {"title": "Community Manager", "company": "Uniswap"}
    assert c.unmash_aggregator_title(short) is short  # returns input unchanged


def test_clean_salary():
    assert c.clean_salary({"min": 90, "max": 140}) == (90_000, 140_000)  # k-style
    assert c.clean_salary({"min": 80_000, "max": 120_000}) == (80_000, 120_000)
    assert c.clean_salary({"min": 270, "max": 62}) == (None, None)  # reversed garbage
    assert c.clean_salary({"min": 0, "max": 100_000}) == (None, None)
    assert c.clean_salary(None) == (None, None)
    assert c.clean_salary({"min": 10, "max": 15}) == (10_000, 15_000)


def test_infer_source_tier():
    assert c.infer_source_tier("CryptoJobsList", None) == 2
    assert c.infer_source_tier("We Work Remotely", "Remote_Board") == 2  # aggregator wins over category
    assert c.infer_source_tier("Uniswap", "DeFi") == 3
    assert c.infer_source_tier("Unknown Co", "Remote_Board") == 1


def test_infer_remote_status():
    assert c.infer_remote_status("Remote, Americas") == "remote"
    assert c.infer_remote_status("Hybrid - London") == "hybrid"
    assert c.infer_remote_status("San Francisco, on-site") == "onsite"
    assert c.infer_remote_status("Anywhere in the World") == "remote"
    assert c.infer_remote_status(None) is None
    assert c.infer_remote_status("") is None


def test_clean_scraped_jobs_pipeline():
    raw = [
        {"title": "Community Manager", "company": "Uniswap", "category": "DeFi"},
        {"title": "Latest hiring", "company": "X: @someone", "category": "X_Feed"},
        {
            "title": (
                "Browse jobs from top remote companies — find flexible remote"
                " roles curated by we work remotely"
            ),
            "company": "We Work Remotely",
            "category": "Remote_Board",
        },
        {
            # Must be >= 80 chars to exercise the unmash path
            "title": "Senior Frontend Engineer - DeFi Dashboard2dOptimism FoundationRemote AmericasFull-Time$100,000 - $140,000 USD",
            "company": "We Work Remotely",
            "category": "Remote_Board",
        },
        {"title": "", "company": "Empty"},  # dropped: empty title
    ]
    cleaned, stats = c.clean_scraped_jobs(raw)
    assert stats["dropped_x_feeds"] == 1
    assert stats["dropped_junk"] == 1
    assert stats["unmashed"] == 1
    assert stats["dropped_empty"] == 1
    assert stats["output"] == 2
    titles = sorted(j["title"] for j in cleaned)
    assert titles == ["Community Manager", "Senior Frontend Engineer - DeFi Dashboard"], titles


def test_job_to_supabase_row_shape():
    job = {
        "title": "Growth Lead",
        "company": "Uniswap",
        "category": "DeFi",
        "location": "Remote, Americas",
        "salary": {"min": 120_000, "max": 160_000},
        "description": "Build growth.",
        "url": "https://uniswap.org/careers/growth-lead",
        "source_url": "https://uniswap.org/careers",
    }
    row = c.job_to_supabase_row(job, "2026-04-20T15:00:00+00:00")
    # Must have dedup_key and required fields
    assert row["dedup_key"] == c.make_dedup_key("Growth Lead", "Uniswap")
    assert row["title"] == "Growth Lead"
    assert row["company"] == "Uniswap"
    assert row["source"] == "Uniswap"
    assert row["source_tier"] == 3
    assert row["vertical"] == "DeFi"
    assert row["remote_status"] == "remote"
    assert row["salary_min_usd"] == 120_000
    assert row["salary_max_usd"] == 160_000
    assert row["last_seen_at"] == "2026-04-20T15:00:00+00:00"
    assert row["is_active"] is True
    # Must NOT include first_seen_at or AI-filled fields (preserved on conflict)
    assert "first_seen_at" not in row
    assert "function_category" not in row
    assert "score_total" not in row


def test_job_to_supabase_row_unmashed_aggregator():
    """Unmashed WWR job: source = WWR (tier 1), company = real employer."""
    job = {
        "title": "Senior Backend Engineer",
        "company": "Vanta",
        "_discovery_channel": "We Work Remotely",
        "category": "Remote_Board",
        "location": "San Francisco",
    }
    row = c.job_to_supabase_row(job, "2026-04-20T15:00:00+00:00")
    assert row["source"] == "We Work Remotely"
    assert row["source_tier"] == 1
    assert row["company"] == "Vanta"


def _run_all():
    tests = [name for name in globals() if name.startswith("test_")]
    failed = []
    for name in tests:
        try:
            globals()[name]()
            print(f"  OK  {name}")
        except AssertionError as e:
            print(f"  FAIL {name}: {e}")
            failed.append(name)
        except Exception as e:
            print(f"  ERROR {name}: {e}")
            failed.append(name)
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_all())
