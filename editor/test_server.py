import json
import tempfile
import unittest
from pathlib import Path

try:
    from .server import atomic_write, validate_config
except ImportError:
    from server import atomic_write, validate_config


def sample():
    return {
        "version": 1,
        "groups": [{"id": "g", "name": "组", "order": 10, "columns": 5, "max_items": None}],
        "services": [{"id": "s", "name": "服务", "group_id": "g", "local_ip": "127.0.0.1", "tailscale_ip": "", "port": "80", "pinned": False, "tag": "", "icon_path": "", "order": 10, "position": None}],
    }


class ConfigTests(unittest.TestCase):
    def test_valid_config(self):
        self.assertEqual(validate_config(sample()), [])

    def test_duplicate_and_invalid_references(self):
        payload = sample()
        payload["groups"].append(dict(payload["groups"][0]))
        payload["services"][0]["group_id"] = "missing"
        self.assertTrue(validate_config(payload))

    def test_invalid_group_limits(self):
        payload = sample()
        payload["groups"][0]["columns"] = 13
        payload["groups"][0]["max_items"] = 0
        self.assertGreaterEqual(len(validate_config(payload)), 2)

    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            atomic_write(path, sample())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], 1)


if __name__ == "__main__":
    unittest.main()
