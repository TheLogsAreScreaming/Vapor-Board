"""Release comparison for the optional update check (no network)."""
import json
import unittest
from vapor_board import updates


def reply(*tags, **extra):
    return json.dumps([{"tag_name": tag, **extra} for tag in tags]).encode()


class UpdateTests(unittest.TestCase):
    def test_versions_sort_with_final_after_candidates(self):
        order = ["1.0.0rc1", "v1.0.0-rc.2", "v1.0.0-rc.10", "1.0.0", "1.0.1"]
        parsed = [updates.parse_version(v) for v in order]
        self.assertEqual(parsed, sorted(parsed))
        self.assertIsNone(updates.parse_version("banana"))

    def test_reports_only_something_newer(self):
        self.assertEqual(updates.check("1.0.0rc2", lambda: reply("v1.0.0-rc.3", "v1.0.0-rc.2")), "v1.0.0-rc.3")
        self.assertIsNone(updates.check("1.0.0rc2", lambda: reply("v1.0.0-rc.2", "v1.0.0-rc.1")))

    def test_drafts_and_odd_tags_are_ignored(self):
        self.assertIsNone(updates.check("1.0.0", lambda: reply("v9.9.9", draft=True)))
        self.assertIsNone(updates.check("1.0.0", lambda: reply("nightly")))

    def test_bad_replies_raise(self):
        with self.assertRaises(ValueError):
            updates.check("1.0.0", lambda: b"not json")
        with self.assertRaises(ValueError):
            updates.check("1.0.0", lambda: b'{"message": "rate limited"}')


if __name__ == "__main__":
    unittest.main()
