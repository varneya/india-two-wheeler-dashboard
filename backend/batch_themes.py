"""Optional incremental Groq batch. Run from backend/ with venv/bin/python.

Only THEMES_LLM_BACKEND=groq:<model> enables this job. No provider fallback,
retries, new dependencies or database migration. The shared state directory
must survive restarts: it holds a flock and an atomic UTC daily quota record.
An interrupted/failed request halts that UTC day's batch, including reruns.
"""

from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sqlite3
import time

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import requests

import database
from config import BACKEND_DIR, settings


LOG = logging.getLogger("themes-batch")
BATCH_SOURCE = "nightly-groq-v1"
STATUS_URL = "http://127.0.0.1:8000/api/refresh-all/status"


class BatchSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )
    themes_llm_backend: str = ""
    themes_batch_max_requests: int = Field(default=10, ge=0)
    themes_batch_gap_seconds: float = Field(default=90, ge=90, allow_inf_nan=False)
    themes_batch_state_dir: Path = BACKEND_DIR / ".cache" / "themes-batch"


def review_fingerprint(reviews: list[dict]) -> str:
    """Hash all review identities, full text and ratings, ignoring scrape time.

    Ordering and scraped_at change on unchanged upserts; they must not spend
    another request. Include all reviews, even beyond the LLM's sample, since
    the runner attributes themes and computes quality over the whole corpus.
    """
    rows = [json.dumps(
        [r.get("id"), r.get("post_id"), r.get("source"),
         r.get("review_text"), r.get("overall_rating")],
        ensure_ascii=False, separators=(",", ":"),
    ) for r in reviews]
    return hashlib.sha256(json.dumps(sorted(rows), ensure_ascii=False).encode()).hexdigest()


def refresh_is_idle() -> bool:
    """Fail closed on active refresh, unavailable server, or unknown payload."""
    try:
        with requests.Session() as session:
            session.trust_env = False  # Never proxy localhost or send credentials.
            response = session.get(STATUS_URL, timeout=5, allow_redirects=False)
            if response.status_code != 200:
                return False
            payload = response.json()
            return isinstance(payload, dict) and payload.get("running") is False
    except (requests.RequestException, ValueError):
        return False


def latest_batch_runs(backend: str) -> dict[str, dict]:
    """Read the last successful batch for each bike and the exact backend.

    get_latest_themes() can return interactive runs or a different backend.
    The runner saves themes_analysis only on success, and preserves our config.
    """
    latest = {}
    with closing(database.get_conn()) as conn:
        rows = conn.execute(
            "SELECT id, bike_id, config FROM themes_analysis "
            "WHERE method = 'llm' ORDER BY id DESC"
        )
        for row in rows:
            try:
                config = json.loads(row["config"])
            except (TypeError, ValueError):
                continue
            if (isinstance(config, dict)
                    and config.get("batch_source") == BATCH_SOURCE
                    and config.get("backend") == backend
                    and config.get("pool_scope") == "bike"):
                latest.setdefault(row["bike_id"], {"id": row["id"], "config": config})
    return latest


