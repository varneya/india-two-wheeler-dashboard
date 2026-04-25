import json as _json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "sales.db"

# The original single-bike data was for XSR 155. All un-tagged rows get
# attributed to this bike during the multi-bike migration.
LEGACY_BIKE_ID = "yamaha-xsr-155"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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


def init_db():
    with get_conn() as conn:
        # ------------- Base tables (idempotent CREATE IF NOT EXISTS) -------------
        conn.executescript("""
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
            -- Brand-level monthly retail data (FADA). Sits alongside sales_data
            -- (which is model-level wholesale). Kept separate so model-level
            -- queries don't accidentally aggregate over brand rows.
            CREATE TABLE IF NOT EXISTS retail_brand_sales (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_id    TEXT NOT NULL,
                month       TEXT NOT NULL,
                units       INTEGER NOT NULL,
                source      TEXT NOT NULL DEFAULT 'fada_retail',
                source_url  TEXT,
                scraped_at  TEXT NOT NULL,
                UNIQUE(brand_id, month, source)
            );
        """)

        # ------------- Add bike_id columns (idempotent) -------------
        for table in ("sales_data", "reviews", "themes_analysis"):
            if not _column_exists(conn, table, "bike_id"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN bike_id TEXT")
                print(f"[migrate] added bike_id to {table}")

        # ------------- Backfill legacy rows -------------
        for table in ("sales_data", "reviews", "themes_analysis"):
            updated = conn.execute(
                f"UPDATE {table} SET bike_id = ? WHERE bike_id IS NULL OR bike_id = ''",
                (LEGACY_BIKE_ID,),
            ).rowcount
            if updated:
                print(f"[migrate] backfilled {updated} rows in {table} -> {LEGACY_BIKE_ID}")

        # ------------- Migrate sales_data unique constraint -------------
        # Old schema had UNIQUE(month). New: UNIQUE(bike_id, month).
        # SQLite can't drop a UNIQUE constraint defined inline -> rebuild table
        # if the legacy unique constraint is detected on the `month` column.
        sd_sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='sales_data'"
        ).fetchone()
        sd_sql = (sd_sql_row["sql"] or "") if sd_sql_row else ""
        # Normalise whitespace and detect "month ... UNIQUE" before the next column
        sd_sql_norm = " ".join(sd_sql.split())
        legacy_unique = bool(re.search(r"month\s+\w+\s+UNIQUE", sd_sql_norm))
        if legacy_unique:
            print("[migrate] rebuilding sales_data to drop legacy UNIQUE(month)")
            conn.executescript("""
                CREATE TABLE sales_data_new (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    month       TEXT NOT NULL,
                    units_sold  INTEGER NOT NULL,
                    source_url  TEXT,
                    confidence  TEXT DEFAULT 'high',
                    scraped_at  TEXT NOT NULL,
                    bike_id     TEXT
                );
                INSERT INTO sales_data_new (id, month, units_sold, source_url, confidence, scraped_at, bike_id)
                  SELECT id, month, units_sold, source_url, confidence, scraped_at, bike_id FROM sales_data;
                DROP TABLE sales_data;
                ALTER TABLE sales_data_new RENAME TO sales_data;
            """)

        # ------------- Add source column to sales_data (idempotent) -------------
        # Lets us tag rows by where they came from (rushlane, autopunditz, ...).
        # Defaults to 'rushlane' so all existing data stays attributed correctly.
        if not _column_exists(conn, "sales_data", "source"):
            conn.execute(
                "ALTER TABLE sales_data ADD COLUMN source TEXT NOT NULL DEFAULT 'rushlane'"
            )
            print("[migrate] added source column to sales_data (default: rushlane)")

        # Backfill any pre-existing NULLs (shouldn't exist with NOT NULL DEFAULT,
        # but safe-guard for any edge case where the column was added without a default).
        backfilled = conn.execute(
            "UPDATE sales_data SET source = 'rushlane' WHERE source IS NULL OR source = ''"
        ).rowcount
        if backfilled:
            print(f"[migrate] backfilled source='rushlane' on {backfilled} sales rows")

        # Unique index: (bike_id, month, source) — same bike-month from two
        # sources is allowed. Drop the older 2-column index if present so the
        # new 3-column one takes over.
        existing_idx = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='sales_data' AND name='idx_sales_bike_month'"
        ).fetchone()
        if existing_idx:
            conn.execute("DROP INDEX idx_sales_bike_month")
            print("[migrate] dropped legacy idx_sales_bike_month (2-column)")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_bike_month_source "
            "ON sales_data(bike_id, month, source)"
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
    """Delete a bike + all its sales/reviews/themes. Returns rows removed."""
    with get_conn() as conn:
        n_sales = conn.execute("DELETE FROM sales_data WHERE bike_id = ?", (bike_id,)).rowcount
        n_reviews = conn.execute("DELETE FROM reviews WHERE bike_id = ?", (bike_id,)).rowcount
        n_themes = conn.execute("DELETE FROM themes_analysis WHERE bike_id = ?", (bike_id,)).rowcount
        conn.execute("DELETE FROM bikes WHERE id = ?", (bike_id,))
    return n_sales + n_reviews + n_themes


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
# Retail brand sales (FADA)
# ---------------------------------------------------------------------------

def upsert_retail_brand_sale(
    brand_id: str,
    month: str,
    units: int,
    source_url: str | None = None,
    source: str = "fada_retail",
):
    """Upsert a brand-level monthly retail row (e.g. from FADA)."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO retail_brand_sales (brand_id, month, units, source, source_url, scraped_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(brand_id, month, source) DO UPDATE SET
                 units=excluded.units,
                 source_url=excluded.source_url,
                 scraped_at=excluded.scraped_at""",
            (brand_id, month, units, source, source_url, now),
        )


def get_retail_brand_sales(brand_id: str | None = None,
                           source: str | None = None) -> list[dict]:
    """Return retail rows. Filter by brand_id and/or source."""
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
                FROM retail_brand_sales {where}
                ORDER BY month ASC""",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_wholesale_brand_totals(brand_id: str) -> list[dict]:
    """Sum model-level wholesale rows up to brand-monthly totals.
    `brand_id` matches the prefix of bike_id (e.g. 'yamaha' -> 'yamaha-*').
    Excludes any retail rows (source != 'fada_retail') so we don't mix sources."""
    prefix = f"{brand_id}-%"
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT month, SUM(units_sold) AS units
               FROM sales_data
               WHERE bike_id LIKE ?
                 AND source != 'fada_retail'
               GROUP BY month
               ORDER BY month ASC""",
            (prefix,),
        ).fetchall()
    return [{"month": r["month"], "units": r["units"]} for r in rows]


# ---------------------------------------------------------------------------
# Themes — bike-scoped
# ---------------------------------------------------------------------------

def save_themes_analysis(bike_id: str, method: str, config: dict, themes: list):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO themes_analysis (bike_id, method, config, themes, run_at)
               VALUES (?, ?, ?, ?, ?)""",
            (bike_id, method, _json.dumps(config), _json.dumps(themes), now),
        )


def get_latest_themes(bike_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT method, config, themes, run_at FROM themes_analysis
               WHERE bike_id = ? ORDER BY id DESC LIMIT 1""",
            (bike_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "method": row["method"],
        "config": _json.loads(row["config"]),
        "themes": _json.loads(row["themes"]),
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
