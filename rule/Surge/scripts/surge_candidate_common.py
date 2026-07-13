"""Shared, side-effect-free parsing helpers for Surge candidate exporters."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse


def as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " | ".join(as_text(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def load_requests(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for key in ("recent-requests", "requests", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    if isinstance(data, list):
        return data
    raise SystemExit(f"Unsupported Surge request dump shape: {path}")


def extract_host(row: dict) -> str:
    url = as_text(row.get("URL") or row.get("url"))
    remote = as_text(row.get("remoteHost") or row.get("remote_host"))

    match = re.search(r"\(([^)]+)\)", url)
    if match:
        return match.group(1).strip()
    if "://" in url:
        parsed = urlparse(url)
        if parsed.hostname:
            return parsed.hostname

    candidate = (url or remote).split()[0].strip() if (url or remote) else ""
    candidate = candidate.strip("[]")
    if not candidate:
        return ""
    if ":" in candidate and not re.match(r"^\d+\.\d+\.\d+\.\d+:", candidate):
        host, port = candidate.rsplit(":", 1)
        if port.isdigit():
            return host
    return candidate


def extract_path(row: dict) -> str:
    url = as_text(row.get("URL") or row.get("url"))
    if "://" not in url:
        return ""
    return urlparse(url).path or ""


def base_domain(host: str) -> str:
    host = host.lower().strip(".")
    if not host:
        return ""
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        return host
    parts = host.split(".")
    return host if len(parts) <= 2 else ".".join(parts[-2:])


def first_time(row: dict) -> str:
    notes = row.get("notes")
    source = " ".join(as_text(value) for value in notes) if isinstance(notes, list) else as_text(notes)
    match = re.search(r"\b(\d{2}:\d{2}:\d{2})", source)
    return match.group(1) if match else ""


def is_rejected(row: dict) -> bool:
    return bool(row.get("rejected") is True or as_text(row.get("policyName")) == "REJECT")


def load_existing_rules(paths: list[Path]) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "[")) or "=" in stripped:
                continue
            parts = [part.strip() for part in stripped.split(",")]
            if len(parts) >= 2 and parts[0] in {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"}:
                rules.append((parts[0], parts[1].lower()))
    return rules


def matches_existing(host: str, rules: list[tuple[str, str]]) -> bool:
    host = host.lower().strip(".")
    for rule_type, value in rules:
        if rule_type == "DOMAIN" and host == value:
            return True
        if rule_type == "DOMAIN-SUFFIX" and (host == value or host.endswith("." + value)):
            return True
        if rule_type == "DOMAIN-KEYWORD" and value in host:
            return True
    return False
