#!/usr/bin/env python3
"""Validate self-hosted modules and checked-in generated-rule metadata."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / "rewrite/Surge"
MANIFEST = ROOT / "rule/Surge/sources/managed-rules.yaml"
GENERATOR = ROOT / "scripts/generate-managed-surge-rules.py"
SCRIPT_PATH_RE = re.compile(r"(?:^|,)script-path=([^,\s]+)")
STABLE_REF_RE = re.compile(r"surge-self-v\d{4}\.\d{2}\.\d{2}")


def fail(message: str) -> None:
    raise SystemExit(message)


def load_generator():
    spec = importlib.util.spec_from_file_location("managed_rules_generator", GENERATOR)
    if spec is None or spec.loader is None:
        fail(f"cannot load generator: {GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def local_path_for_script_url(url: str) -> Path:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme != "https":
        fail(f"script-path must use HTTPS: {url}")

    if parsed.netloc == "raw.githubusercontent.com":
        if len(parts) < 4 or parts[:2] != ["mulanshan", "surge"]:
            fail(f"script-path must be hosted by mulanshan/surge: {url}")
        if not STABLE_REF_RE.fullmatch(parts[2]):
            fail(f"script-path must use an immutable surge-self stable tag: {url}")
        relative = Path(*parts[3:])
    else:
        fail(f"script-path must use raw.githubusercontent.com with a stable tag: {url}")

    if relative.is_absolute() or ".." in relative.parts:
        fail(f"unsafe script-path: {url}")
    return relative


def module_script_targets() -> dict[Path, list[Path]]:
    targets: dict[Path, list[Path]] = {}
    modules = sorted(MODULE_DIR.glob("*.sgmodule"))
    if not modules:
        fail("no Surge modules found")

    for module in modules:
        module_targets: list[Path] = []
        for line in module.read_text(encoding="utf-8").splitlines():
            match = SCRIPT_PATH_RE.search(line)
            if not match:
                continue
            relative = local_path_for_script_url(match.group(1))
            if not (ROOT / relative).is_file():
                fail(f"{module.relative_to(ROOT)} references missing {relative}")
            module_targets.append(relative)
        targets[module] = module_targets
    return targets


def check_compatibility_modules(targets: dict[Path, list[Path]]) -> None:
    instagram = targets.get(MODULE_DIR / "instagram-self.sgmodule", [])
    instagram_legacy = targets.get(MODULE_DIR / "instagram-feed-self.sgmodule", [])
    if instagram != instagram_legacy:
        fail("Instagram compatibility module must use the same local script as Instagram Self")


def rule_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "//", ";"))
    ]


def check_generated_rules() -> None:
    generator = load_generator()
    generated_dir, rule_sets = generator.load_manifest(MANIFEST)
    expected_outputs = {rule_set.output for rule_set in rule_sets}
    actual_outputs = {path.name for path in generated_dir.glob("*.list")}
    missing = sorted(expected_outputs - actual_outputs)
    if missing:
        fail(f"missing generated rulesets: {', '.join(missing)}")

    for rule_set in rule_sets:
        rules_path = generated_dir / rule_set.output
        metadata_path = rules_path.with_suffix(rules_path.suffix + ".json")
        if not metadata_path.is_file():
            fail(f"missing generated metadata: {metadata_path.relative_to(ROOT)}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        expected_output = str(rules_path.relative_to(ROOT))
        if metadata.get("id") != rule_set.rule_id or metadata.get("output") != expected_output:
            fail(f"stale id/output metadata: {metadata_path.relative_to(ROOT)}")

        expected_sources = [(source.name, source.url) for source in rule_set.sources]
        actual_sources = [(source.get("name"), source.get("url")) for source in metadata.get("sources", [])]
        if actual_sources != expected_sources:
            fail(f"manifest/source metadata mismatch: {metadata_path.relative_to(ROOT)}")

        rules = rule_lines(rules_path)
        if len(rules) != len(set(rules)):
            fail(f"duplicate generated rules: {rules_path.relative_to(ROOT)}")
        if metadata.get("unique_rule_count") != len(rules):
            fail(f"generated rule count mismatch: {metadata_path.relative_to(ROOT)}")
        text = rules_path.read_text(encoding="utf-8")
        for source in metadata.get("sources", []):
            sha256 = source.get("sha256", "")
            if not re.fullmatch(r"[0-9a-f]{64}", sha256):
                fail(f"invalid source SHA-256: {metadata_path.relative_to(ROOT)}")
            if f"#   sha256: {sha256}" not in text:
                fail(f"source SHA-256 missing from ruleset header: {rules_path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-only", action="store_true")
    args = parser.parse_args()

    if not args.generated_only:
        targets = module_script_targets()
        check_compatibility_modules(targets)
        script_count = sum(len(items) for items in targets.values())
        print(f"module paths OK: {len(targets)} modules, {script_count} self-hosted script references")

    check_generated_rules()
    print("generated-rule metadata OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
