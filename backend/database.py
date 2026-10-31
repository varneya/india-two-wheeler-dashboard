import json as _json
from contextlib import closing
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "sales.db"

# The original single-bike data was for XSR 155. All un-tagged rows get
# attributed to this bike during the multi-bike migration.
LEGACY_BIKE_ID = "yamaha-xsr-155"


# Industry-standard segment seed. cc_min/cc_max define the band; the
# matching body_style (commuter, sports, naked, ...) determines which
# segment a variant lands in. Used by the Owner Insights "compare with
# segment peers" filter and any future segment-level aggregation.
# Loosely follows BikeWale's body-style nav + SIAM's cc bands.
_SEGMENT_SEED = [
    # Commuters
    {"segment_id": "commuter-100-125",        "display_name": "100-125cc Commuter",        "body_style": "commuter",       "cc_min": 100, "cc_max": 125, "sort_order": 10},
    {"segment_id": "commuter-125-150",        "display_name": "125-150cc Commuter",        "body_style": "commuter",       "cc_min": 125, "cc_max": 150, "sort_order": 20},
    {"segment_id": "commuter-premium-150-200","display_name": "150-200cc Premium Commuter","body_style": "commuter",       "cc_min": 150, "cc_max": 200, "sort_order": 30},
    # Sports (full fairing)
    {"segment_id": "sports-150-300",          "display_name": "150-300cc Sports",          "body_style": "sports",         "cc_min": 150, "cc_max": 300, "sort_order": 40},
    {"segment_id": "sports-300-500",          "display_name": "300-500cc Sports",          "body_style": "sports",         "cc_min": 300, "cc_max": 500, "sort_order": 50},
    {"segment_id": "sports-500+",             "display_name": "500cc+ Sports",             "body_style": "sports",         "cc_min": 500, "cc_max": None,"sort_order": 60},
    # Naked / streetfighter
    {"segment_id": "naked-150-300",           "display_name": "150-300cc Naked",           "body_style": "naked",          "cc_min": 150, "cc_max": 300, "sort_order": 70},
    {"segment_id": "naked-300-500",           "display_name": "300-500cc Naked",           "body_style": "naked",          "cc_min": 300, "cc_max": 500, "sort_order": 80},
    {"segment_id": "naked-500+",              "display_name": "500cc+ Naked",              "body_style": "naked",          "cc_min": 500, "cc_max": None,"sort_order": 90},
    # Modern Classic / Retro
    {"segment_id": "modern-classic-350",      "display_name": "Modern Classic (300-400cc)","body_style": "modern-classic", "cc_min": 300, "cc_max": 400, "sort_order": 100},
    {"segment_id": "modern-classic-500+",     "display_name": "Modern Classic (500cc+)",   "body_style": "modern-classic", "cc_min": 500, "cc_max": None,"sort_order": 110},
    # Adventure / ADV
    {"segment_id": "adventure-200-400",       "display_name": "Adventure (200-400cc)",     "body_style": "adventure",      "cc_min": 200, "cc_max": 400, "sort_order": 120},
    {"segment_id": "adventure-500+",          "display_name": "Adventure (500cc+)",        "body_style": "adventure",      "cc_min": 500, "cc_max": None,"sort_order": 130},
    # Cruiser
    {"segment_id": "cruiser-150-300",         "display_name": "150-300cc Cruiser",         "body_style": "cruiser",        "cc_min": 150, "cc_max": 300, "sort_order": 140},
    {"segment_id": "cruiser-350+",            "display_name": "350cc+ Cruiser",            "body_style": "cruiser",        "cc_min": 350, "cc_max": None,"sort_order": 150},
    # Scooters (ICE)
    {"segment_id": "scooter-100-125",         "display_name": "100-125cc Scooter",         "body_style": "scooter",        "cc_min": 100, "cc_max": 125, "sort_order": 160},
    {"segment_id": "scooter-125-200",         "display_name": "125-200cc Scooter",         "body_style": "scooter",        "cc_min": 125, "cc_max": 200, "sort_order": 170},
    # Electric
    {"segment_id": "e-scooter",               "display_name": "Electric Scooter",          "body_style": "e-scooter",      "cc_min": None,"cc_max": None,"sort_order": 180},
    {"segment_id": "e-bike",                  "display_name": "Electric Motorcycle",       "body_style": "e-bike",         "cc_min": None,"cc_max": None,"sort_order": 190},
    # Misc / mopeds (XL100, etc.)
    {"segment_id": "moped",                   "display_name": "Moped",                     "body_style": "moped",          "cc_min": 50,  "cc_max": 110, "sort_order": 200},
]


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Per-connection policy. journal_mode=WAL persists in the DB file (set in
    # init_db), but these three do NOT survive across connections — without
    # them here, only the init connection ever ran with them:
    #   synchronous=NORMAL   safe-with-WAL fsync level (big write speedup)
    #   foreign_keys=ON      enforce the bike_specs/bike_brochures FKs
    #   busy_timeout         wait out brief writer overlap from the parallel
    #                        refresh stages instead of raising "locked"
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
    except BaseException:
        conn.close()
        raise
    return conn


# ---------------------------------------------------------------------------
# Schema + migrations
# ---------------------------------------------------------------------------

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def _execute_statements(conn: sqlite3.Connection, script: str):
    """Execute our static DDL without executescript's implicit COMMIT.

    Statements in these scripts end on their own line. complete_statement
    handles quoted semicolons and SQL comments without splitting inside them.
    """
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        conn.execute(statement)


def _ensure_schema(conn: sqlite3.Connection):
    """Create missing tables and add columns without rewriting existing rows."""
    # ------------- Base tables (idempotent CREATE IF NOT EXISTS) -------------
    _execute_statements(conn, """
        CREATE TABLE IF NOT EXISTS bikes (
            id              TEXT PRIMARY KEY,
            brand           TEXT NOT NULL,
            model           TEXT NOT NULL,
            display_name    TEXT NOT NULL,
            keywords        TEXT NOT NULL,
            bikewale_slug   TEXT,
            bikewale_ok     INTEGER DEFAULT 0,
            launch_month    TEXT,
            first_seen_at   TEXT NOT NULL,
            last_seen_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sales_data (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            month       TEXT NOT NULL,
            units_sold  INTEGER NOT NULL,
            source_url  TEXT,
            confidence  TEXT DEFAULT 'high',
            scraped_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scrape_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at       TEXT NOT NULL,
            urls_tried   INTEGER DEFAULT 0,
            urls_success INTEGER DEFAULT 0,
            error_msg    TEXT
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            source         TEXT NOT NULL,
            post_id        TEXT UNIQUE NOT NULL,
            username       TEXT,
            review_text    TEXT,
            overall_rating REAL,
            thread_url     TEXT,
            scraped_at     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at       TEXT NOT NULL,
            total_scraped INTEGER DEFAULT 0,
            error_msg    TEXT
        );
        CREATE TABLE IF NOT EXISTS themes_analysis (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            method     TEXT NOT NULL,
            config     TEXT NOT NULL,
            themes     TEXT NOT NULL,
            run_at     TEXT NOT NULL
        );
        -- Brand-level monthly wholesale data from AutoPunditz aggregate
        -- posts. Distinct from `sales_data` (model-level) — this table
        -- holds the curated brand TOTAL each month, used as the primary
        -- line on the brand-level chart.
        CREATE TABLE IF NOT EXISTS wholesale_brand_sales (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_id    TEXT NOT NULL,
            month       TEXT NOT NULL,
            units       INTEGER NOT NULL,
            source      TEXT NOT NULL DEFAULT 'autopunditz',
            source_url  TEXT,
            scraped_at  TEXT NOT NULL,
            UNIQUE(brand_id, month, source)
        );
        -- Per-review embedding cache. Lookup key is (post_id, model) so a
        -- future model swap doesn't accidentally serve stale vectors.
        CREATE TABLE IF NOT EXISTS review_embeddings (
            post_id    TEXT NOT NULL,
            model      TEXT NOT NULL,
            embedding  BLOB NOT NULL,
            dim        INTEGER NOT NULL,
            cached_at  TEXT NOT NULL,
            PRIMARY KEY (post_id, model)
        );
        -- HTTP conditional-GET cache. For each URL we ever fetched, store
        -- the validators (ETag, Last-Modified) and a SHA256 of the body so
        -- subsequent fetches can short-circuit on 304 Not Modified or on
        -- a matching content hash (for hosts that ignore validators).
        CREATE TABLE IF NOT EXISTS url_cache (
            url           TEXT PRIMARY KEY,
            etag          TEXT,
            last_modified TEXT,
            content_hash  TEXT,
            last_status   INTEGER,
            last_fetched_at TEXT NOT NULL
        );
        -- Per-bike-source review cursor: the newest post_id we've seen.
        -- Lets each review scraper stop pagination early once it hits a
        -- known post id, instead of always re-walking the full first page.
        CREATE TABLE IF NOT EXISTS review_cursor (
            bike_id        TEXT NOT NULL,
            source         TEXT NOT NULL,
            last_post_id   TEXT,
            updated_at     TEXT NOT NULL,
            PRIMARY KEY (bike_id, source)
        );
        -- Stage 6 — YouTube transcripts. video_transcripts holds the full
        -- transcript + metadata once per video; video_bike_match maps a
        -- video to one or more bikes (a comparison video maps to many).
        -- A shadow row in the `reviews` table per (video, bike) feeds the
        -- existing themes/embedding pipeline for free.
        CREATE TABLE IF NOT EXISTS video_transcripts (
            video_id          TEXT PRIMARY KEY,
            channel_handle    TEXT NOT NULL,
            channel_name      TEXT NOT NULL,
            video_url         TEXT NOT NULL,
            title             TEXT NOT NULL,
            description       TEXT,
            duration_s        INTEGER,
            published_at      TEXT,
            transcript        TEXT,
            language          TEXT,
            -- 'ok' | 'rate_limited' | 'no_captions' | 'pending'
            transcript_status TEXT NOT NULL DEFAULT 'ok',
            fetched_at        TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS video_bike_match (
            video_id  TEXT NOT NULL,
            bike_id   TEXT NOT NULL,
            matched_at TEXT NOT NULL,
            PRIMARY KEY (video_id, bike_id)
        );
        -- Per-channel "newest video we've inspected" pointer. Lets the
        -- YouTube scraper walk a small newest-first window each refresh
        -- and bail as soon as it hits a video it's already seen, instead
        -- of re-listing 50 videos per channel every time.
        CREATE TABLE IF NOT EXISTS youtube_channel_cursor (
            channel_handle  TEXT PRIMARY KEY,
            last_video_id   TEXT NOT NULL,
            last_checked_at TEXT NOT NULL
        );

        -- ----------------------------------------------------------------
        -- Variant-level catalogue (Phase 1 of the BikeWale-as-base refactor)
        -- ----------------------------------------------------------------
        -- bike_segments: hand-seeded industry-standard segments (cc x body
        -- style grid). Stable across refreshes; populated once on init.
        -- Lets the Owner Insights tab compare a bike's reviews against
        -- siblings in the same segment.
        CREATE TABLE IF NOT EXISTS bike_segments (
            segment_id   TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            body_style   TEXT NOT NULL,
            cc_min       INTEGER,
            cc_max       INTEGER,
            sort_order   INTEGER NOT NULL DEFAULT 100
        );

        -- bike_variants: every variant currently on sale in India,
        -- scraped from BikeWale. Rolls up to a parent_model_id (which
        -- matches the existing `bikes.id` scheme so today's sales data
        -- attaches without rewrites). One row per variant — Pulsar 150,
        -- Pulsar N160, Pulsar N250 are three rows that all roll up to
        -- 'bajaj-pulsar'.
        CREATE TABLE IF NOT EXISTS bike_variants (
            variant_id        TEXT PRIMARY KEY,
            parent_model_id   TEXT NOT NULL,
            brand_id          TEXT NOT NULL,
            segment_id        TEXT,
            display_name      TEXT NOT NULL,
            displacement_cc   INTEGER,
            price_onroad      INTEGER,
            bikewale_slug     TEXT NOT NULL,
            bikedekho_slug    TEXT,
            image_url         TEXT,
            status            TEXT NOT NULL DEFAULT 'on_sale',
            launch_year       INTEGER,
            discovered_at     TEXT NOT NULL,
            last_seen_at      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_variants_parent
            ON bike_variants(parent_model_id);
        CREATE INDEX IF NOT EXISTS idx_variants_segment
            ON bike_variants(segment_id);
        CREATE INDEX IF NOT EXISTS idx_variants_brand
            ON bike_variants(brand_id);

        -- bike_specs: technical specifications per variant per source.
        -- One row per (variant, source) so BikeWale + OEM specs can sit
        -- side-by-side and queries can prefer OEM where present.
        --
        -- Hybrid shape: ~25 typed columns for the query-hot fields
        -- (engine cc, power, weight, dimensions, brakes, ABS) + a
        -- raw_specs_json TEXT blob containing the full categorized
        -- payload (every field BikeWale exposes — Instrument Cluster,
        -- Safety & Convenience, Lights, etc.). New spec fields don't
        -- require migrations; they flow into raw_specs_json.
        CREATE TABLE IF NOT EXISTS bike_specs (
            variant_id           TEXT NOT NULL,
            source               TEXT NOT NULL,
            source_url           TEXT NOT NULL,
            scraped_at           TEXT NOT NULL,

            -- Engine
            engine_cc            INTEGER,
            max_power_bhp        REAL,
            max_power_rpm        INTEGER,
            max_torque_nm        REAL,
            max_torque_rpm       INTEGER,
            cylinders            INTEGER,
            cooling              TEXT,
            fuel_system          TEXT,
            transmission         TEXT,
            gears                INTEGER,
            starter              TEXT,
            emission_standard    TEXT,
            fuel_type            TEXT,

            -- Performance
            mileage_kmpl         REAL,
            top_speed_kmph       REAL,
            fuel_tank_l          REAL,

            -- Dimensions
            kerb_weight_kg       REAL,
            seat_height_mm       INTEGER,
            ground_clearance_mm  INTEGER,
            wheelbase_mm         INTEGER,
            length_mm            INTEGER,
            width_mm             INTEGER,
            height_mm            INTEGER,

            -- Brakes / ABS
            front_brake_type     TEXT,
            front_brake_disc_mm  INTEGER,
            rear_brake_type      TEXT,
            rear_brake_disc_mm   INTEGER,
            abs_type             TEXT,

            -- Full payload (Power & Performance, Brakes & Wheels,
            -- Suspensions & Chassis, Dimensions, Warranty, plus the
            -- feature categories) as JSON, structured as:
            --   { "<category>": { "<field>": {"value": str, "unit": str} } }
            raw_specs_json       TEXT NOT NULL,

            PRIMARY KEY (variant_id, source),
            FOREIGN KEY (variant_id) REFERENCES bike_variants(variant_id)
              ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_bike_specs_cc
            ON bike_specs(engine_cc);
        CREATE INDEX IF NOT EXISTS idx_bike_specs_power
            ON bike_specs(max_power_bhp);
        CREATE INDEX IF NOT EXISTS idx_bike_specs_weight
            ON bike_specs(kerb_weight_kg);

        -- bike_brochures: OEM brochure PDFs per variant. The PDF
        -- itself lives on disk at `local_path` (backend/brochures_cache/
        -- <sha256>.pdf); we store metadata + content hash only so the
        -- DB stays small and we can detect republished PDFs.
        CREATE TABLE IF NOT EXISTS bike_brochures (
            variant_id        TEXT NOT NULL,
            brochure_url      TEXT NOT NULL,
            sha256            TEXT NOT NULL,
            local_path        TEXT NOT NULL,
            file_size_bytes   INTEGER NOT NULL,
            content_type      TEXT,
            first_seen_at     TEXT NOT NULL,
            last_seen_at      TEXT NOT NULL,
            PRIMARY KEY (variant_id, sha256),
            FOREIGN KEY (variant_id) REFERENCES bike_variants(variant_id)
              ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_brochures_variant
            ON bike_brochures(variant_id, last_seen_at DESC);
    """)

    # ------------- Add bike_id columns (idempotent) -------------
    for table in ("sales_data", "reviews", "themes_analysis"):
        if not _column_exists(conn, table, "bike_id"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN bike_id TEXT")
            print(f"[migrate] added bike_id to {table}")

    # ------------- themes_analysis.metrics (idempotent) -------------
    if not _column_exists(conn, "themes_analysis", "metrics"):
        conn.execute("ALTER TABLE themes_analysis ADD COLUMN metrics TEXT")
        print("[migrate] added metrics column to themes_analysis")


    # ------------- Add source column to sales_data (idempotent) -------------
    # Lets us tag rows by where they came from (rushlane, autopunditz, ...).
    # Defaults to 'rushlane' so all existing data stays attributed correctly.
    if not _column_exists(conn, "sales_data", "source"):
        conn.execute(
            "ALTER TABLE sales_data ADD COLUMN source TEXT NOT NULL DEFAULT 'rushlane'"
        )
        print("[migrate] added source column to sales_data (default: rushlane)")


def _migrate_1_youtube_cleanup(conn: sqlite3.Connection):
    """Remove the original YouTube shadow reviews once."""
    # Version 1 already shipped with this exact one-shot cleanup. Never
    # reuse its number for schema changes: existing databases may be at 1.
    deleted_yt = conn.execute("DELETE FROM reviews WHERE source = 'youtube'").rowcount
    if deleted_yt:
        print(f"[migrate] removed {deleted_yt} legacy youtube shadow rows from reviews")


def _migrate_2_legacy_schema(conn: sqlite3.Connection):
    """Upgrade all historical unversioned schemas, including version 1 files."""
    # ------------- Backfill legacy rows -------------
    for table in ("sales_data", "reviews", "themes_analysis"):
        updated = conn.execute(
            f"UPDATE {table} SET bike_id = ? WHERE bike_id IS NULL OR bike_id = ''",
            (LEGACY_BIKE_ID,),
        ).rowcount
        if updated:
            print(f"[migrate] backfilled {updated} rows in {table} -> {LEGACY_BIKE_ID}")

    # Backfill any pre-existing NULLs (shouldn't exist with NOT NULL DEFAULT,
    # but safe-guard for any edge case where the column was added without a default).
    backfilled = conn.execute(
        "UPDATE sales_data SET source = 'rushlane' WHERE source IS NULL OR source = ''"
    ).rowcount
    if backfilled:
        print(f"[migrate] backfilled source='rushlane' on {backfilled} sales rows")

    # PRAGMA inspection covers inline UNIQUE, table constraints and explicit
    # indexes, regardless of whitespace, quoting or NOT NULL placement.
    legacy_unique = False
    for index in conn.execute("PRAGMA index_list(sales_data)").fetchall():
        if index["unique"]:
            columns = tuple(row["name"] for row in conn.execute(
                "SELECT name FROM pragma_index_info(?) ORDER BY seqno", (index["name"],)
            ))
            if columns in (("month",), ("bike_id", "month")):
                if index["origin"] == "c":
                    name = index["name"].replace('"', '""')
                    conn.execute(f'DROP INDEX "{name}"')
                else:
                    legacy_unique = True
    if legacy_unique:
        print("[migrate] rebuilding sales_data to drop legacy unique constraint")
        _execute_statements(conn, """
            CREATE TABLE sales_data_new (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                month       TEXT NOT NULL,
                units_sold  INTEGER NOT NULL,
                source_url  TEXT,
                confidence  TEXT DEFAULT 'high',
                scraped_at  TEXT NOT NULL,
                bike_id     TEXT,
                source      TEXT NOT NULL DEFAULT 'rushlane'
            );
            INSERT INTO sales_data_new
                (id, month, units_sold, source_url, confidence, scraped_at, bike_id, source)
              SELECT id, month, units_sold, source_url, confidence, scraped_at, bike_id, source
              FROM sales_data;
            DROP TABLE sales_data;
            ALTER TABLE sales_data_new RENAME TO sales_data;
        """)
    conn.execute("DROP INDEX IF EXISTS idx_sales_bike_month")

    # ------------- Drop retail_brand_sales (FADA) ----------------------
    # FADA was removed entirely; the table is no longer maintained and
    # nothing reads it. Drop on first init after the upgrade so the
    # schema matches the code.
    if _table_exists(conn, "retail_brand_sales"):
        conn.execute("DROP TABLE retail_brand_sales")
        print("[migrate] dropped retail_brand_sales (FADA removed)")

    # ------------- video_transcripts: add transcript_status + drop ----
    #                NOT NULL on transcript (rebuild table)
    if _table_exists(conn, "video_transcripts"):
        cols = [r[1] for r in conn.execute("PRAGMA table_info(video_transcripts)").fetchall()]
        transcript_col = next(
            (r for r in conn.execute("PRAGMA table_info(video_transcripts)").fetchall()
             if r[1] == "transcript"),
            None,
        )
        transcript_is_required = transcript_col is not None and transcript_col[3] == 1
        need_rebuild = transcript_is_required or "transcript_status" not in cols
        if need_rebuild:
            # Rebuild with the correct shape: transcript NULLABLE, +
            # transcript_status column. We can't ALTER COLUMN in SQLite,
            # so create a fresh table and copy rows over.
            conn.execute("ALTER TABLE video_transcripts RENAME TO video_transcripts_old")
            conn.execute("""
                CREATE TABLE video_transcripts (
                    video_id          TEXT PRIMARY KEY,
                    channel_handle    TEXT NOT NULL,
                    channel_name      TEXT NOT NULL,
                    video_url         TEXT NOT NULL,
                    title             TEXT NOT NULL,
                    description       TEXT,
                    duration_s        INTEGER,
                    published_at      TEXT,
                    transcript        TEXT,
                    language          TEXT,
                    transcript_status TEXT NOT NULL DEFAULT 'ok',
                    fetched_at        TEXT NOT NULL
                )
            """)
            # Carry over both schemas (with or without transcript_status)
            if "transcript_status" in cols:
                conn.execute("""
                    INSERT INTO video_transcripts
                      (video_id, channel_handle, channel_name, video_url, title,
                       description, duration_s, published_at, transcript, language,
                       transcript_status, fetched_at)
                    SELECT video_id, channel_handle, channel_name, video_url, title,
                           description, duration_s, published_at, transcript, language,
                           transcript_status, fetched_at
                    FROM video_transcripts_old
                """)
            else:
                conn.execute("""
                    INSERT INTO video_transcripts
                      (video_id, channel_handle, channel_name, video_url, title,
                       description, duration_s, published_at, transcript, language,
                       fetched_at)
                    SELECT video_id, channel_handle, channel_name, video_url, title,
                           description, duration_s, published_at, transcript, language,
                           fetched_at
                    FROM video_transcripts_old
                """)
            conn.execute("DROP TABLE video_transcripts_old")
            print("[migrate] rebuilt video_transcripts: transcript nullable + transcript_status column")


def _ensure_indexes_and_seeds(conn: sqlite3.Connection):
    """Ensure current indexes and seed rows without replacing existing data."""
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_bike_month_source "
        "ON sales_data(bike_id, month, source)"
    )

    # ------------- Seed bike_segments (idempotent INSERT OR IGNORE) ----
    # Hand-curated industry-standard segments grouped by cc band x body
    # style. Sort order keeps related segments together (commuters →
    # sports → naked → modern-classic → adventure → cruiser → scooters
    # → electric).
    for s in _SEGMENT_SEED:
        conn.execute(
            """INSERT OR IGNORE INTO bike_segments
                 (segment_id, display_name, body_style, cc_min, cc_max, sort_order)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                s["segment_id"], s["display_name"], s["body_style"],
                s.get("cc_min"), s.get("cc_max"), s["sort_order"],
            ),
        )

    # ------------- Seed XSR 155 bike row if missing -------------
    if not conn.execute("SELECT 1 FROM bikes WHERE id = ?", (LEGACY_BIKE_ID,)).fetchone():
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO bikes
               (id, brand, model, display_name, keywords, bikewale_slug,
                bikewale_ok, launch_month, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                LEGACY_BIKE_ID,
                "Yamaha",
                "XSR 155",
                "Yamaha XSR 155",
                _json.dumps(["XSR 155", "XSR"]),
                "yamaha-bikes/xsr-155",
                1,
                "2025-11",
                now, now,
            ),
        )
        print(f"[migrate] seeded bike row: {LEGACY_BIKE_ID}")


# Append new migrations with increasing numbers; never renumber shipped ones.
_MIGRATIONS = (
    (1, _migrate_1_youtube_cleanup),
    (2, _migrate_2_legacy_schema),
)


def init_db():
    """Ensure schema and apply pending upgrades atomically, then close.

    WAL is a persistent connection setting and must be selected outside the
    transaction. BEGIN IMMEDIATE serializes concurrent initializers before
    they read user_version. All schema/data changes and version marks commit
    together; a failure leaves the previous version retryable.
    """
    with closing(get_conn()) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > _MIGRATIONS[-1][0]:
                raise RuntimeError(f"Database version {version} is newer than supported")
            _ensure_schema(conn)
            for target, migrate in _MIGRATIONS:
                if version < target:
                    migrate(conn)
                    conn.execute(f"PRAGMA user_version = {target}")
            _ensure_indexes_and_seeds(conn)


# ---------------------------------------------------------------------------
# Bikes
# ---------------------------------------------------------------------------

def upsert_bike(
    bike_id: str,
    brand: str,
    model: str,
    display_name: str,
    keywords: list[str],
    bikewale_slug: str | None = None,
    launch_month: str | None = None,
):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        existing = conn.execute("SELECT 1 FROM bikes WHERE id = ?", (bike_id,)).fetchone()
        if existing:
            conn.execute(
                """UPDATE bikes
                   SET display_name = ?, keywords = ?, last_seen_at = ?,
                       bikewale_slug = COALESCE(?, bikewale_slug),
                       launch_month = COALESCE(launch_month, ?)
                   WHERE id = ?""",
                (display_name, _json.dumps(keywords), now, bikewale_slug, launch_month, bike_id),
            )
        else:
            conn.execute(
                """INSERT INTO bikes
                   (id, brand, model, display_name, keywords, bikewale_slug,
                    bikewale_ok, launch_month, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
                (bike_id, brand, model, display_name, _json.dumps(keywords),
                 bikewale_slug, launch_month, now, now),
            )


def set_bikewale_ok(bike_id: str, ok: bool, slug: str | None = None):
    with get_conn() as conn:
        if slug is not None:
            conn.execute(
                "UPDATE bikes SET bikewale_ok = ?, bikewale_slug = ? WHERE id = ?",
                (1 if ok else 0, slug, bike_id),
            )
        else:
            conn.execute(
                "UPDATE bikes SET bikewale_ok = ? WHERE id = ?",
                (1 if ok else 0, bike_id),
            )


def get_bike(bike_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM bikes WHERE id = ?", (bike_id,)).fetchone()
    if not row:
        return None
    out = dict(row)
    out["keywords"] = _json.loads(out.get("keywords") or "[]")
    return out


def delete_bike(bike_id: str) -> int:
    """Delete an analytics bike and its sales, reviews (and their
    cached embeddings), themes, review cursors, video-bike matches.
    The separately scraped variant catalogue and its specs/brochures survive:
    parent_model_id is a grouping key, not an ownership foreign key to bikes.
    Returns rows removed."""
    with get_conn() as conn:
        # Embeddings first — they're keyed by the reviews' post_ids, which
        # are gone once the reviews are deleted.
        n_emb = conn.execute(
            """DELETE FROM review_embeddings WHERE post_id IN
                 (SELECT post_id FROM reviews WHERE bike_id = ?)""",
            (bike_id,),
        ).rowcount
        n_sales = conn.execute("DELETE FROM sales_data WHERE bike_id = ?", (bike_id,)).rowcount
        n_reviews = conn.execute("DELETE FROM reviews WHERE bike_id = ?", (bike_id,)).rowcount
        n_themes = conn.execute("DELETE FROM themes_analysis WHERE bike_id = ?", (bike_id,)).rowcount
        n_cursors = conn.execute("DELETE FROM review_cursor WHERE bike_id = ?", (bike_id,)).rowcount
        n_matches = conn.execute("DELETE FROM video_bike_match WHERE bike_id = ?", (bike_id,)).rowcount
        conn.execute("DELETE FROM bikes WHERE id = ?", (bike_id,))
    return n_sales + n_reviews + n_themes + n_cursors + n_matches + n_emb


def get_all_bikes() -> list[dict]:
    """Return bikes with sales aggregates and review/theme presence flags."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT b.*,
                   COALESCE(s.total_units, 0)     AS total_units,
                   COALESCE(s.months_tracked, 0)  AS months_tracked,
                   COALESCE(s.latest_month, NULL) AS latest_month,
                   COALESCE(r.review_count, 0)    AS review_count,
                   COALESCE(t.themes_count, 0)    AS themes_count
            FROM bikes b
            LEFT JOIN (
                SELECT bike_id,
                       SUM(units_sold)    AS total_units,
                       COUNT(DISTINCT month) AS months_tracked,
                       MAX(month)         AS latest_month
                FROM sales_data
                GROUP BY bike_id
            ) s ON s.bike_id = b.id
            LEFT JOIN (
                SELECT bike_id, COUNT(*) AS review_count
                FROM reviews
                GROUP BY bike_id
            ) r ON r.bike_id = b.id
            LEFT JOIN (
                SELECT bike_id, COUNT(*) AS themes_count
                FROM themes_analysis
                GROUP BY bike_id
            ) t ON t.bike_id = b.id
            ORDER BY total_units DESC, b.display_name ASC
        """).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["keywords"] = _json.loads(d.get("keywords") or "[]")
        d["has_reviews"] = bool(d.get("bikewale_ok")) or d.get("review_count", 0) > 0
        d["has_themes"] = d.get("themes_count", 0) > 0
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Sales — all bike-scoped
# ---------------------------------------------------------------------------

def upsert_sale(bike_id: str, month: str, units_sold: int,
                source_url: str = None, confidence: str = "high",
                source: str = "rushlane"):
    """Upsert a sales row. `source` keys the row alongside (bike_id, month) so
    multiple sources (rushlane, autopunditz, ...) can coexist for the same bike-month."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sales_data (bike_id, month, units_sold, source_url, confidence, scraped_at, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(bike_id, month, source) DO UPDATE SET
                 units_sold=excluded.units_sold,
                 source_url=excluded.source_url,
                 confidence=excluded.confidence,
                 scraped_at=excluded.scraped_at""",
            (bike_id, month, units_sold, source_url, confidence, now, source),
        )


def get_all_sales(bike_id: str | None = None,
                  source: str | None = None) -> list[dict]:
    """List sales rows. Filter by bike_id and/or source. Default source=None
    returns ALL sources, so existing callers see everything."""
    with get_conn() as conn:
        clauses = []
        params: list = []
        if bike_id:
            clauses.append("bike_id = ?")
            params.append(bike_id)
        if source:
            clauses.append("source = ?")
            params.append(source)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"""SELECT bike_id, month, units_sold, source_url, confidence, scraped_at, source
                FROM sales_data {where}
                ORDER BY bike_id, month ASC, source ASC""",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_metrics(bike_id: str) -> dict:
    sales = get_all_sales(bike_id=bike_id)
    if not sales:
        return {"latest_month": None, "peak_month": None, "total_units": 0,
                "months_tracked": 0, "last_refresh": None}

    peak = max(sales, key=lambda r: r["units_sold"])
    latest = sales[-1]
    total = sum(r["units_sold"] for r in sales)

    last_refresh = None
    with get_conn() as conn:
        row = conn.execute("SELECT run_at FROM scrape_log ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            last_refresh = row["run_at"]

    return {
        "latest_month": {"month": latest["month"], "units_sold": latest["units_sold"]},
        "peak_month": {"month": peak["month"], "units_sold": peak["units_sold"]},
        "total_units": total,
        "months_tracked": len(sales),
        "last_refresh": last_refresh,
    }


def log_scrape_run(urls_tried: int, urls_success: int, error_msg: str = None):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO scrape_log (run_at, urls_tried, urls_success, error_msg) VALUES (?, ?, ?, ?)",
            (now, urls_tried, urls_success, error_msg),
        )


def get_last_scrape_log() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT run_at, urls_tried, urls_success, error_msg FROM scrape_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Reviews — bike-scoped
# ---------------------------------------------------------------------------

def upsert_review(bike_id: str, source: str, post_id: str, username: str,
                  review_text: str, overall_rating: float = None,
                  thread_url: str = None):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO reviews
               (bike_id, source, post_id, username, review_text, overall_rating, thread_url, scraped_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(post_id) DO UPDATE SET
                 bike_id=excluded.bike_id,
                 username=excluded.username,
                 review_text=excluded.review_text,
                 overall_rating=excluded.overall_rating,
                 scraped_at=excluded.scraped_at""",
            (bike_id, source, post_id, username, review_text, overall_rating, thread_url, now),
        )


def get_all_reviews(bike_id: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if bike_id:
            rows = conn.execute(
                """SELECT id, bike_id, source, post_id, username, review_text,
                          overall_rating, thread_url, scraped_at
                   FROM reviews WHERE bike_id = ?
                   ORDER BY source, scraped_at DESC""",
                (bike_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, bike_id, source, post_id, username, review_text,
                          overall_rating, thread_url, scraped_at
                   FROM reviews ORDER BY bike_id, source, scraped_at DESC"""
            ).fetchall()
    return [dict(r) for r in rows]


def get_reviews_by_brand(brand: str) -> list[dict]:
    """All reviews for every bike whose `bikes.brand` matches (case-insensitive).

    Used by cross-bike pooling — clustering 500 reviews across a brand reveals
    far sharper themes than 10 reviews from a single niche bike. The bike_id
    on each row is preserved so callers can compute per-bike attribution
    (e.g. `localized_share`)."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT r.id, r.bike_id, r.source, r.post_id, r.username,
                      r.review_text, r.overall_rating, r.thread_url,
                      r.scraped_at
               FROM reviews r
               JOIN bikes b ON b.id = r.bike_id
               WHERE LOWER(b.brand) = LOWER(?)
               ORDER BY r.bike_id, r.source, r.scraped_at DESC""",
            (brand,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_reviews_by_scope(scope: str, scope_id: str) -> list[dict]:
    """Dispatch helper for cross-bike pooling.

    scope='bike'  -> get_all_reviews(bike_id=scope_id)
    scope='brand' -> get_reviews_by_brand(scope_id)  (scope_id is the brand slug)
    """
    if scope == "bike":
        return get_all_reviews(bike_id=scope_id)
    if scope == "brand":
        return get_reviews_by_brand(scope_id)
    raise ValueError(f"unknown scope: {scope!r}")


def get_review_summary(bike_id: str) -> dict:
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE bike_id = ?", (bike_id,)
        ).fetchone()[0]
        by_source = {
            row["source"]: row["cnt"]
            for row in conn.execute(
                "SELECT source, COUNT(*) as cnt FROM reviews WHERE bike_id = ? GROUP BY source",
                (bike_id,),
            ).fetchall()
        }
        avg_row = conn.execute(
            "SELECT AVG(overall_rating) as avg FROM reviews "
            "WHERE bike_id = ? AND overall_rating IS NOT NULL",
            (bike_id,),
        ).fetchone()
        avg_rating = round(avg_row["avg"], 2) if avg_row["avg"] else None
        last_run = conn.execute(
            "SELECT run_at FROM reviews_log ORDER BY id DESC LIMIT 1"
        ).fetchone()

    return {
        "total": total,
        "by_source": by_source,
        "avg_rating": avg_rating,
        "last_refresh": last_run["run_at"] if last_run else None,
    }


def log_reviews_run(total_scraped: int, error_msg: str = None):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO reviews_log (run_at, total_scraped, error_msg) VALUES (?, ?, ?)",
            (now, total_scraped, error_msg),
        )


