#!/usr/bin/env python3
"""Small NAS editor API for config.json and fixed Tailscale publication."""

from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import secrets
import tempfile
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    import paramiko
except ImportError:  # pragma: no cover - reported by the health endpoint
    paramiko = None


ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", ROOT / "config.json"))
ICON_DIR = Path(os.environ.get("ICON_DIR", ROOT / "icons"))
REMOTE_HOST = os.environ.get("REMOTE_HOST", "")
REMOTE_PORT = int(os.environ.get("REMOTE_PORT", "22"))
REMOTE_USER = os.environ.get("REMOTE_USER", "")
REMOTE_KEY_PATH = os.environ.get("REMOTE_KEY_PATH", "")
REMOTE_PASSWORD = os.environ.get("REMOTE_PASSWORD", "")
REMOTE_KNOWN_HOSTS = os.environ.get("REMOTE_KNOWN_HOSTS", "/root/.ssh/known_hosts")
REMOTE_CONFIG_PATH = os.environ.get("REMOTE_CONFIG_PATH", "")
MAX_BODY = 2 * 1024 * 1024
# config.json contains navigation data only (no credentials). Keep the file
# writable/readable for the NAS user even though the container runs as root.
CONFIG_FILE_MODE = 0o664
WRITE_LOCK = threading.Lock()


def validate_config(payload: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return ["version must be 1"]
    groups = payload.get("groups")
    services = payload.get("services")
    if not isinstance(groups, list) or not isinstance(services, list):
        return ["groups and services must be arrays"]

    group_ids: set[str] = set()
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("id"), str) or not group["id"].strip():
            errors.append("each group needs a non-empty id")
            continue
        group_id = group["id"]
        if group_id in group_ids:
            errors.append(f"duplicate group id: {group_id}")
        group_ids.add(group_id)
        if not isinstance(group.get("name"), str) or not group["name"].strip():
            errors.append(f"group {group_id} needs a name")
        if not isinstance(group.get("order"), int):
            errors.append(f"group {group_id} order must be an integer")
        columns = group.get("columns")
        if not isinstance(columns, int) or not 1 <= columns <= 12:
            errors.append(f"group {group_id} columns must be 1-12")
        max_items = group.get("max_items")
        if max_items is not None and (not isinstance(max_items, int) or max_items < 1):
            errors.append(f"group {group_id} max_items must be null or >= 1")

    service_ids: set[str] = set()
    for service in services:
        if not isinstance(service, dict):
            errors.append("each service must be an object")
            continue
        service_id = service.get("id")
        if not isinstance(service_id, str) or not service_id.strip():
            errors.append("each service needs a non-empty id")
            continue
        if service_id in service_ids:
            errors.append(f"duplicate service id: {service_id}")
        service_ids.add(service_id)
        if not isinstance(service.get("name"), str) or not service["name"].strip():
            errors.append(f"service {service_id} needs a name")
        if service.get("group_id") not in group_ids:
            errors.append(f"service {service_id} references an unknown group")
        if not isinstance(service.get("order"), int):
            errors.append(f"service {service_id} order must be an integer")
        if not isinstance(service.get("position"), (dict, type(None))):
            errors.append(f"service {service_id} position must be object or null")
    return errors


def atomic_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, CONFIG_FILE_MODE)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def build_connect_kwargs() -> dict[str, object]:
    """Build deterministic Paramiko authentication options from environment."""
    kwargs: dict[str, object] = {
        "port": REMOTE_PORT,
        "username": REMOTE_USER,
        "timeout": 10,
        "look_for_keys": False,
        "allow_agent": False,
    }
    # An empty or missing key is valid in password-only mode. This also makes
    # the default /dev/null compose mount harmless.
    if REMOTE_KEY_PATH:
        key_path = Path(REMOTE_KEY_PATH)
        if key_path.is_file() and key_path.stat().st_size > 0:
            kwargs["key_filename"] = REMOTE_KEY_PATH
    if REMOTE_PASSWORD:
        kwargs["password"] = REMOTE_PASSWORD
    if "key_filename" not in kwargs and "password" not in kwargs:
        raise RuntimeError("remote authentication is not configured")
    return kwargs


