#!/usr/bin/env python3
"""Probe every source in config/sources.yaml from THIS machine.

For each source it checks, politely and read-only:
  * robots.txt (is our fetch allowed?)
  * the declared feed URL (reachable? valid RSS/Atom? how fresh?)
  * if there is no working feed: feed auto-discovery on the homepage
    (<link rel="alternate"> tags and a few conventional paths)

It never scrapes article pages. It reads robots.txt only; it cannot read a
site's terms of service, so review those yourself before relying on any
source that is not an official feed.

Standard library + PyYAML only. Writes data/probe_report.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aoc.config import load_sources  # noqa: E402

COMMON_PATHS = ["/feed", "/feed/", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml"]
STALE_AFTER_DAYS = 30
MAX_CANDIDATES = 8


def user_agent() -> str:
    contact = os.environ.get("AOC_CONTACT", "").strip()
    suffix = f"; {contact}" if contact else ""
    return f"AIOverCoffee/0.1 (personal newsletter reader{suffix})"


def fetch(url: str, timeout: float = 15, max_bytes: int = 2_000_000) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent(),
            "Accept": "application/rss+xml, application/atom+xml, application/xml, "
            "text/xml, text/html;q=0.8, */*;q=0.5",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {
                "status": resp.status,
                "body": resp.read(max_bytes),
                "final_url": resp.geturl(),
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "body": b"", "final_url": url, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001 - report any network failure as data
        return {"status": None, "body": b"", "final_url": url, "error": f"{type(exc).__name__}: {exc}"}


def robots_allows(url: str, timeout: float = 10) -> bool | None:
    """True = allowed, False = disallowed, None = could not be determined."""
    p = urlparse(url)
    r = fetch(f"{p.scheme}://{p.netloc}/robots.txt", timeout=timeout)
    if r["status"] is None:
        return None
    if r["status"] in (404, 410):
        return True
    if r["status"] != 200:
        return None
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(r["body"].decode("utf-8", "replace").splitlines())
    return rp.can_fetch(user_agent(), url)


def parse_date(text: str | None) -> datetime | None:
    text = (text or "").strip()
    if not text:
        return None
    dt = None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        pass
    if dt is None:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(body: bytes) -> dict | None:
    """Return {'format', 'entries', 'newest'} for RSS/RDF/Atom, else None."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    fmt = _local(root.tag)
    if fmt not in ("rss", "rdf", "feed"):
        return None
    entries = 0
    newest: datetime | None = None
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        entries += 1
        for child in el:
            if _local(child.tag) in ("pubdate", "date", "published", "updated"):
                dt = parse_date(child.text)
                if dt and (newest is None or dt > newest):
                    newest = dt
    return {
        "format": {"rdf": "rss1", "feed": "atom"}.get(fmt, fmt),
        "entries": entries,
        "newest": newest.isoformat() if newest else None,
    }


_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)


def discover_feed_links(html: str, base_url: str) -> list[str]:
    found: list[str] = []
    for tag in _LINK_RE.findall(html):
        if not re.search(r"rel\s*=\s*[\"']?alternate", tag, re.I):
            continue
        if not re.search(r"type\s*=\s*[\"']?application/(rss|atom)\+xml", tag, re.I):
            continue
        m = re.search(r"href\s*=\s*[\"']([^\"']+)[\"']", tag, re.I)
        if m:
            url = urljoin(base_url, m.group(1).replace("&amp;", "&"))
            if url not in found:
                found.append(url)
    return found


def _try_feed(url: str, result: dict, timeout: float) -> str:
    allowed = robots_allows(url, timeout=timeout)
    if allowed is False:
        result["notes"].append(f"robots.txt disallows fetching {url}")
        return "blocked_by_robots"
    if allowed is None:
        note = "robots.txt could not be read; treated as unknown"
        if note not in result["notes"]:
            result["notes"].append(note)
    r = fetch(url, timeout=timeout)
    if r["error"]:
        result["notes"].append(f"{url}: {r['error']}")
        return "unreachable" if r["status"] is None else "http_error"
    info = parse_feed(r["body"])
    if not info:
        result["notes"].append(f"{url}: reachable but not a valid RSS/Atom feed")
        return "not_a_feed"
    result.update(feed_url=url, robots=allowed, **info)
    if info["newest"]:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(info["newest"])
        result["age_hours"] = round(age.total_seconds() / 3600, 1)
        if age.days > STALE_AFTER_DAYS:
            result["notes"].append(f"newest entry is {age.days} days old (stale)")
    return "ok"


