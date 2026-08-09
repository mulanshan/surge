#!/usr/bin/env python3
"""Validate self-hosted modules and checked-in generated-rule metadata."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / "rewrite/Surge"
MANIFEST = ROOT / "rule/Surge/sources/managed-rules.yaml"
GENERATOR = ROOT / "scripts/generate-managed-surge-rules.py"
WORKFLOW_DIR = ROOT / ".github/workflows"
WORKFLOW_CONTRACT_CHECKER = ROOT / "scripts/check_workflow_contracts.rb"
SCRIPT_PATH_RE = re.compile(r"(?:^|,)script-path=([^,\s]+)")
STABLE_REF_RE = re.compile(r"surge-self-v\d{4}\.\d{2}\.\d{2}(?:\.\d+)?")
ACTION_USE_RE = re.compile(r"^\s*uses:\s*([^\s#]+)")
FULL_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
CANONICAL_MODULE_NAMES = {
    "youtube-self.sgmodule": "YouTube",
    "instagram-self.sgmodule": "Instagram",
    "amap-self.sgmodule": "高德地图",
    "camscanner-self.sgmodule": "扫描全能王",
    "jd-self.sgmodule": "京东",
    "wechat-self.sgmodule": "微信",
}
RETIRED_MODULE_FILES = {
    "instagram-feed-self.sgmodule",
}
# These two frozen files intentionally preserve an old public URL while active
# AI rules are maintained in rule/Surge/ai.list. They are not generator inputs.
GENERATED_COMPATIBILITY_ARTIFACTS = {
    "gemini.list",
    "gemini.list.json",
}


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


def check_module_display_names() -> None:
    for retired_name in sorted(RETIRED_MODULE_FILES):
        if (MODULE_DIR / retired_name).exists():
            fail(f"retired module file still exists: rewrite/Surge/{retired_name}")

    for file_name, expected_name in CANONICAL_MODULE_NAMES.items():
        module = MODULE_DIR / file_name
        if not module.is_file():
            fail(f"missing canonical module: rewrite/Surge/{file_name}")
        first_line = module.read_text(encoding="utf-8").splitlines()[0]
        if first_line != f"#!name={expected_name}":
            fail(f"unexpected module display name in rewrite/Surge/{file_name}: {first_line}")

    for module in sorted(MODULE_DIR.glob("*.sgmodule")):
        first_line = module.read_text(encoding="utf-8").splitlines()[0]
        if not first_line.startswith("#!name="):
            fail(f"module has no display name: {module.relative_to(ROOT)}")
        if "self" in first_line.casefold():
            fail(f"module display name still contains Self: {module.relative_to(ROOT)}")


def check_supply_chain_files() -> None:
    workflows = sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])
    if not workflows:
        fail("no GitHub Actions workflows found")
    for workflow in workflows:
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            match = ACTION_USE_RE.match(line)
            if not match:
                continue
            action = match.group(1)
            if action.startswith("./"):
                continue
            if "@" not in action or not FULL_COMMIT_RE.fullmatch(action.rsplit("@", 1)[1]):
                fail(
                    f"GitHub Action must use a full commit SHA: "
                    f"{workflow.relative_to(ROOT)}:{line_number}: {action}"
                )

    if not WORKFLOW_CONTRACT_CHECKER.is_file():
        fail("missing scripts/check_workflow_contracts.rb")
    try:
        workflow_contracts = subprocess.run(
            ["ruby", str(WORKFLOW_CONTRACT_CHECKER), str(WORKFLOW_DIR)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        fail(f"cannot run structured workflow checker: {exc}")
    if workflow_contracts.returncode:
        fail(
            "structured workflow contract failed: "
            + (workflow_contracts.stderr.strip() or workflow_contracts.stdout.strip())
        )

    if not (ROOT / ".github/dependabot.yml").is_file():
        fail("missing .github/dependabot.yml for pinned Action updates")

    tracking_workflow = WORKFLOW_DIR / "pinned-upstream-drift.yml"
    if not tracking_workflow.is_file() or "--check-upstream" not in tracking_workflow.read_text(
        encoding="utf-8"
    ):
        fail("missing read-only pinned upstream tracking workflow")

    refresh_workflow = WORKFLOW_DIR / "rules-drift.yml"
    refresh_text = refresh_workflow.read_text(encoding="utf-8")
    if re.search(r"(?m)^  schedule:", refresh_text):
        fail("write-capable managed-source refresh workflow must not be scheduled")
    for required in (
        "workflow_dispatch:",
        "rule_set:",
        "source_commit:",
        "BASE_BRANCH: ${{ github.event.repository.default_branch }}",
        "UPDATE_BRANCH: codex/managed-rules-refresh-${{ github.run_id }}-${{ github.run_attempt }}",
        "ref: ${{ github.event.repository.default_branch }}",
        'git switch -c "$UPDATE_BRANCH" "origin/$BASE_BRANCH"',
        'git push origin "HEAD:refs/heads/$UPDATE_BRANCH"',
        '--base "$BASE_BRANCH"',
        '--refresh-sources --only "$RULE_SET"',
        "rule/Surge/upstream/*",
        "printf '`%s`",
    ):
        if required not in refresh_text:
            fail(f"managed-source refresh workflow is missing safety invariant: {required}")
    for forbidden in ("git switch -C", "--force", "gh pr list"):
        if forbidden in refresh_text:
            fail(f"managed-source refresh workflow contains unsafe branch reuse: {forbidden}")
    if re.search(r"<<\s*EOF", refresh_text):
        fail("managed-source refresh workflow contains an unquoted executable heredoc")

    required_licenses = {
        ROOT / "LICENSES/blackmatrix7-ios_rule_script-GPL-2.0-only.txt": (
            "8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643"
        ),
        ROOT / "LICENSES/SukkaW-Surge-AGPL-3.0-only.txt": (
            "8486a10c4393cee1c25392769ddd3b2d6c242d6ec7928e1414efff7dfb2f07ef"
        ),
    }
    missing = sorted(str(path.relative_to(ROOT)) for path in required_licenses if not path.is_file())
    if missing:
        fail(f"missing bundled third-party license text: {', '.join(missing)}")
    for path, expected_sha256 in required_licenses.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_sha256:
            fail(f"bundled third-party license text changed: {path.relative_to(ROOT)}")


def rule_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "//", ";"))
    ]


def check_generated_rules() -> None:
    generator = load_generator()
    generated_dir, rule_sets = generator.load_manifest(MANIFEST)
    expected_outputs = {
        "README.md",
        "rule-section-managed.conf",
        *GENERATED_COMPATIBILITY_ARTIFACTS,
    }
    for rule_set in rule_sets:
        expected_outputs.add(rule_set.output)
        expected_outputs.add(f"{rule_set.output}.json")
        if rule_set.domain_set_output is not None and rule_set.non_domain_output is not None:
            expected_outputs.update([rule_set.domain_set_output, rule_set.non_domain_output])
    symlinks = sorted(path.name for path in generated_dir.iterdir() if path.is_symlink())
    if symlinks:
        fail("generated artifacts must be regular files, not symlinks: " + ", ".join(symlinks))
    unexpected_entries = sorted(path.name for path in generated_dir.iterdir() if not path.is_file())
    if unexpected_entries:
        fail(
            "generated directory must be flat; unexpected non-file entry(s): "
            + ", ".join(unexpected_entries)
        )
    actual_outputs = {path.name for path in generated_dir.iterdir() if path.is_file()}
    unregistered = sorted(actual_outputs - expected_outputs)
    if unregistered:
        fail(f"unregistered generated artifact(s): {', '.join(unregistered)}")
    missing = sorted(name for name in expected_outputs if not (generated_dir / name).is_file())
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

        expected_domain_set_output = (
            str((generated_dir / rule_set.domain_set_output).relative_to(ROOT))
            if rule_set.domain_set_output
            else None
        )
        expected_non_domain_output = (
            str((generated_dir / rule_set.non_domain_output).relative_to(ROOT))
            if rule_set.non_domain_output
            else None
        )
        if metadata.get("domain_set_output") != expected_domain_set_output:
            fail(f"stale DOMAIN-SET metadata: {metadata_path.relative_to(ROOT)}")
        if metadata.get("non_domain_output") != expected_non_domain_output:
            fail(f"stale residual ruleset metadata: {metadata_path.relative_to(ROOT)}")

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
        artifact_texts = [text]
        if rule_set.domain_set_output is not None and rule_set.non_domain_output is not None:
            domain_path = generated_dir / rule_set.domain_set_output
            residual_path = generated_dir / rule_set.non_domain_output
            domain_lines = rule_lines(domain_path)
            residual_lines = rule_lines(residual_path)
            if any("," in line for line in domain_lines):
                fail(f"invalid DOMAIN-SET entry: {domain_path.relative_to(ROOT)}")
            reconstructed = set(residual_lines)
            for line in domain_lines:
                reconstructed.add(
                    f"DOMAIN-SUFFIX,{line[1:]}" if line.startswith(".") else f"DOMAIN,{line}"
                )
            if reconstructed != set(rules):
                fail(f"optimized split is not equivalent: {rules_path.relative_to(ROOT)}")
            if metadata.get("domain_set_rule_count") != len(domain_lines):
                fail(f"DOMAIN-SET count mismatch: {metadata_path.relative_to(ROOT)}")
            if metadata.get("non_domain_rule_count") != len(residual_lines):
                fail(f"residual rule count mismatch: {metadata_path.relative_to(ROOT)}")
            artifact_texts.extend(
                [
                    domain_path.read_text(encoding="utf-8"),
                    residual_path.read_text(encoding="utf-8"),
                ]
            )
        for source in metadata.get("sources", []):
            sha256 = source.get("sha256", "")
            if not re.fullmatch(r"[0-9a-f]{64}", sha256):
                fail(f"invalid source SHA-256: {metadata_path.relative_to(ROOT)}")
            if any(f"#   sha256: {sha256}" not in artifact for artifact in artifact_texts):
                fail(f"source SHA-256 missing from generated artifact header: {rules_path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-only", action="store_true")
    args = parser.parse_args()

    if not args.generated_only:
        check_module_display_names()
        check_supply_chain_files()
        targets = module_script_targets()
        script_count = sum(len(items) for items in targets.values())
        print(f"module paths OK: {len(targets)} modules, {script_count} self-hosted script references")

    check_generated_rules()
    print("generated-rule metadata OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
