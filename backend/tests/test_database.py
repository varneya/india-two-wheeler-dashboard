"""Persistence contracts and deletion invariants against real temporary SQLite."""

from contextlib import closing
import sqlite3
import struct

import pytest


def test_connection_policy_applies_to_each_connection(db, tmp_path):
    assert db.DB_PATH.parent == tmp_path
    for _ in range(2):
        with closing(db.get_conn()) as conn:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_test_harness_refuses_live_database_paths(db):
    from pathlib import Path

    live_path = Path(db.__file__).resolve().parent / "sales.db"
    for filename in (live_path, f"file:{live_path}?mode=rw"):
        with pytest.raises(pytest.fail.Exception, match="outside test tmp_path"):
            sqlite3.connect(filename, uri=True)


def test_bike_upsert_preserves_launch_and_optional_metadata(db, bike_factory):
    original = bike_factory(bikewale_slug="test-bikes/roadster")
    updated = bike_factory(display_name="Updated Roadster", keywords=["Roadster", "RS"],
                           launch_month="2026-01")
    assert updated["display_name"] == "Updated Roadster"
    assert updated["keywords"] == ["Roadster", "RS"]
    assert updated["launch_month"] == "2025-11"
    assert updated["bikewale_slug"] == "test-bikes/roadster"
    assert updated["first_seen_at"] == original["first_seen_at"]
    assert sum(row["id"] == original["id"] for row in db.get_all_bikes()) == 1


def test_sales_upsert_keeps_bikes_and_sources_independent(db, bike_factory):
    first, other = bike_factory(), bike_factory("test-other")
    db.upsert_sale(first["id"], "2025-12", 100, source="rushlane")
    db.upsert_sale(first["id"], "2025-12", 120, source="rushlane", confidence="medium")
    db.upsert_sale(first["id"], "2025-12", 130, source="autopunditz")
    db.upsert_sale(other["id"], "2025-12", 999)
    rows = db.get_all_sales(first["id"])
    assert {(row["source"], row["units_sold"]) for row in rows} == {("rushlane", 120), ("autopunditz", 130)}
    assert db.get_all_sales(first["id"], source="rushlane")[0]["confidence"] == "medium"
    assert db.get_all_sales(other["id"])[0]["units_sold"] == 999


def test_sales_are_chronological_and_metrics_are_bike_scoped(db, bike_factory):
    bike = bike_factory()
    other = bike_factory("test-other")
    db.upsert_sale(bike["id"], "2026-01", 200)
    db.upsert_sale(bike["id"], "2025-11", 300)
    db.upsert_sale(bike["id"], "2025-12", 100)
    db.upsert_sale(other["id"], "2026-01", 9999)
    assert [row["month"] for row in db.get_all_sales(bike["id"])] == ["2025-11", "2025-12", "2026-01"]
    metrics = db.get_metrics(bike["id"])
    assert metrics["total_units"] == 600
    assert metrics["months_tracked"] == 3
    assert metrics["peak_month"] == {"month": "2025-11", "units_sold": 300}
    assert metrics["latest_month"] == {"month": "2026-01", "units_sold": 200}
    assert db.get_metrics("missing")["total_units"] == 0


def test_review_upsert_and_brand_pooling(db, bike_factory):
    first = bike_factory()
    sibling = bike_factory("test-sibling")
    other = bike_factory("other-bike", brand="Other")
    for bike, post in ((first, "first"), (sibling, "sibling"), (other, "other")):
        db.upsert_review(bike["id"], "fixture", post, "owner", "Original review", 3.0)
    db.upsert_review(first["id"], "fixture", "first", "owner", "Updated review", 4.0)
    reviews = db.get_all_reviews(first["id"])
    assert len(reviews) == 1
    assert reviews[0]["review_text"] == "Updated review"
    assert reviews[0]["overall_rating"] == 4.0
    assert {row["post_id"] for row in db.get_reviews_by_brand("TEST")} == {"first", "sibling"}
    with pytest.raises(ValueError, match="unknown scope"):
        db.get_reviews_by_scope("invalid", first["id"])


