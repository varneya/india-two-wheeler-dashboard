"""Migration integration tests; every connection targets a temporary database.

Run from the repository root:
    backend/venv/bin/python -m unittest discover -s backend/tests -p test_migrations.py -v
"""

from contextlib import closing, contextmanager, redirect_stdout
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend import database


class MigrationTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name) / "scratch.db"
        self.addCleanup(patch.stopall)
        patch.object(database, "DB_PATH", self.path).start()
        self.connections = []
        self.statements = []
        original_get_conn = database.get_conn

        def tracked_get_conn():
            conn = original_get_conn()
            self.connections.append(conn)
            conn.set_trace_callback(self.statements.append)
            return conn

        patch.object(database, "get_conn", side_effect=tracked_get_conn).start()
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def tearDown(self):
        # Retain references so garbage collection cannot hide a leaked handle.
        for conn in self.connections:
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
                conn.execute("SELECT 1")

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            yield conn

    def dump(self):
        with self.db() as conn:
            return list(conn.iterdump())

    def assert_version(self, expected):
        with self.db() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], expected)

    def legacy(self, month="TEXT UNIQUE NOT NULL", extra="", constraint="",
               video_status=False, transcript_required=True, version=0):
        """Independent fixtures for schemas predating numbered migrations."""
        with self.db() as conn:
            conn.executescript(f"""
                CREATE TABLE sales_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    month {month}, units_sold INTEGER NOT NULL,
                    source_url TEXT, confidence TEXT DEFAULT 'high',
                    scraped_at TEXT NOT NULL {extra} {constraint}
                );
                INSERT INTO sales_data
                    (id, month, units_sold, source_url, confidence, scraped_at)
                    VALUES (41, '2025-11', 123, 'https://example.test/sales', 'low', 'then');
                CREATE TABLE reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
                    post_id TEXT UNIQUE NOT NULL, username TEXT, review_text TEXT,
                    overall_rating REAL, thread_url TEXT, scraped_at TEXT NOT NULL
                );
                INSERT INTO reviews (source, post_id, review_text, scraped_at)
                    VALUES ('bikewale', 'owner', 'Good bike', 'then'),
                           ('youtube', 'shadow', 'Transcript', 'then');
                CREATE TABLE themes_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, method TEXT NOT NULL,
                    config TEXT NOT NULL, themes TEXT NOT NULL, run_at TEXT NOT NULL
                );
                INSERT INTO themes_analysis (method, config, themes, run_at)
                    VALUES ('tfidf', '{{}}', '[]', 'then');
                CREATE TABLE retail_brand_sales (brand TEXT, units INTEGER);
                INSERT INTO retail_brand_sales VALUES ('legacy', 12);
                CREATE TABLE video_transcripts (
                    video_id TEXT PRIMARY KEY, channel_handle TEXT NOT NULL,
                    channel_name TEXT NOT NULL, video_url TEXT NOT NULL,
                    title TEXT NOT NULL, description TEXT, duration_s INTEGER,
                    published_at TEXT, transcript TEXT {'NOT NULL' if transcript_required else ''},
                    language TEXT, fetched_at TEXT NOT NULL
                    {", transcript_status TEXT NOT NULL DEFAULT 'ok'" if video_status else ''}
                );
                INSERT INTO video_transcripts
                    (video_id, channel_handle, channel_name, video_url, title,
                     transcript, language, fetched_at)
                    VALUES ('v1', '@channel', 'Channel', 'https://example.test/v1',
                            'Review', 'Original transcript', 'en', 'then');
                PRAGMA user_version = {version};
            """)

    def assert_sales_constraints(self):
        with self.db() as conn:
            # Same month is valid for another bike or another source.
            conn.execute("""INSERT INTO sales_data
                (bike_id, month, source, units_sold, scraped_at)
                VALUES (?, '2025-11', 'autopunditz', 124, 'now'),
                       ('other-bike', '2025-11', 'rushlane', 12, 'now')
                """, (database.LEGACY_BIKE_ID,))
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("""INSERT INTO sales_data
                    (bike_id, month, source, units_sold, scraped_at)
                    VALUES ('other-bike', '2025-11', 'rushlane', 13, 'now')""")

    def test_fresh_init_and_idempotence(self):
        database.init_db()
        self.assert_version(2)
        with self.db() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({
                'bikes', 'sales_data', 'scrape_log', 'reviews', 'reviews_log',
                'themes_analysis', 'wholesale_brand_sales', 'review_embeddings',
                'url_cache', 'review_cursor', 'video_transcripts', 'video_bike_match',
                'youtube_channel_cursor', 'bike_segments', 'bike_variants',
                'bike_specs', 'bike_brochures',
            }.issubset(tables))
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], 'wal')
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM bike_segments").fetchone()[0],
                             len(database._SEGMENT_SEED))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM bikes").fetchone()[0], 1)
            self.assertTrue(database._column_exists(conn, 'themes_analysis', 'metrics'))
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        before = self.dump()
        self.statements.clear()
        database.init_db()
        self.assertEqual(before, self.dump())
        writes = [sql.strip().upper() for sql in self.statements]
        self.assertFalse(any(sql.startswith(('DELETE ', 'DROP ', 'ALTER ', 'UPDATE ')) for sql in writes))
        self.assertFalse(any(sql.startswith('PRAGMA USER_VERSION =') for sql in writes))
        self.assert_sales_constraints()

    def test_original_single_bike_upgrade_preserves_data(self):
        self.legacy()
        database.init_db()
        self.assert_version(2)
        with self.db() as conn:
            sale = dict(conn.execute("SELECT * FROM sales_data").fetchone())
            self.assertEqual(sale, dict(id=41, month='2025-11', units_sold=123,
                source_url='https://example.test/sales', confidence='low', scraped_at='then',
                bike_id=database.LEGACY_BIKE_ID, source='rushlane'))
            reviews = [tuple(r) for r in conn.execute("SELECT post_id, review_text, bike_id FROM reviews")]
            self.assertEqual(reviews, [('owner', 'Good bike', database.LEGACY_BIKE_ID)])
            theme = conn.execute("SELECT bike_id, themes, metrics FROM themes_analysis").fetchone()
            self.assertEqual(tuple(theme), (database.LEGACY_BIKE_ID, '[]', None))
            self.assertFalse(database._table_exists(conn, 'retail_brand_sales'))
            video = conn.execute("SELECT transcript, transcript_status, language FROM video_transcripts").fetchone()
            self.assertEqual(tuple(video), ('Original transcript', 'ok', 'en'))
            conn.execute("UPDATE video_transcripts SET transcript = NULL")
        self.assert_sales_constraints()
        before = self.dump()
        database.init_db()
        self.assertEqual(before, self.dump())

    def test_not_null_before_unique_month_upgrade(self):
        self.legacy(month='TEXT NOT NULL UNIQUE')
        database.init_db()
        self.assert_sales_constraints()

    def test_table_level_unique_month_preserves_existing_source(self):
        self.legacy(month='TEXT NOT NULL', extra=', source TEXT', constraint=', UNIQUE("month")')
        with self.db() as conn:
            conn.execute("UPDATE sales_data SET source = 'custom-source'")
        database.init_db()
        with self.db() as conn:
            self.assertEqual(conn.execute("SELECT source FROM sales_data WHERE id=41").fetchone()[0],
                             'custom-source')
        self.assert_sales_constraints()

    def test_table_level_bike_month_constraint_upgrade(self):
        self.legacy(month='TEXT NOT NULL', extra=', bike_id TEXT, source TEXT',
                    constraint=', UNIQUE(bike_id, month)')
        with self.db() as conn:
            conn.execute("UPDATE sales_data SET bike_id = '', source = ''")
        database.init_db()
        with self.db() as conn:
            self.assertEqual(tuple(conn.execute("SELECT bike_id, source FROM sales_data").fetchone()),
                             (database.LEGACY_BIKE_ID, 'rushlane'))
        self.assert_sales_constraints()

    def test_existing_version_one_upgrades_without_repeating_cleanup(self):
        self.legacy(month='TEXT NOT NULL', extra=', bike_id TEXT, source TEXT',
                    video_status=True, version=1)
        with self.db() as conn:
            conn.execute("CREATE UNIQUE INDEX idx_sales_bike_month ON sales_data(bike_id, month)")
            conn.execute("UPDATE sales_data SET bike_id = 'existing-bike', source = 'autopunditz'")
            conn.execute("UPDATE video_transcripts SET transcript_status = 'pending'")
        database.init_db()
        self.assert_version(2)
        with self.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM reviews WHERE source='youtube'").fetchone()[0], 1)
            self.assertEqual(tuple(conn.execute("SELECT bike_id, source FROM sales_data").fetchone()),
                             ('existing-bike', 'autopunditz'))
            self.assertEqual(conn.execute("SELECT transcript_status FROM video_transcripts").fetchone()[0], 'pending')
            conn.execute("UPDATE video_transcripts SET transcript=NULL")
            conn.execute("""INSERT INTO sales_data (bike_id, month, source, units_sold, scraped_at)
                VALUES ('existing-bike', '2025-11', 'rushlane', 123, 'now')""")
        before = self.dump()
        database.init_db()
        self.assertEqual(before, self.dump())

    def test_nullable_video_without_status_upgrades(self):
        self.legacy(transcript_required=False)
        with self.db() as conn:
            conn.execute("UPDATE video_transcripts SET transcript=NULL")
        database.init_db()
        with self.db() as conn:
            self.assertEqual(tuple(conn.execute("SELECT transcript, transcript_status FROM video_transcripts").fetchone()),
                             (None, 'ok'))

    def test_cleanup_and_backfills_do_not_repeat(self):
        self.legacy()
        database.init_db()
        with self.db() as conn:
            conn.execute("""INSERT INTO reviews (source, post_id, scraped_at, bike_id)
                VALUES ('youtube', 'new-youtube', 'now', '')""")
            conn.execute("CREATE TABLE retail_brand_sales (note TEXT)")
            conn.execute("INSERT INTO retail_brand_sales VALUES ('new data')")
            conn.execute("UPDATE sales_data SET bike_id='', source=''")
        before = self.dump()
        database.init_db()
        self.assertEqual(before, self.dump())

    def test_current_version_still_ensures_missing_schema_and_seeds(self):
        database.init_db()
        with self.db() as conn:
            conn.execute("DROP TABLE url_cache")
            conn.execute("DROP INDEX idx_sales_bike_month_source")
            conn.execute("DELETE FROM bike_segments WHERE segment_id='e-bike'")
            conn.execute("UPDATE bike_segments SET display_name='Custom label' WHERE segment_id='e-scooter'")
            conn.execute("UPDATE bikes SET display_name='Custom bike'")
        database.init_db()
        with self.db() as conn:
            self.assertTrue(database._table_exists(conn, 'url_cache'))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM bike_segments").fetchone()[0], len(database._SEGMENT_SEED))
            self.assertEqual(conn.execute("SELECT display_name FROM bike_segments WHERE segment_id='e-scooter'").fetchone()[0], 'Custom label')
            self.assertEqual(conn.execute("SELECT display_name FROM bikes").fetchone()[0], 'Custom bike')
        self.assert_sales_constraints()

    def test_failure_after_migrations_rolls_back_schema_data_and_version(self):
        self.legacy()
        before = self.dump()

        def fail(conn):
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
            conn.execute("CREATE TABLE failed_migration (value TEXT)")
            raise RuntimeError('injected failure')

        with patch.object(database, '_MIGRATIONS', (*database._MIGRATIONS, (3, fail))):
            with self.assertRaisesRegex(RuntimeError, 'injected failure'):
                database.init_db()
        self.assert_version(0)
        self.assertEqual(before, self.dump())
        database.init_db()
        self.assert_version(2)
        self.assert_sales_constraints()

    def test_index_failure_rolls_back_version_one_upgrade(self):
        self.legacy(month='TEXT NOT NULL', extra=', bike_id TEXT, source TEXT', version=1)
        with self.db() as conn:
            conn.execute("""INSERT INTO sales_data (month, units_sold, scraped_at)
                VALUES ('2025-11', 999, 'duplicate')""")
        before = self.dump()
        with self.assertRaises(sqlite3.IntegrityError):
            database.init_db()
        self.assert_version(1)
        self.assertEqual(before, self.dump())
        with self.db() as conn:
            conn.execute("DELETE FROM sales_data WHERE scraped_at='duplicate'")
        database.init_db()
        self.assert_version(2)
        with self.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM reviews WHERE source='youtube'").fetchone()[0], 1)

    def test_fresh_failure_leaves_no_partial_schema(self):
        with patch.object(database, '_ensure_indexes_and_seeds', side_effect=RuntimeError('seed failed')):
            with self.assertRaisesRegex(RuntimeError, 'seed failed'):
                database.init_db()
        self.assert_version(0)
        with self.db() as conn:
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master").fetchall(), [])
        database.init_db()
        self.assert_version(2)

    def test_future_version_is_rejected_without_schema_changes(self):
        with self.db() as conn:
            conn.execute("PRAGMA user_version=99")
            conn.execute("CREATE TABLE future_data (value TEXT)")
            conn.execute("INSERT INTO future_data VALUES ('preserved')")
        before = self.dump()
        with self.assertRaisesRegex(RuntimeError, 'newer than supported'):
            database.init_db()
        self.assert_version(99)
        self.assertEqual(before, self.dump())

    def test_connection_setup_failure_closes_connection(self):
        class FailingConnection(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql == 'PRAGMA foreign_keys=ON':
                    raise sqlite3.OperationalError('setup failed')
                return super().execute(sql, *args)

        conn = sqlite3.connect(self.path, factory=FailingConnection)
        self.connections.append(conn)
        with patch.object(database.sqlite3, 'connect', return_value=conn):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'setup failed'):
                database.init_db()


if __name__ == '__main__':
    unittest.main()
