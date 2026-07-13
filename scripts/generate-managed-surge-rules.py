#!/usr/bin/env python3
"""Generate pinned, reviewable Surge rulesets from selected upstream rules."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import sys
import tempfile
import textwrap
import urllib.request
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "rule/Surge/sources/managed-rules.yaml"

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
    "suggested_policy",
    "suggested_options",
    "include_process_name",
    "include_rules",
    "exclude_rules",
    "sources",
}
SOURCE_KEYS = {"name", "url", "expected_sha256", "license", "license_url"}
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
    url: str
    expected_sha256: str
    license: str
    license_url: str


@dataclasses.dataclass(frozen=True)
class RuleSet:
    rule_id: str
    name: str
    description: str
    output: str
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
    if rule_type in {"IP-CIDR", "IP-CIDR6"} and len(parts) == 2:
        parts.append("no-resolve")
    parts[0] = rule_type
    return ",".join(parts)


def load_manifest(path: Path) -> tuple[Path, list[RuleSet]]:
    data = parse_simple_yaml(path)
    reject_unknown_keys(data, TOP_LEVEL_KEYS, "manifest")
    if data.get("version") != 2:
        raise ValueError("manifest: version must be 2")
    generated_dir_value = require_string(data, "generated_dir", "manifest")
    generated_dir = ROOT / generated_dir_value
    try:
        generated_dir.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError("manifest: generated_dir must stay inside the repository") from exc
    if not isinstance(data.get("sets"), list) or not data["sets"]:
        raise ValueError("manifest: sets must be a non-empty list")

    sets: list[RuleSet] = []
    seen_ids: set[str] = set()
    seen_outputs: set[str] = set()
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
        if rule_id in seen_ids or output in seen_outputs:
            raise ValueError(f"{context}: duplicate id or output")
        seen_ids.add(rule_id)
        seen_outputs.add(output)

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
            url = require_string(source_item, "url", source_context)
            license_url = require_string(source_item, "license_url", source_context)
            if not url.startswith("https://") or not license_url.startswith("https://"):
                raise ValueError(f"{source_context}: source and license URLs must use HTTPS")
            sources.append(
                Source(
                    name=source_name,
                    url=url,
                    expected_sha256=expected_sha256,
                    license=require_string(source_item, "license", source_context),
                    license_url=license_url,
                )
            )

        sets.append(
            RuleSet(
                rule_id=rule_id,
                name=require_string(item, "name", context),
                description=require_string(item, "description", context),
                output=output,
                suggested_policy=require_string(item, "suggested_policy", context),
                suggested_options=list(options),
                include_process_name=include_process_name,
                include_rules=frozenset(inclusions),
                exclude_rules=frozenset(exclusions),
                sources=sources,
            )
        )
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


def build_one(
    rule_set: RuleSet,
    timeout: int,
    *,
    enforce_expected_hashes: bool = True,
    fetcher: Callable[[str, int], bytes] = fetch_text,
) -> GeneratedRuleSet:
    entries: dict[str, set[str]] = {rule: {"manifest include_rules"} for rule in rule_set.include_rules}
    source_meta: list[dict[str, Any]] = []
    source_hashes: dict[tuple[str, str], str] = {}

    for source in rule_set.sources:
        raw = fetcher(source.url, timeout)
        sha = hashlib.sha256(raw).hexdigest()
        source_hashes[(rule_set.rule_id, source.name)] = sha
        if enforce_expected_hashes and sha != source.expected_sha256:
            raise SourceHashMismatch(
                f"{rule_set.rule_id}/{source.name}: upstream sha256 changed\n"
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
        source_meta.append(
            {
                "name": source.name,
                "url": source.url,
                "sha256": sha,
                "expected_sha256": sha if not enforce_expected_hashes else source.expected_sha256,
                "license": source.license,
                "license_url": source.license_url,
                "rule_count": len(rules),
            }
        )

    ordered = sorted(entries, key=rule_sort_key)
    lines = [
        f"# NAME: {rule_set.name}",
        f"# ID: {rule_set.rule_id}",
        "# Generated by scripts/generate-managed-surge-rules.py",
        "# Do not edit this file directly unless you intentionally want to fork it.",
    ]
    for wrapped in safe_width_lines(rule_set.description):
        lines.append(f"# {wrapped}")
    lines.extend([f"# Suggested policy: {rule_set.suggested_policy}", "# Sources:"])
    for meta in source_meta:
        lines.append(f"# - {meta['name']}: {meta['url']}")
        lines.append(f"#   sha256: {meta['sha256']}")
        lines.append(f"#   license: {meta['license']} ({meta['license_url']})")
        lines.append(f"#   rules: {meta['rule_count']}")
    if rule_set.include_rules:
        lines.append("# Curated rules moved from overlapping generated sets:")
        for rule in sorted(rule_set.include_rules, key=rule_sort_key):
            lines.append(f"# - {rule}")
    if rule_set.exclude_rules:
        lines.append("# Excluded overlapping rules:")
        for rule in sorted(rule_set.exclude_rules, key=rule_sort_key):
            lines.append(f"# - {rule}")
    lines.extend([f"# Total unique rules: {len(ordered)}", ""])
    lines.extend(ordered)
    list_text = "\n".join(lines).rstrip() + "\n"

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
    return GeneratedRuleSet(
        metadata=metadata,
        list_text=list_text,
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
        "Refresh upstream hashes and snapshots only on a review branch. Inspect the complete diff",
        "and merge it through a PR; this command does not publish anything by itself:",
        "",
        "```bash",
        "scripts/generate-managed-surge-rules.py --refresh-sources",
        "```",
        "",
        "| ID | File | Suggested policy | Unique rules |",
        "| --- | --- | --- | ---: |",
    ]
    for item in generated:
        lines.append(
            f"| {item['id']} | `{Path(item['output']).name}` | `{item['suggested_policy']}` | {item['unique_rule_count']} |"
        )
    return "\n".join(lines) + "\n"


def refreshed_manifest_text(path: Path, source_hashes: dict[tuple[str, str], str]) -> str:
    """Replace only expected_sha256 values while preserving the reviewed manifest layout."""
    lines = path.read_text(encoding="utf-8").splitlines()
    current_set = ""
    current_source = ""
    seen: set[tuple[str, str]] = set()
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if indent == 2 and stripped.startswith("- id:"):
            current_set = stripped.split(":", 1)[1].strip()
            current_source = ""
        elif indent == 6 and stripped.startswith("- name:"):
            current_source = stripped.split(":", 1)[1].strip()
        elif indent == 8 and stripped.startswith("expected_sha256:"):
            key = (current_set, current_source)
            if key not in source_hashes:
                raise ValueError(f"Cannot refresh unrecognized source digest at {current_set}/{current_source}")
            line = f"        expected_sha256: {source_hashes[key]}"
            seen.add(key)
        output.append(line)
    missing = set(source_hashes) - seen
    if missing:
        names = ", ".join(f"{rule_id}/{source}" for rule_id, source in sorted(missing))
        raise ValueError(f"Cannot find expected_sha256 field(s) in manifest: {names}")
    return "\n".join(output) + "\n"


def compare_candidate(path: Path, expected_text: str) -> bool:
    return path.exists() and path.read_text(encoding="utf-8") == expected_text


def write_staged_file(staging_dir: Path, relative_name: str, text: str) -> Path:
    path = staging_dir / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def atomic_replace(staged_path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged_path, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--only", action="append", help="Process only the named rule set id.")
    parser.add_argument("--timeout", type=int, default=30)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="Verify pins and snapshots; never write.")
    modes.add_argument("--update", action="store_true", help="Write snapshots only when all pins match.")
    modes.add_argument(
        "--refresh-sources",
        action="store_true",
        help="Refresh source pins and snapshots for PR review; never use as a production publish step.",
    )
    args = parser.parse_args()

    try:
        generated_dir, all_sets = load_manifest(args.manifest)
        sets = all_sets
        if args.only:
            wanted = set(args.only)
            sets = [rule_set for rule_set in all_sets if rule_set.rule_id in wanted]
            missing = wanted - {rule_set.rule_id for rule_set in sets}
            if missing:
                print(f"Unknown ruleset id(s): {', '.join(sorted(missing))}", file=sys.stderr)
                return 2
        if args.refresh_sources and args.only:
            print("--refresh-sources cannot be combined with --only; refresh must be repository-wide.", file=sys.stderr)
            return 2

        mode = (
            "refresh"
            if args.refresh_sources
            else "update"
            if args.update
            else "check"
        )
        if not args.check and not args.update and not args.refresh_sources:
            print("Defaulting to read-only check mode; pass --update to write reviewed pinned snapshots.")

        generated_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".managed-rules-", dir=generated_dir.parent) as temporary:
            staging_dir = Path(temporary)
            built: list[GeneratedRuleSet] = []
            source_hashes: dict[tuple[str, str], str] = {}
            for rule_set in sets:
                print(f"Fetching {rule_set.rule_id} -> {rule_set.output}")
                item = build_one(
                    rule_set,
                    args.timeout,
                    enforce_expected_hashes=mode != "refresh",
                )
                built.append(item)
                source_hashes.update(item.source_hashes)
                write_staged_file(staging_dir, rule_set.output, item.list_text)
                write_staged_file(staging_dir, f"{rule_set.output}.json", item.metadata_text)

            generated_metadata = [item.metadata for item in built]
            index_items = (
                read_index_metadata(generated_dir, all_sets, generated_metadata)
                if args.only
                else generated_metadata
            )
            readme_text = index_text(index_items)
            write_staged_file(staging_dir, "README.md", readme_text)

            staged_manifest: Path | None = None
            if mode == "refresh":
                manifest_text = refreshed_manifest_text(args.manifest, source_hashes)
                staged_manifest = write_staged_file(staging_dir, "managed-rules.yaml", manifest_text)

            if mode == "check":
                mismatches: list[str] = []
                for rule_set, item in zip(sets, built):
                    if not compare_candidate(generated_dir / rule_set.output, item.list_text):
                        mismatches.append(rule_set.output)
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

            for rule_set in sets:
                atomic_replace(staging_dir / rule_set.output, generated_dir / rule_set.output)
                atomic_replace(staging_dir / f"{rule_set.output}.json", generated_dir / f"{rule_set.output}.json")
            atomic_replace(staging_dir / "README.md", generated_dir / "README.md")

            if mode == "refresh":
                assert staged_manifest is not None
                atomic_replace(staged_manifest, args.manifest)
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
