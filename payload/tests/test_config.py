import unittest

from aoc import config


class ConfigTests(unittest.TestCase):
    def test_deep_merge_overrides_nested_values_only(self):
        base = {"a": {"x": 1, "y": 2}, "b": 1}
        merged = config.deep_merge(base, {"a": {"y": 9}, "c": 3})
        self.assertEqual(merged, {"a": {"x": 1, "y": 9}, "b": 1, "c": 3})
        self.assertEqual(base, {"a": {"x": 1, "y": 2}, "b": 1})  # input untouched

    def test_shipped_config_loads(self):
        cfg = config.load_config()
        self.assertEqual(cfg["publication"]["name"], "AI Over Coffee")
        self.assertRegex(cfg["schedule"]["edition_time"], r"^\d{2}:\d{2}$")

    def test_shipped_sources_are_valid(self):
        sources = config.load_sources()
        self.assertGreaterEqual(len(sources), 10)
        ids = [s["id"] for s in sources]
        self.assertEqual(len(ids), len(set(ids)))

    def test_validation_rejects_bad_sources(self):
        good = {"id": "a", "name": "A", "kind": "company"}
        config.validate_sources([good])
        for bad in (
            [good, dict(good)],                          # duplicate id
            [{**good, "kind": "blog"}],                  # unknown kind
            [{**good, "reliability": 9}],                # out of range
            [{**good, "feed_url": "ftp://x.test/feed"}], # not http(s)
            [{"id": "", "name": "A", "kind": "company"}],
        ):
            with self.assertRaises(ValueError):
                config.validate_sources(bad)


if __name__ == "__main__":
    unittest.main()
