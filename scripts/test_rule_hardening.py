#!/usr/bin/env python3
"""Regression tests for managed rules and candidate-export safety gates."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
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
            tracking_url=None,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            license="MIT",
            license_url="https://example.invalid/LICENSE",
        )
        rule_set = generator.RuleSet(
            rule_id="apple-fixture",
            name="Apple fixture",
            description="Fixture",
            output="apple-fixture.list",
            domain_set_output=None,
            non_domain_output=None,
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
version: 3
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

            path.write_text(
                "version: 3\n"
                "generated_dir: rule/Surge/generated\n"
                "sets:\n"
                "  - id: fixture\n"
                "    name: Fixture\n"
                "    description: Fixture\n"
                "    output: fixture.non-domain.list\n"
                "    domain_set_output: fixture.domainset\n"
                "    non_domain_output: fixture.non-domain.list\n"
                "    suggested_policy: DIRECT\n"
                "    sources:\n"
                "      - name: fixture\n"
                "        url: https://example.invalid/rules.list\n"
                f"        expected_sha256: {'0' * 64}\n"
                "        license: MIT\n"
                "        license_url: https://example.invalid/LICENSE\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate id or output"):
                generator.load_manifest(path)

    def test_domain_set_split_preserves_only_exact_and_suffix_domains(self):
        domain_set, non_domain = generator.split_domain_set_entries(
            [
                "DOMAIN,exact.example",
                "DOMAIN-SUFFIX,suffix.example",
                "DOMAIN-KEYWORD,keyword",
                "USER-AGENT,Example*",
                "IP-CIDR,192.0.2.0/24,no-resolve",
            ]
        )
        self.assertEqual(domain_set, ["exact.example", ".suffix.example"])
        self.assertEqual(
            non_domain,
            [
                "DOMAIN-KEYWORD,keyword",
                "USER-AGENT,Example*",
                "IP-CIDR,192.0.2.0/24,no-resolve",
            ],
        )

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

    def test_tracking_url_is_checked_without_becoming_the_build_input(self):
        reviewed = b"DOMAIN,reviewed.example\n"
        upstream = b"DOMAIN,changed.example\n"
        source = generator.Source(
            name="fixture",
            url="https://example.invalid/immutable/rules.list",
            tracking_url="https://example.invalid/main/rules.list",
            expected_sha256=hashlib.sha256(reviewed).hexdigest(),
            license="MIT",
            license_url="https://example.invalid/LICENSE",
        )
        rule_set = generator.RuleSet(
            rule_id="fixture",
            name="Fixture",
            description="Fixture",
            output="fixture.list",
            domain_set_output=None,
            non_domain_output=None,
            suggested_policy="DIRECT",
            suggested_options=[],
            include_process_name=False,
            include_rules=frozenset(),
            exclude_rules=frozenset(),
            sources=[source],
        )

        requested = []

        def fetcher(url, _timeout):
            requested.append(url)
            return upstream

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            current = generator.check_upstream_tracking([rule_set], 1, fetcher=fetcher)
        self.assertFalse(current)
        self.assertIn("Tracking drift: fixture/fixture", stderr.getvalue())
        self.assertEqual(requested, [source.tracking_url])


def optimized_rule_set_counts():
    """Discover optimized (domain-set split) rule sets from generation metadata.

    The generator records domain_set_rule_count / non_domain_rule_count in each
    <id>.list.json. Cross-checking files against that metadata removes the old
    hand-maintained expected-count ledger while keeping the equivalence gate:
    the metadata claims a count, the checked-in files must match it, and the
    split outputs must reconstruct the compatibility list exactly.
    """
    generated = ROOT / "rule/Surge/generated"
    counts = {}
    for meta_path in sorted(generated.glob("*.list.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("domain_set_output"):
            counts[meta["id"]] = (
                meta["domain_set_rule_count"],
                meta["non_domain_rule_count"],
            )
    return counts


class RepositoryInvariantTests(unittest.TestCase):
    def test_optimized_domain_sets_are_equivalent_to_compatibility_rulesets(self):
        expected_counts = optimized_rule_set_counts()
        self.assertGreaterEqual(len(expected_counts), 9)
        generated = ROOT / "rule/Surge/generated"
        for rule_id, (domain_count, residual_count) in expected_counts.items():
            with self.subTest(rule_id=rule_id):
                compatibility = {
                    line
                    for line in (generated / f"{rule_id}.list").read_text(encoding="utf-8").splitlines()
                    if line and not line.startswith("#")
                }
                domain_lines = [
                    line
                    for line in (generated / f"{rule_id}.domainset").read_text(encoding="utf-8").splitlines()
                    if line and not line.startswith("#")
                ]
                residual = {
                    line
                    for line in (generated / f"{rule_id}.non-domain.list").read_text(
                        encoding="utf-8"
                    ).splitlines()
                    if line and not line.startswith("#")
                }
                self.assertEqual(len(domain_lines), domain_count)
                self.assertEqual(len(residual), residual_count)
                self.assertTrue(all("," not in line for line in domain_lines))
                reconstructed = set(residual)
                for line in domain_lines:
                    if line.startswith("."):
                        reconstructed.add(f"DOMAIN-SUFFIX,{line[1:]}")
                    else:
                        reconstructed.add(f"DOMAIN,{line}")
                self.assertEqual(reconstructed, compatibility)

    def test_domain_set_resources_stay_adjacent_with_policy_and_option_parity(self):
        optimized_ids = sorted(optimized_rule_set_counts())
        self.assertGreaterEqual(len(optimized_ids), 9)
        section = (ROOT / "rule/Surge/generated/rule-section-managed.conf").read_text(
            encoding="utf-8"
        )
        rules = [
            line
            for line in section.splitlines()
            if line.startswith(("DOMAIN-SET,", "RULE-SET,"))
        ]
        positions = {}
        for rule_id in optimized_ids:
            with self.subTest(rule_id=rule_id):
                domain_marker = f"/generated/{rule_id}.domainset,"
                residual_marker = f"/generated/{rule_id}.non-domain.list,"
                position = next(i for i, line in enumerate(rules) if domain_marker in line)
                positions[rule_id] = position
                self.assertIn(residual_marker, rules[position + 1])
                domain_parts = rules[position].split(",")
                residual_parts = rules[position + 1].split(",")
                self.assertEqual(domain_parts[2], residual_parts[2])
                self.assertNotIn("no-resolve", domain_parts[3:])
                self.assertEqual(
                    domain_parts[3:],
                    [option for option in residual_parts[3:] if option != "no-resolve"],
                )
                self.assertNotIn(f"/generated/{rule_id}.list,", section)
        # The broad global fallback must stay the last optimized entry.
        self.assertEqual(positions["global"], max(positions.values()))

    def test_domain_rules_precede_ip_rules_in_managed_section(self):
        # Sukka ordering invariant: domain-family rules must all appear before
        # IP-family rules so matching never triggers avoidable DNS resolution.
        section_lines = (
            ROOT / "rule/Surge/generated/rule-section-managed.conf"
        ).read_text(encoding="utf-8").splitlines()
        ip_prefixes = ("IP-CIDR,", "IP-CIDR6,", "IP-ASN,", "GEOIP,")
        domain_prefixes = ("DOMAIN-SET,", "RULE-SET,", "DOMAIN,", "DOMAIN-SUFFIX,", "DOMAIN-KEYWORD,")
        first_ip = next(
            (i for i, line in enumerate(section_lines) if line.startswith(ip_prefixes)),
            len(section_lines),
        )
        last_domain = max(
            (i for i, line in enumerate(section_lines) if line.startswith(domain_prefixes)),
            default=-1,
        )
        self.assertLess(last_domain, first_ip)

    def test_apple_tv_precedes_apple_direct_and_overlap_markers_are_filtered(self):
        section = (ROOT / "rule/Surge/generated/rule-section-managed.conf").read_text(encoding="utf-8")
        for split in ("apple-bm7", "apple-sukka"):
            self.assertLess(
                section.index("generated/apple-tv.list"),
                section.index(f"generated/{split}.list"),
            )
        apple_bm7 = (ROOT / "rule/Surge/generated/apple-bm7.list").read_text(encoding="utf-8")
        for rule in ("PROCESS-NAME,TV", "USER-AGENT,AppleTV*", "USER-AGENT,com.apple.tv*"):
            self.assertNotIn("\n" + rule + "\n", apple_bm7)
        apple_tv = (ROOT / "rule/Surge/generated/apple-tv.list").read_text(encoding="utf-8")
        self.assertIn("\nPROCESS-NAME,TV\n", apple_tv)
        # License separation: each split output must carry exactly one license family.
        apple_sukka = (ROOT / "rule/Surge/generated/apple-sukka.list").read_text(encoding="utf-8")
        self.assertIn("GPL-2.0-only", apple_bm7)
        self.assertNotIn("AGPL-3.0-only", apple_bm7)
        self.assertIn("AGPL-3.0-only", apple_sukka)
        self.assertNotIn("GPL-2.0-only", apple_sukka)

    def test_fanqie_rule_copies_stay_identical(self):
        # Three deployment copies of the same ruleset (Surge canonical, Surge
        # Chinese-named alias, Loon) are maintained by hand; CI must fail the
        # moment their effective rule lines diverge.
        copies = [
            ROOT / "rule/Surge/fanqie-novel-cn.list",
            ROOT / "rule/Surge/番茄小说.list",
            ROOT / "rule/Loon/fanqie-novel-cn.list",
        ]
        payloads = {
            str(path.relative_to(ROOT)): [
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if line and not line.startswith("#")
            ]
            for path in copies
        }
        baseline_name = str(copies[0].relative_to(ROOT))
        for name, lines in payloads.items():
            self.assertEqual(lines, payloads[baseline_name], f"{name} diverged from {baseline_name}")

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
            result = subprocess.run(
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
            self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o700)
            self.assertFalse(list(output_path.glob("*.requests.json")))
            self.assertIn("raw_json=input-not-copied", result.stdout)
            for exported in output_path.iterdir():
                self.assertEqual(stat.S_IMODE(exported.stat().st_mode), 0o600)
        self.assertIn("DOMAIN,ad-foo.fqnovel.com,REJECT", candidates)
        self.assertNotIn("sub.adnxs.com", candidates)

    def test_candidate_exporters_retain_raw_only_when_explicitly_requested(self):
        request_data = '[{"URL":"https://ads.example.test/path","policyName":"DIRECT"}]\n'
        exporters = [
            "export-fanqie-candidates.sh",
            "export-camscanner-candidates.sh",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            input_path = temporary_path / "requests.json"
            input_path.write_text(request_data, encoding="utf-8")
            for exporter in exporters:
                with self.subTest(exporter=exporter):
                    output_path = temporary_path / exporter
                    result = subprocess.run(
                        [
                            str(ROOT / "rule/Surge/scripts" / exporter),
                            "--input",
                            str(input_path),
                            "--out-dir",
                            str(output_path),
                            "--keep-raw",
                        ],
                        cwd=ROOT,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    raw_files = list(output_path.glob("*.requests.json"))
                    self.assertEqual(len(raw_files), 1)
                    self.assertIn(f"raw_json={raw_files[0]}", result.stdout)
                    self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o700)
                    for exported in output_path.iterdir():
                        self.assertEqual(stat.S_IMODE(exported.stat().st_mode), 0o600)

    def test_camscanner_export_never_persists_request_paths(self):
        secret_path = "account/550e8400-e29b-41d4-a716-446655440000/SECRET-TOKEN"
        request_data = (
            '[{"URL":"https://api.camscanner.com/'
            + secret_path
            + '","policyName":"DIRECT"}]\n'
        )
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            input_path = temporary_path / "requests.json"
            output_path = temporary_path / "out"
            input_path.write_text(request_data, encoding="utf-8")
            subprocess.run(
                [
                    str(ROOT / "rule/Surge/scripts/export-camscanner-candidates.sh"),
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
            exported_text = "\n".join(
                path.read_text(encoding="utf-8") for path in output_path.iterdir()
            )
            self.assertNotIn(secret_path, exported_text)
            self.assertNotIn("SECRET-TOKEN", exported_text)

    def test_live_export_uses_verified_stdin_auth_and_deletes_temporary_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            bin_path = temporary_path / "bin"
            log_path = temporary_path / "log"
            tmp_path = temporary_path / "tmp"
            output_path = temporary_path / "out"
            for path in (bin_path, log_path, tmp_path):
                path.mkdir()
            fake_curl = bin_path / "curl"
            fake_curl.write_text(
                "#!/bin/sh\n"
                "config=\"$(cat)\"\n"
                "printf '%s' \"$config\" > \"$SURGE_TEST_LOG/curl.config\"\n"
                "printf '%s' \"$*\" > \"$SURGE_TEST_LOG/curl.args\"\n"
                "printf '%s\\n' '[{\"URL\":\"https://ad-live.fqnovel.com/ad\",\"policyName\":\"DIRECT\"}]'\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o700)
            ios_profile = temporary_path / "DMIT.conf"
            ios_profile.write_text(
                "http-api = synthetic-export-key@0.0.0.0:1132\n",
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "PATH": f"{bin_path}:{os.environ['PATH']}",
                "SURGE_TEST_LOG": str(log_path),
                "TMPDIR": str(tmp_path),
            }
            result = subprocess.run(
                [
                    str(ROOT / "rule/Surge/scripts/export-fanqie-candidates.sh"),
                    "--host",
                    "ios-surge.local",
                    "--profile",
                    str(ios_profile),
                    "--out-dir",
                    str(output_path),
                ],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            config = (log_path / "curl.config").read_text(encoding="utf-8")
            args = (log_path / "curl.args").read_text(encoding="utf-8")
            self.assertIn("synthetic-export-key", config)
            self.assertNotIn("insecure", config)
            self.assertNotIn("synthetic-export-key", args)
            self.assertTrue(args.startswith("-q "), args)
            self.assertIn("raw_json=not-retained", result.stdout)
            self.assertFalse(list(output_path.glob("*.requests.json")))
            self.assertFalse(list(tmp_path.iterdir()))

    def test_local_status_probe_has_no_credentialed_discovery_or_raw_cli_auth(self):
        script = (ROOT / "local-surge-control/scripts/surge-status.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("arp -a", script)
        self.assertNotIn("--remote", script)
        self.assertNotIn("curl -k", script)
        self.assertNotIn("FAIL: ${output}", script)
        self.assertIn("curl -q --noproxy '*' --config -", script)
        self.assertIn("set +x", script)
        self.assertIn("SURGE_IOS_PROFILE", script)
        self.assertIn("SURGE_MAC_PROFILE", script)
        self.assertIn("DMIT-Mac.conf", script)
        self.assertNotIn("wifi-access-http-auth", script)
        for exporter in (
            "export-fanqie-candidates.sh",
            "export-camscanner-candidates.sh",
        ):
            exporter_text = (ROOT / "rule/Surge/scripts" / exporter).read_text(
                encoding="utf-8"
            )
            self.assertIn("curl -q --noproxy '*' --config -", exporter_text)
            self.assertIn("set +x", exporter_text)

    def test_local_status_probe_uses_each_device_profile_key_over_stdin(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            bin_path = temporary_path / "bin"
            log_path = temporary_path / "log"
            bin_path.mkdir()
            log_path.mkdir()
            fake_curl = bin_path / "curl"
            fake_curl.write_text(
                "#!/bin/sh\n"
                "config=\"$(cat)\"\n"
                "case \"$*\" in\n"
                "  *127.0.0.1*) name=mac ;;\n"
                "  *ios-surge.local*) name=ios ;;\n"
                "  *) name=unknown ;;\n"
                "esac\n"
                "printf '%s' \"$config\" > \"$SURGE_TEST_LOG/$name.config\"\n"
                "printf '%s' \"$*\" > \"$SURGE_TEST_LOG/$name.args\"\n"
                "printf '%s\\n' '{\"events\":[]}' '200'\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o700)
            mac_profile = temporary_path / "DMIT-Mac.conf"
            ios_profile = temporary_path / "DMIT.conf"
            mac_profile.write_text(
                "http-api = synthetic-mac-key@127.0.0.1:1132\n",
                encoding="utf-8",
            )
            ios_profile.write_text(
                "http-api = synthetic-ios-key@0.0.0.0:1132\n",
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "PATH": f"{bin_path}:{os.environ['PATH']}",
                "SURGE_TEST_LOG": str(log_path),
                "SURGE_MAC_PROFILE": str(mac_profile),
                "SURGE_IOS_PROFILE": str(ios_profile),
                "SURGE_IOS_HOST": "ios-surge.local",
            }
            result = subprocess.run(
                [str(ROOT / "local-surge-control/scripts/surge-status.sh"), "all"],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("mac   https-http-api         OK", result.stdout)
            self.assertIn("ios   https-http-api         OK", result.stdout)
            mac_config = (log_path / "mac.config").read_text(encoding="utf-8")
            ios_config = (log_path / "ios.config").read_text(encoding="utf-8")
            self.assertIn("synthetic-mac-key", mac_config)
            self.assertNotIn("synthetic-ios-key", mac_config)
            self.assertIn("synthetic-ios-key", ios_config)
            self.assertNotIn("synthetic-mac-key", ios_config)
            self.assertNotIn("synthetic-mac-key", (log_path / "mac.args").read_text())
            self.assertNotIn("synthetic-ios-key", (log_path / "ios.args").read_text())
            self.assertTrue((log_path / "mac.args").read_text().startswith("-q "))
            self.assertTrue((log_path / "ios.args").read_text().startswith("-q "))

    def test_local_status_failure_is_nonzero_and_xtrace_hides_api_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            bin_path = temporary_path / "bin"
            bin_path.mkdir()
            fake_curl = bin_path / "curl"
            fake_curl.write_text(
                "#!/bin/sh\n"
                "cat >/dev/null\n"
                "printf '%s\\n' '{\"events\":[]}' '200'\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o700)
            profile = temporary_path / "DMIT-Mac.conf"
            profile.write_text(
                "http-api = synthetic-xtrace-secret@127.0.0.1:1132\n",
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "PATH": f"{bin_path}:{os.environ['PATH']}",
                "SURGE_MAC_PROFILE": str(profile),
            }
            traced = subprocess.run(
                [
                    "bash",
                    "-x",
                    str(ROOT / "local-surge-control/scripts/surge-status.sh"),
                    "mac",
                ],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertNotIn("synthetic-xtrace-secret", traced.stderr)

            failed = subprocess.run(
                [str(ROOT / "local-surge-control/scripts/surge-status.sh"), "mac"],
                cwd=ROOT,
                env={**env, "SURGE_MAC_PROFILE": str(temporary_path / "missing.conf")},
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(failed.returncode, 1)
            self.assertIn("FAIL: device profile is not readable", failed.stdout)

            invalid_ca = subprocess.run(
                [str(ROOT / "local-surge-control/scripts/surge-status.sh"), "mac"],
                cwd=ROOT,
                env={**env, "SURGE_HTTP_CA": "bad\ninsecure"},
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(invalid_ca.returncode, 2)
            self.assertIn("must not contain a newline", invalid_ca.stderr)


if __name__ == "__main__":
    unittest.main()
