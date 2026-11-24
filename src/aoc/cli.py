"""Command line entry point:  python -m aoc.cli <command>"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import db_path, load_config, load_sources, project_root
from .db import SCHEMA_VERSION, current_version, init_db, sync_sources


def cmd_init_db(_args: argparse.Namespace) -> int:
    cfg = load_config()
    path = db_path(cfg)
    conn = init_db(path)
    n = sync_sources(conn, load_sources())
    print(f"Database ready: {path}")
    print(f"Schema version: {current_version(conn)} (latest {SCHEMA_VERSION})")
    print(f"Sources synced from config: {n}")
    conn.close()
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    cfg = load_config()
    path = db_path(cfg)
    if not path.exists():
        print(f"No database yet at {path}. Run: scripts/aoc init-db")
        return 1
    conn = init_db(path)
    count = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    print(f"{cfg['publication']['name']} v{__version__}   root: {project_root()}")
    print(f"schema version : {current_version(conn)}")
    print(f"sources        : {count('SELECT COUNT(*) FROM sources')} "
          f"({count('SELECT COUNT(*) FROM sources WHERE feed_url IS NULL')} without a feed URL)")
    print(f"articles       : {count('SELECT COUNT(*) FROM articles')}")
    print(f"editions       : {count('SELECT COUNT(*) FROM editions')}")
    conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aoc", description="AI Over Coffee")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create or migrate the database and sync sources").set_defaults(func=cmd_init_db)
    sub.add_parser("status", help="show a short status summary").set_defaults(func=cmd_status)
    sub.add_parser("version", help="print version").set_defaults(
        func=lambda _a: print(__version__) or 0
    )
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
