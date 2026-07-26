#!/usr/bin/env python3
"""Focused tests for release-manifest and canonical-module compatibility."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release_verifier = load_module("release_verifier", ROOT / "scripts/verify-surge-release.py")
repository_checker = load_module("repository_checker", ROOT / ".github/scripts/check_repository.py")


def manifest(tag: str, status: str, names: list[str]) -> dict:
    item = {
        "schema_version": 1,
        "tag": tag,
        "status": status,
        "scripts": [
            {
                "name": name,
                "path": release_verifier.EXPECTED[name][1],
                "sha256": "0" * 64,
            }
            for name in names
        ],
    }
    if status == "retired-moved":
        item["observed_tag_commit"] = "1" * 40
    else:
        item["release_commit"] = "1" * 40
    return item


def retired_entry(tag: str = "camscanner-self-v1.0.0", body: str = "⚠️ RETIRED MOVED TAG\n") -> dict:
    return {
        "tag": tag,
        "status": "retired-moved",
        "observed_tag_commit": "2" * 40,
        "release": {
            "name": "Retired release",
            "draft": False,
            "prerelease": True,
            "required_marker": "⚠️ RETIRED MOVED TAG",
            "body_sha256": release_verifier.sha256(body.encode("utf-8")),
        },
    }


def release_record(entry: dict, body: str = "⚠️ RETIRED MOVED TAG\n") -> dict:
    expected = entry["release"]
    return {
        "tag_name": entry["tag"],
        "name": expected["name"],
        "draft": expected["draft"],
        "prerelease": expected["prerelease"],
        "body": body,
    }


class ReleaseManifestTests(unittest.TestCase):
    def load_from(self, manifests: list[dict]) -> dict[str, dict]:
        with tempfile.TemporaryDirectory() as temporary:
            releases = Path(temporary)
            for item in manifests:
                (releases / f"{item['tag']}.json").write_text(json.dumps(item), encoding="utf-8")
            with mock.patch.object(release_verifier, "RELEASES", releases):
                return release_verifier.load_manifests()

    def test_active_six_and_historical_five_are_both_strictly_validated(self) -> None:
        current_names = list(release_verifier.EXPECTED)
        legacy_names = [name for name in current_names if name != "WeChat"]
        manifests = self.load_from(
            [
                manifest("surge-self-v2026.07.13", "retired-moved", legacy_names),
                manifest("surge-self-v2026.07.13.2", "active", current_names),
            ]
        )

        self.assertEqual(
            set(manifests["surge-self-v2026.07.13"]["scripts_by_name"]),
            set(legacy_names),
        )
        self.assertEqual(
            set(manifests["surge-self-v2026.07.13.2"]["scripts_by_name"]),
            set(current_names),
        )

    def test_active_manifest_cannot_use_the_historical_five_script_set(self) -> None:
        legacy_names = [name for name in release_verifier.EXPECTED if name != "WeChat"]
        with self.assertRaisesRegex(SystemExit, "active manifest must list exactly 6 current scripts"):
            self.load_from([manifest("surge-self-v2026.07.13.2", "active", legacy_names)])

    def test_historical_manifest_cannot_mix_old_and_new_script_sets(self) -> None:
        mixed_names = ["YouTube", "Instagram", "Amap", "CamScanner", "WeChat"]
        with self.assertRaisesRegex(SystemExit, "unexpected historical script set"):
            self.load_from(
                [
                    manifest("surge-self-v2026.07.13", "retired-moved", mixed_names),
                    manifest("surge-self-v2026.07.13.2", "active", list(release_verifier.EXPECTED)),
                ]
            )

    def load_retired_from(self, records: list[dict]) -> dict[str, dict]:
        with tempfile.TemporaryDirectory() as temporary:
            releases = Path(temporary)
            (releases / "retired-tags.json").write_text(
                json.dumps({"schema_version": 1, "tags": records}),
                encoding="utf-8",
            )
            with mock.patch.object(release_verifier, "RELEASES", releases):
                return release_verifier.load_retired_tags()

    def test_retired_allowlist_requires_a_full_observed_commit(self) -> None:
        item = retired_entry()
        item["observed_tag_commit"] = "short"
        with self.assertRaisesRegex(SystemExit, "full observed_tag_commit"):
            self.load_retired_from([item])

    def test_release_registry_rejects_manifest_allowlist_overlap(self) -> None:
        tag = "surge-self-v2026.07.13.2"
        with self.assertRaisesRegex(SystemExit, "both release manifests and retired allowlist"):
            release_verifier.validate_release_registry(
                {tag: manifest(tag, "active", list(release_verifier.EXPECTED))},
                {tag: retired_entry(tag)},
            )


class RemoteReleaseIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        active_tag = "surge-self-v2026.07.13.4"
        active = manifest(active_tag, "active", list(release_verifier.EXPECTED))
        active["scripts_by_name"] = {item["name"]: item for item in active["scripts"]}
        self.manifests = {active_tag: active}
        retired = retired_entry()
        self.retired = {retired["tag"]: retired}
        self.expected = set(self.manifests) | set(self.retired)
        self.releases = {tag: {"tag_name": tag} for tag in self.expected}

    def test_github_list_paginates_until_a_short_page(self) -> None:
        first = [{"name": f"tag-{index}"} for index in range(100)]
        second = [{"name": "last"}]
        with mock.patch.object(release_verifier, "github_json", side_effect=[first, second]) as request:
            items = release_verifier.github_list("owner/repo", "tags")
        self.assertEqual(len(items), 101)
        self.assertEqual(
            [call.args[1] for call in request.call_args_list],
            ["tags?per_page=100&page=1", "tags?per_page=100&page=2"],
        )

    def verify_with_registry(self, tags: set[str], releases: dict[str, dict]) -> None:
        with (
            mock.patch.dict("os.environ", {"GITHUB_TOKEN": "synthetic"}),
            mock.patch.object(release_verifier, "remote_release_registry", return_value=(tags, releases)),
            mock.patch.object(release_verifier, "verify_manifest_remote_tag"),
            mock.patch.object(release_verifier, "verify_manifest_release"),
            mock.patch.object(release_verifier, "verify_retired_release"),
        ):
            release_verifier.verify_remote(self.manifests, self.retired, "owner/repo")

    def test_remote_audit_accepts_only_the_exact_closed_set(self) -> None:
        self.verify_with_registry(set(self.expected), dict(self.releases))

    def test_remote_audit_rejects_unknown_and_missing_tags(self) -> None:
        missing = set(self.expected)
        missing.remove(next(iter(missing)))
        with self.assertRaisesRegex(SystemExit, "tag set mismatch; missing"):
            self.verify_with_registry(missing, dict(self.releases))
        with self.assertRaisesRegex(SystemExit, "tag set mismatch;.*unknown"):
            self.verify_with_registry(self.expected | {"rogue-self-v9"}, dict(self.releases))

    def test_remote_audit_rejects_unknown_and_missing_releases(self) -> None:
        missing = dict(self.releases)
        missing.pop(next(iter(missing)))
        with self.assertRaisesRegex(SystemExit, "Release set mismatch; missing"):
            self.verify_with_registry(set(self.expected), missing)
        unknown = {**self.releases, "rogue-self-v9": {"tag_name": "rogue-self-v9"}}
        with self.assertRaisesRegex(SystemExit, "Release set mismatch;.*unknown"):
            self.verify_with_registry(set(self.expected), unknown)

    def test_remote_audit_requires_a_token_for_draft_visibility(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(SystemExit, "requires GITHUB_TOKEN"):
                release_verifier.verify_remote(self.manifests, self.retired, "owner/repo")

    def test_retired_release_checks_commit_metadata_marker_and_body_hash(self) -> None:
        entry = next(iter(self.retired.values()))
        release = release_record(entry)
        with mock.patch.object(
            release_verifier,
            "dereference_remote_tag",
            return_value=entry["observed_tag_commit"],
        ):
            release_verifier.verify_retired_release(entry, release, "owner/repo")

        changed = dict(release)
        changed["body"] = "⚠️ RETIRED MOVED TAG\nchanged\n"
        with mock.patch.object(
            release_verifier,
            "dereference_remote_tag",
            return_value=entry["observed_tag_commit"],
        ):
            with self.assertRaisesRegex(SystemExit, "body changed"):
                release_verifier.verify_retired_release(entry, changed, "owner/repo")

        no_marker = dict(release)
        no_marker["body"] = "retired\n"
        with mock.patch.object(
            release_verifier,
            "dereference_remote_tag",
            return_value=entry["observed_tag_commit"],
        ):
            with self.assertRaisesRegex(SystemExit, "marker missing"):
                release_verifier.verify_retired_release(entry, no_marker, "owner/repo")

        wrong_metadata = dict(release)
        wrong_metadata["draft"] = True
        with mock.patch.object(
            release_verifier,
            "dereference_remote_tag",
            return_value=entry["observed_tag_commit"],
        ):
            with self.assertRaisesRegex(SystemExit, "draft changed"):
                release_verifier.verify_retired_release(entry, wrong_metadata, "owner/repo")

        with mock.patch.object(release_verifier, "dereference_remote_tag", return_value="3" * 40):
            with self.assertRaisesRegex(SystemExit, "moved again"):
                release_verifier.verify_retired_release(entry, release, "owner/repo")

    def test_release_edit_accepts_registered_retired_tag(self) -> None:
        entry = next(iter(self.retired.values()))
        release = release_record(entry)
        with (
            mock.patch.object(release_verifier, "github_json", return_value=release),
            mock.patch.object(
                release_verifier,
                "dereference_remote_tag",
                return_value=entry["observed_tag_commit"],
            ),
        ):
            release_verifier.verify_selected_release({}, self.retired, entry["tag"], "owner/repo")

    def test_tag_push_accepts_only_the_active_manifest(self) -> None:
        active_tag = next(iter(self.manifests))
        with mock.patch.object(release_verifier, "verify_manifest_payload") as verify:
            release_verifier.verify_tag_payload(self.manifests, self.retired, active_tag)
            verify.assert_called_once_with(self.manifests[active_tag], active_tag)

        retired_tag = next(iter(self.retired))
        with self.assertRaisesRegex(SystemExit, "retired and must not be pushed"):
            release_verifier.verify_tag_payload(self.manifests, self.retired, retired_tag)
        with self.assertRaisesRegex(SystemExit, "unregistered release tag"):
            release_verifier.verify_tag_payload(self.manifests, self.retired, "rogue-self-v9")

    def test_workflow_always_uses_the_default_branch_verifier(self) -> None:
        workflow = (ROOT / ".github/workflows/release-integrity.yml").read_text(encoding="utf-8")
        self.assertIn('      - "*-self-v*"', workflow)
        self.assertIn("  create:", workflow)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", workflow)
        self.assertNotIn("github.event_name == 'push' && github.ref", workflow)
        self.assertIn("github.event_name == 'push' || github.event_name == 'create'", workflow)
        # Structural pinning invariant instead of hardcoded version comments
        # (which rot on every dependabot bump): every action reference must be
        # pinned to a full 40-hex commit and carry a version comment.
        uses_lines = [line for line in workflow.splitlines() if "uses:" in line]
        self.assertGreaterEqual(len(uses_lines), 2)
        for line in uses_lines:
            self.assertRegex(line, r"uses: [\w./-]+@[0-9a-f]{40} # v\d", line)


class RepositoryInvariantTests(unittest.TestCase):
    def test_wechat_module_display_name_is_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            module_dir = Path(temporary)
            for file_name, display_name in repository_checker.CANONICAL_MODULE_NAMES.items():
                (module_dir / file_name).write_text(f"#!name={display_name}\n", encoding="utf-8")
            with mock.patch.object(repository_checker, "MODULE_DIR", module_dir):
                repository_checker.check_module_display_names()
                (module_dir / "wechat-self.sgmodule").write_text("#!name=WeChat\n", encoding="utf-8")
                with self.assertRaisesRegex(SystemExit, "unexpected module display name"):
                    repository_checker.check_module_display_names()


if __name__ == "__main__":
    unittest.main()
