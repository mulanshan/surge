#!/usr/bin/env python3
"""Credential-safe Stdio-to-HTTPS MCP bridge for local macOS Surge 6.11+.

Reads the HTTP API key from DMIT-Mac.conf at runtime, enforces a loopback-only
HTTPS endpoint with TLS verification, and passes X-Key to curl via stdin config
so credentials never appear in mcp_config.json, process arguments, or stderr.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


sys.dont_write_bytecode = True

ALLOWED_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "[::1]", "localhost"})
HTTP_API_RE = re.compile(r"^http-api\s*=\s*([^@\r\n]+)@", re.MULTILINE)


def default_mac_profile() -> Path:
    override = os.environ.get("SURGE_MAC_PROFILE", "").strip()
    if override:
        return Path(override)
    return (
        Path.home()
        / "Library"
        / "Mobile Documents"
        / "iCloud~com~nssurge~inc"
        / "Documents"
        / "DMIT-Mac.conf"
    )


def resolve_endpoint() -> tuple[str, int, str]:
    host = os.environ.get("SURGE_MCP_HOST", "127.0.0.1").strip()
    if host not in ALLOWED_LOOPBACK_HOSTS:
        raise ValueError(
            "SURGE_MCP_HOST must be a loopback host (127.0.0.1, [::1], or localhost); "
            "LAN MCP exposure is refused."
        )

    raw_port = os.environ.get("SURGE_HTTP_API_PORT", "1132").strip()
    if not raw_port.isdigit() or not (1 <= int(raw_port) <= 65535):
        raise ValueError("SURGE_HTTP_API_PORT must be an integer between 1 and 65535.")

    if os.environ.get("SURGE_HTTP_INSECURE", "0").strip() not in {"", "0"}:
        raise ValueError("SURGE_HTTP_INSECURE is refused for MCP control; TLS verification is mandatory.")

    ca_path = os.environ.get("SURGE_HTTP_CA", "").strip()
    if "\n" in ca_path or "\r" in ca_path:
        raise ValueError("SURGE_HTTP_CA must not contain a newline.")
    if ca_path and not os.access(ca_path, os.R_OK):
        raise ValueError("SURGE_HTTP_CA is not readable.")

    return host, int(raw_port), ca_path


def extract_http_key(profile_path: Path) -> str:
    if not profile_path.is_file() or not os.access(profile_path, os.R_OK):
        raise ValueError("Mac Surge profile is not readable; set SURGE_MAC_PROFILE.")
    match = HTTP_API_RE.search(profile_path.read_text(encoding="utf-8", errors="replace"))
    if not match:
        raise ValueError("http-api is not configured in the Mac Surge profile.")
    key = match.group(1).strip()
    if not key or "\n" in key or "\r" in key:
        raise ValueError("Invalid http-api credential format in profile.")
    return key


def escape_curl_quoted(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_curl_config(http_key: str, ca_path: str, payload_file: Path) -> str:
    lines = [
        f'header = "X-Key: {escape_curl_quoted(http_key)}"',
        'header = "Content-Type: application/json"',
        'header = "Accept: application/json, text/event-stream"',
        f'data-binary = "@{escape_curl_quoted(str(payload_file))}"',
        "silent",
        "connect-timeout = 3",
        "max-time = 60",
    ]
    if ca_path:
        lines.append(f'cacert = "{escape_curl_quoted(ca_path)}"')
    return "\n".join(lines) + "\n"


def jsonrpc_error(request_id: object, code: int, message: str) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        },
        ensure_ascii=False,
    )


def forward_message(raw_line: str, url: str, http_key: str, ca_path: str) -> list[str]:
    try:
        parsed = json.loads(raw_line)
    except json.JSONDecodeError:
        return [jsonrpc_error(None, -32700, "Invalid JSON-RPC input.")]

    has_id = isinstance(parsed, dict) and "id" in parsed
    request_id = parsed.get("id") if isinstance(parsed, dict) else None
    if isinstance(parsed, list):
        has_id = any(isinstance(item, dict) and "id" in item for item in parsed)

    old_umask = os.umask(0o077)
    temp_path: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix="surge-mcp-req.", suffix=".json")
        temp_path = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw_line)

        config = build_curl_config(http_key, ca_path, temp_path)
        completed = subprocess.run(
            [
                "curl",
                "-q",
                "--noproxy",
                "*",
                "--config",
                "-",
                "-X",
                "POST",
                "--write-out",
                "\n%{http_code}",
                url,
            ],
            input=config,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        os.umask(old_umask)
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    output = completed.stdout
    body, _, http_code = output.rpartition("\n")
    http_code = http_code.strip()

    if completed.returncode != 0 or not http_code.isdigit() or http_code == "000":
        if not has_id:
            return []
        return [
            jsonrpc_error(
                request_id,
                -32000,
                "Surge MCP TLS or transport check failed at loopback endpoint.",
            )
        ]

    status = int(http_code)
    if status in {202, 204} or (status == 200 and not body.strip()):
        return []

    if status in {401, 403}:
        if not has_id:
            return []
        reason = (
            "Surge MCP authentication denied."
            if status == 401
            else "Surge MCP endpoint forbidden; confirm http-api-mcp = true in DMIT-Mac.conf."
        )
        return [jsonrpc_error(request_id, -32001, reason)]

    if status != 200:
        if not has_id:
            return []
        return [jsonrpc_error(request_id, -32002, f"Surge MCP returned HTTP {status}.")]

    stripped = body.strip()
    sse_payloads = [
        line[5:].strip()
        for line in stripped.splitlines()
        if line.startswith("data:") and line[5:].strip()
    ]
    candidates = sse_payloads if sse_payloads else [stripped]
    responses: list[str] = []
    for item in candidates:
        try:
            obj = json.loads(item)
        except json.JSONDecodeError:
            if has_id:
                responses.append(
                    jsonrpc_error(request_id, -32603, "Invalid JSON payload from Surge MCP.")
                )
            continue
        responses.append(json.dumps(obj, ensure_ascii=False))
    return responses


def main() -> int:
    os.umask(0o077)
    try:
        host, port, ca_path = resolve_endpoint()
        profile_path = default_mac_profile()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    url = f"https://{host}:{port}/v1/mcp"
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            http_key = extract_http_key(profile_path)
        except ValueError as exc:
            parsed_id = None
            try:
                msg = json.loads(stripped)
                if isinstance(msg, dict) and "id" in msg:
                    parsed_id = msg["id"]
                else:
                    continue
            except json.JSONDecodeError:
                pass
            sys.stdout.write(jsonrpc_error(parsed_id, -32003, str(exc)) + "\n")
            sys.stdout.flush()
            continue

        for response_line in forward_message(stripped, url, http_key, ca_path):
            sys.stdout.write(response_line + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
