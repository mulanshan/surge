#!/usr/bin/env python3
"""Regression tests for reproducible managed-rule build inputs."""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "rule/Surge/sources/managed-rules.yaml"
GENERATOR = ROOT / "scripts/generate-managed-surge-rules.py"
RULE_TEMPLATE = ROOT / "rule/Surge/generated/rule-section-managed.conf"
ROOT_README = ROOT / "README.md"
RELEASE_PROCESS = ROOT / "docs/RELEASE_PROCESS.md"
BLACKMATRIX_COMMIT = "86ada72372ec0586be75901f47d5ccca6e28c655"
CLAUDE_SHA256 = "870e7e25d798e7f00338507f773b0eea4dfd15e25e9df0a27d5ae421ae1ab378"


def load_generator():
    spec = importlib.util.spec_from_file_location("managed_source_generator", GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


generator = load_generator()


def minimal_manifest(source_lines: str) -> str:
    return (
        "version: 3\n"
        "generated_dir: rule/Surge/generated\n"
        "sets:\n"
        "  - id: fixture\n"
        "    name: Fixture\n"
        "    description: Fixture\n"
        "    output: fixture.list\n"
        "    suggested_policy: DIRECT\n"
        "    sources:\n"
        "      - name: fixture\n"
        f"{source_lines}"
        f"        expected_sha256: {'a' * 64}\n"
        "        license: MIT\n"
        "        license_url: https://example.invalid/LICENSE\n"
    )


class ManifestInvariantTests(unittest.TestCase):
    def test_all_sources_have_tracking_and_reproducible_build_inputs(self) -> None:
        _generated, sets = generator.load_manifest(MANIFEST)
        sources = [source for rule_set in sets for source in rule_set.sources]
        self.assertEqual(len(sources), 22)
        self.assertTrue(all(source.tracking_url for source in sources))
        self.assertEqual(sum(source.snapshot is not None for source in sources), 7)

        blackmatrix_refs = set()
        for source in sources:
            if source.snapshot is not None:
                path = generator.snapshot_path(source.snapshot, source.name)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source.expected_sha256)
                self.assertIsNone(source.url)
                continue
            self.assertIsNotNone(source.url)
            self.assertTrue(generator.immutable_remote_source(source.url))
            parts = generator.raw_github_parts(source.url)
            self.assertIsNotNone(parts)
            if parts[:2] == ("blackmatrix7", "ios_rule_script"):
                blackmatrix_refs.add(parts[2])
        self.assertEqual(blackmatrix_refs, {BLACKMATRIX_COMMIT})

    def test_claude_routes_use_a_reviewed_generated_source(self) -> None:
        _generated, sets = generator.load_manifest(MANIFEST)
        by_id = {rule_set.rule_id: rule_set for rule_set in sets}
        claude = by_id["claude"]

        self.assertEqual(claude.output, "claude.list")
        self.assertEqual(claude.suggested_policy, "hinet")
        self.assertEqual(claude.suggested_options, ["extended-matching", "no-resolve"])
        self.assertEqual(len(claude.sources), 1)
        source = claude.sources[0]
        self.assertIn(f"/{BLACKMATRIX_COMMIT}/", source.url)
        self.assertIn("/master/", source.tracking_url)
        self.assertEqual(source.expected_sha256, CLAUDE_SHA256)
        self.assertEqual(source.license, "GPL-2.0-only")

        template = RULE_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(
            "RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/"
            "rule/Surge/generated/claude.list,hinet,extended-matching,no-resolve",
            template,
        )
        self.assertNotIn("Claude/Anthropic domains are covered by ai.list", template)

    def test_managed_source_counts_and_claude_docs_stay_current(self) -> None:
        readme = ROOT_README.read_text(encoding="utf-8")
        release_process = RELEASE_PROCESS.read_text(encoding="utf-8")

        self.assertIn("15 个 Blackmatrix 输入", readme)
        self.assertNotIn("14 个 Blackmatrix 输入", readme)
        self.assertIn("generated/claude.list", readme)
        self.assertNotIn("包括 Gemini、Claude、Cursor", readme)
        self.assertIn("all 22 moving tracking URLs", release_process)

    def assert_manifest_error(self, source_lines: str, pattern: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.yaml"
            path.write_text(minimal_manifest(source_lines), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, pattern):
                generator.load_manifest(path)

    def test_moving_remote_url_requires_snapshot(self) -> None:
        self.assert_manifest_error(
            "        url: https://raw.githubusercontent.com/example/project/master/rules.list\n"
            "        tracking_url: https://raw.githubusercontent.com/example/project/main/rules.list\n",
            "remote build input must be",
        )

    def test_url_and_tracking_url_must_differ(self) -> None:
        url = (
            "https://raw.githubusercontent.com/example/project/"
            "0123456789abcdef0123456789abcdef01234567/rules.list"
        )
        self.assert_manifest_error(
            f"        url: {url}\n        tracking_url: {url}\n",
            "url and tracking_url must differ",
        )

    def test_tracking_url_cannot_hide_another_commit_pin(self) -> None:
        build_url = (
            "https://raw.githubusercontent.com/example/project/"
            "0123456789abcdef0123456789abcdef01234567/rules.list"
        )
        tracking_url = (
            "https://raw.githubusercontent.com/example/project/"
            "89abcdef0123456789abcdef0123456789abcdef/rules.list"
        )
        self.assert_manifest_error(
            f"        url: {build_url}\n        tracking_url: {tracking_url}\n",
            "tracking_url must use a moving ref",
        )

    def test_snapshot_cannot_escape_upstream_directory(self) -> None:
        self.assert_manifest_error(
            "        snapshot: ../outside.conf\n"
            "        tracking_url: https://example.invalid/rules.conf\n",
            "snapshot must be a repository-relative path|snapshot must stay under",
        )

    def test_generated_directory_cannot_escape_repository_with_parent_components(self) -> None:
        source = (
            "        url: https://raw.githubusercontent.com/example/project/"
            "0123456789abcdef0123456789abcdef01234567/rules.list\n"
            "        tracking_url: https://raw.githubusercontent.com/example/project/main/rules.list\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.yaml"
            path.write_text(
                minimal_manifest(source).replace(
                    "generated_dir: rule/Surge/generated",
                    "generated_dir: ../outside",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "generated_dir must stay inside"):
                generator.load_manifest(path)


class SnapshotBuildTests(unittest.TestCase):
    def write_snapshot_manifest(self, temporary_root: Path) -> tuple[Path, Path]:
        snapshot = "rule/Surge/upstream/sukka/ip/telegram.conf"
        digest = hashlib.sha256((ROOT / snapshot).read_bytes()).hexdigest()
        generated = temporary_root / "generated"
        manifest = temporary_root / "manifest.yaml"
        manifest.write_text(
            "version: 3\n"
            f"generated_dir: {generated.relative_to(ROOT)}\n"
            "sets:\n"
            "  - id: fixture\n"
            "    name: Fixture\n"
            "    description: Fixture\n"
            "    output: fixture.list\n"
            "    suggested_policy: DIRECT\n"
            "    sources:\n"
            "      - name: fixture\n"
            f"        snapshot: {snapshot}\n"
            "        tracking_url: https://example.invalid/tracking.list\n"
            f"        expected_sha256: {digest}\n"
            "        license: MIT\n"
            "        license_url: https://example.invalid/LICENSE\n",
            encoding="utf-8",
        )
        return manifest, generated

    def test_snapshot_bytes_are_the_build_input_and_hash_gate(self) -> None:
        snapshot = "rule/Surge/upstream/sukka/non_ip/apple_cn.conf"
        raw = (ROOT / snapshot).read_bytes()
        source = generator.Source(
            name="snapshot fixture",
            url=None,
            snapshot=snapshot,
            tracking_url="https://ruleset.skk.moe/List/non_ip/apple_cn.conf",
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            license="AGPL-3.0-only",
            license_url="https://ruleset.skk.moe/LICENSE",
        )
        rule_set = generator.RuleSet(
            rule_id="snapshot-fixture",
            name="Snapshot fixture",
            description="Fixture",
            output="snapshot-fixture.list",
            domain_set_output=None,
            non_domain_output=None,
            suggested_policy="DIRECT",
            suggested_options=[],
            include_process_name=False,
            include_rules=frozenset(),
            exclude_rules=frozenset(),
            sources=[source],
        )

        def no_network(_url: str, _timeout: int) -> bytes:
            raise AssertionError("snapshot build attempted a network request")

        built = generator.build_one(rule_set, 1, fetcher=no_network)
        self.assertIn(f'"snapshot": "{snapshot}"', built.metadata_text)
        with self.assertRaises(generator.SourceHashMismatch):
            generator.build_one(
                dataclasses.replace(
                    rule_set,
                    sources=[dataclasses.replace(source, expected_sha256="0" * 64)],
                ),
                1,
                fetcher=no_network,
            )

    def test_refresh_is_explicit_and_separates_snapshot_from_commit_pin(self) -> None:
        _generated, sets = generator.load_manifest(MANIFEST)
        by_id = {rule_set.rule_id: rule_set for rule_set in sets}

        with self.assertRaisesRegex(ValueError, "--source-commit is required"):
            generator.prepare_refresh(
                [by_id["microsoft"]],
                1,
                source_commit=None,
                fetcher=lambda _url, _timeout: b"unused",
            )

        def mismatched_remote_fetcher(url: str, _timeout: int) -> bytes:
            return b"moving head\n" if "/master/" in url else b"selected commit\n"

        with self.assertRaisesRegex(ValueError, "does not match the current tracking URL"):
            generator.prepare_refresh(
                [by_id["microsoft"]],
                1,
                source_commit=BLACKMATRIX_COMMIT,
                fetcher=mismatched_remote_fetcher,
            )

        pinned_bytes = b"reviewed upstream head\n"
        remote_sets, remote_overrides, _remote_snapshots, remote_urls = generator.prepare_refresh(
            sets,
            1,
            source_commit=BLACKMATRIX_COMMIT,
            selected_rule_ids={"microsoft"},
            fetcher=lambda _url, _timeout: pinned_bytes,
        )
        remote_sources = [
            source for rule_set in remote_sets for source in rule_set.sources if source.url
        ]
        # Derive expectations from the manifest itself instead of a hand-kept
        # ledger that silently rots whenever a set is added or split.
        expected_remote_sources = sum(
            1 for rule_set in sets for source in rule_set.sources if source.url
        )
        self.assertEqual(len(remote_sets), len(sets))
        self.assertGreaterEqual(expected_remote_sources, 1)
        self.assertEqual(len(remote_sources), expected_remote_sources)
        self.assertEqual(len(remote_urls), expected_remote_sources)
        self.assertTrue(
            all(f"/{BLACKMATRIX_COMMIT}/" in source.url for source in remote_sources)
        )
        remote_source = by_id["microsoft"].sources[0]
        self.assertEqual(remote_overrides["microsoft"][remote_source.name], pinned_bytes)
        self.assertIn(
            f"/{BLACKMATRIX_COMMIT}/",
            remote_urls[("microsoft", remote_source.name)],
        )

        snapshot_source = by_id["global"].sources[0]
        snapshot_bytes = (ROOT / snapshot_source.snapshot).read_bytes()
        requested = []

        def snapshot_fetcher(url: str, _timeout: int) -> bytes:
            requested.append(url)
            return snapshot_bytes

        refreshed, overrides, snapshots, urls = generator.prepare_refresh(
            [by_id["global"]],
            1,
            source_commit=None,
            fetcher=snapshot_fetcher,
        )
        self.assertEqual(requested, [snapshot_source.tracking_url])
        self.assertEqual(snapshots[snapshot_source.snapshot], snapshot_bytes)
        self.assertFalse(urls)
        self.assertEqual(overrides["global"][snapshot_source.name], snapshot_bytes)
        self.assertEqual(refreshed[0].sources[0].snapshot, snapshot_source.snapshot)

    def test_refresh_cli_requires_explicit_scope(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--refresh-sources"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires one or more explicit --only", result.stderr)

    def test_check_upstream_cli_uses_a_distinct_drift_exit_code(self) -> None:
        with mock.patch.object(
            generator,
            "check_upstream_tracking",
            return_value=False,
        ):
            with mock.patch.object(
                sys,
                "argv",
                [str(GENERATOR), "--check-upstream", "--only", "microsoft"],
            ):
                self.assertEqual(generator.main(), 3)

    def test_check_mode_does_not_create_a_staging_directory(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            temporary_root = Path(temporary)
            manifest, generated = self.write_snapshot_manifest(temporary_root)
            generated.mkdir()
            _generated_dir, sets = generator.load_manifest(manifest)
            item = generator.build_one(sets[0], 1)
            (generated / sets[0].output).write_text(item.list_text, encoding="utf-8")
            (generated / f"{sets[0].output}.json").write_text(item.metadata_text, encoding="utf-8")
            (generated / "README.md").write_text(generator.index_text([item.metadata]), encoding="utf-8")

            with (
                mock.patch.object(sys, "argv", [str(GENERATOR), "--manifest", str(manifest), "--check"]),
                mock.patch.object(
                    generator.tempfile,
                    "TemporaryDirectory",
                    side_effect=OSError("check mode attempted to create staging"),
                ) as staging,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = generator.main()

            self.assertEqual(result, 0)
            staging.assert_not_called()

    def test_refresh_rolls_back_all_outputs_when_one_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            temporary_root = Path(temporary)
            manifest, generated = self.write_snapshot_manifest(temporary_root)
            generated.mkdir()
            _generated_dir, sets = generator.load_manifest(manifest)
            old_files = {
                generated / "fixture.list": b"old rules\n",
                generated / "fixture.list.json": b"old metadata\n",
                generated / "README.md": b"old index\n",
                manifest: manifest.read_bytes(),
            }
            for path, data in old_files.items():
                path.write_bytes(data)

            original_replace = generator.atomic_replace
            replace_count = 0

            def fail_second_replace(staged_path: Path, destination: Path) -> None:
                nonlocal replace_count
                replace_count += 1
                if replace_count == 2:
                    raise OSError("synthetic replace failure")
                original_replace(staged_path, destination)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        str(GENERATOR),
                        "--manifest",
                        str(manifest),
                        "--refresh-sources",
                        "--only",
                        "fixture",
                    ],
                ),
                mock.patch.object(
                    generator,
                    "prepare_refresh",
                    return_value=(sets, {}, {}, {}),
                ),
                mock.patch.object(generator, "atomic_replace", side_effect=fail_second_replace),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                result = generator.main()

            self.assertEqual(result, 1)
            self.assertIn("synthetic replace failure", stderr.getvalue())
            self.assertGreaterEqual(replace_count, 2)
            for path, data in old_files.items():
                self.assertEqual(path.read_bytes(), data, f"partial refresh changed {path}")


if __name__ == "__main__":
    unittest.main()