def probe_source(src: dict, sleep: float = 0.5, timeout: float = 15) -> dict:
    result = {
        "id": src["id"],
        "name": src["name"],
        "kind": src["kind"],
        "declared_feed": src.get("feed_url"),
        "homepage": src.get("homepage"),
        "status": "no_feed_found",
        "feed_url": None,
        "format": None,
        "entries": None,
        "newest": None,
        "age_hours": None,
        "robots": None,
        "notes": [],
    }
    declared = src.get("feed_url")
    if declared:
        outcome = _try_feed(declared, result, timeout)
        if outcome == "ok":
            result["status"] = "ok"
            return result
        result["status"] = outcome
        time.sleep(sleep)

    homepage = src.get("homepage")
    if not homepage:
        if not declared:
            result["notes"].append("no feed_url and no homepage configured")
        return result

    home_allowed = robots_allows(homepage, timeout=timeout)
    if home_allowed is False:
        result["notes"].append("robots.txt disallows the homepage; not discovering feeds there")
        result["status"] = "blocked_by_robots"
        return result

    candidates: list[str] = []
    page = fetch(homepage, timeout=timeout)
    if page["error"]:
        result["notes"].append(f"homepage {homepage}: {page['error']}")
        if result["status"] == "no_feed_found":
            result["status"] = "unreachable" if page["status"] is None else "http_error"
        if page["status"] is None:
            # The host does not answer at all; guessing more paths would be noise.
            return result
    else:
        candidates += discover_feed_links(page["body"].decode("utf-8", "replace"), page["final_url"])
    p = urlparse(homepage)
    origin = f"{p.scheme}://{p.netloc}"
    candidates += [origin + path for path in COMMON_PATHS]
    seen = {declared}
    for url in candidates[:MAX_CANDIDATES]:
        if url in seen:
            continue
        seen.add(url)
        time.sleep(sleep)
        if _try_feed(url, result, timeout) == "ok":
            result["status"] = "ok_discovered"
            result["notes"].append("feed found by auto-discovery; confirm it is the right feed")
            return result
    if result["status"] in ("ok", "ok_discovered"):
        return result
    if result["status"] == "no_feed_found":
        result["notes"].append(
            "no RSS/Atom feed found; consider a sitemap or skipping this source "
            "(check the site's terms before any scraping)"
        )
    return result


def print_table(results: list[dict]) -> None:
    print(f"\n{'id':<15} {'status':<17} {'entries':>7} {'newest (h ago)':>15}  feed")
    print("-" * 100)
    for r in results:
        age = "-" if r["age_hours"] is None else f"{r['age_hours']:.0f}"
        entries = "-" if r["entries"] is None else str(r["entries"])
        print(f"{r['id']:<15} {r['status']:<17} {entries:>7} {age:>15}  {r['feed_url'] or '-'}")
    print()
    for r in results:
        for note in r["notes"]:
            print(f"  [{r['id']}] {note}")
    ok = sum(r["status"] in ("ok", "ok_discovered") for r in results)
    print(f"\n{ok} of {len(results)} sources have a working feed right now.")
    print("This is a snapshot from this machine at this moment. It reads robots.txt only;")
    print("it cannot check terms of service, so review those before relying on a source.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", help="comma-separated source ids to probe")
    ap.add_argument("--timeout", type=float, default=15)
    ap.add_argument("--sleep", type=float, default=0.5, help="pause between requests (seconds)")
    ap.add_argument("--report", default=str(ROOT / "data" / "probe_report.json"))
    args = ap.parse_args(argv)

    sources = load_sources(ROOT)
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        sources = [s for s in sources if s["id"] in wanted]
        if not sources:
            print("No matching source ids.", file=sys.stderr)
            return 2

    results = []
    for i, src in enumerate(sources, 1):
        print(f"[{i}/{len(sources)}] probing {src['id']} ...", flush=True)
        results.append(probe_source(src, sleep=args.sleep, timeout=args.timeout))

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(), "results": results},
            indent=2,
        ),
        encoding="utf-8",
    )
    print_table(results)
    print(f"Report written to {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