def get_last_reviews_log() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT run_at, total_scraped, error_msg FROM reviews_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Wholesale brand sales (AutoPunditz aggregate)
# ---------------------------------------------------------------------------

def upsert_wholesale_brand_sale(
    brand_id: str,
    month: str,
    units: int,
    source_url: str | None = None,
    source: str = "autopunditz",
):
    """Upsert a brand-level monthly wholesale row (e.g. from AutoPunditz)."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO wholesale_brand_sales (brand_id, month, units, source, source_url, scraped_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(brand_id, month, source) DO UPDATE SET
                 units=excluded.units,
                 source_url=excluded.source_url,
                 scraped_at=excluded.scraped_at""",
            (brand_id, month, units, source, source_url, now),
        )


def get_wholesale_brand_sales(brand_id: str | None = None,
                              source: str | None = None) -> list[dict]:
    """Return wholesale brand rows. Filter by brand_id and/or source."""
    with get_conn() as conn:
        clauses = []
        params: list = []
        if brand_id:
            clauses.append("brand_id = ?")
            params.append(brand_id)
        if source:
            clauses.append("source = ?")
            params.append(source)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"""SELECT brand_id, month, units, source, source_url, scraped_at
                FROM wholesale_brand_sales {where}
                ORDER BY month ASC""",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_brand_metrics(brand_id: str) -> dict:
    """Brand-level aggregate metrics (latest / peak / total / months_tracked),
    summed across every bike in the brand from RushLane wholesale rows.
    Same response shape as `get_metrics(bike_id)` so the frontend can reuse
    the MetricsCards component without branching."""
    sales = get_wholesale_brand_totals(brand_id)
    if not sales:
        return {
            "latest_month": None, "peak_month": None, "total_units": 0,
            "months_tracked": 0, "last_refresh": None,
        }

    peak = max(sales, key=lambda r: r["units"])
    latest = sales[-1]
    total = sum(r["units"] for r in sales)

    last_refresh = None
    with get_conn() as conn:
        row = conn.execute("SELECT run_at FROM scrape_log ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            last_refresh = row["run_at"]

    return {
        "latest_month": {"month": latest["month"], "units_sold": int(latest["units"])},
        "peak_month": {"month": peak["month"], "units_sold": int(peak["units"])},
        "total_units": int(total),
        "months_tracked": len(sales),
        "last_refresh": last_refresh,
    }


def get_wholesale_brand_totals(brand_id: str, source: str = "rushlane") -> list[dict]:
    """Sum model-level wholesale rows up to brand-monthly totals for a single
    `source` (default 'rushlane'). `brand_id` matches the prefix of bike_id
    (e.g. 'yamaha' -> 'yamaha-*'). Filtering to one source avoids double-counting
    when multiple wholesale sources (rushlane, autopunditz) report on the same
    bike-month."""
    prefix = f"{brand_id}-%"
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT month, SUM(units_sold) AS units
               FROM sales_data
               WHERE bike_id LIKE ?
                 AND source = ?
               GROUP BY month
               ORDER BY month ASC""",
            (prefix, source),
        ).fetchall()
    return [{"month": r["month"], "units": r["units"]} for r in rows]


# ---------------------------------------------------------------------------
# URL conditional-GET cache + per-bike review cursors
# ---------------------------------------------------------------------------

def get_url_cache_entry(url: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT url, etag, last_modified, content_hash, last_status, last_fetched_at "
            "FROM url_cache WHERE url = ?",
            (url,),
        ).fetchone()
    return dict(row) if row else None


def upsert_url_cache(
    url: str,
    etag: str | None,
    last_modified: str | None,
    content_hash: str | None,
    last_status: int,
):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO url_cache (url, etag, last_modified, content_hash,
                                      last_status, last_fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                 etag = excluded.etag,
                 last_modified = excluded.last_modified,
                 content_hash = excluded.content_hash,
                 last_status = excluded.last_status,
                 last_fetched_at = excluded.last_fetched_at""",
            (url, etag, last_modified, content_hash, last_status, now),
        )