def test_latest_themes_round_trip_is_bike_scoped(db, bike_factory):
    first, other = bike_factory(), bike_factory("test-other")
    db.save_themes_analysis(first["id"], "keyword", {}, [{"name": "Old"}])
    themes = [{"name": "Engine", "keywords": ["engine"], "mention_count": 2}]
    config = {"keywords": {"Engine": ["engine"]}, "pool_scope": "bike"}
    db.save_themes_analysis(first["id"], "keyword", config, themes, {"n_reviews": 2})
    db.save_themes_analysis(other["id"], "keyword", {}, [{"name": "Other"}])
    latest = db.get_latest_themes(first["id"])
    assert latest["themes"] == themes
    assert latest["config"] == config
    assert latest["metrics"] == {"n_reviews": 2}
    assert db.get_latest_themes("missing") is None


def test_embedding_cache_is_keyed_by_review_and_model(db):
    old, new = struct.pack("f", 0.25), struct.pack("f", 0.5)
    db.cache_embeddings(["post"], "model-a", [old], 1)
    db.cache_embeddings(["post"], "model-b", [old], 1)
    db.cache_embeddings(["post"], "model-a", [new], 1)
    assert db.get_cached_embeddings(["post", "missing"], "model-a") == {"post": new}
    assert db.get_cached_embeddings(["post"], "model-b") == {"post": old}
    assert db.get_cached_embeddings([], "model-a") == {}
    with pytest.raises(ValueError, match="length mismatch"):
        db.cache_embeddings(["post"], "model-a", [], 1)
    assert db.get_cached_embeddings(["post"], "model-a") == {"post": new}


@pytest.fixture
def related_bikes(db, bike_factory):
    """Two bikes share a transcript and brochure hash, but own separate rows."""
    first, other = bike_factory(), bike_factory("test-other")
    db.upsert_video_transcript(
        video_id="shared-video", channel_handle="@fixture", channel_name="Fixture",
        video_url="https://video.example/shared", title="Comparison", description=None,
        duration_s=60, published_at="2025-12-01", transcript="Both bikes reviewed",
        language="en",
    )
    db.upsert_youtube_channel_cursor("@fixture", "shared-video")
    for bike in (first, other):
        bike_id = bike["id"]
        db.upsert_sale(bike_id, "2025-12", 123)
        db.upsert_review(bike_id, "fixture", bike_id + "-post", "owner", "A useful review")
        for model in ("model-a", "model-b"):
            db.cache_embeddings([bike_id + "-post"], model, [struct.pack("f", 0.5)], 1)
        db.save_themes_analysis(bike_id, "keyword", {}, [{"name": bike_id}])
        db.upsert_review_cursor(bike_id, "fixture", bike_id + "-post")
        db.upsert_video_bike_match("shared-video", bike_id)
        variant_id = bike_id + "-variant"
        db.upsert_bike_variant(variant_id, bike_id, "test", bike["display_name"], "test-bikes/roadster")
        db.upsert_bike_spec(variant_id, "fixture", "https://specs.example/bike", {"engine_cc": 155}, "{}")
        db.upsert_brochure(variant_id, "https://brochures.example/shared.pdf", "a" * 64,
                           "brochures_cache/shared.pdf", 123, "application/pdf")
    return first, other


