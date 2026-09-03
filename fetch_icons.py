#!/usr/bin/env python3
"""Fetch service icons from config.toml and write icon_path fields.

Icons are saved as icons/<first-page-title-word>.<ext>. Services whose page
title starts with the same English word reuse the same icon.

Run manually after editing config.toml:
  python fetch_icons.py
"""

from __future__ import annotations

import json
import re
import ssl
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.toml"
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


def parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw.startswith('"') and raw.endswith('"'):
        return json.loads(raw)
    return raw


def parse_config(path: Path) -> tuple[list[str], list[Service]]:
    header: list[str] = []
    services: list[Service] = []
    current: Service | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "[[services]]":
            current = Service()
            services.append(current)
            continue
        if current is None:
            header.append(line)
            continue
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        if sep:
            current.values[key.strip()] = parse_value(value)

    return header, services


def quote(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(str(value or ""), ensure_ascii=False)


def write_config(path: Path, header: list[str], services: list[Service]) -> None:
    keys = ["name", "group", "local_ip", "tailscale_ip", "port", "pinned", "tag", "icon_path"]
    lines = list(header)
    while lines and lines[-1] == "":
        lines.pop()
    lines.append("")

    for service in services:
        lines.append("[[services]]")
        for key in keys:
            if key in service.values or key == "icon_path":
                lines.append(f"{key} = {quote(service.values.get(key, ''))}")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


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
    header, services = parse_config(CONFIG_PATH)

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

    write_config(CONFIG_PATH, header, services)
    print(f"完成：{ok}/{len(services)} 个服务写入 icon_path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
