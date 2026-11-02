"""Run: python3 -m unittest discover -s service -p 'test_*.py'"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock


class Stop(Exception):
    """Ends snapshot_loop after one pass; it otherwise runs forever."""


class SnapshotLoop(unittest.TestCase):
    def test_changed_source_does_not_replace_the_process(self):
        source = os.path.join(os.path.dirname(__file__), "status_endpoint.py")
        with tempfile.TemporaryDirectory() as d:
            copy = shutil.copy(source, d)
            spec = importlib.util.spec_from_file_location("status_copy", copy)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.SNAPSHOT = os.path.join(d, "snapshot.json")
            module.build = lambda: {"ok": True}

            os.utime(copy, (1, 1))  # as a save or a checkout would
            with mock.patch("os.execv") as execv, mock.patch(
                "time.sleep", side_effect=Stop
            ):
                with self.assertRaises(Stop):
                    module.snapshot_loop()

            execv.assert_not_called()
            with open(module.SNAPSHOT) as f:
                self.assertEqual(json.load(f), {"ok": True})


if __name__ == "__main__":
    unittest.main()