def test_delete_removes_dependents_and_preserves_other_bike_and_shared_video(db, related_bikes):
    first, other = related_bikes
    other_sales = db.get_all_sales(other["id"])
    other_reviews = db.get_all_reviews(other["id"])
    other_themes = db.get_latest_themes(other["id"])
    assert db.delete_bike(first["id"]) > 0
    assert db.get_bike(first["id"]) is None
    assert db.get_all_sales(first["id"]) == []
    assert db.get_all_reviews(first["id"]) == []
    assert db.get_latest_themes(first["id"]) is None
    assert db.get_review_cursor(first["id"], "fixture") is None
    assert db.get_video_transcripts_for_bike(first["id"]) == []
    for model in ("model-a", "model-b"):
        assert db.get_cached_embeddings([first["id"] + "-post"], model) == {}
        assert db.get_cached_embeddings([other["id"] + "-post"], model)
    assert db.get_bike(other["id"]) == other
    assert db.get_all_sales(other["id"]) == other_sales
    assert db.get_all_reviews(other["id"]) == other_reviews
    assert db.get_latest_themes(other["id"]) == other_themes
    assert db.get_review_cursor(other["id"], "fixture") == other["id"] + "-post"
    assert db.video_transcript_exists("shared-video")
    assert db.get_video_transcripts_for_bike(other["id"])[0]["video_id"] == "shared-video"
    assert db.get_youtube_channel_cursor("@fixture") == "shared-video"
    assert db.delete_bike(first["id"]) == 0


def test_delete_bike_preserves_independent_catalogue_specs_and_brochures(db, related_bikes):
    first, other = related_bikes
    # Analytics cleanup uses the older curated whitelist. Matching parent IDs
    # are a naming crosswalk, not ownership of the independent BikeWale rows.
    catalogue_before = {
        bike["id"]: {
            "variants": db.list_variants(parent_model_id=bike["id"], on_sale_only=False),
            "specs": db.get_bike_specs(bike["id"] + "-variant"),
            "brochures": db.list_brochures(bike["id"] + "-variant"),
        }
        for bike in (first, other)
    }
    db.delete_bike(first["id"])
    assert db.get_bike(first["id"]) is None
    for bike in (first, other):
        before = catalogue_before[bike["id"]]
        assert before["variants"] and before["specs"] and before["brochures"]
        assert db.list_variants(parent_model_id=bike["id"], on_sale_only=False) == before["variants"]
        assert db.get_bike_specs(bike["id"] + "-variant") == before["specs"]
        assert db.list_brochures(bike["id"] + "-variant") == before["brochures"]
    with closing(db.get_conn()) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_deleting_variant_cascades_specs_and_brochures(db, related_bikes):
    first, other = related_bikes
    variant_id = first["id"] + "-variant"
    with closing(db.get_conn()) as conn, conn:
        conn.execute("DELETE FROM bike_variants WHERE variant_id = ?", (variant_id,))
    assert db.get_bike_specs(variant_id) == []
    assert db.list_brochures(variant_id) == []
    assert db.get_bike(first["id"]) is not None
    assert len(db.get_bike_specs(other["id"] + "-variant")) == 1
    assert len(db.list_brochures(other["id"] + "-variant")) == 1


@pytest.mark.parametrize("kind", ["spec", "brochure"])
def test_cannot_create_spec_or_brochure_without_variant(db, kind):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        if kind == "spec":
            db.upsert_bike_spec("missing", "fixture", "https://specs.example/missing", {}, "{}")
        else:
            db.upsert_brochure("missing", "https://brochures.example/missing.pdf", "b" * 64,
                               "brochures_cache/missing.pdf", 1)
    assert db.get_bike_specs("missing") == []
    assert db.list_brochures("missing") == []


def test_delete_failure_rolls_back_earlier_deletes(db, related_bikes):
    first, _ = related_bikes
    # Abort after embeddings and sales would have been deleted. All preceding
    # statements in delete_bike must roll back with the failed transaction.
    with closing(db.get_conn()) as conn, conn:
        conn.execute("""CREATE TRIGGER reject_review_delete BEFORE DELETE ON reviews
                        BEGIN SELECT RAISE(ABORT, 'fixture deletion failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="fixture deletion failure"):
        db.delete_bike(first["id"])
    assert db.get_bike(first["id"]) is not None
    assert len(db.get_all_sales(first["id"])) == 1
    assert len(db.get_all_reviews(first["id"])) == 1
    for model in ("model-a", "model-b"):
        assert db.get_cached_embeddings([first["id"] + "-post"], model)
    assert db.get_review_cursor(first["id"], "fixture") is not None
    assert len(db.list_variants(parent_model_id=first["id"])) == 1