def clear_url_cache() -> int:
    """Wipe the cache. Returns the number of rows deleted. Used by the
    /api/refresh-all?force=true endpoint."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM url_cache")
        return cur.rowcount


def get_review_cursor(bike_id: str, source: str) -> str | None:
    """Return last_post_id we've seen for this (bike, source), or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT last_post_id FROM review_cursor WHERE bike_id = ? AND source = ?",
            (bike_id, source),
        ).fetchone()
    return row["last_post_id"] if row else None


def upsert_review_cursor(bike_id: str, source: str, last_post_id: str):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO review_cursor (bike_id, source, last_post_id, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(bike_id, source) DO UPDATE SET
                 last_post_id = excluded.last_post_id,
                 updated_at = excluded.updated_at""",
            (bike_id, source, last_post_id, now),
        )


# ---------------------------------------------------------------------------
# YouTube video transcripts (Stage 6)
# ---------------------------------------------------------------------------

def upsert_video_transcript(
    video_id: str,
    channel_handle: str,
    channel_name: str,
    video_url: str,
    title: str,
    description: str | None,
    duration_s: int | None,
    published_at: str | None,
    transcript: str | None,
    language: str | None,
    transcript_status: str = "ok",
):
    """Upsert video metadata. `transcript` may be None when the captions
    fetch failed (rate-limit or no captions); in that case set
    `transcript_status` to 'rate_limited' or 'no_captions' so the next
    refresh can retry the pending ones.

    Note: ON CONFLICT preserves existing transcript text if the new attempt
    didn't fetch one. So a successful pull never gets clobbered by a later
    rate-limited retry that only has metadata."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO video_transcripts
               (video_id, channel_handle, channel_name, video_url, title,
                description, duration_s, published_at, transcript, language,
                transcript_status, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(video_id) DO UPDATE SET
                 title = excluded.title,
                 description = excluded.description,
                 duration_s = excluded.duration_s,
                 published_at = excluded.published_at,
                 -- only overwrite transcript when the new fetch actually
                 -- got one; otherwise keep what we already had
                 transcript = COALESCE(excluded.transcript, video_transcripts.transcript),
                 language = COALESCE(excluded.language, video_transcripts.language),
                 transcript_status = CASE
                     WHEN excluded.transcript IS NOT NULL THEN excluded.transcript_status
                     WHEN video_transcripts.transcript IS NOT NULL THEN video_transcripts.transcript_status
                     ELSE excluded.transcript_status
                 END,
                 fetched_at = excluded.fetched_at""",
            (video_id, channel_handle, channel_name, video_url, title,
             description, duration_s, published_at, transcript, language,
             transcript_status, now),
        )


def video_transcript_exists(video_id: str) -> bool:
    """True only when we successfully fetched a transcript for this video.
    Videos with metadata-only rows (rate_limited / no_captions / pending)
    return False so the next refresh retries them."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM video_transcripts "
            "WHERE video_id = ? AND transcript IS NOT NULL",
            (video_id,),
        ).fetchone()
    return row is not None


def list_all_video_transcripts(
    channel_handle: str | None = None,
    bike_id: str | None = None,
    q: str | None = None,
    limit: int = 500,
    include_transcript: bool = False,
) -> list[dict]:
    """List videos for the Influencer Reviews tab. Filterable by channel
    handle, bike_id (joins through video_bike_match), and free-text search.

    bike_id is the link to the dashboard's top picker — when the user
    has Honda Shine selected, we scope to videos tagged with
    'honda-shine' so the listing matches the page context.

    `include_transcript` defaults to False — the listing endpoint serves
    metadata only. Transcripts are 5–10k chars each; fetching all of them
    on tab load makes the network round-trip slow on the dev proxy and
    is wasteful when most users won't expand them."""
    cols = (
        "v.video_id, v.channel_handle, v.channel_name, v.video_url, "
        "v.title, v.description, v.duration_s, v.published_at, v.language, "
        "v.transcript_status, v.fetched_at"
        + (", v.transcript" if include_transcript else "")
    )
    join = ""
    clauses: list[str] = []
    params: list = []
    if bike_id:
        join = "JOIN video_bike_match m ON v.video_id = m.video_id"
        clauses.append("m.bike_id = ?")
        params.append(bike_id)
    if channel_handle:
        clauses.append("v.channel_handle = ?")
        params.append(channel_handle)
    if q:
        clauses.append("(LOWER(v.title) LIKE ? OR LOWER(v.description) LIKE ?)")
        params.append(f"%{q.lower()}%")
        params.append(f"%{q.lower()}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT {cols}
               FROM video_transcripts v {join} {where}
               ORDER BY COALESCE(v.published_at, v.fetched_at) DESC
               LIMIT ?""",
            (*params, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_channel_video_counts() -> dict[str, int]:
    """Return {channel_handle: video_count} across all rows in
    video_transcripts. Used by the Influencer Reviews tab to label
    filter chips without pulling the full list."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT channel_handle, COUNT(*) FROM video_transcripts "
            "GROUP BY channel_handle"
        ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def upsert_video_bike_match(video_id: str, bike_id: str):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO video_bike_match (video_id, bike_id, matched_at)
               VALUES (?, ?, ?)
               ON CONFLICT(video_id, bike_id) DO NOTHING""",
            (video_id, bike_id, now),
        )


def get_video_transcripts_for_bike(
    bike_id: str, include_transcript: bool = True
) -> list[dict]:
    """List videos matched to this bike (newest first). When
    `include_transcript` is True, the full transcript blob is returned
    alongside metadata — used by the Influencer Reviews tab."""
    cols = (
        "v.video_id, v.channel_handle, v.channel_name, v.video_url, "
        "v.title, v.description, v.published_at, v.duration_s, v.language, "
        "v.fetched_at"
        + (", v.transcript" if include_transcript else "")
    )
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT {cols}
               FROM video_transcripts v
               JOIN video_bike_match m ON v.video_id = m.video_id
               WHERE m.bike_id = ?
               ORDER BY COALESCE(v.published_at, v.fetched_at) DESC""",
            (bike_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_youtube_channel_cursor(channel_handle: str) -> str | None:
    """Return the newest video_id we've inspected for this channel, or None
    if we've never refreshed it before."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT last_video_id FROM youtube_channel_cursor WHERE channel_handle = ?",
            (channel_handle,),
        ).fetchone()
    return row["last_video_id"] if row else None


def upsert_youtube_channel_cursor(channel_handle: str, last_video_id: str):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO youtube_channel_cursor
                 (channel_handle, last_video_id, last_checked_at)
               VALUES (?, ?, ?)
               ON CONFLICT(channel_handle) DO UPDATE SET
                 last_video_id = excluded.last_video_id,
                 last_checked_at = excluded.last_checked_at""",
            (channel_handle, last_video_id, now),
        )


def clear_youtube_channel_cursors() -> int:
    """Wipe the cursors. Called when refresh-all?force=true so the next
    refresh re-walks every channel from scratch."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM youtube_channel_cursor")
        return cur.rowcount


# ---------------------------------------------------------------------------
# Themes — bike-scoped
# ---------------------------------------------------------------------------

def save_themes_analysis(
    bike_id: str,
    method: str,
    config: dict,
    themes: list,
    metrics: dict | None = None,
):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO themes_analysis (bike_id, method, config, themes, metrics, run_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                bike_id,
                method,
                _json.dumps(config),
                _json.dumps(themes),
                _json.dumps(metrics) if metrics is not None else None,
                now,
            ),
        )


def get_latest_themes(bike_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT method, config, themes, metrics, run_at FROM themes_analysis
               WHERE bike_id = ? ORDER BY id DESC LIMIT 1""",
            (bike_id,),
        ).fetchone()
    if not row:
        return None
    metrics_raw = row["metrics"]
    return {
        "method": row["method"],
        "config": _json.loads(row["config"]),
        "themes": _json.loads(row["themes"]),
        "metrics": _json.loads(metrics_raw) if metrics_raw else None,
        "run_at": row["run_at"],
    }


def get_themes_status(bike_id: str | None = None) -> dict:
    with get_conn() as conn:
        if bike_id:
            total = conn.execute(
                "SELECT COUNT(*) FROM themes_analysis WHERE bike_id = ?", (bike_id,)
            ).fetchone()[0]
            last = conn.execute(
                "SELECT method, run_at FROM themes_analysis WHERE bike_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (bike_id,),
            ).fetchone()
        else:
            total = conn.execute("SELECT COUNT(*) FROM themes_analysis").fetchone()[0]
            last = conn.execute(
                "SELECT method, run_at FROM themes_analysis ORDER BY id DESC LIMIT 1"
            ).fetchone()
    return {
        "total_analyses": total,
        "last_method": last["method"] if last else None,
        "last_run_at": last["run_at"] if last else None,
    }


# ---------------------------------------------------------------------------
# Review embedding cache
# ---------------------------------------------------------------------------

_SOURCE_DISPLAY_ORDER = ["autopunditz", "rushlane"]


def _source_sort_key(source: str) -> tuple[int, str]:
    """Sort key that puts AutoPunditz first, RushLane second, then any
    other source alphabetically. Used for consistent ordering of the
    distribution popover in both bike-level and brand-level charts."""
    if source in _SOURCE_DISPLAY_ORDER:
        return (_SOURCE_DISPLAY_ORDER.index(source), source)
    return (len(_SOURCE_DISPLAY_ORDER), source)


def get_sales_by_month_with_sources(bike_id: str) -> list[dict]:
    """Per-month breakdown showing every source that reported a value for
    this bike. Used by the unified Sales view's distribution popover and by
    forecast.build_complete_index when picking the canonical value.

    Sources within each month are ordered AutoPunditz first, RushLane
    second, then anything else alphabetically — matches the brand-level
    promotion where AutoPunditz is the primary.

    Returns rows in chronological order, one per (bike_id, month):
        [{
            "month": "2026-03",
            "sources": [
                {"source": "autopunditz", "units_sold": 13500, "source_url": "..."},
                {"source": "rushlane",    "units_sold": 13500, "source_url": "..."},
            ],
        }, ...]
    """
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT month, source, units_sold, source_url
               FROM sales_data
               WHERE bike_id = ?
               ORDER BY month ASC""",
            (bike_id,),
        ).fetchall()
    by_month: dict[str, list[dict]] = {}
    for r in rows:
        m = r["month"]
        by_month.setdefault(m, []).append({
            "source": r["source"],
            "units_sold": int(r["units_sold"]),
            "source_url": r["source_url"],
        })
    out = []
    for m, sources in by_month.items():
        sources.sort(key=lambda s: _source_sort_key(s["source"]))
        out.append({"month": m, "sources": sources})
    return out


def get_cached_embeddings(post_ids: list[str], model: str) -> dict[str, bytes]:
    """Return {post_id: embedding_bytes} for any cached entries. Caller is
    responsible for deserialising via numpy.frombuffer(..., dtype=float32)."""
    if not post_ids:
        return {}
    placeholders = ",".join("?" * len(post_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT post_id, embedding FROM review_embeddings "
            f"WHERE model = ? AND post_id IN ({placeholders})",
            (model, *post_ids),
        ).fetchall()
    return {r["post_id"]: r["embedding"] for r in rows}


def cache_embeddings(
    post_ids: list[str],
    model: str,
    embeddings_bytes: list[bytes],
    dim: int,
) -> None:
    """Upsert per-post embeddings. Lengths of post_ids and embeddings_bytes
    must match. No-op for empty inputs."""
    if not post_ids:
        return
    if len(post_ids) != len(embeddings_bytes):
        raise ValueError(
            f"post_ids ({len(post_ids)}) / embeddings_bytes ({len(embeddings_bytes)}) length mismatch"
        )
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO review_embeddings (post_id, model, embedding, dim, cached_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(post_id, model) DO UPDATE SET "
            "  embedding = excluded.embedding, dim = excluded.dim, cached_at = excluded.cached_at",
            [(pid, model, blob, dim, now) for pid, blob in zip(post_ids, embeddings_bytes)],
        )


# ---------------------------------------------------------------------------
# Bike segments + variants (BikeWale-as-base catalogue)
# ---------------------------------------------------------------------------

def list_segments() -> list[dict]:
    """All segments in display order. Used for filter dropdowns and to
    drive the 'compare with segment peers' filter on Owner Insights."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT segment_id, display_name, body_style, cc_min, cc_max, sort_order
               FROM bike_segments
               ORDER BY sort_order ASC, display_name ASC"""
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_bike_variant(
    variant_id: str,
    parent_model_id: str,
    brand_id: str,
    display_name: str,
    bikewale_slug: str,
    segment_id: str | None = None,
    displacement_cc: int | None = None,
    price_onroad: int | None = None,
    bikedekho_slug: str | None = None,
    image_url: str | None = None,
    status: str = "on_sale",
    launch_year: int | None = None,
):
    """Upsert a variant. last_seen_at is bumped on every call so we can
    later detect rows that fell off BikeWale (mark as discontinued)."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO bike_variants
                 (variant_id, parent_model_id, brand_id, segment_id, display_name,
                  displacement_cc, price_onroad, bikewale_slug, bikedekho_slug,
                  image_url, status, launch_year, discovered_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(variant_id) DO UPDATE SET
                 parent_model_id = excluded.parent_model_id,
                 brand_id = excluded.brand_id,
                 segment_id = COALESCE(excluded.segment_id, bike_variants.segment_id),
                 display_name = excluded.display_name,
                 displacement_cc = COALESCE(excluded.displacement_cc, bike_variants.displacement_cc),
                 price_onroad = COALESCE(excluded.price_onroad, bike_variants.price_onroad),
                 bikewale_slug = excluded.bikewale_slug,
                 bikedekho_slug = COALESCE(excluded.bikedekho_slug, bike_variants.bikedekho_slug),
                 image_url = COALESCE(excluded.image_url, bike_variants.image_url),
                 status = excluded.status,
                 launch_year = COALESCE(excluded.launch_year, bike_variants.launch_year),
                 last_seen_at = excluded.last_seen_at""",
            (variant_id, parent_model_id, brand_id, segment_id, display_name,
             displacement_cc, price_onroad, bikewale_slug, bikedekho_slug,
             image_url, status, launch_year, now, now),
        )


def list_variants(
    parent_model_id: str | None = None,
    segment_id: str | None = None,
    brand_id: str | None = None,
    on_sale_only: bool = True,
) -> list[dict]:
    """List variants with optional filters. Used by per-bike views (filter
    by parent_model_id) and segment-peer comparison (filter by segment_id)."""
    clauses: list[str] = []
    params: list = []
    if parent_model_id:
        clauses.append("parent_model_id = ?")
        params.append(parent_model_id)
    if segment_id:
        clauses.append("segment_id = ?")
        params.append(segment_id)
    if brand_id:
        clauses.append("brand_id = ?")
        params.append(brand_id)
    if on_sale_only:
        clauses.append("status = 'on_sale'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT variant_id, parent_model_id, brand_id, segment_id,
                       display_name, displacement_cc, price_onroad,
                       bikewale_slug, bikedekho_slug, image_url, status,
                       launch_year, discovered_at, last_seen_at
               FROM bike_variants {where}
               ORDER BY brand_id, parent_model_id, displacement_cc""",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Specs & brochures
# ---------------------------------------------------------------------------

# Columns of bike_specs that the scraper derives from raw_specs_json.
# Listed once so `upsert_bike_spec` and the SQL stay in sync.
_SPEC_TYPED_COLS = (
    "engine_cc", "max_power_bhp", "max_power_rpm", "max_torque_nm",
    "max_torque_rpm", "cylinders", "cooling", "fuel_system",
    "transmission", "gears", "starter", "emission_standard", "fuel_type",
    "mileage_kmpl", "top_speed_kmph", "fuel_tank_l",
    "kerb_weight_kg", "seat_height_mm", "ground_clearance_mm", "wheelbase_mm",
    "length_mm", "width_mm", "height_mm",
    "front_brake_type", "front_brake_disc_mm", "rear_brake_type",
    "rear_brake_disc_mm", "abs_type",
)


def upsert_bike_spec(
    variant_id: str,
    source: str,
    source_url: str,
    typed: dict,
    raw_specs_json: str,
):
    """Upsert spec row for a (variant, source). `typed` is a dict whose keys
    are a subset of _SPEC_TYPED_COLS; missing keys are stored as NULL.
    `raw_specs_json` is the full categorised payload as a JSON string."""
    now = datetime.now(timezone.utc).isoformat()
    cols = ("variant_id", "source", "source_url", "scraped_at",
            *_SPEC_TYPED_COLS, "raw_specs_json")
    values = [
        variant_id, source, source_url, now,
        *(typed.get(c) for c in _SPEC_TYPED_COLS),
        raw_specs_json,
    ]
    placeholders = ", ".join("?" * len(cols))
    col_list = ", ".join(cols)
    update_set = ", ".join(
        f"{c} = excluded.{c}"
        for c in cols if c not in ("variant_id", "source")
    )
    with get_conn() as conn:
        conn.execute(
            f"""INSERT INTO bike_specs ({col_list}) VALUES ({placeholders})
                ON CONFLICT(variant_id, source) DO UPDATE SET {update_set}""",
            values,
        )


def get_bike_specs(variant_id: str, source: str | None = None) -> list[dict]:
    """Fetch spec row(s) for a variant. If source is omitted, returns all
    sources for the variant (BikeWale + any OEM-direct rows)."""
    with get_conn() as conn:
        if source:
            rows = conn.execute(
                "SELECT * FROM bike_specs WHERE variant_id = ? AND source = ?",
                (variant_id, source),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM bike_specs WHERE variant_id = ? ORDER BY source",
                (variant_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def upsert_brochure(
    variant_id: str,
    brochure_url: str,
    sha256: str,
    local_path: str,
    file_size_bytes: int,
    content_type: str | None = None,
):
    """Upsert a brochure entry. Re-saving the same sha256 just bumps
    last_seen_at; a new sha256 inserts a new row (i.e. OEM republished)."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO bike_brochures
                 (variant_id, brochure_url, sha256, local_path,
                  file_size_bytes, content_type, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(variant_id, sha256) DO UPDATE SET
                 brochure_url = excluded.brochure_url,
                 local_path = excluded.local_path,
                 file_size_bytes = excluded.file_size_bytes,
                 content_type = COALESCE(excluded.content_type, bike_brochures.content_type),
                 last_seen_at = excluded.last_seen_at""",
            (variant_id, brochure_url, sha256, local_path,
             file_size_bytes, content_type, now, now),
        )


def list_brochures(variant_id: str) -> list[dict]:
    """All brochures known for a variant, most-recently-seen first."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT variant_id, brochure_url, sha256, local_path,
                      file_size_bytes, content_type,
                      first_seen_at, last_seen_at
               FROM bike_brochures
               WHERE variant_id = ?
               ORDER BY last_seen_at DESC""",
            (variant_id,),
        ).fetchall()
    return [dict(r) for r in rows]
