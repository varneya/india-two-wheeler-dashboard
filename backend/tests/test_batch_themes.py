"""Offline batch integration tests with real temporary SQLite persistence."""

from datetime import datetime, timezone
import fcntl
import json
from unittest.mock import Mock

import pytest
import requests

import batch_themes as batch
import themes_llm
import themes_runner


BACKEND = "groq:test-free-model"


@pytest.fixture
def job(tmp_path, monkeypatch):
    options = batch.BatchSettings(
        _env_file=None, themes_llm_backend=BACKEND,
        themes_batch_state_dir=tmp_path / "batch-state",
        themes_batch_max_requests=10, themes_batch_gap_seconds=90,
    )
    monkeypatch.setattr(batch.settings, "groq_api_key", "synthetic-test-key")
    idle = Mock(return_value=True)
    monkeypatch.setattr(batch, "refresh_is_idle", idle)
    now = [datetime(2026, 10, 31, 7, tzinfo=timezone.utc).timestamp()]
    monkeypatch.setattr(batch.time, "time", lambda: now[0])
    sleep = Mock(side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(batch.time, "sleep", sleep)
    provider = Mock(side_effect=lambda *a, **kw: [{
        "name": "Comfort", "keywords": ["seat"], "sentiment": "positive",
        "mention_count": 1, "example_quotes": ["Comfortable seat"],
    }])
    monkeypatch.setattr(themes_llm, "analyze", provider)
    runner = Mock(wraps=themes_runner.run_analysis)
    monkeypatch.setattr(themes_runner, "run_analysis", runner)
    return options, provider, runner, idle, now, sleep


@pytest.fixture
def review_factory(db, bike_factory):
    def create(bike_id="test-roadster", post_id=None, text="Comfortable seat", rating=4):
        bike_factory(bike_id)
        db.upsert_review(bike_id, "bikewale", post_id or bike_id, "Owner", text, rating)
        return db.get_reviews_by_scope("bike", bike_id)
    return create


def checkpoint(options):
    return json.loads((options.themes_batch_state_dir / "checkpoint.json").read_text())


def test_disabled_by_default_without_status_or_db(job, monkeypatch):
    options, provider, runner, idle, *_ = job
    monkeypatch.delenv("THEMES_LLM_BACKEND", raising=False)
    options.themes_llm_backend = batch.BatchSettings(_env_file=None).themes_llm_backend
    assert options.themes_llm_backend == ""
    monkeypatch.setattr(batch.database, "get_conn", Mock(side_effect=AssertionError("DB read")))
    assert batch.run_batch(options) == 0
    idle.assert_not_called()
    runner.assert_not_called()
    provider.assert_not_called()
    assert not options.themes_batch_state_dir.exists()


@pytest.mark.parametrize("backend", ["claude", "openai:paid", "ollama:local", "groq:", "groq: a"])
def test_only_explicit_groq_model_allowed(job, backend):
    options, provider, runner, idle, *_ = job
    options.themes_llm_backend = backend
    assert batch.run_batch(options) == 1
    provider.assert_not_called()
    runner.assert_not_called()
    idle.assert_not_called()


@pytest.mark.parametrize("key", [None, "", "   ", "your_api_key_here"])
def test_missing_key_never_calls_provider(job, monkeypatch, key):
    options, provider, *_ = job
    monkeypatch.setattr(batch.settings, "groq_api_key", key)
    assert batch.run_batch(options) == 1
    provider.assert_not_called()


def test_zero_budget_disables_job(job):
    options, provider, runner, idle, *_ = job
    options.themes_batch_max_requests = 0
    assert batch.run_batch(options) == 0
    idle.assert_not_called()
    runner.assert_not_called()


@pytest.mark.parametrize("gap", [0, 89, -1, float("inf"), float("nan")])
def test_pacing_cannot_be_less_than_90_seconds(gap):
    with pytest.raises(ValueError):
        batch.BatchSettings(_env_file=None, themes_batch_gap_seconds=gap)


def test_refresh_guard_precedes_all_database_reads(job, monkeypatch):
    options, provider, runner, idle, *_ = job
    idle.return_value = False
    monkeypatch.setattr(batch.database, "get_conn", Mock(side_effect=AssertionError("DB read")))
    assert batch.run_batch(options) == 0
    provider.assert_not_called()
    runner.assert_not_called()


@pytest.mark.parametrize("payload, status, expected", [
    ({"running": False}, 200, True), ({"running": True}, 200, False),
    ({}, 200, False), ({"running": 0}, 200, False),
    ({"running": "false"}, 200, False), ([], 200, False),
    ({"running": False}, 503, False), ({"running": False}, 302, False),
])
def test_localhost_status_contract(monkeypatch, payload, status, expected):
    response = Mock(status_code=status)
    response.json.return_value = payload
    get = Mock(return_value=response)
    monkeypatch.setattr(requests.Session, "get", get)
    assert batch.refresh_is_idle() is expected
    get.assert_called_once_with(batch.STATUS_URL, timeout=5, allow_redirects=False)


@pytest.mark.parametrize("error", [requests.ConnectionError(), requests.Timeout(), ValueError()])
def test_unreachable_or_invalid_status_skips(monkeypatch, error):
    monkeypatch.setattr(requests.Session, "get", Mock(side_effect=error))
    assert batch.refresh_is_idle() is False


def test_fingerprint_ignores_order_and_scrape_metadata():
    rows = [dict(id=1, post_id="a", source="x", review_text="Good", overall_rating=4),
            dict(id=2, post_id="b", source="x", review_text="Bad", overall_rating=2)]
    changed_metadata = [{**row, "scraped_at": "new", "username": "new"} for row in reversed(rows)]
    assert batch.review_fingerprint(rows) == batch.review_fingerprint(changed_metadata)
    for key, value in [("id", 3), ("post_id", "c"), ("source", "y"),
                       ("review_text", "Changed"), ("overall_rating", 1)]:
        assert batch.review_fingerprint(rows) != batch.review_fingerprint([{**rows[0], key: value}, rows[1]])
    assert batch.review_fingerprint(rows) != batch.review_fingerprint(rows[:1])


def test_incremental_persists_fingerprint_and_ignores_reupsert(job, review_factory, db):
    options, provider, runner, *_ = job
    reviews = review_factory()
    assert batch.run_batch(options) == 0
    saved = db.get_latest_themes("test-roadster")
    assert saved["config"] == {
        "backend": BACKEND, "batch_source": batch.BATCH_SOURCE, "pool_scope": "bike",
        "review_fingerprint": batch.review_fingerprint(reviews), "review_count": 1,
    }
    assert saved["themes"][0]["avg_rating"] == 4
    review_factory()  # scraped_at advances but review content is identical.
    assert batch.run_batch(options) == 0
    provider.assert_called_once()
    runner.assert_called_once()
    assert checkpoint(options)["requests"] == 1


@pytest.mark.parametrize("change", ["text", "rating", "new-review", "delete-review"])
def test_content_changes_trigger_new_batch(job, review_factory, db, change):
    options, provider, *_ = job
    review_factory()
    review_factory(post_id="second")
    assert batch.run_batch(options) == 0
    if change == "text":
        review_factory(text="Seat is too hard")
    elif change == "rating":
        review_factory(rating=1)
    elif change == "new-review":
        review_factory(post_id="third")
    else:
        with db.get_conn() as conn:
            conn.execute("DELETE FROM reviews WHERE post_id = 'second'")
    assert batch.run_batch(options) == 0
    assert provider.call_count == 2


def test_same_backend_batch_history_survives_interactive_and_other_models(job, review_factory, db):
    options, provider, *_ = job
    review_factory()
    assert batch.run_batch(options) == 0
    original = db.get_latest_themes("test-roadster")["config"]
    for method, config in [
        ("llm", {"backend": BACKEND, "pool_scope": "bike"}),
        ("llm", {**original, "backend": "groq:other-model"}),
        ("llm", {**original, "pool_scope": "brand", "review_fingerprint": "wrong"}),
        ("keyword", {**original, "review_fingerprint": "wrong"}),
    ]:
        db.save_themes_analysis("test-roadster", method, config, [])
    assert batch.run_batch(options) == 0
    assert provider.call_count == 1
    options.themes_llm_backend = "groq:new-model"
    assert batch.run_batch(options) == 0
    assert provider.call_count == 2


def test_compares_latest_success_not_any_matching_older_run(job, review_factory):
    options, provider, *_ = job
    review_factory(text="A")
    batch.run_batch(options)
    review_factory(text="B")
    batch.run_batch(options)
    review_factory(text="A")
    batch.run_batch(options)
    assert provider.call_count == 3


def test_default_daily_cap_pacing_and_reexecution(job, review_factory):
    options, provider, runner, idle, now, sleep = job
    for i in range(12):
        review_factory(f"bike-{i:02}")
    assert batch.run_batch(options) == 0
    assert provider.call_count == 10
    assert sleep.call_count == 9
    assert all(call.args == (90,) for call in sleep.call_args_list)
    assert checkpoint(options)["requests"] == 10
    options.themes_llm_backend = "groq:another-model"
    assert batch.run_batch(options) == 0
    assert provider.call_count == 10
    options.themes_llm_backend = BACKEND
    now[0] += 86400
    assert batch.run_batch(options) == 0
    assert provider.call_count == 12
    assert checkpoint(options)["requests"] == 2


def test_pacing_survives_restart(job, review_factory):
    options, provider, runner, idle, now, sleep = job
    review_factory()
    batch.run_batch(options)
    now[0] += 20
    review_factory(text="Changed seat")
    batch.run_batch(options)
    sleep.assert_called_once_with(70)


def test_slow_request_still_gets_full_gap_after_completion(job, review_factory):
    options, provider, runner, idle, now, sleep = job
    review_factory("a")
    review_factory("b")
    original = provider.side_effect

    def slow_provider(*args, **kwargs):
        now[0] += 120
        return original(*args, **kwargs)

    provider.side_effect = slow_provider
    assert batch.run_batch(options) == 0
    sleep.assert_called_once_with(90)


def test_next_day_clears_halt_but_keeps_cross_midnight_gap(job, review_factory):
    options, provider, runner, idle, now, sleep = job
    now[0] = datetime(2026, 10, 31, 23, 59, 30, tzinfo=timezone.utc).timestamp()
    review_factory()
    original = provider.side_effect
    provider.side_effect = lambda *a, **kw: {"error": "429"}
    assert batch.run_batch(options) == 1
    now[0] += 40
    provider.side_effect = original
    assert batch.run_batch(options) == 0
    sleep.assert_called_once_with(50)
    assert checkpoint(options)["requests"] == 1
    assert checkpoint(options)["halted"] is False


@pytest.mark.parametrize("failure", [{"error": "429 quota exceeded"}, {"error": "bad JSON"}, RuntimeError("crash")])
def test_failure_has_no_retries_or_fallback_and_halts_reruns(job, review_factory, db, failure):
    options, provider, runner, idle, now, sleep = job
    review_factory("a")
    review_factory("b")
    provider.side_effect = failure if isinstance(failure, Exception) else lambda *a, **kw: failure
    assert batch.run_batch(options) == 1
    assert checkpoint(options)["requests"] == 1
    assert checkpoint(options)["halted"] is True
    assert db.get_latest_themes("a") is None
    assert batch.run_batch(options) == 0
    assert provider.call_count == 1
    sleep.assert_not_called()
    assert runner.call_args.args[1]["backend"] == BACKEND


def test_interrupted_call_reserved_before_execution(job, review_factory):
    options, provider, runner, *_ = job
    review_factory()

    def interrupt(*args, **kwargs):
        assert checkpoint(options)["requests"] == 1
        assert checkpoint(options)["halted"] is True
        raise KeyboardInterrupt()

    runner.side_effect = interrupt
    with pytest.raises(KeyboardInterrupt):
        batch.run_batch(options)
    assert batch.run_batch(options) == 0
    assert runner.call_count == 1


def test_existing_lock_skips_without_reading_database(job, monkeypatch):
    options, provider, runner, idle, *_ = job
    options.themes_batch_state_dir.mkdir()
    with (options.themes_batch_state_dir / "batch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(batch.database, "get_conn", Mock(side_effect=AssertionError("DB read")))
        assert batch.run_batch(options) == 0
    idle.assert_not_called()
    runner.assert_not_called()


def test_refresh_start_during_pacing_stops_before_next_request(job, review_factory):
    options, provider, runner, idle, now, sleep = job
    review_factory("a")
    review_factory("b")
    sleep.side_effect = lambda seconds: idle.configure_mock(return_value=False)
    assert batch.run_batch(options) == 0
    assert provider.call_count == 1
    assert checkpoint(options)["requests"] == 1


def test_midnight_stops_current_batch_and_preserves_pacing(job, review_factory):
    options, provider, runner, idle, now, sleep = job
    now[0] = datetime(2026, 10, 31, 23, 59, 30, tzinfo=timezone.utc).timestamp()
    review_factory("a")
    review_factory("b")
    assert batch.run_batch(options) == 0
    assert provider.call_count == 1
    assert batch.run_batch(options) == 0
    assert provider.call_count == 2
    assert checkpoint(options)["requests"] == 1


@pytest.mark.parametrize("contents", ["broken json", "[]", "{}", '{"day":"2099-01-01"}'])
def test_corrupt_checkpoint_fails_closed(job, contents):
    options, provider, runner, idle, *_ = job
    options.themes_batch_state_dir.mkdir()
    (options.themes_batch_state_dir / "checkpoint.json").write_text(contents)
    with pytest.raises(ValueError):
        batch.run_batch(options)
    idle.assert_not_called()
    runner.assert_not_called()


def test_checkpoint_write_failure_prevents_request(job, review_factory, monkeypatch):
    options, provider, runner, *_ = job
    review_factory()
    monkeypatch.setattr(batch, "write_checkpoint", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        batch.run_batch(options)
    runner.assert_not_called()


def test_env_overrides_dotenv(tmp_path, monkeypatch):
    envfile = tmp_path / ".env"
    envfile.write_text("THEMES_LLM_BACKEND=groq:file-model\nTHEMES_BATCH_MAX_REQUESTS=3\n")
    monkeypatch.setenv("THEMES_LLM_BACKEND", BACKEND)
    monkeypatch.delenv("THEMES_BATCH_MAX_REQUESTS", raising=False)
    options = batch.BatchSettings(_env_file=envfile)
    assert options.themes_llm_backend == BACKEND
    assert options.themes_batch_max_requests == 3
