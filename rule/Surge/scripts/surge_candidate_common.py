"""Shared, side-effect-free parsing and session-export helpers for Surge candidate exporters."""

from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode, urlparse


HTTP_API_RE = re.compile(r"^http-api\s*=\s*([^@\r\n]+)@", re.MULTILINE)


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


def is_ip_literal(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def extract_host(row: dict) -> str:
    url = as_text(row.get("URL") or row.get("url"))
    remote = as_text(row.get("remoteHost") or row.get("remote_host"))

    match = re.search(r"\(([^)]+)\)", url)
    if match:
        inner = match.group(1).strip().strip("[]")
        return inner
    if "://" in url:
        parsed = urlparse(url)
        if parsed.hostname:
            return parsed.hostname

    candidate = (url or remote).split()[0].strip() if (url or remote) else ""
    if not candidate:
        return ""

    # Bracketed IPv6 literal with optional :port, e.g. [240e:39d::1]:443 or [240e:39d::1]
    bracket_match = re.match(r"^\[([^\]]+)\](?::(\d+))?$", candidate)
    if bracket_match:
        return bracket_match.group(1).strip()

    # Unbracketed IPv6 literal without port, e.g. 240e:39d::8080
    if is_ip_literal(candidate):
        return str(ipaddress.ip_address(candidate))

    # host:port or IPv4:port
    if ":" in candidate and candidate.count(":") == 1:
        host, port = candidate.rsplit(":", 1)
        if port.isdigit():
            return host

    return candidate.strip("[]")


def extract_path(row: dict) -> str:
    url = as_text(row.get("URL") or row.get("url"))
    if "://" not in url:
        return ""
    return urlparse(url).path or ""


def base_domain(host: str) -> str:
    host = host.lower().strip(".")
    if not host:
        return ""
    if is_ip_literal(host):
        return str(ipaddress.ip_address(host))
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


def _escape_curl_quoted(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_curl_config(http_key: str, ca_path: str, insecure: bool) -> str:
    lines = [
        f'header = "X-Key: {_escape_curl_quoted(http_key)}"',
        "silent",
        "show-error",
        "fail",
        "connect-timeout = 5",
        "max-time = 30",
    ]
    if insecure:
        lines.append("insecure")
    elif ca_path:
        lines.append(f'cacert = "{_escape_curl_quoted(ca_path)}"')
    return "\n".join(lines) + "\n"


def _curl_get_json(url: str, config: str) -> dict:
    completed = subprocess.run(
        ["curl", "-q", "--noproxy", "*", "--config", "-", url],
        input=config,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"Surge HTTPS API request failed for {urlparse(url).path} (exit {completed.returncode})."
        )
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON from Surge HTTPS API {urlparse(url).path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Unexpected payload type from Surge HTTPS API {urlparse(url).path}.")
    return data


def fetch_capture_session_dump(
    *,
    profile_path: Path,
    remote_host: str,
    remote_port: str,
    session_spec: str,
    output_path: Path,
    ca_path: str = "",
    insecure: bool = False,
    filter_text: str = "",
    page_limit: int = 500,
) -> str:
    """Export all requests from a Surge 6.11+ / iOS 6.0+ saved capture session via stdin X-Key."""
    match = HTTP_API_RE.search(profile_path.read_text(encoding="utf-8", errors="replace"))
    if not match or not match.group(1).strip():
        raise SystemExit("Cannot read http-api from profile.")
    http_key = match.group(1).strip()
    if "\n" in http_key or "\r" in http_key:
        raise SystemExit("Invalid http-api credential in profile.")

    config = _build_curl_config(http_key, ca_path, insecure)
    base_url = f"https://{remote_host}:{remote_port}"

    session_name = session_spec.strip()
    if session_name == "latest":
        listing = _curl_get_json(f"{base_url}/v1/capture/sessions", config)
        sessions = listing.get("sessions")
        if not isinstance(sessions, list) or not sessions:
            raise SystemExit("No saved capture sessions found on target Surge instance.")
        first = sessions[0]
        resolved = first.get("name") if isinstance(first, dict) else None
        if not isinstance(resolved, str) or not resolved.strip():
            raise SystemExit("Invalid session entry returned by /v1/capture/sessions.")
        session_name = resolved.strip()

    all_requests: list[dict] = []
    offset = 0
    while True:
        params: dict[str, str | int] = {
            "session": session_name,
            "offset": offset,
            "limit": page_limit,
        }
        if filter_text:
            params["filter"] = filter_text
        query = urlencode(params)
        page = _curl_get_json(f"{base_url}/v1/capture/sessions/requests?{query}", config)
        batch = page.get("requests")
        if not isinstance(batch, list):
            raise SystemExit("Missing requests array in /v1/capture/sessions/requests response.")
        all_requests.extend(batch)

        returned = page.get("returned", len(batch))
        target_total = page.get("matched") if filter_text and "matched" in page else page.get("total")
        if not isinstance(returned, int) or returned <= 0:
            break
        offset += returned
        if isinstance(target_total, int) and offset >= target_total:
            break

    old_umask = os.umask(0o077)
    try:
        output_path.write_text(
            json.dumps({"session": session_name, "requests": all_requests}, ensure_ascii=False),
            encoding="utf-8",
        )
        output_path.chmod(0o600)
    finally:
        os.umask(old_umask)
    return session_name
