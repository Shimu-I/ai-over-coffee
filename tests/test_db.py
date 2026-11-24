import sqlite3
import tempfile
import unittest
from pathlib import Path

from aoc import db


class DbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "t.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_creates_schema(self):
        conn = db.init_db(self.path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("sources", "articles", "clusters", "collection_runs",
                  "editions", "delivery_log", "schema_version"):
            self.assertIn(t, tables)
        self.assertEqual(db.current_version(conn), db.SCHEMA_VERSION)
        conn.close()

    def test_migrate_is_idempotent(self):
        conn = db.init_db(self.path)
        db.migrate(conn)
        db.migrate(conn)
        rows = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        self.assertEqual(rows, db.SCHEMA_VERSION)
        conn.close()

    def test_article_url_is_unique_and_fk_enforced(self):
        conn = db.init_db(self.path)
        db.sync_sources(conn, [{"id": "s1", "name": "S1", "kind": "company"}])
        ins = ("INSERT INTO articles(source_id,url,url_norm,title,fetched_at) "
               "VALUES (?,?,?,?,?)")
        conn.execute(ins, ("s1", "https://x.test/a", "x.test/a", "A", db.utc_now_iso()))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(ins, ("s1", "https://x.test/a?utm=1", "x.test/a", "A again", db.utc_now_iso()))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(ins, ("missing", "https://x.test/b", "x.test/b", "B", db.utc_now_iso()))
        conn.close()

    def test_sync_sources_preserves_runtime_state(self):
        conn = db.init_db(self.path)
        src = {"id": "s1", "name": "S1", "kind": "company", "feed_url": None}
        db.sync_sources(conn, [src])
        conn.execute("UPDATE sources SET consecutive_failures=4, last_error='boom', etag='abc' WHERE id='s1'")
        conn.commit()
        db.sync_sources(conn, [{**src, "name": "S1 renamed", "feed_url": "https://x.test/feed"}])
        row = conn.execute("SELECT * FROM sources WHERE id='s1'").fetchone()
        self.assertEqual(row["name"], "S1 renamed")
        self.assertEqual(row["feed_url"], "https://x.test/feed")
        self.assertEqual(row["consecutive_failures"], 4)
        self.assertEqual(row["etag"], "abc")
        conn.close()


if __name__ == "__main__":
    unittest.main()
