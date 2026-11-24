import importlib.util
import threading
import unittest
from datetime import datetime, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "probe_sources", Path(__file__).resolve().parents[1] / "scripts" / "probe_sources.py"
)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

NOW = format_datetime(datetime.now(timezone.utc))
RSS = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>a</title><pubDate>{NOW}</pubDate></item>
<item><title>b</title><pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate></item>
</channel></rss>""".encode()
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
<entry><title>a</title><updated>2024-05-01T10:00:00Z</updated></entry></feed>"""
HOME = b'<html><head><link rel="alternate" type="application/atom+xml" href="/atom.xml"></head></html>'
NOFEED = b"<html><head><title>no feed here</title></head></html>"
ROBOTS = b"User-agent: *\nDisallow: /private/\n"

ROUTES = {
    "/rss.xml": (200, RSS), "/atom.xml": (200, ATOM), "/home": (200, HOME),
    "/robots.txt": (200, ROBOTS),
    "/private/feed.xml": (200, RSS), "/broken": (500, b"oops"),
}
# A separate site with no feeds at all, so conventional-path guessing finds nothing.
EMPTY_ROUTES = {"/nofeed": (200, NOFEED)}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, body = self.server.routes.get(self.path, (404, b"not found"))
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class ProbeTests(unittest.TestCase):
    @staticmethod
    def _serve(routes):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.routes = routes
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, f"http://127.0.0.1:{server.server_address[1]}"

    @classmethod
    def setUpClass(cls):
        cls.server, cls.base = cls._serve(ROUTES)
        cls.empty_server, cls.empty_base = cls._serve(EMPTY_ROUTES)

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.server, cls.empty_server):
            srv.shutdown()
            srv.server_close()

    def src(self, **kw):
        return {"id": "t", "name": "T", "kind": "company", **kw}

    def test_parse_rss_and_atom(self):
        r = probe.parse_feed(RSS)
        self.assertEqual((r["format"], r["entries"]), ("rss", 2))
        self.assertIsNotNone(r["newest"])
        a = probe.parse_feed(ATOM)
        self.assertEqual((a["format"], a["entries"]), ("atom", 1))
        self.assertIsNone(probe.parse_feed(b"<html></html>"))
        self.assertIsNone(probe.parse_feed(b"not xml at all"))

    def test_discover_links_resolves_relative_urls(self):
        links = probe.discover_feed_links(HOME.decode(), "http://h.test/home")
        self.assertEqual(links, ["http://h.test/atom.xml"])

    def test_declared_feed_ok(self):
        r = probe.probe_source(self.src(feed_url=self.base + "/rss.xml"), sleep=0)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["entries"], 2)
        self.assertLess(r["age_hours"], 1)

    def test_robots_blocks_feed(self):
        r = probe.probe_source(self.src(feed_url=self.base + "/private/feed.xml"), sleep=0)
        self.assertEqual(r["status"], "blocked_by_robots")
        self.assertIsNone(r["feed_url"])

    def test_discovery_from_homepage(self):
        r = probe.probe_source(self.src(feed_url=None, homepage=self.base + "/home"), sleep=0)
        self.assertEqual(r["status"], "ok_discovered")
        self.assertEqual(r["feed_url"], self.base + "/atom.xml")

    def test_no_feed_found_is_reported_not_invented(self):
        r = probe.probe_source(self.src(feed_url=None, homepage=self.empty_base + "/nofeed"), sleep=0)
        self.assertEqual(r["status"], "no_feed_found")
        self.assertIsNone(r["feed_url"])

    def test_http_error_is_reported(self):
        r = probe.probe_source(self.src(feed_url=self.base + "/broken"), sleep=0)
        self.assertEqual(r["status"], "http_error")

    def test_unreachable_host(self):
        r = probe.probe_source(self.src(feed_url="http://127.0.0.1:9/feed"), sleep=0, timeout=2)
        self.assertEqual(r["status"], "unreachable")


if __name__ == "__main__":
    unittest.main()
