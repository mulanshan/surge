#!/usr/bin/env python3
"""Regression tests for managed rules and candidate-export safety gates."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


generator = load_module("managed_rule_generator", ROOT / "scripts/generate-managed-surge-rules.py")
common = load_module(
    "surge_candidate_common",
    ROOT / "rule/Surge/scripts/surge_candidate_common.py",
)


class GeneratorTests(unittest.TestCase):
    def test_ip_cidr_case_is_canonical_and_no_resolve_is_added(self):
        expected = "IP-CIDR,192.0.2.0/24,no-resolve"
        self.assertEqual(generator.normalize_rule_line("IP-CIDR,192.0.2.0/24"), expected)
        self.assertEqual(generator.normalize_rule_line("ip-cidr,192.0.2.0/24"), expected)

    def test_policy_and_unknown_options_are_rejected(self):
        for line in ("DOMAIN,example.com,DIRECT", "DOMAIN,example.com,unknown"):
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, "policy"):
                generator.normalize_rule_line(line)

    def test_source_hash_is_a_hard_gate_and_exclusions_apply(self):
        raw = b"PROCESS-NAME,TV\nUSER-AGENT,AppleTV*\nDOMAIN,tv.apple.com\n"
        source = generator.Source(
            name="fixture",
            url="https://example.invalid/rules.list",
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            license="MIT",
            license_url="https://example.invalid/LICENSE",
        )
        rule_set = generator.RuleSet(
            rule_id="apple-fixture",
            name="Apple fixture",
            description="Fixture",
            output="apple-fixture.list",
            suggested_policy="DIRECT",
            suggested_options=[],
            include_process_name=True,
            include_rules=frozenset(),
            exclude_rules=frozenset({"PROCESS-NAME,TV", "USER-AGENT,AppleTV*"}),
            sources=[source],
        )
        built = generator.build_one(rule_set, 1, fetcher=lambda _url, _timeout: raw)
        self.assertIn("DOMAIN,tv.apple.com", built.list_text)
        self.assertNotIn("\nPROCESS-NAME,TV\n", built.list_text)
        self.assertNotIn("\nUSER-AGENT,AppleTV*\n", built.list_text)

        changed = raw + b"DOMAIN,unexpected.example\n"
        with self.assertRaises(generator.SourceHashMismatch):
            generator.build_one(rule_set, 1, fetcher=lambda _url, _timeout: changed)

    def test_manifest_schema_rejects_unknown_fields_and_options(self):
        template = """\
version: 2
generated_dir: rule/Surge/generated
sets:
  - id: fixture
    name: Fixture
    description: Fixture
    output: fixture.list
    suggested_policy: DIRECT
    suggested_options:
      - {option}
    {unknown}
    sources:
      - name: fixture
        url: https://example.invalid/rules.list
        expected_sha256: {sha}
        license: MIT
        license_url: https://example.invalid/LICENSE
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.yaml"
            path.write_text(
                template.format(option="no-resolve", unknown="mystery: true", sha="0" * 64),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unknown field"):
                generator.load_manifest(path)
            path.write_text(
                template.format(option="mystery-option", unknown="# no unknown field", sha="0" * 64),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "suggested_options"):
                generator.load_manifest(path)

    def test_refresh_changes_only_expected_digest_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.yaml"
            path.write_text(
                "sets:\n"
                "  - id: fixture\n"
                "    sources:\n"
                "      - name: upstream\n"
                f"        expected_sha256: {'0' * 64}\n"
                "        license: MIT\n",
                encoding="utf-8",
            )
            refreshed = generator.refreshed_manifest_text(
                path, {("fixture", "upstream"): "a" * 64}
            )
        self.assertIn(f"expected_sha256: {'a' * 64}", refreshed)
        self.assertIn("license: MIT", refreshed)


class RepositoryInvariantTests(unittest.TestCase):
    def test_apple_tv_precedes_apple_direct_and_overlap_markers_are_filtered(self):
        section = (ROOT / "rule/Surge/generated/rule-section-managed.conf").read_text(encoding="utf-8")
        self.assertLess(section.index("generated/apple-tv.list"), section.index("generated/apple.list"))
        apple = (ROOT / "rule/Surge/generated/apple.list").read_text(encoding="utf-8")
        for rule in ("PROCESS-NAME,TV", "USER-AGENT,AppleTV*", "USER-AGENT,com.apple.tv*"):
            self.assertNotIn("\n" + rule + "\n", apple)
        apple_tv = (ROOT / "rule/Surge/generated/apple-tv.list").read_text(encoding="utf-8")
        self.assertIn("\nPROCESS-NAME,TV\n", apple_tv)

    def test_fanqie_compatibility_list_matches_safe_basic_subset(self):
        basic_lines = (ROOT / "rewrite/Surge/basic-adblock.sgmodule").read_text(encoding="utf-8").splitlines()
        expected = {
            ",".join(line.split(",")[:2])
            for line in basic_lines
            if line.startswith("DOMAIN,") and line.split(",")[1].endswith(".fqnovel.com")
        }
        compatibility = {
            line
            for line in (ROOT / "rule/Surge/fanqie-novel-adblock.list").read_text(encoding="utf-8").splitlines()
            if line.startswith("DOMAIN,")
        }
        self.assertEqual(compatibility, expected)

    def test_domain_suffix_matching_is_shared_and_subdomain_safe(self):
        rules = [("DOMAIN-SUFFIX", "adnxs.com")]
        self.assertTrue(common.matches_existing("adnxs.com", rules))
        self.assertTrue(common.matches_existing("sub.adnxs.com", rules))
        self.assertFalse(common.matches_existing("notadnxs.com", rules))

    def test_fanqie_export_emits_three_field_rules_and_honors_suffixes(self):
        request_data = """[
          {"URL": "https://sub.adnxs.com/ad", "policyName": "DIRECT"},
          {"URL": "https://ad-foo.fqnovel.com/ad", "policyName": "DIRECT"}
        ]
        """
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            input_path = temporary_path / "requests.json"
            output_path = temporary_path / "out"
            input_path.write_text(request_data, encoding="utf-8")
            subprocess.run(
                [
                    str(ROOT / "rule/Surge/scripts/export-fanqie-candidates.sh"),
                    "--input",
                    str(input_path),
                    "--out-dir",
                    str(output_path),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            candidates = next(output_path.glob("*.candidate-rules.list")).read_text(encoding="utf-8")
        self.assertIn("DOMAIN,ad-foo.fqnovel.com,REJECT", candidates)
        self.assertNotIn("sub.adnxs.com", candidates)


if __name__ == "__main__":
    unittest.main()
