import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from . import server
except ImportError:
    import server

atomic_write = server.atomic_write
build_connect_kwargs = server.build_connect_kwargs
validate_config = server.validate_config


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

    def test_password_authentication(self):
        with patch.object(server, "REMOTE_KEY_PATH", ""), patch.object(server, "REMOTE_PASSWORD", "secret"):
            kwargs = build_connect_kwargs()
        self.assertEqual(kwargs["password"], "secret")
        self.assertNotIn("key_filename", kwargs)

    def test_key_authentication(self):
        with tempfile.NamedTemporaryFile() as key:
            key.write(b"test-private-key")
            key.flush()
            with patch.object(server, "REMOTE_KEY_PATH", key.name), patch.object(server, "REMOTE_PASSWORD", ""):
                kwargs = build_connect_kwargs()
        self.assertEqual(kwargs["key_filename"], key.name)
        self.assertNotIn("password", kwargs)

    def test_authentication_required(self):
        with patch.object(server, "REMOTE_KEY_PATH", ""), patch.object(server, "REMOTE_PASSWORD", ""):
            with self.assertRaisesRegex(RuntimeError, "authentication is not configured"):
                build_connect_kwargs()


if __name__ == "__main__":
    unittest.main()