def utc_day(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()


def read_checkpoint(path: Path, day: str) -> dict:
    if not path.exists():
        return {"day": day, "requests": 0, "last_request_at": 0, "halted": False}
    state = json.loads(path.read_text(encoding="utf-8"))
    # A corrupt checkpoint must never silently reset the request budget.
    if (not isinstance(state, dict)
            or not isinstance(state.get("day"), str)
            or type(state.get("requests")) is not int or state["requests"] < 0
            or type(state.get("halted")) is not bool
            or type(state.get("last_request_at")) not in (int, float)
            or not math.isfinite(state["last_request_at"])
            or state["last_request_at"] < 0):
        raise ValueError("Invalid themes batch checkpoint; preserve it and investigate")
    datetime.strptime(state["day"], "%Y-%m-%d")
    if state["day"] > day:
        raise ValueError("Checkpoint day is in the future; check the system clock")
    if state["day"] != day:
        # Preserve pacing even across midnight.
        state = {**state, "day": day, "requests": 0, "halted": False}
    return state


def write_checkpoint(path: Path, state: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def run_locked(options: BatchSettings, backend: str) -> int:
    checkpoint = options.themes_batch_state_dir / "checkpoint.json"
    day = utc_day(time.time())
    state = read_checkpoint(checkpoint, day)
    if state["halted"] or state["requests"] >= options.themes_batch_max_requests:
        LOG.info("Skipped: daily budget exhausted or previous request failed/interrupted")
        return 0
    if not refresh_is_idle():
        LOG.info("Skipped: refresh active or localhost status unavailable")
        return 0

    # No database reads or heavyweight runner imports until the idle check.
    previous = latest_batch_runs(backend)
    with closing(database.get_conn()) as conn:
        bikes = [row[0] for row in conn.execute(
            "SELECT DISTINCT bike_id FROM reviews ORDER BY bike_id"
        )]
    # Give never-processed and oldest successful batches priority.
    bikes.sort(key=lambda bike: (previous.get(bike, {}).get("id", 0), bike))
    import themes_runner

    completed = 0
    for bike_id in bikes:
        if state["requests"] >= options.themes_batch_max_requests or utc_day(time.time()) != day:
            break
        if not refresh_is_idle():
            LOG.info("Stopped: refresh active or localhost status unavailable")
            break
        reviews = database.get_reviews_by_scope("bike", bike_id)
        if not reviews:
            continue
        fingerprint = review_fingerprint(reviews)
        if previous.get(bike_id, {}).get("config", {}).get("review_fingerprint") == fingerprint:
            continue

        delay = state["last_request_at"] + options.themes_batch_gap_seconds - time.time()
        if delay > 0:
            time.sleep(delay)
        # Refresh may have started while we waited. Reload the corpus before
        # fingerprinting; the runner independently reads the same bike scope.
        if utc_day(time.time()) != day or not refresh_is_idle():
            break
        reviews = database.get_reviews_by_scope("bike", bike_id)
        if not reviews:
            continue
        fingerprint = review_fingerprint(reviews)
        if previous.get(bike_id, {}).get("config", {}).get("review_fingerprint") == fingerprint:
            continue
        config = {
            "backend": backend, "batch_source": BATCH_SOURCE,
            "review_fingerprint": fingerprint, "review_count": len(reviews),
        }
        # Reserve BEFORE calling: errors, process kills and restarts all count.
        # Keep halted until success so even a killed job cannot retry today.
        state.update(requests=state["requests"] + 1, last_request_at=time.time(), halted=True)
        write_checkpoint(checkpoint, state)
        try:
            result = themes_runner.run_analysis("llm", config, bike_id, pool_scope="bike")
        except Exception:
            LOG.error("Batch failed for %s; stopped for this UTC day (no retry)", bike_id)
            return 1
        if not isinstance(result, dict) or result.get("error") or result.get("themes") is None:
            # Avoid logging raw provider responses, review text or credentials.
            LOG.error("Analysis failed for %s; stopped for this UTC day (no retry)", bike_id)
            return 1
        # Pace from completion as well, so variable database/prompt work cannot
        # shorten the actual provider-to-provider gap below the configured floor.
        state.update(halted=False, last_request_at=time.time())
        write_checkpoint(checkpoint, state)
        completed += 1
        LOG.info("Saved themes for %s (%s requests used today)", bike_id, state["requests"])
    LOG.info("Batch finished: %s saved, %s requests used today", completed, state["requests"])
    return 0


def run_batch(options: BatchSettings) -> int:
    backend = options.themes_llm_backend.strip()
    if not backend or options.themes_batch_max_requests == 0:
        LOG.info("Disabled: configure THEMES_LLM_BACKEND=groq:<model> to opt in")
        return 0
    if not backend.startswith("groq:") or not backend[5:].strip() or any(c.isspace() for c in backend):
        LOG.error("THEMES_LLM_BACKEND must explicitly select groq:<model>; no fallback")
        return 1
    if not (settings.groq_api_key or "").strip() or settings.groq_api_key.strip() == "your_api_key_here":
        LOG.error("GROQ_API_KEY is required for the optional batch")
        return 1
    options.themes_batch_state_dir.mkdir(parents=True, exist_ok=True)
    with (options.themes_batch_state_dir / "batch.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.info("Skipped: another themes batch holds the lock")
            return 0
        try:
            return run_locked(options, backend)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return run_batch(BatchSettings())
    except (OSError, ValueError, sqlite3.Error):
        LOG.error("Batch stopped: invalid configuration or inaccessible database/checkpoint")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
