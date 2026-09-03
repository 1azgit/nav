#!/usr/bin/env python3
"""Fetch service icons from config.json and update icon_path fields.

Icons are saved as icons/<first-page-title-word>.<ext>. Services whose page
title starts with the same English word reuse the same icon.

Run manually after editing config.json:
  python fetch_icons.py
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
ICON_DIR = ROOT / "icons"
TIMEOUT = 6


@dataclass
class Service:
    values: dict[str, Any] = field(default_factory=dict)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.icons: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
            return
        if tag != "link":
            return
        data = {k.lower(): (v or "") for k, v in attrs}
        rel = data.get("rel", "").lower()
        href = data.get("href", "")
        if href and ("icon" in rel or rel == "shortcut icon" or rel == "apple-touch-icon"):
            self.icons.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join(part.strip() for part in self.title_parts if part.strip())


def parse_config(path: Path) -> tuple[dict[str, Any], list[Service]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("services"), list):
        raise ValueError("config.json must contain a services array")
    services = [Service(values) for values in payload["services"] if isinstance(values, dict)]
    if len(services) != len(payload["services"]):
        raise ValueError("each service in config.json must be an object")
    return payload, services


def write_config(path: Path, payload: dict[str, Any], services: list[Service]) -> None:
    payload["services"] = [service.values for service in services]
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def service_url(service: Service) -> str | None:
    host = str(service.values.get("local_ip") or service.values.get("tailscale_ip") or "").strip()
    port = str(service.values.get("port") or "").strip()
    if not host:
        return None
    proto = "https" if port == "443" else "http"
    if port:
        return f"{proto}://{host}:{port}"
    return f"{proto}://{host}"


def request_bytes(url: str, accept: str) -> tuple[bytes, str]:
    req = Request(url, headers={"User-Agent": "OmniNavIconFetcher/1.0", "Accept": accept})
    ctx = ssl._create_unverified_context()
    with urlopen(req, timeout=TIMEOUT, context=ctx) as res:
        return res.read(2_000_000), res.headers.get("Content-Type", "")


def parse_page(base_url: str) -> tuple[list[str], str]:
    candidates: list[str] = []
    title = ""
    try:
        html, _ = request_bytes(base_url, "text/html,*/*")
        parser = PageParser()
        parser.feed(html[:500_000].decode("utf-8", errors="ignore"))
        candidates.extend(urljoin(base_url, href) for href in parser.icons)
        title = parser.title
    except Exception:
        pass

    origin = "{0.scheme}://{0.netloc}/".format(urlsplit(base_url))
    candidates.extend([
        urljoin(origin, "/favicon.ico"),
        urljoin(origin, "/favicon.png"),
        urljoin(origin, "/apple-touch-icon.png"),
    ])

    seen: set[str] = set()
    unique: list[str] = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique, title


def extension(url: str, content_type: str, data: bytes) -> str:
    ctype = content_type.lower()
    path = urlsplit(url).path.lower()
    if "png" in ctype or data.startswith(b"\x89PNG") or path.endswith(".png"):
        return ".png"
    if "svg" in ctype or path.endswith(".svg"):
        return ".svg"
    if "jpeg" in ctype or "jpg" in ctype or data.startswith(b"\xff\xd8") or path.endswith((".jpg", ".jpeg")):
        return ".jpg"
    if "webp" in ctype or path.endswith(".webp"):
        return ".webp"
    return ".ico"


def icon_key(*values: str) -> str:
    for value in values:
        match = re.search(r"[A-Za-z][A-Za-z0-9]*", str(value or ""))
        if match:
            return match.group(0).lower()
    return ""


def host_key(base_url: str) -> str:
    host = urlsplit(base_url).hostname or ""
    return icon_key(host)


def existing_icon(key: str) -> str:
    for path in sorted(ICON_DIR.glob(f"{key}.*")):
        if path.is_file():
            return path.relative_to(ROOT).as_posix()
    return ""


def fetch_icon(service: Service, index: int) -> str:
    base = service_url(service)
    if not base:
        return ""

    candidates, page_title = parse_page(base)
    key = icon_key(page_title, str(service.values.get("name", "")), host_key(base))
    if not key:
        return ""

    existing = existing_icon(key)
    if existing:
        return existing

    for url in candidates:
        try:
            data, ctype = request_bytes(url, "image/*,*/*")
        except (URLError, TimeoutError, OSError):
            continue
        if len(data) < 32:
            continue
        ext = extension(url, ctype, data)
        filename = f"{key}{ext}"
        target = ICON_DIR / filename
        target.write_bytes(data)
        return target.relative_to(ROOT).as_posix()
    return ""


def main() -> int:
    if not CONFIG_PATH.exists():
        print(f"未找到 {CONFIG_PATH}", file=sys.stderr)
        return 1

    ICON_DIR.mkdir(parents=True, exist_ok=True)
    payload, services = parse_config(CONFIG_PATH)

    ok = 0
    for idx, service in enumerate(services):
        name = service.values.get("name", f"service-{idx + 1}")
        current_icon = str(service.values.get("icon_path") or "")
        icon_path = fetch_icon(service, idx)
        if not icon_path and current_icon.startswith("icons/"):
            icon_path = current_icon
        service.values["icon_path"] = icon_path
        if icon_path:
            ok += 1
            print(f"[OK] {name}: {icon_path}")
        else:
            print(f"[--] {name}: 未获取到图标")

    write_config(CONFIG_PATH, payload, services)
    print(f"完成：{ok}/{len(services)} 个服务写入 icon_path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
