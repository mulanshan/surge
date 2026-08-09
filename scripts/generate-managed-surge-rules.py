#!/usr/bin/env python3
"""Generate pinned, reviewable Surge rulesets from selected upstream rules."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import ipaddress
import json
import os
import re
import shutil
import sys
import tempfile
import textwrap
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "rule/Surge/sources/managed-rules.yaml"
UPSTREAM_DIR = ROOT / "rule/Surge/upstream"

ALLOWED_RULES = {
    "DOMAIN",
    "DOMAIN-SUFFIX",
    "DOMAIN-KEYWORD",
    "DOMAIN-WILDCARD",
    "DOMAIN-SET",
    "IP-CIDR",
    "IP-CIDR6",
    "IP-ASN",
    "GEOIP",
    "USER-AGENT",
    "URL-REGEX",
    "DEST-PORT",
    "PROTOCOL",
}
IP_RULES = {"IP-CIDR", "IP-CIDR6", "IP-ASN"}
ALLOWED_RULE_OPTIONS = {"no-resolve"}
ALLOWED_SUGGESTED_OPTIONS = {"extended-matching", "no-resolve"}
TOP_LEVEL_KEYS = {"version", "generated_dir", "sets"}
SET_KEYS = {
    "id",
    "name",
    "description",
    "output",
    "domain_set_output",
    "non_domain_output",
    "suggested_policy",
    "suggested_options",
    "include_process_name",
    "include_rules",
    "exclude_rules",
    "sources",
}
SOURCE_KEYS = {
    "name",
    "url",
    "snapshot",
    "tracking_url",
    "expected_sha256",
    "license",
    "license_url",
}
MARKER_PATTERNS = (
    re.compile(r"rul35et", re.IGNORECASE),
    re.compile(r"mad3_by_5ukk4w", re.IGNORECASE),
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class SourceHashMismatch(ValueError):
    """Raised when an upstream source no longer matches its reviewed digest."""


@dataclasses.dataclass(frozen=True)
class Source:
    name: str
    url: str | None
    tracking_url: str | None
    expected_sha256: str
    license: str
    license_url: str
    snapshot: str | None = None


@dataclasses.dataclass(frozen=True)
class RuleSet:
    rule_id: str
    name: str
    description: str
    output: str
    domain_set_output: str | None
    non_domain_output: str | None
    suggested_policy: str
    suggested_options: list[str]
    include_process_name: bool
    include_rules: frozenset[str]
    exclude_rules: frozenset[str]
    sources: list[Source]


@dataclasses.dataclass(frozen=True)
class GeneratedRuleSet:
    metadata: dict[str, Any]
    list_text: str
    domain_set_text: str | None
    non_domain_text: str | None
    metadata_text: str
    source_hashes: dict[tuple[str, str], str]


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value in {"true", "false"}:
        return value == "true"
    if re.fullmatch(r"[0-9]+", value):
        return int(value)
    return value


def parse_simple_yaml(path: Path) -> dict[str, Any]:
    """Parse and retain the deliberately small manifest schema."""
    result: dict[str, Any] = {"sets": []}
    current_set: dict[str, Any] | None = None
    current_key: str | None = None
    current_source: dict[str, Any] | None = None

    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ValueError(f"{path}:{line_number}: tabs are not allowed for indentation")
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))

        if indent == 0 and stripped == "sets:":
            continue
        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            result[key] = parse_scalar(value)
            continue

        if indent == 2 and stripped.startswith("- "):
            current_set = {
                "sources": [],
                "suggested_options": [],
                "include_rules": [],
                "exclude_rules": [],
            }
            result["sets"].append(current_set)
            current_key = None
            current_source = None
            item = stripped[2:]
            if ":" not in item:
                raise ValueError(f"{path}:{line_number}: set entries require a key")
            key, value = item.split(":", 1)
            current_set[key] = parse_scalar(value)
            continue

        if current_set is None:
            raise ValueError(f"{path}:{line_number}: unexpected manifest line")

        if indent == 4 and stripped.endswith(":"):
            current_key = stripped[:-1]
            current_set.setdefault(current_key, [])
            current_source = None
            continue

        if indent == 4 and ":" in stripped:
            key, value = stripped.split(":", 1)
            current_set[key] = parse_scalar(value)
            current_key = None
            current_source = None
            continue

        if indent == 6 and stripped.startswith("- "):
            item = stripped[2:]
            if current_key == "sources":
                current_source = {}
                current_set["sources"].append(current_source)
                if ":" not in item:
                    raise ValueError(f"{path}:{line_number}: source entries require a key")
                key, value = item.split(":", 1)
                current_source[key] = parse_scalar(value)
            elif current_key in {"suggested_options", "include_rules", "exclude_rules"}:
                current_set[current_key].append(parse_scalar(item))
            else:
                raise ValueError(f"{path}:{line_number}: unexpected list entry")
            continue

        if indent == 8 and current_key == "sources" and current_source is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current_source[key] = parse_scalar(value)
            continue

        raise ValueError(f"{path}:{line_number}: unsupported manifest line")

    return result


def require_string(mapping: dict[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}: {key} must be a non-empty string")
    return value.strip()


def reject_unknown_keys(mapping: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise ValueError(f"{context}: unknown field(s): {', '.join(sorted(unknown))}")


def raw_github_parts(url: str) -> tuple[str, str, str, str] | None:
    parsed = urllib.parse.urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme != "https" or parsed.netloc != "raw.githubusercontent.com" or len(parts) < 4:
        return None
    return parts[0], parts[1], parts[2], "/".join(parts[3:])


def immutable_remote_source(url: str) -> bool:
    parts = raw_github_parts(url)
    return parts is not None and bool(re.fullmatch(r"[0-9a-f]{40}", parts[2]))


def snapshot_path(value: str, context: str, *, require_file: bool = True) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{context}: snapshot must be a repository-relative path")
    candidate = ROOT / relative
    try:
        candidate.resolve().relative_to(UPSTREAM_DIR.resolve())
    except ValueError as exc:
        raise ValueError(f"{context}: snapshot must stay under rule/Surge/upstream") from exc
    if candidate.is_symlink():
        raise ValueError(f"{context}: snapshot must not be a symbolic link")
    if require_file and not candidate.is_file():
        raise ValueError(f"{context}: snapshot file does not exist: {value}")
    return candidate


def repin_raw_github_url(url: str, commit: str) -> str:
    parts = raw_github_parts(url)
    if parts is None or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit refresh requires a raw.githubusercontent.com source and 40-hex commit")
    owner, repository, _old_ref, path = parts
    return f"https://raw.githubusercontent.com/{owner}/{repository}/{commit}/{path}"


def normalize_rule_line(
    line: str,
    *,
    include_process_name: bool = False,
    context: str = "upstream rule",
) -> str | None:
    """Return a canonical policy-free rule, or None for comments/ignored rows."""
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "//", ";", "[", "payload:", "- ")):
        return None

    parts = [part.strip() for part in stripped.split(",")]
    rule_type = parts[0].upper()
    if rule_type == "PROCESS-NAME" and not include_process_name:
        return None
    if rule_type != "PROCESS-NAME" and rule_type not in ALLOWED_RULES:
        if "," in stripped and re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", parts[0]):
            raise ValueError(f"{context}: unsupported rule type {parts[0]!r}")
        return None
    if len(parts) < 2 or not parts[1]:
        raise ValueError(f"{context}: malformed {rule_type} rule")
    if any(pattern.search(parts[1]) for pattern in MARKER_PATTERNS):
        return None
    if len(parts) > 3:
        raise ValueError(f"{context}: too many fields; RULE-SET entries cannot contain a policy")
    if len(parts) == 3:
        option = parts[2].lower()
        if option not in ALLOWED_RULE_OPTIONS or rule_type not in IP_RULES:
            raise ValueError(
                f"{context}: unknown option or policy {parts[2]!r}; generated rules must be policy-free"
            )
        parts[2] = option
    if rule_type in {"IP-CIDR", "IP-CIDR6"}:
        family = 4 if rule_type == "IP-CIDR" else 6
        label = "IPv4" if family == 4 else "IPv6"
        try:
            network = ipaddress.ip_network(parts[1], strict=False)
        except ValueError as exc:
            raise ValueError(f"{context}: invalid {label} CIDR {parts[1]!r}") from exc
        if network.version != family:
            raise ValueError(f"{context}: invalid {label} CIDR {parts[1]!r}")
        if "/" not in parts[1]:
            address = ipaddress.ip_address(parts[1])
            parts[1] = f"{address.compressed}/{network.max_prefixlen}"
    if rule_type in {"IP-CIDR", "IP-CIDR6"} and len(parts) == 2:
        parts.append("no-resolve")
    parts[0] = rule_type
    return ",".join(parts)


def load_manifest(path: Path) -> tuple[Path, list[RuleSet]]:
    data = parse_simple_yaml(path)
    reject_unknown_keys(data, TOP_LEVEL_KEYS, "manifest")
    if data.get("version") != 3:
        raise ValueError("manifest: version must be 3")
    generated_dir_value = require_string(data, "generated_dir", "manifest")
    generated_dir = (ROOT / generated_dir_value).resolve()
    try:
        generated_dir.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError("manifest: generated_dir must stay inside the repository") from exc
    if not isinstance(data.get("sets"), list) or not data["sets"]:
        raise ValueError("manifest: sets must be a non-empty list")

    sets: list[RuleSet] = []
    seen_ids: set[str] = set()
    seen_outputs: set[str] = set()
    seen_snapshots: set[str] = set()
    blackmatrix_pins: set[str] = set()
    for index, item in enumerate(data["sets"], 1):
        context = f"set #{index}"
        if not isinstance(item, dict):
            raise ValueError(f"{context}: must be a mapping")
        reject_unknown_keys(item, SET_KEYS, context)
        rule_id = require_string(item, "id", context)
        output = require_string(item, "output", context)
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", rule_id):
            raise ValueError(f"{context}: invalid id {rule_id!r}")
        if Path(output).name != output or not output.endswith(".list"):
            raise ValueError(f"{context}: output must be a .list basename")
        raw_domain_set_output = item.get("domain_set_output")
        raw_non_domain_output = item.get("non_domain_output")
        if (raw_domain_set_output is None) != (raw_non_domain_output is None):
            raise ValueError(
                f"{context}: domain_set_output and non_domain_output must be configured together"
            )
        domain_set_output: str | None = None
        non_domain_output: str | None = None
        if raw_domain_set_output is not None:
            domain_set_output = require_string(item, "domain_set_output", context)
            non_domain_output = require_string(item, "non_domain_output", context)
            if Path(domain_set_output).name != domain_set_output or not domain_set_output.endswith(
                ".domainset"
            ):
                raise ValueError(f"{context}: domain_set_output must be a .domainset basename")
            if Path(non_domain_output).name != non_domain_output or not non_domain_output.endswith(
                ".non-domain.list"
            ):
                raise ValueError(
                    f"{context}: non_domain_output must be a .non-domain.list basename"
                )
        outputs = [output]
        if domain_set_output is not None and non_domain_output is not None:
            outputs.extend([domain_set_output, non_domain_output])
        if (
            rule_id in seen_ids
            or len(outputs) != len(set(outputs))
            or any(name in seen_outputs for name in outputs)
        ):
            raise ValueError(f"{context}: duplicate id or output")
        seen_ids.add(rule_id)
        seen_outputs.update(outputs)

        options = item.get("suggested_options", [])
        if not isinstance(options, list) or any(option not in ALLOWED_SUGGESTED_OPTIONS for option in options):
            raise ValueError(f"{context}: suggested_options contains an unknown option")
        include_process_name = item.get("include_process_name", False)
        if not isinstance(include_process_name, bool):
            raise ValueError(f"{context}: include_process_name must be true or false")

        inclusions: set[str] = set()
        raw_inclusions = item.get("include_rules", [])
        if not isinstance(raw_inclusions, list):
            raise ValueError(f"{context}: include_rules must be a list")
        for raw_rule in raw_inclusions:
            if not isinstance(raw_rule, str):
                raise ValueError(f"{context}: include_rules entries must be strings")
            normalized = normalize_rule_line(raw_rule, include_process_name=True, context=f"{context} inclusion")
            if not normalized:
                raise ValueError(f"{context}: inclusion is not a usable rule: {raw_rule!r}")
            inclusions.add(normalized)

        exclusions: set[str] = set()
        raw_exclusions = item.get("exclude_rules", [])
        if not isinstance(raw_exclusions, list):
            raise ValueError(f"{context}: exclude_rules must be a list")
        for raw_rule in raw_exclusions:
            if not isinstance(raw_rule, str):
                raise ValueError(f"{context}: exclude_rules entries must be strings")
            normalized = normalize_rule_line(raw_rule, include_process_name=True, context=f"{context} exclusion")
            if not normalized:
                raise ValueError(f"{context}: exclusion is not a usable rule: {raw_rule!r}")
            exclusions.add(normalized)
        overlap = inclusions & exclusions
        if overlap:
            raise ValueError(
                f"{context}: rules cannot be both included and excluded: {', '.join(sorted(overlap))}"
            )

        raw_sources = item.get("sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ValueError(f"{context}: sources must be a non-empty list")
        sources: list[Source] = []
        seen_source_names: set[str] = set()
        for source_index, source_item in enumerate(raw_sources, 1):
            source_context = f"{context} source #{source_index}"
            if not isinstance(source_item, dict):
                raise ValueError(f"{source_context}: must be a mapping")
            reject_unknown_keys(source_item, SOURCE_KEYS, source_context)
            source_name = require_string(source_item, "name", source_context)
            if source_name in seen_source_names:
                raise ValueError(f"{source_context}: duplicate source name")
            seen_source_names.add(source_name)
            expected_sha256 = require_string(source_item, "expected_sha256", source_context).lower()
            if not SHA256_RE.fullmatch(expected_sha256):
                raise ValueError(f"{source_context}: expected_sha256 must be 64 lowercase hex characters")
            url_value = source_item.get("url")
            snapshot_value = source_item.get("snapshot")
            if (url_value is None) == (snapshot_value is None):
                raise ValueError(f"{source_context}: configure exactly one of url or snapshot")
            tracking_url = require_string(source_item, "tracking_url", source_context)
            license_url = require_string(source_item, "license_url", source_context)
            if not tracking_url.startswith("https://") or not license_url.startswith("https://"):
                raise ValueError(f"{source_context}: tracking and license URLs must use HTTPS")

            url: str | None = None
            snapshot: str | None = None
            if url_value is not None:
                url = require_string(source_item, "url", source_context)
                if url == tracking_url:
                    raise ValueError(f"{source_context}: url and tracking_url must differ")
                if not immutable_remote_source(url):
                    raise ValueError(
                        f"{source_context}: remote build input must be a raw GitHub 40-hex commit URL; "
                        "use snapshot for moving or non-GitHub sources"
                    )
                pinned_parts = raw_github_parts(url)
                tracking_parts = raw_github_parts(tracking_url)
                assert pinned_parts is not None
                if tracking_parts is None or (
                    pinned_parts[0], pinned_parts[1], pinned_parts[3]
                ) != (tracking_parts[0], tracking_parts[1], tracking_parts[3]):
                    raise ValueError(
                        f"{source_context}: tracking_url must identify the same GitHub repository path"
                    )
                if re.fullmatch(r"[0-9a-f]{40}", tracking_parts[2]):
                    raise ValueError(
                        f"{source_context}: tracking_url must use a moving ref, not a commit pin"
                    )
                if pinned_parts[:2] == ("blackmatrix7", "ios_rule_script"):
                    blackmatrix_pins.add(pinned_parts[2])
            else:
                snapshot = require_string(source_item, "snapshot", source_context)
                snapshot_path(snapshot, source_context)
                if snapshot in seen_snapshots:
                    raise ValueError(f"{source_context}: duplicate snapshot path: {snapshot}")
                seen_snapshots.add(snapshot)
            sources.append(
                Source(
                    name=source_name,
                    url=url,
                    tracking_url=tracking_url,
                    expected_sha256=expected_sha256,
                    license=require_string(source_item, "license", source_context),
                    license_url=license_url,
                    snapshot=snapshot,
                )
            )

        sets.append(
            RuleSet(
                rule_id=rule_id,
                name=require_string(item, "name", context),
                description=require_string(item, "description", context),
                output=output,
                domain_set_output=domain_set_output,
                non_domain_output=non_domain_output,
                suggested_policy=require_string(item, "suggested_policy", context),
                suggested_options=list(options),
                include_process_name=include_process_name,
                include_rules=frozenset(inclusions),
                exclude_rules=frozenset(exclusions),
                sources=sources,
            )
        )
    if len(blackmatrix_pins) > 1:
        raise ValueError("manifest: all blackmatrix7/ios_rule_script sources must use one commit pin")
    return generated_dir, sets


def fetch_text(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "mulanshan-surge-rule-generator/2.0",
            "Accept": "text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def rule_sort_key(line: str) -> tuple[int, str]:
    rule_type = line.split(",", 1)[0]
    order = {
        "DOMAIN": 0,
        "DOMAIN-SUFFIX": 1,
        "DOMAIN-KEYWORD": 2,
        "DOMAIN-WILDCARD": 3,
        "PROCESS-NAME": 4,
        "USER-AGENT": 5,
        "IP-CIDR": 6,
        "IP-CIDR6": 7,
        "IP-ASN": 8,
        "GEOIP": 9,
    }
    return (order.get(rule_type, 99), line)


def safe_width_lines(text: str, width: int = 88) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)


def split_domain_set_entries(ordered_rules: list[str]) -> tuple[list[str], list[str]]:
    """Convert exact/suffix domain rules and retain every other rule verbatim."""
    domain_set: list[str] = []
    non_domain: list[str] = []
    for rule in ordered_rules:
        rule_type, value, *_rest = rule.split(",")
        if rule_type == "DOMAIN":
            domain_set.append(value)
        elif rule_type == "DOMAIN-SUFFIX":
            domain_set.append(f".{value}")
        else:
            non_domain.append(rule)
    return domain_set, non_domain


def load_source_bytes(
    source: Source,
    timeout: int,
    *,
    fetcher: Callable[[str, int], bytes] = fetch_text,
) -> bytes:
    if source.snapshot is not None:
        return snapshot_path(source.snapshot, f"source {source.name}").read_bytes()
    if source.url is None:
        raise ValueError(f"source {source.name}: missing immutable url or snapshot")
    return fetcher(source.url, timeout)


def build_one(
    rule_set: RuleSet,
    timeout: int,
    *,
    enforce_expected_hashes: bool = True,
    fetcher: Callable[[str, int], bytes] = fetch_text,
    source_overrides: dict[str, bytes] | None = None,
    allowed_hash_changes: set[str] | None = None,
) -> GeneratedRuleSet:
    entries: dict[str, set[str]] = {rule: {"manifest include_rules"} for rule in rule_set.include_rules}
    source_meta: list[dict[str, Any]] = []
    source_hashes: dict[tuple[str, str], str] = {}

    for source in rule_set.sources:
        raw = (
            source_overrides[source.name]
            if source_overrides is not None and source.name in source_overrides
            else load_source_bytes(source, timeout, fetcher=fetcher)
        )
        sha = hashlib.sha256(raw).hexdigest()
        source_hashes[(rule_set.rule_id, source.name)] = sha
        hash_may_change = not enforce_expected_hashes or (
            allowed_hash_changes is not None and source.name in allowed_hash_changes
        )
        if not hash_may_change and sha != source.expected_sha256:
            raise SourceHashMismatch(
                f"{rule_set.rule_id}/{source.name}: pinned source sha256 changed\n"
                f"  expected: {source.expected_sha256}\n"
                f"  actual:   {sha}\n"
                "Run --refresh-sources only on a review branch, inspect the complete diff, and open a PR."
            )
        text = raw.decode("utf-8-sig", errors="replace")
        rules: set[str] = set()
        for line_number, line in enumerate(text.splitlines(), 1):
            normalized = normalize_rule_line(
                line,
                include_process_name=rule_set.include_process_name,
                context=f"{rule_set.rule_id}/{source.name}:{line_number}",
            )
            if normalized and normalized not in rule_set.exclude_rules:
                rules.add(normalized)
                entries.setdefault(normalized, set()).add(source.name)
        metadata = {
            "name": source.name,
            "url": source.url,
            "snapshot": source.snapshot,
            "sha256": sha,
            "expected_sha256": sha if hash_may_change else source.expected_sha256,
            "license": source.license,
            "license_url": source.license_url,
            "rule_count": len(rules),
        }
        metadata["tracking_url"] = source.tracking_url
        source_meta.append(metadata)

    ordered = sorted(entries, key=rule_sort_key)
    if not ordered:
        raise ValueError(f"{rule_set.rule_id}: contains no usable rules")
    header_lines = [
        f"# NAME: {rule_set.name}",
        f"# ID: {rule_set.rule_id}",
        "# Generated by scripts/generate-managed-surge-rules.py",
        "# Do not edit this file directly unless you intentionally want to fork it.",
    ]
    for wrapped in safe_width_lines(rule_set.description):
        header_lines.append(f"# {wrapped}")
    header_lines.extend([f"# Suggested policy: {rule_set.suggested_policy}", "# Sources:"])
    for meta in source_meta:
        location = meta["url"] or f"snapshot:{meta['snapshot']}"
        header_lines.append(f"# - {meta['name']}: {location}")
        header_lines.append(f"#   tracking: {meta['tracking_url']}")
        header_lines.append(f"#   sha256: {meta['sha256']}")
        header_lines.append(f"#   license: {meta['license']} ({meta['license_url']})")
        header_lines.append(f"#   rules: {meta['rule_count']}")
    if rule_set.include_rules:
        header_lines.append("# Curated rules moved from overlapping generated sets:")
        for rule in sorted(rule_set.include_rules, key=rule_sort_key):
            header_lines.append(f"# - {rule}")
    if rule_set.exclude_rules:
        header_lines.append("# Excluded overlapping rules:")
        for rule in sorted(rule_set.exclude_rules, key=rule_sort_key):
            header_lines.append(f"# - {rule}")
    lines = [*header_lines, f"# Total unique rules: {len(ordered)}", "", *ordered]
    list_text = "\n".join(lines).rstrip() + "\n"

    domain_set_text: str | None = None
    non_domain_text: str | None = None
    domain_set_entries: list[str] = []
    non_domain_entries: list[str] = []
    if rule_set.domain_set_output is not None:
        domain_set_entries, non_domain_entries = split_domain_set_entries(ordered)
        if not domain_set_entries:
            raise ValueError(f"{rule_set.rule_id}: optimized split contains no domain rules")
        domain_set_lines = [
            *header_lines,
            "# Artifact: Surge DOMAIN-SET (exact domains and leading-dot suffix domains only).",
            f"# Total DOMAIN-SET entries: {len(domain_set_entries)}",
            "",
            *domain_set_entries,
        ]
        domain_set_text = "\n".join(domain_set_lines).rstrip() + "\n"
        non_domain_lines = [
            *header_lines,
            "# Artifact: residual Surge RULE-SET (all rules not representable by DOMAIN-SET).",
            f"# Total residual rules: {len(non_domain_entries)}",
            "",
            *non_domain_entries,
        ]
        non_domain_text = "\n".join(non_domain_lines).rstrip() + "\n"

    metadata = {
        "id": rule_set.rule_id,
        "name": rule_set.name,
        "output": str((ROOT / "rule/Surge/generated" / rule_set.output).relative_to(ROOT)),
        "description": rule_set.description,
        "suggested_policy": rule_set.suggested_policy,
        "suggested_options": rule_set.suggested_options,
        "included_rules": sorted(rule_set.include_rules, key=rule_sort_key),
        "excluded_rules": sorted(rule_set.exclude_rules, key=rule_sort_key),
        "unique_rule_count": len(ordered),
        "sources": source_meta,
    }
    if rule_set.domain_set_output is not None and rule_set.non_domain_output is not None:
        metadata.update(
            {
                "domain_set_output": str(
                    (ROOT / "rule/Surge/generated" / rule_set.domain_set_output).relative_to(ROOT)
                ),
                "non_domain_output": str(
                    (ROOT / "rule/Surge/generated" / rule_set.non_domain_output).relative_to(ROOT)
                ),
                "domain_set_rule_count": len(domain_set_entries),
                "non_domain_rule_count": len(non_domain_entries),
            }
        )
    return GeneratedRuleSet(
        metadata=metadata,
        list_text=list_text,
        domain_set_text=domain_set_text,
        non_domain_text=non_domain_text,
        metadata_text=json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        source_hashes=source_hashes,
    )


def load_metadata(metadata_path: Path) -> dict[str, Any]:
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def read_index_metadata(
    output_dir: Path,
    rule_sets: list[RuleSet],
    generated: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    generated_by_id = {item["id"]: item for item in generated}
    items: list[dict[str, Any]] = []
    for rule_set in rule_sets:
        if rule_set.rule_id in generated_by_id:
            items.append(generated_by_id[rule_set.rule_id])
        else:
            items.append(load_metadata(output_dir / f"{rule_set.output}.json"))
    return items


def index_text(generated: list[dict[str, Any]]) -> str:
    lines = [
        "# Generated Surge Rules",
        "",
        "These files are generated mirrors of selected upstream rulesets. Each source is pinned",
        "by SHA-256 in `../sources/managed-rules.yaml`; generated lists contain no policy field.",
        "",
        "Check the pinned sources and committed snapshots without writing:",
        "",
        "```bash",
        "scripts/generate-managed-surge-rules.py --check",
        "```",
        "",
        "Regenerate from already-reviewed, pinned sources:",
        "",
        "```bash",
        "scripts/generate-managed-surge-rules.py --update",
        "```",
        "",
        "Compare all moving tracking URLs with the reviewed build inputs:",
        "",
        "```bash",
        "scripts/generate-managed-surge-rules.py --check-upstream",
        "```",
        "",
        "Refresh one reviewed snapshot on a branch, or atomically repin every remote source",
        "to an explicitly reviewed GitHub commit. Both modes require a rule-set scope:",
        "",
        "```bash",
        "scripts/generate-managed-surge-rules.py --refresh-sources --only global",
        "scripts/generate-managed-surge-rules.py --refresh-sources --only microsoft --source-commit <40hex>",
        "```",
        "",
        "| ID | Compatibility file | Optimized files | Suggested policy | Unique rules |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for item in generated:
        optimized = "-"
        if item.get("domain_set_output") and item.get("non_domain_output"):
            optimized = (
                f"`{Path(item['domain_set_output']).name}` ({item['domain_set_rule_count']}) + "
                f"`{Path(item['non_domain_output']).name}` ({item['non_domain_rule_count']})"
            )
        lines.append(
            f"| {item['id']} | `{Path(item['output']).name}` | {optimized} | "
            f"`{item['suggested_policy']}` | {item['unique_rule_count']} |"
        )
    return "\n".join(lines) + "\n"


def refreshed_manifest_text(
    path: Path,
    source_hashes: dict[tuple[str, str], str],
    source_urls: dict[tuple[str, str], str] | None = None,
) -> str:
    """Replace selected source pins while preserving the reviewed manifest layout."""
    source_urls = source_urls or {}
    lines = path.read_text(encoding="utf-8").splitlines()
    current_set = ""
    current_source = ""
    seen_hashes: set[tuple[str, str]] = set()
    seen_urls: set[tuple[str, str]] = set()
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if indent == 2 and stripped.startswith("- id:"):
            current_set = stripped.split(":", 1)[1].strip()
            current_source = ""
        elif indent == 6 and stripped.startswith("- name:"):
            current_source = stripped.split(":", 1)[1].strip()
        elif indent == 8 and stripped.startswith("url:"):
            key = (current_set, current_source)
            if key in source_urls:
                line = f"        url: {source_urls[key]}"
                seen_urls.add(key)
        elif indent == 8 and stripped.startswith("expected_sha256:"):
            key = (current_set, current_source)
            if key in source_hashes:
                line = f"        expected_sha256: {source_hashes[key]}"
                seen_hashes.add(key)
        output.append(line)
    missing_hashes = set(source_hashes) - seen_hashes
    if missing_hashes:
        names = ", ".join(f"{rule_id}/{source}" for rule_id, source in sorted(missing_hashes))
        raise ValueError(f"Cannot find expected_sha256 field(s) in manifest: {names}")
    missing_urls = set(source_urls) - seen_urls
    if missing_urls:
        names = ", ".join(f"{rule_id}/{source}" for rule_id, source in sorted(missing_urls))
        raise ValueError(f"Cannot find url field(s) in manifest: {names}")
    return "\n".join(output) + "\n"


def compare_candidate(path: Path, expected_text: str) -> bool:
    return path.exists() and path.read_text(encoding="utf-8") == expected_text


def write_staged_file(staging_dir: Path, relative_name: str, text: str) -> Path:
    path = staging_dir / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_staged_bytes(staging_dir: Path, relative_name: str, data: bytes) -> Path:
    path = staging_dir / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def atomic_replace(staged_path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged_path, destination)


def replace_files_transactionally(
    replacements: list[tuple[Path, Path]],
    staging_dir: Path,
) -> None:
    """Replace a set of files and restore every prior destination on failure."""
    destinations = [destination for _staged, destination in replacements]
    if len(destinations) != len(set(destinations)):
        raise ValueError("transaction contains duplicate destinations")

    rollback_dir = staging_dir / ".rollback"
    rollback_dir.mkdir()
    applied: list[tuple[Path, Path | None]] = []
    try:
        for index, (staged_path, destination) in enumerate(replacements):
            destination.parent.mkdir(parents=True, exist_ok=True)
            backup: Path | None = None
            if destination.exists():
                backup = rollback_dir / str(index)
                shutil.copy2(destination, backup)
            applied.append((destination, backup))
            atomic_replace(staged_path, destination)
    except OSError as exc:
        rollback_errors: list[str] = []
        for destination, backup in reversed(applied):
            try:
                if backup is None:
                    if destination.exists():
                        destination.unlink()
                else:
                    os.replace(backup, destination)
            except OSError as rollback_exc:
                rollback_errors.append(f"{destination}: {rollback_exc}")
        if rollback_errors:
            raise OSError(
                f"file transaction failed ({exc}); rollback also failed: "
                + "; ".join(rollback_errors)
            ) from exc
        raise


def check_upstream_tracking(
    rule_sets: list[RuleSet],
    timeout: int,
    *,
    fetcher: Callable[[str, int], bytes] = fetch_text,
) -> bool:
    """Check moving tracking URLs without using them as reproducible build inputs."""
    tracked = [
        (rule_set, source)
        for rule_set in rule_sets
        for source in rule_set.sources
        if source.tracking_url is not None
    ]
    if not tracked:
        raise ValueError("No tracking_url sources are configured.")

    drifted: list[str] = []
    for rule_set, source in tracked:
        assert source.tracking_url is not None
        raw = fetcher(source.tracking_url, timeout)
        actual = hashlib.sha256(raw).hexdigest()
        label = f"{rule_set.rule_id}/{source.name}"
        if actual == source.expected_sha256:
            print(f"Tracking current: {label}")
            continue
        drifted.append(label)
        print(
            f"Tracking drift: {label}\n"
            f"  reviewed: {source.expected_sha256}\n"
            f"  upstream: {actual}\n"
            f"  tracking: {source.tracking_url}",
            file=sys.stderr,
        )

    if drifted:
        print(
            "Upstream tracking drift requires a reviewed commit pin, source hash, and generated diff. "
            "Do not replace the immutable source URL with a moving branch URL.",
            file=sys.stderr,
        )
        return False
    print(f"Verified {len(tracked)} moving tracking source(s); reviewed pins are current.")
    return True


def prepare_refresh(
    rule_sets: list[RuleSet],
    timeout: int,
    *,
    source_commit: str | None,
    selected_rule_ids: set[str] | None = None,
    fetcher: Callable[[str, int], bytes] = fetch_text,
) -> tuple[
    list[RuleSet],
    dict[str, dict[str, bytes]],
    dict[str, bytes],
    dict[tuple[str, str], str],
]:
    """Refresh selected snapshots and atomically repin every remote source."""
    if source_commit is not None and not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("--source-commit must be a 40-character lowercase hexadecimal commit")
    if selected_rule_ids is None:
        selected_rule_ids = {rule_set.rule_id for rule_set in rule_sets}
    selected_remote = any(
        rule_set.rule_id in selected_rule_ids and source.url is not None
        for rule_set in rule_sets
        for source in rule_set.sources
    )
    if selected_remote and source_commit is None:
        raise ValueError("--source-commit is required when refreshing a selected remote source")

    refreshed_sets: list[RuleSet] = []
    source_overrides: dict[str, dict[str, bytes]] = {}
    snapshot_updates: dict[str, bytes] = {}
    source_url_updates: dict[tuple[str, str], str] = {}
    for rule_set in rule_sets:
        refreshed_sources: list[Source] = []
        overrides: dict[str, bytes] = {}
        for source in rule_set.sources:
            refresh_snapshot = (
                source.snapshot is not None and rule_set.rule_id in selected_rule_ids
            )
            refresh_remote = source.url is not None and source_commit is not None
            if not refresh_snapshot and not refresh_remote:
                refreshed_sources.append(source)
                continue
            if source.tracking_url is None:
                raise ValueError(f"{rule_set.rule_id}/{source.name}: tracking_url is required")
            if refresh_snapshot:
                assert source.snapshot is not None
                raw = fetcher(source.tracking_url, timeout)
                snapshot_updates[source.snapshot] = raw
                refreshed_source = source
            else:
                assert source.url is not None and source_commit is not None
                refreshed_url = repin_raw_github_url(source.url, source_commit)
                raw = fetcher(refreshed_url, timeout)
                tracking_raw = fetcher(source.tracking_url, timeout)
                if hashlib.sha256(raw).digest() != hashlib.sha256(tracking_raw).digest():
                    raise ValueError(
                        f"{rule_set.rule_id}/{source.name}: --source-commit does not match the "
                        "current tracking URL; resolve and review the upstream head commit explicitly"
                    )
                source_url_updates[(rule_set.rule_id, source.name)] = refreshed_url
                refreshed_source = dataclasses.replace(source, url=refreshed_url)
            overrides[source.name] = raw
            refreshed_sources.append(refreshed_source)
        if overrides:
            source_overrides[rule_set.rule_id] = overrides
        refreshed_sets.append(dataclasses.replace(rule_set, sources=refreshed_sources))
    return refreshed_sets, source_overrides, snapshot_updates, source_url_updates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--only", action="append", help="Process only the named rule set id.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--source-commit",
        help="Explicit 40-hex GitHub commit used to atomically repin every remote source during refresh.",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="Verify pins and snapshots; never write.")
    modes.add_argument("--update", action="store_true", help="Write snapshots only when all pins match.")
    modes.add_argument(
        "--refresh-sources",
        action="store_true",
        help="Refresh source pins and snapshots for PR review; never use as a production publish step.",
    )
    modes.add_argument(
        "--check-upstream",
        action="store_true",
        help="Compare moving tracking URLs with reviewed immutable pins; never write.",
    )
    args = parser.parse_args()

    try:
        generated_dir, all_sets = load_manifest(args.manifest)
        selected_sets = all_sets
        wanted: set[str] = set()
        if args.only:
            wanted = set(args.only)
            selected_sets = [rule_set for rule_set in all_sets if rule_set.rule_id in wanted]
            missing = wanted - {rule_set.rule_id for rule_set in selected_sets}
            if missing:
                print(f"Unknown ruleset id(s): {', '.join(sorted(missing))}", file=sys.stderr)
                return 2
        if args.refresh_sources and not args.only:
            print("--refresh-sources requires one or more explicit --only rule-set ids.", file=sys.stderr)
            return 2
        if args.source_commit and not args.refresh_sources:
            print("--source-commit is valid only with --refresh-sources.", file=sys.stderr)
            return 2
        if args.check_upstream:
            return 0 if check_upstream_tracking(selected_sets, args.timeout) else 1

        mode = (
            "refresh"
            if args.refresh_sources
            else "update"
            if args.update
            else "check"
        )
        if not args.check and not args.update and not args.refresh_sources and not args.check_upstream:
            print("Defaulting to read-only check mode; pass --update to write reviewed pinned snapshots.")

        source_overrides: dict[str, dict[str, bytes]] = {}
        snapshot_updates: dict[str, bytes] = {}
        source_url_updates: dict[tuple[str, str], str] = {}
        refresh_keys: set[tuple[str, str]] = set()
        if mode == "refresh":
            print(
                "Refreshing snapshots only for explicit rule-set ids: "
                + ", ".join(sorted(wanted))
            )
            if args.source_commit:
                print(
                    "Atomically repinning every remote source to commit "
                    f"{args.source_commit} and verifying it against each moving tracking URL."
                )
            sets, source_overrides, snapshot_updates, source_url_updates = prepare_refresh(
                all_sets,
                args.timeout,
                source_commit=args.source_commit,
                selected_rule_ids=wanted,
            )
            refresh_keys = {
                (rule_id, source_name)
                for rule_id, overrides in source_overrides.items()
                for source_name in overrides
            }
        else:
            sets = selected_sets

        built: list[GeneratedRuleSet] = []
        source_hashes: dict[tuple[str, str], str] = {}
        for rule_set in sets:
            print(f"Fetching {rule_set.rule_id} -> {rule_set.output}")
            item = build_one(
                rule_set,
                args.timeout,
                enforce_expected_hashes=True,
                source_overrides=source_overrides.get(rule_set.rule_id),
                allowed_hash_changes=(
                    set(source_overrides.get(rule_set.rule_id, {}))
                    if mode == "refresh"
                    else None
                ),
            )
            built.append(item)
            source_hashes.update(item.source_hashes)

        generated_metadata = [item.metadata for item in built]
        index_items = (
            read_index_metadata(generated_dir, all_sets, generated_metadata)
            if args.only and mode != "refresh"
            else generated_metadata
        )
        readme_text = index_text(index_items)

        if mode == "check":
            mismatches: list[str] = []
            for rule_set, item in zip(sets, built):
                if not compare_candidate(generated_dir / rule_set.output, item.list_text):
                    mismatches.append(rule_set.output)
                if item.domain_set_text is not None and rule_set.domain_set_output is not None:
                    if not compare_candidate(
                        generated_dir / rule_set.domain_set_output, item.domain_set_text
                    ):
                        mismatches.append(rule_set.domain_set_output)
                if item.non_domain_text is not None and rule_set.non_domain_output is not None:
                    if not compare_candidate(
                        generated_dir / rule_set.non_domain_output, item.non_domain_text
                    ):
                        mismatches.append(rule_set.non_domain_output)
                if not compare_candidate(generated_dir / f"{rule_set.output}.json", item.metadata_text):
                    mismatches.append(f"{rule_set.output}.json")
            if not compare_candidate(generated_dir / "README.md", readme_text):
                mismatches.append("README.md")
            if mismatches:
                print("Generated snapshots are stale: " + ", ".join(mismatches), file=sys.stderr)
                print("Run --update after reviewing pinned inputs.", file=sys.stderr)
                return 1
            print(f"Verified {len(built)} pinned rulesets; no files changed.")
            return 0

        generated_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".managed-rules-", dir=generated_dir.parent) as temporary:
            staging_dir = Path(temporary)
            replacements: list[tuple[Path, Path]] = []
            for rule_set, item in zip(sets, built):
                replacements.append(
                    (
                        write_staged_file(staging_dir, rule_set.output, item.list_text),
                        generated_dir / rule_set.output,
                    )
                )
                if item.domain_set_text is not None and rule_set.domain_set_output is not None:
                    replacements.append(
                        (
                            write_staged_file(
                                staging_dir,
                                rule_set.domain_set_output,
                                item.domain_set_text,
                            ),
                            generated_dir / rule_set.domain_set_output,
                        )
                    )
                if item.non_domain_text is not None and rule_set.non_domain_output is not None:
                    replacements.append(
                        (
                            write_staged_file(
                                staging_dir,
                                rule_set.non_domain_output,
                                item.non_domain_text,
                            ),
                            generated_dir / rule_set.non_domain_output,
                        )
                    )
                replacements.append(
                    (
                        write_staged_file(
                            staging_dir,
                            f"{rule_set.output}.json",
                            item.metadata_text,
                        ),
                        generated_dir / f"{rule_set.output}.json",
                    )
                )
            replacements.append(
                (
                    write_staged_file(staging_dir, "README.md", readme_text),
                    generated_dir / "README.md",
                )
            )

            if mode == "refresh":
                refreshed_hashes = {
                    key: value for key, value in source_hashes.items() if key in refresh_keys
                }
                manifest_text = refreshed_manifest_text(
                    args.manifest,
                    refreshed_hashes,
                    source_url_updates,
                )
                for index, (relative, data) in enumerate(sorted(snapshot_updates.items())):
                    replacements.append(
                        (
                            write_staged_bytes(staging_dir, f"snapshot-{index}", data),
                            snapshot_path(relative, "refresh snapshot", require_file=False),
                        )
                    )
                replacements.append(
                    (
                        write_staged_file(staging_dir, "managed-rules.yaml", manifest_text),
                        args.manifest,
                    )
                )

            replace_files_transactionally(replacements, staging_dir)
            if mode == "refresh":
                print(
                    "Refreshed source pins and snapshots. Review every upstream and generated diff, "
                    "then open a PR; nothing was published."
                )
            else:
                print(f"Wrote {len(built)} pinned rulesets to {generated_dir.relative_to(ROOT)}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
