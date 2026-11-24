"""SQLite storage: connection, versioned migrations, source sync."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    # ---- version 1 ----
    """
    CREATE TABLE sources (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        reliability INTEGER NOT NULL DEFAULT 3,
        feed_url TEXT,
        homepage TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        etag TEXT,
        last_modified TEXT,
        last_checked_at TEXT,
        last_ok_at TEXT,
        last_new_item_at TEXT,
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        last_error TEXT
    );

    CREATE TABLE clusters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        headline TEXT,
        lead_article_id INTEGER
    );

    CREATE TABLE articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL REFERENCES sources(id),
        url TEXT NOT NULL,
        url_norm TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        summary TEXT,
        author TEXT,
        published_at TEXT,
        fetched_at TEXT NOT NULL,
        content_hash TEXT,
        cluster_id INTEGER REFERENCES clusters(id),
        score REAL,
        processed_at TEXT,
        used_in_edition TEXT
    );
    CREATE INDEX idx_articles_source ON articles(source_id);
    CREATE INDEX idx_articles_published ON articles(published_at);
    CREATE INDEX idx_articles_unprocessed ON articles(processed_at);

    CREATE TABLE collection_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL REFERENCES sources(id),
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        new_articles INTEGER NOT NULL DEFAULT 0,
        error TEXT
    );

    CREATE TABLE editions (
        edition_date TEXT PRIMARY KEY,
        pdf_path TEXT,
        status TEXT NOT NULL,
        page_count INTEGER,
        built_at TEXT,
        sent_at TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT
    );

    CREATE TABLE delivery_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        edition_date TEXT NOT NULL REFERENCES editions(edition_date),
        attempted_at TEXT NOT NULL,
        ok INTEGER NOT NULL,
        error TEXT
    );
    """,
]

SCHEMA_VERSION = len(MIGRATIONS)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not exists:
        return 0
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version").fetchone()
    return int(row["v"])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply any missing migrations, each in its own transaction. Returns version."""
    version = current_version(conn)
    for target, sql in enumerate(MIGRATIONS, start=1):
        if target <= version:
            continue
        script = (
            "BEGIN;\n"
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER NOT NULL, applied_at TEXT NOT NULL);\n"
            + sql
            + f"\nINSERT INTO schema_version(version, applied_at) "
            f"VALUES ({target}, '{utc_now_iso()}');\nCOMMIT;"
        )
        try:
            conn.executescript(script)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return current_version(conn)


def init_db(path: str | Path) -> sqlite3.Connection:
    conn = connect(path)
    migrate(conn)
    return conn


def sync_sources(conn: sqlite3.Connection, sources: list[dict[str, Any]]) -> int:
    """Insert or update sources from config. Runtime state (failure counters,
    checkpoints) is preserved. Returns the number of sources processed."""
    with conn:
        for src in sources:
            conn.execute(
                """
                INSERT INTO sources (id, name, kind, reliability, feed_url, homepage, enabled)
                VALUES (:id, :name, :kind, :reliability, :feed_url, :homepage, :enabled)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    kind = excluded.kind,
                    reliability = excluded.reliability,
                    feed_url = excluded.feed_url,
                    homepage = excluded.homepage,
                    enabled = excluded.enabled
                """,
                {
                    "id": src["id"],
                    "name": src["name"],
                    "kind": src["kind"],
                    "reliability": src.get("reliability", 3),
                    "feed_url": src.get("feed_url"),
                    "homepage": src.get("homepage"),
                    "enabled": 1 if src.get("enabled", True) else 0,
                },
            )
    return len(sources)
