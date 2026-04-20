"""
Thin Supabase client wrapper for scraper writes.

Fails soft: every operation swallows exceptions and prints to stderr rather
than raising, so a Supabase outage never breaks the jobs.json write path.
The scraper can always degrade to json-only mode.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

UPSERT_BATCH_SIZE = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_client():
    """Return a Supabase client, or None if env vars or the lib are missing."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client  # type: ignore
    except ImportError:
        print("  [supabase] supabase-py not installed", file=sys.stderr)
        return None
    try:
        return create_client(url, key)
    except Exception as e:
        print(f"  [supabase] client init failed: {e}", file=sys.stderr)
        return None


def upsert_jobs(client, rows: list[dict]) -> tuple[int, int]:
    """
    Upsert rows into `jobs` with on_conflict=dedup_key, batched.
    Returns (rows_written, batch_errors). Never raises.
    """
    if client is None or not rows:
        return (0, 0)
    written = 0
    errors = 0
    for i in range(0, len(rows), UPSERT_BATCH_SIZE):
        batch = rows[i : i + UPSERT_BATCH_SIZE]
        batch_num = i // UPSERT_BATCH_SIZE + 1
        try:
            resp = client.table("jobs").upsert(batch, on_conflict="dedup_key").execute()
            got = len(resp.data) if getattr(resp, "data", None) else len(batch)
            written += got
            print(f"  [supabase] upsert batch {batch_num}: +{got} rows")
        except Exception as e:
            errors += 1
            print(f"  [supabase] upsert batch {batch_num} FAILED: {e}", file=sys.stderr)
    return (written, errors)


def log_source_health(
    client,
    source: str,
    jobs_found: int,
    success: bool,
    duration_ms: int | None = None,
    error_message: str | None = None,
) -> None:
    """Insert one row into sources_health. Silent on client=None."""
    if client is None:
        return
    row = {
        "source": source,
        "jobs_found": jobs_found,
        "success": success,
        "duration_ms": duration_ms,
        "error_message": (error_message or "")[:1000] or None,
        "run_at": _now_iso(),
    }
    try:
        client.table("sources_health").insert(row).execute()
    except Exception as e:
        print(f"  [supabase] sources_health insert failed for {source}: {e}", file=sys.stderr)