def publish(payload: object) -> None:
    if paramiko is None:
        raise RuntimeError("paramiko is not installed")
    if not all((REMOTE_HOST, REMOTE_USER, REMOTE_CONFIG_PATH)):
        raise RuntimeError("remote publish environment is incomplete")
    destination = posixpath.normpath(REMOTE_CONFIG_PATH)
    if destination in {"/", ".", ""} or not destination.endswith(".json"):
        raise RuntimeError("REMOTE_CONFIG_PATH must be a JSON file path")

    client = paramiko.SSHClient()
    if Path(REMOTE_KNOWN_HOSTS).is_file():
        client.load_host_keys(REMOTE_KNOWN_HOSTS)
    else:
        client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    temp_remote = f"{destination}.tmp.{secrets.token_hex(6)}"
    try:
        client.connect(REMOTE_HOST, **build_connect_kwargs())
        sftp = client.open_sftp()
        try:
            with sftp.file(temp_remote, "w") as remote_file:
                remote_file.write((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
                remote_file.flush()
            command = f"mv -- {json.dumps(temp_remote)} {json.dumps(destination)}"
            _, stdout, stderr = client.exec_command(command, timeout=10)
            if stdout.channel.recv_exit_status() != 0:
                raise RuntimeError(stderr.read().decode("utf-8", errors="replace") or "remote rename failed")
        finally:
            try:
                sftp.remove(temp_remote)
            except Exception:
                pass
            sftp.close()
    finally:
        client.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "OmniNavEditor/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(fmt % args)

    def send_json(self, status: int, body: object) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> object:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY:
            raise ValueError("request body is missing or too large")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json(HTTPStatus.OK, {"ok": True, "paramiko": paramiko is not None, "config": str(CONFIG_PATH)})
            return
        if path == "/api/config":
            try:
                self.send_json(HTTPStatus.OK, json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
            except Exception as exc:
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return
        if path == "/api/icons":
            icons = sorted(p.relative_to(ROOT).as_posix() for p in ICON_DIR.iterdir() if p.is_file()) if ICON_DIR.exists() else []
            self.send_json(HTTPStatus.OK, {"icons": icons})
            return
        self.serve_static(path)

    def serve_static(self, path: str) -> None:
        if path.startswith("/icons/"):
            target = (ROOT / path.removeprefix("/").lstrip("/")).resolve()
            static_root = ICON_DIR.resolve()
        else:
            relative = "index.html" if path in {"", "/"} else path.lstrip("/")
            target = (EDITOR_ROOT / "static" / relative).resolve()
            static_root = (EDITOR_ROOT / "static").resolve()
        if static_root not in target.parents and target != static_root or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_PUT(self) -> None:
        if urlparse(self.path).path != "/api/config":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self.read_json()
            errors = validate_config(payload)
            if errors:
                self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"ok": False, "errors": errors})
                return
            with WRITE_LOCK:
                atomic_write(CONFIG_PATH, payload)
            self.send_json(HTTPStatus.OK, {"ok": True, "services": len(payload["services"])})
        except Exception as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/validate", "/api/publish"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self.read_json()
            errors = validate_config(payload)
            if errors:
                self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"ok": False, "errors": errors})
                return
            if path == "/api/publish":
                publish(payload)
            self.send_json(HTTPStatus.OK, {"ok": True, "published": path == "/api/publish"})
        except Exception as exc:
            self.send_json(HTTPStatus.BAD_GATEWAY if path == "/api/publish" else HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})


if __name__ == "__main__":
    host = os.environ.get("EDITOR_BIND", "0.0.0.0")
    port = int(os.environ.get("EDITOR_PORT", "8080"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()
