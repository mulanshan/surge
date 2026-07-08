#!/usr/bin/env python3
"""Generate personal Surge rulesets from selected upstream rules."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sys
import textwrap
import urllib.request
from pathlib import Path
from typing import Any


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

MARKER_PATTERNS = (
    re.compile(r"rul35et", re.IGNORECASE),
    re.compile(r"mad3_by_5ukk4w", re.IGNORECASE),
)


@dataclasses.dataclass
class Source:
    name: str
    url: str


@dataclasses.dataclass
class RuleSet:
    rule_id: str
    name: str
    description: str
    output: str
    suggested_policy: str
    suggested_options: list[str]
    include_process_name: bool
    sources: list[Source]


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value in {"true", "false"}:
        return value == "true"
    return value


def parse_simple_yaml(path: Path) -> dict[str, Any]:
    """Parse the limited YAML shape used by managed-rules.yaml.

    This avoids introducing a dependency just to read a small manifest. It
    supports top-level scalars and a `sets` array with nested `sources` and
    `suggested_options` arrays.
    """
    result: dict[str, Any] = {"sets": []}
    current_set: dict[str, Any] | None = None
    current_key: str | None = None
    current_source: dict[str, Any] | None = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))

        if indent == 0 and stripped.startswith("sets:"):
            continue
        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            result[key] = parse_scalar(value)
            continue

        if indent == 2 and stripped.startswith("- "):
            current_set = {"sources": [], "suggested_options": []}
            result["sets"].append(current_set)
            current_key = None
            item = stripped[2:]
            if ":" in item:
                key, value = item.split(":", 1)
                current_set[key] = parse_scalar(value)
            continue

        if current_set is None:
            raise ValueError(f"Unexpected manifest line: {raw}")

        if indent == 4 and stripped.endswith(":"):
            current_key = stripped[:-1]
            if current_key not in current_set:
                current_set[current_key] = []
            continue

        if indent == 4 and ":" in stripped:
            key, value = stripped.split(":", 1)
            current_set[key] = parse_scalar(value)
            current_key = None
            continue

        if indent == 6 and stripped.startswith("- "):
            item = stripped[2:]
            if current_key == "sources":
                current_source = {}
                current_set["sources"].append(current_source)
                if ":" in item:
                    key, value = item.split(":", 1)
                    current_source[key] = parse_scalar(value)
            elif current_key == "suggested_options":
                current_set["suggested_options"].append(parse_scalar(item))
            else:
                raise ValueError(f"Unexpected list line: {raw}")
            continue

        if indent == 8 and current_key == "sources" and current_source is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current_source[key] = parse_scalar(value)
            continue

        raise ValueError(f"Unsupported manifest line: {raw}")

    return result


def load_manifest(path: Path) -> tuple[Path, list[RuleSet]]:
    data = parse_simple_yaml(path)
    generated_dir = ROOT / str(data["generated_dir"])
    sets: list[RuleSet] = []
    for item in data["sets"]:
        sources = [Source(name=s["name"], url=s["url"]) for s in item["sources"]]
        sets.append(
            RuleSet(
                rule_id=item["id"],
                name=item["name"],
                description=item["description"],
                output=item["output"],
                suggested_policy=item["suggested_policy"],
                suggested_options=list(item.get("suggested_options", [])),
                include_process_name=bool(item.get("include_process_name", False)),
                sources=sources,
            )
        )
    return generated_dir, sets


def fetch_text(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "mulanshan-surge-rule-generator/1.0",
            "Accept": "text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def normalize_rule_line(line: str, *, include_process_name: bool = False) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith(("#", "//", ";", "[", "payload:", "- ")):
        return None
    if stripped.startswith("IP-CIDR,") and "," not in stripped[len("IP-CIDR,") :]:
        return stripped

    rule_type = stripped.split(",", 1)[0].strip().upper()
    if rule_type == "PROCESS-NAME" and include_process_name:
        parts = [part.strip() for part in stripped.split(",")]
        if len(parts) < 2 or not parts[1]:
            return None
        parts[0] = rule_type
        return ",".join(parts)
    if rule_type not in ALLOWED_RULES:
        return None
    parts = [part.strip() for part in stripped.split(",")]
    if len(parts) < 2 or not parts[1]:
        return None
    if any(pattern.search(parts[1]) for pattern in MARKER_PATTERNS):
        return None
    parts[0] = rule_type
    if rule_type in {"IP-CIDR", "IP-CIDR6"} and len(parts) == 2:
        parts.append("no-resolve")
    return ",".join(parts)


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


def generate_one(rule_set: RuleSet, output_dir: Path, timeout: int) -> dict[str, Any]:
    entries: dict[str, set[str]] = {}
    source_meta: list[dict[str, Any]] = []

    for source in rule_set.sources:
        raw = fetch_text(source.url, timeout=timeout)
        sha = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8-sig", errors="replace")
        rules: set[str] = set()
        for line in text.splitlines():
            normalized = normalize_rule_line(line, include_process_name=rule_set.include_process_name)
            if normalized:
                rules.add(normalized)
                entries.setdefault(normalized, set()).add(source.name)
        source_meta.append(
            {
                "name": source.name,
                "url": source.url,
                "sha256": sha,
                "rule_count": len(rules),
            }
        )

    ordered = sorted(entries, key=rule_sort_key)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / rule_set.output
    metadata_path = output_path.with_suffix(output_path.suffix + ".json")

    lines = [
        f"# NAME: {rule_set.name}",
        f"# ID: {rule_set.rule_id}",
        "# Generated by scripts/generate-managed-surge-rules.py",
        "# Do not edit this file directly unless you intentionally want to fork it.",
    ]
    for wrapped in safe_width_lines(rule_set.description):
        lines.append(f"# {wrapped}")
    lines.extend(
        [
            f"# Suggested policy: {rule_set.suggested_policy}",
            "# Sources:",
        ]
    )
    for meta in source_meta:
        lines.append(f"# - {meta['name']}: {meta['url']}")
        lines.append(f"#   sha256: {meta['sha256']}")
        lines.append(f"#   rules: {meta['rule_count']}")
    lines.append(f"# Total unique rules: {len(ordered)}")
    lines.append("")
    lines.extend(ordered)
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    metadata = {
        "id": rule_set.rule_id,
        "name": rule_set.name,
        "output": str(output_path.relative_to(ROOT)),
        "description": rule_set.description,
        "suggested_policy": rule_set.suggested_policy,
        "suggested_options": rule_set.suggested_options,
        "unique_rule_count": len(ordered),
        "sources": source_meta,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


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
            continue
        items.append(load_metadata(output_dir / f"{rule_set.output}.json"))
    return items


def write_index(output_dir: Path, generated: list[dict[str, Any]]) -> None:
    lines = [
        "# Generated Surge Rules",
        "",
        "These files are generated mirrors of selected upstream rulesets.",
        "Each `.list` file is a Surge RULE-SET file without policy decisions.",
        "",
        "Regenerate:",
        "",
        "```bash",
        "scripts/generate-managed-surge-rules.py",
        "```",
        "",
        "| ID | File | Suggested policy | Unique rules |",
        "| --- | --- | --- | ---: |",
    ]
    for item in generated:
        lines.append(
            f"| {item['id']} | `{Path(item['output']).name}` | `{item['suggested_policy']}` | {item['unique_rule_count']} |"
        )
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--only", action="append", help="Generate only the named rule set id.")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    generated_dir, all_sets = load_manifest(args.manifest)
    sets = all_sets
    if args.only:
        wanted = set(args.only)
        sets = [rule_set for rule_set in all_sets if rule_set.rule_id in wanted]
        missing = wanted - {rule_set.rule_id for rule_set in sets}
        if missing:
            print(f"Unknown ruleset id(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    generated = []
    for rule_set in sets:
        print(f"Generating {rule_set.rule_id} -> {rule_set.output}")
        generated.append(generate_one(rule_set, generated_dir, timeout=args.timeout))
    if args.only:
        index_items = read_index_metadata(generated_dir, all_sets, generated)
    else:
        index_items = generated
    write_index(generated_dir, index_items)
    print(f"Wrote {len(generated)} rulesets to {generated_dir.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
