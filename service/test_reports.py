"""Run: python3 -m unittest discover -s service -p 'test_*.py'"""
import json
import os
import tempfile
import unittest

import reports


def body(**over):
    d = {"agent": "claude_code", "state": "working", "task": "Stage 7"}
    d.update(over)
    return json.dumps(d).encode()


class Validate(unittest.TestCase):
    def test_good(self):
        r = reports.validate(body(needs_seabass="sign in"))
        self.assertEqual(r["agent"], "claude_code")
        self.assertEqual(r["needs_seabass"], "sign in")

    def test_refused(self):
        for raw in (
            b"not json",
            b"[]",
            body(agent="stranger"),
            body(state="ready"),
            body(task=""),
            body(task="x" * 201),
            body(task=5),
            body(needs_seabass="x" * 201),
            body(needs_seabass=5),
        ):
            with self.assertRaises(reports.Refused, msg=raw):
                reports.validate(raw)

    def test_extra_fields_are_dropped(self):
        self.assertNotIn("at", reports.validate(body(at="2099", extra=1)))


class Gate(unittest.TestCase):
    good = dict(client="127.0.0.1", host="127.0.0.1:8787",
                ctype="application/json", origin=None, length="50")

    def check(self, **over):
        reports.gate(**{**self.good, **over})

    def test_good(self):
        self.check()
        self.check(host="localhost:8787", ctype="application/json; charset=utf-8")

    def test_refused(self):
        for over, code in (
            ({"client": "100.1.2.3"}, 403),
            ({"host": "evil.example"}, 403),
            ({"origin": "https://evil.example"}, 403),
            ({"origin": "null"}, 403),
            ({"ctype": "text/plain"}, 415),
            ({"ctype": None}, 415),
            ({"length": None}, 411),
            ({"length": "abc"}, 411),
            ({"length": "-1"}, 411),
            ({"length": str(reports.MAX_BODY + 1)}, 413),
        ):
            with self.assertRaises(reports.Refused, msg=over) as c:
                self.check(**over)
            self.assertEqual(c.exception.code, code)


class HostAllowed(unittest.TestCase):
    extra = ("100.1.2.3", "seabass")

    def test_ours(self):
        for host in ("127.0.0.1:8787", "localhost", "LOCALHOST:8787", "100.1.2.3:8787",
                     "seabass:8787", "seabass.tail123.ts.net:8787"):
            self.assertTrue(reports.host_allowed(host, self.extra), host)

    def test_foreign(self):
        for host in (None, "", "evil.example", "evil.example:8787", "ts.net.evil.example",
                     "127.0.0.1.evil.example:8787"):
            self.assertFalse(reports.host_allowed(host, self.extra), host)


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "sub", "reports.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_file_is_empty(self):
        self.assertEqual(reports.load(self.path), {})

    def test_corrupt_file_is_empty(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write("{oops")
        self.assertEqual(reports.load(self.path), {})

    def test_latest_wins_and_each_agent_kept(self):
        reports.store(self.path, reports.validate(body(task="one")), now=100)
        reports.store(self.path, reports.validate(body(task="two")), now=200)
        reports.store(self.path, reports.validate(body(agent="merlin")), now=300)
        got = reports.load(self.path)
        self.assertEqual(got["claude_code"]["task"], "two")
        self.assertEqual(got["claude_code"]["at"], 200)
        self.assertIn("merlin", got)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["reports.json"])


class Views(unittest.TestCase):
    def test_agents(self):
        rs = {
            "claude_code": {"state": "working", "task": "t", "at": 1000},
            "merlin": {"state": "idle", "task": "t", "at": 0},
        }
        now = reports.SILENT_AFTER_S + 100
        v = reports.agent_view({**rs, "claude_code": {**rs["claude_code"], "at": now - 180}}, now)
        self.assertEqual(v["claude_code"], "working · 3m ago")
        self.assertEqual(v["merlin"], "silent")
        self.assertEqual(v["gemini_spark"], "silent")
        self.assertEqual(set(v), set(reports.AGENTS))

    def test_relay_counts_paperclip_and_reports(self):
        rs = {"merlin": {"state": "blocked", "task": "t", "at": 90, "needs_seabass": "sign in"}}
        r = reports.relay_view(rs, {"in_review": 8, "blocked": 2, "done": 15, "todo": 1}, now=100)
        self.assertEqual(r["needs_seabass"], 11)
        self.assertEqual(r["open_tasks"], 11)
        self.assertIn("merlin: t", r["last_entry"])
        self.assertEqual(r["needs_seabass_items"], ["merlin: sign in"])

    def test_paperclip_down_is_unknown_never_zero(self):
        r = reports.relay_view({}, None, now=100)
        self.assertEqual(r["needs_seabass"], "unknown")
        self.assertEqual(r["open_tasks"], "unknown")
        self.assertEqual(r["last_entry"], "No agent has reported yet")

    def test_stale_ask_still_counts(self):
        rs = {"merlin": {"state": "blocked", "task": "t", "at": 0, "needs_seabass": "x"}}
        self.assertEqual(reports.relay_view(rs, {}, now=10**9)["needs_seabass"], 1)


if __name__ == "__main__":
    unittest.main()
