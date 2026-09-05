#!/usr/bin/env python3
"""Convert the legacy config.toml into the editor's config.json model."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw in {"true", "false"}:
        return raw == "true"
    if raw.startswith('"') and raw.endswith('"'):
        return json.loads(raw)
    return raw


def slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "group"


def parse_toml(path: Path) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[[services]]":
            current = {}
            services.append(current)
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        current[key.strip()] = parse_value(value)
    return services


def migrate(source: Path, target: Path) -> dict[str, Any]:
    source_services = parse_toml(source)
    group_ids: dict[str, str] = {}
    used_ids: set[str] = set()
    groups: list[dict[str, Any]] = [{
        "id": "favorites",
        "name": "常用",
        "order": 0,
        "columns": 5,
        "max_items": 10,
    }]
    used_ids.add("favorites")
    services: list[dict[str, Any]] = []
    group_orders: dict[str, int] = {"favorites": 0}

    for service_index, item in enumerate(source_services):
        pinned = item.get("pinned") is True
        group_name = str(item.get("group") or "").strip() or "未分组"
        if pinned:
            group_id = "favorites"
        elif group_name not in group_ids:
            base = "ungrouped" if group_name == "未分组" else slug(group_name)
            group_id = base
            suffix = 2
            while group_id in used_ids:
                group_id = f"{base}-{suffix}"
                suffix += 1
            used_ids.add(group_id)
            group_ids[group_name] = group_id
            groups.append({
                "id": group_id,
                "name": group_name,
                "order": len(groups) * 10,
                "columns": 5,
                "max_items": None,
            })
            group_orders[group_id] = 0
        else:
            group_id = group_ids[group_name]

        group_orders[group_id] = group_orders.get(group_id, 0) + 10

        base_id = slug(str(item.get("name") or "service"))
        service_id = f"{base_id}-{service_index + 1}"
        services.append({
            "id": service_id,
            "name": str(item.get("name") or ""),
            "group_id": group_id,
            "local_ip": str(item.get("local_ip") or ""),
            "tailscale_ip": str(item.get("tailscale_ip") or ""),
            "port": str(item.get("port") or ""),
            "tag": str(item.get("tag") or ""),
            "icon_path": str(item.get("icon_path") or ""),
            "order": group_orders[group_id],
            "position": None,
        })

    payload = {"version": 1, "groups": groups, "services": services}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", type=Path, default=ROOT / "config.toml")
    parser.add_argument("target", nargs="?", type=Path, default=ROOT / "config.json")
    args = parser.parse_args()
    result = migrate(args.source, args.target)
    print(f"migrated {len(result['services'])} services in {len(result['groups'])} groups to {args.target}")
