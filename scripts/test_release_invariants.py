#!/usr/bin/env python3
"""Focused tests for release-manifest and canonical-module compatibility."""

from __future__ import annotations

import importlib.util
import json
import subprocess
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
    distribution = {
        "retired-moved": "retired",
        "superseded": "inactive",
    }.get(status, status)
    item = {
        "schema_version": 2,
        "tag": tag,
        "integrity": "retired-moved" if status == "retired-moved" else "intact",
        "distribution": distribution,
        "live_device_validation": (
            "pending"
            if distribution == "candidate"
            else "passed"
            if distribution == "active"
            else "not-recorded"
        ),
        "rollback_eligible": False,
        "scripts": [
            {
                "name": name,
                "path": release_verifier.EXPECTED[name][1],
                "sha256": "0" * 64,
            }
            for name in names
        ],
    }
    if distribution == "retired":
        item["observed_tag_commit"] = "1" * 40
    else:
        item["release_commit"] = "1" * 40
    if item["live_device_validation"] in {"passed", "failed"}:
        evidence = "docs/MODULE_STATUS.md#current-ios-rollout-evidence"
        item["live_device_evidence"] = evidence
        item["live_device_evidence_sha256"] = release_verifier.evidence_sha256(evidence)
    return item


def lifecycle_manifest(
    tag: str,
    distribution: str,
    names: list[str],
    *,
    release_commit: str | None = "1" * 40,
    live_device_validation: str = "not-recorded",
    rollback_eligible: bool = False,
    supersedes: str | None = None,
    superseded_by: str | None = None,
) -> dict:
    item = {
        "schema_version": 2,
        "tag": tag,
        "integrity": "intact",
        "distribution": distribution,
        "live_device_validation": live_device_validation,
        "rollback_eligible": rollback_eligible,
        "scripts": [
            {
                "name": name,
                "path": release_verifier.EXPECTED[name][1],
                "sha256": "0" * 64,
            }
            for name in names
        ],
    }
    if release_commit is not None:
        item["release_commit"] = release_commit
    if live_device_validation in {"passed", "failed"}:
        evidence = "docs/MODULE_STATUS.md#current-ios-rollout-evidence"
        item["live_device_evidence"] = evidence
        item["live_device_evidence_sha256"] = release_verifier.evidence_sha256(evidence)
    if rollback_eligible:
        evidence = (
            "docs/MODULE_STATUS.md#rollback-certification-evidence-for-"
            "surge-self-v202607134"
        )
        item["rollback_evidence"] = evidence
        item["rollback_evidence_sha256"] = release_verifier.evidence_sha256(evidence)
    if supersedes is not None:
        item["supersedes"] = supersedes
    if superseded_by is not None:
        item["superseded_by"] = superseded_by
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
    def load_from(
        self,
        manifests: list[dict],
        *,
        check_live_evidence: bool = False,
    ) -> dict[str, dict]:
        with tempfile.TemporaryDirectory() as temporary:
            releases = Path(temporary)
            for item in manifests:
                (releases / f"{item['tag']}.json").write_text(json.dumps(item), encoding="utf-8")
            with mock.patch.object(release_verifier, "RELEASES", releases):
                if check_live_evidence:
                    return release_verifier.load_manifests()
                with mock.patch.object(release_verifier, "validate_live_device_evidence"):
                    return release_verifier.load_manifests()

    def test_active_six_and_historical_five_are_both_strictly_validated(self) -> None:
        current_names = list(release_verifier.EXPECTED)
        legacy_names = [name for name in current_names if name != "WeChat"]
        retired = manifest("surge-self-v2026.07.13", "retired-moved", legacy_names)
        active = manifest("surge-self-v2026.07.13.2", "active", current_names)
        retired["superseded_by"] = active["tag"]
        active["supersedes"] = retired["tag"]
        manifests = self.load_from(
            [retired, active]
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

    def test_release_manifest_tag_requires_ascii_digits(self) -> None:
        unicode_tag = "surge-self-v٢٠٢٦.٠٧.١٣"
        item = manifest(unicode_tag, "active", list(release_verifier.EXPECTED))
        with self.assertRaisesRegex(SystemExit, "invalid tag/filename"):
            self.load_from([item])

    def test_historical_manifest_cannot_mix_old_and_new_script_sets(self) -> None:
        mixed_names = ["YouTube", "Instagram", "Amap", "CamScanner", "WeChat"]
        retired = manifest("surge-self-v2026.07.13", "retired-moved", mixed_names)
        active = manifest(
            "surge-self-v2026.07.13.2", "active", list(release_verifier.EXPECTED)
        )
        retired["superseded_by"] = active["tag"]
        active["supersedes"] = retired["tag"]
        with self.assertRaisesRegex(SystemExit, "unexpected historical script set"):
            self.load_from([retired, active])

    def test_retired_manifest_may_retain_a_nonempty_explanatory_note(self) -> None:
        names = [name for name in release_verifier.EXPECTED if name != "WeChat"]
        retired = manifest("surge-self-v2026.07.13", "retired-moved", names)
        active = manifest(
            "surge-self-v2026.07.13.1", "active", list(release_verifier.EXPECTED)
        )
        retired["note"] = "This moved tag must never be reused."
        retired["superseded_by"] = active["tag"]
        active["supersedes"] = retired["tag"]
        manifests = self.load_from([retired, active])
        self.assertEqual(manifests[retired["tag"]]["note"], retired["note"])

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

    def test_candidate_manifest_can_be_pre_registered_before_tag_commit_exists(self) -> None:
        current_names = list(release_verifier.EXPECTED)
        active_tag = "surge-self-v2026.07.13.4"
        candidate_tag = "surge-self-v2026.08.08"
        candidate = lifecycle_manifest(
            candidate_tag,
            "candidate",
            current_names,
            release_commit=None,
            live_device_validation="pending",
            supersedes=active_tag,
        )
        active = lifecycle_manifest(
            active_tag,
            "active",
            current_names,
            live_device_validation="passed",
            rollback_eligible=False,
        )
        manifests = self.load_from([active, candidate])
        self.assertEqual(manifests[candidate_tag]["distribution"], "candidate")
        self.assertNotIn("release_commit", manifests[candidate_tag])

    def test_candidate_records_live_validation_before_distribution_activation(self) -> None:
        names = list(release_verifier.EXPECTED)
        active_tag = "surge-self-v2026.07.13.4"
        active = lifecycle_manifest(
            active_tag,
            "active",
            names,
            live_device_validation="passed",
        )
        for validation in ("passed", "failed"):
            with self.subTest(validation=validation):
                candidate = lifecycle_manifest(
                    "surge-self-v2026.08.08",
                    "candidate",
                    names,
                    live_device_validation=validation,
                    supersedes=active_tag,
                )
                manifests = self.load_from([active, candidate])
                self.assertEqual(
                    manifests[candidate["tag"]]["live_device_validation"], validation
                )

    def test_candidate_cannot_record_a_device_result_before_commit_registration(self) -> None:
        names = list(release_verifier.EXPECTED)
        active_tag = "surge-self-v2026.07.13.4"
        active = lifecycle_manifest(
            active_tag,
            "active",
            names,
            live_device_validation="passed",
        )
        candidate = lifecycle_manifest(
            "surge-self-v2026.08.08",
            "candidate",
            names,
            release_commit=None,
            live_device_validation="passed",
            supersedes=active_tag,
        )
        with self.assertRaisesRegex(SystemExit, "device result requires release_commit"):
            self.load_from([active, candidate])

    def test_future_active_distribution_requires_passed_live_validation(self) -> None:
        active = lifecycle_manifest(
            "surge-self-v2026.08.08",
            "active",
            list(release_verifier.EXPECTED),
            live_device_validation="pending",
        )
        with self.assertRaisesRegex(SystemExit, "active distribution requires.*passed"):
            self.load_from([active])

    def test_only_the_recorded_legacy_distribution_may_remain_active_pending(self) -> None:
        active = lifecycle_manifest(
            "surge-self-v2026.07.27.1",
            "active",
            list(release_verifier.EXPECTED),
            live_device_validation="pending",
        )
        active["legacy_unvalidated_activation"] = True
        manifests = self.load_from([active])
        self.assertTrue(manifests[active["tag"]]["legacy_unvalidated_activation"])

    def test_failed_tagged_candidate_can_be_rejected_before_the_next_candidate(self) -> None:
        names = list(release_verifier.EXPECTED)
        active_tag = "surge-self-v2026.07.13.4"
        rejected_tag = "surge-self-v2026.08.08"
        next_tag = "surge-self-v2026.08.08.1"
        active = lifecycle_manifest(
            active_tag,
            "active",
            names,
            live_device_validation="passed",
            superseded_by=rejected_tag,
        )
        rejected = lifecycle_manifest(
            rejected_tag,
            "rejected",
            names,
            live_device_validation="failed",
            supersedes=active_tag,
        )
        candidate = lifecycle_manifest(
            next_tag,
            "candidate",
            names,
            release_commit=None,
            live_device_validation="pending",
            supersedes=rejected_tag,
        )
        manifests = self.load_from([active, rejected, candidate])
        self.assertEqual(manifests[rejected_tag]["distribution"], "rejected")

    def test_tagged_candidate_can_be_rejected_without_faking_a_device_failure(self) -> None:
        names = list(release_verifier.EXPECTED)
        active_tag = "surge-self-v2026.07.13.4"
        rejected_tag = "surge-self-v2026.08.08"
        for validation in ("pending", "passed"):
            with self.subTest(validation=validation):
                active = lifecycle_manifest(
                    active_tag,
                    "active",
                    names,
                    live_device_validation="passed",
                    superseded_by=rejected_tag,
                )
                rejected = lifecycle_manifest(
                    rejected_tag,
                    "rejected",
                    names,
                    live_device_validation=validation,
                    supersedes=active_tag,
                )
                manifests = self.load_from([active, rejected])
                self.assertEqual(
                    manifests[rejected_tag]["live_device_validation"], validation
                )

    def test_manifest_requires_explicit_live_validation_and_rollback_state(self) -> None:
        current_names = list(release_verifier.EXPECTED)
        item = manifest("surge-self-v2026.07.13.2", "active", current_names)
        del item["live_device_validation"]
        del item["rollback_eligible"]
        with self.assertRaisesRegex(SystemExit, "live_device_validation"):
            self.load_from([item])

    def test_passed_or_failed_validation_requires_repository_evidence(self) -> None:
        for validation, distribution in (("passed", "active"), ("failed", "rejected")):
            with self.subTest(validation=validation):
                active_tag = (
                    "surge-self-v2026.08.08"
                    if distribution == "active"
                    else "surge-self-v2026.07.13.4"
                )
                item = lifecycle_manifest(
                    "surge-self-v2026.08.08",
                    distribution,
                    list(release_verifier.EXPECTED),
                    live_device_validation=validation,
                    supersedes=active_tag if distribution == "rejected" else None,
                )
                del item["live_device_evidence"]
                records = [item]
                if distribution == "rejected":
                    active = lifecycle_manifest(
                        active_tag,
                        "active",
                        list(release_verifier.EXPECTED),
                        live_device_validation="passed",
                        superseded_by=item["tag"],
                    )
                    evidence = release_verifier.LEGACY_LIVE_DEVICE_EVIDENCE[active_tag]["reference"]
                    active["live_device_evidence"] = evidence
                    active["live_device_evidence_sha256"] = (
                        release_verifier.evidence_sha256(evidence)
                    )
                    records.insert(0, active)
                with self.assertRaisesRegex(SystemExit, "live_device_evidence"):
                    self.load_from(records, check_live_evidence=True)

    def test_evidence_section_hash_is_required_for_a_recorded_result(self) -> None:
        item = lifecycle_manifest(
            "surge-self-v2026.07.13.4",
            "active",
            list(release_verifier.EXPECTED),
            live_device_validation="passed",
        )
        evidence = release_verifier.LEGACY_LIVE_DEVICE_EVIDENCE[item["tag"]]["reference"]
        item["live_device_evidence"] = evidence
        item.pop("live_device_evidence_sha256", None)
        with self.assertRaisesRegex(SystemExit, "live_device_evidence_sha256"):
            self.load_from([item], check_live_evidence=True)

    def test_rollback_eligibility_requires_hashed_repository_evidence(self) -> None:
        names = list(release_verifier.EXPECTED)
        eligible = lifecycle_manifest(
            "surge-self-v2026.07.13.4",
            "inactive",
            names,
            live_device_validation="passed",
            rollback_eligible=True,
            superseded_by="surge-self-v2026.07.27.1",
        )
        active = lifecycle_manifest(
            "surge-self-v2026.07.27.1",
            "active",
            names,
            live_device_validation="passed",
            supersedes=eligible["tag"],
        )
        eligible.pop("rollback_evidence")
        eligible.pop("rollback_evidence_sha256")
        with self.assertRaisesRegex(SystemExit, "rollback_evidence"):
            self.load_from([eligible, active])

        evidence = (
            "docs/MODULE_STATUS.md#rollback-certification-evidence-for-"
            "surge-self-v202607134"
        )
        eligible["rollback_evidence"] = evidence
        eligible["rollback_evidence_sha256"] = release_verifier.evidence_sha256(evidence)
        manifests = self.load_from([eligible, active])
        self.assertTrue(manifests[eligible["tag"]]["rollback_eligible"])

    def test_supersession_edges_must_be_reciprocal_and_complete(self) -> None:
        names = list(release_verifier.EXPECTED)
        first = lifecycle_manifest(
            "surge-self-v2026.07.13.4",
            "inactive",
            names,
            live_device_validation="passed",
            rollback_eligible=True,
            superseded_by=None,
        )
        active = lifecycle_manifest(
            "surge-self-v2026.07.27.1",
            "active",
            names,
            live_device_validation="passed",
            supersedes=first["tag"],
        )
        with self.assertRaisesRegex(SystemExit, "supersession.*reciprocal"):
            self.load_from([first, active])

    def test_distribution_can_roll_back_without_rewriting_the_supersession_chain(self) -> None:
        names = list(release_verifier.EXPECTED)
        rollback = lifecycle_manifest(
            "surge-self-v2026.07.13.4",
            "active",
            names,
            live_device_validation="passed",
            superseded_by="surge-self-v2026.07.27.1",
        )
        failed = lifecycle_manifest(
            "surge-self-v2026.07.27.1",
            "inactive",
            names,
            live_device_validation="failed",
            supersedes=rollback["tag"],
        )
        manifests = self.load_from([rollback, failed])
        self.assertEqual(manifests[rollback["tag"]]["distribution"], "active")

    def test_worktree_after_rollback_uses_chain_head_payload_and_active_module_pins(self) -> None:
        names = list(release_verifier.EXPECTED)
        rollback_tag = "surge-self-v2026.07.13.4"
        head_tag = "surge-self-v2026.07.27.1"
        rollback = lifecycle_manifest(
            rollback_tag,
            "active",
            names,
            live_device_validation="passed",
            superseded_by=head_tag,
        )
        head = lifecycle_manifest(
            head_tag,
            "inactive",
            names,
            live_device_validation="failed",
            supersedes=rollback_tag,
        )
        manifests = self.load_from([rollback, head])
        paths = {module_name: path for module_name, path in release_verifier.EXPECTED.values()}
        with (
            mock.patch.object(release_verifier, "verify_manifest_payload") as verify,
            mock.patch.object(
                release_verifier,
                "module_tag_and_path",
                side_effect=lambda module_name: (rollback_tag, paths[module_name]),
            ),
        ):
            release_verifier.verify_worktree(manifests)
        self.assertEqual(verify.call_args_list[0], mock.call(manifests[head_tag], None))

    def test_transition_gate_allows_candidate_lifecycle_and_explicit_rollback(self) -> None:
        names = list(release_verifier.EXPECTED)
        active_tag = "surge-self-v2026.07.27.1"
        candidate_tag = "surge-self-v2026.08.08"
        commit = "2" * 40
        active = lifecycle_manifest(
            active_tag, "active", names, live_device_validation="passed"
        )
        candidate = lifecycle_manifest(
            candidate_tag,
            "candidate",
            names,
            release_commit=None,
            live_device_validation="pending",
            supersedes=active_tag,
        )
        preregistered = {active_tag: active, candidate_tag: candidate}

        registered = json.loads(json.dumps(preregistered))
        registered[candidate_tag]["release_commit"] = commit
        release_verifier.validate_manifest_transitions(
            preregistered,
            registered,
            resolve_tag=lambda _tag: None,
            load_manifest_at_commit=lambda _commit, tag: preregistered[tag],
            is_commit_ancestor=lambda _commit: True,
        )

        validated = json.loads(json.dumps(registered))
        validated[candidate_tag]["live_device_validation"] = "passed"
        validated[candidate_tag]["live_device_evidence"] = (
            "docs/MODULE_STATUS.md#current-ios-rollout-evidence"
        )
        validated[candidate_tag]["live_device_evidence_sha256"] = (
            release_verifier.evidence_sha256(validated[candidate_tag]["live_device_evidence"])
        )
        with mock.patch.object(release_verifier, "validate_live_device_evidence"):
            release_verifier.validate_manifest_transitions(
                registered, validated, resolve_tag=lambda _tag: commit
            )

        activated = json.loads(json.dumps(validated))
        activated[active_tag]["distribution"] = "inactive"
        activated[active_tag]["superseded_by"] = candidate_tag
        activated[candidate_tag]["distribution"] = "active"
        release_verifier.validate_manifest_transitions(
            validated, activated, resolve_tag=lambda _tag: commit
        )

        certified = json.loads(json.dumps(activated))
        certified[active_tag]["rollback_eligible"] = True
        certified[active_tag]["rollback_evidence"] = (
            "docs/MODULE_STATUS.md#rollback-certification-evidence-for-"
            "surge-self-v202607271"
        )
        certified[active_tag]["rollback_evidence_sha256"] = "0" * 64
        with mock.patch.object(release_verifier, "validate_rollback_evidence"):
            release_verifier.validate_manifest_transitions(
                activated, certified, resolve_tag=lambda _tag: active["release_commit"]
            )

        rejected = json.loads(json.dumps(registered))
        rejected[active_tag]["superseded_by"] = candidate_tag
        rejected[candidate_tag]["distribution"] = "rejected"
        rejected[candidate_tag]["note"] = "Rejected for a non-device release issue."
        release_verifier.validate_manifest_transitions(
            registered, rejected, resolve_tag=lambda _tag: commit
        )

        release_verifier.validate_manifest_transitions(
            preregistered, {active_tag: active}, resolve_tag=lambda _tag: None
        )

        rolled_back = json.loads(json.dumps(certified))
        rolled_back[active_tag]["distribution"] = "active"
        rolled_back[active_tag]["rollback_eligible"] = False
        rolled_back[candidate_tag]["distribution"] = "inactive"
        with mock.patch.object(release_verifier, "validate_rollback_evidence"):
            release_verifier.validate_manifest_transitions(
                certified,
                rolled_back,
                resolve_tag=lambda _tag: certified[active_tag]["release_commit"],
            )

        next_tag = "surge-self-v2026.08.08.1"
        next_candidate = json.loads(json.dumps(rolled_back))
        next_candidate[next_tag] = lifecycle_manifest(
            next_tag,
            "candidate",
            names,
            release_commit=None,
            live_device_validation="pending",
            supersedes=candidate_tag,
        )
        release_verifier.validate_manifest_transitions(
            rolled_back, next_candidate, resolve_tag=lambda _tag: None
        )

        legacy = lifecycle_manifest(
            release_verifier.LEGACY_UNVALIDATED_ACTIVE_TAG,
            "active",
            names,
            live_device_validation="pending",
        )
        legacy["legacy_unvalidated_activation"] = True
        legacy_passed = json.loads(json.dumps(legacy))
        legacy_passed["live_device_validation"] = "passed"
        legacy_passed["live_device_evidence"] = (
            "docs/MODULE_STATUS.md#current-ios-rollout-evidence"
        )
        legacy_passed["live_device_evidence_sha256"] = release_verifier.evidence_sha256(
            legacy_passed["live_device_evidence"]
        )
        with mock.patch.object(release_verifier, "validate_live_device_evidence"):
            release_verifier.validate_manifest_transitions(
                {legacy["tag"]: legacy},
                {legacy["tag"]: legacy_passed},
                resolve_tag=lambda _tag: legacy["release_commit"],
            )

    def test_transition_gate_rejects_combined_lifecycle_stages(self) -> None:
        names = list(release_verifier.EXPECTED)
        active_tag = "surge-self-v2026.07.27.1"
        candidate_tag = "surge-self-v2026.08.08"
        commit = "3" * 40
        active = lifecycle_manifest(
            active_tag, "active", names, live_device_validation="passed"
        )
        registered_candidate = lifecycle_manifest(
            candidate_tag,
            "candidate",
            names,
            release_commit=commit,
            live_device_validation="pending",
            supersedes=active_tag,
        )
        registered = {active_tag: active, candidate_tag: registered_candidate}

        rejected_with_result = json.loads(json.dumps(registered))
        rejected_with_result[active_tag]["superseded_by"] = candidate_tag
        rejected_with_result[candidate_tag]["distribution"] = "rejected"
        rejected_with_result[candidate_tag]["live_device_validation"] = "failed"
        rejected_with_result[candidate_tag]["live_device_evidence"] = (
            "docs/MODULE_STATUS.md#current-ios-rollout-evidence"
        )
        rejected_with_result[candidate_tag]["live_device_evidence_sha256"] = (
            release_verifier.evidence_sha256(
                rejected_with_result[candidate_tag]["live_device_evidence"]
            )
        )
        with self.assertRaisesRegex(SystemExit, "single allowed release transaction"):
            release_verifier.validate_manifest_transitions(
                registered,
                rejected_with_result,
                resolve_tag=lambda _tag: commit,
            )

        validated = json.loads(json.dumps(registered))
        validated[candidate_tag]["live_device_validation"] = "passed"
        validated[candidate_tag]["live_device_evidence"] = (
            "docs/MODULE_STATUS.md#current-ios-rollout-evidence"
        )
        validated[candidate_tag]["live_device_evidence_sha256"] = (
            release_verifier.evidence_sha256(validated[candidate_tag]["live_device_evidence"])
        )
        activated_and_certified = json.loads(json.dumps(validated))
        activated_and_certified[active_tag]["distribution"] = "inactive"
        activated_and_certified[active_tag]["rollback_eligible"] = True
        activated_and_certified[active_tag]["superseded_by"] = candidate_tag
        activated_and_certified[candidate_tag]["distribution"] = "active"
        with self.assertRaisesRegex(SystemExit, "single allowed release transaction"):
            release_verifier.validate_manifest_transitions(
                validated,
                activated_and_certified,
                resolve_tag=lambda _tag: commit,
            )

        invalid_old_active_state = json.loads(json.dumps(validated))
        invalid_old_active_state[active_tag]["distribution"] = "rejected"
        invalid_old_active_state[active_tag]["superseded_by"] = candidate_tag
        invalid_old_active_state[candidate_tag]["distribution"] = "active"
        with self.assertRaisesRegex(SystemExit, "invalid old active state"):
            release_verifier.validate_manifest_transitions(
                validated,
                invalid_old_active_state,
                resolve_tag=lambda _tag: commit,
            )

        rejected_with_empty_note = json.loads(json.dumps(registered))
        rejected_with_empty_note[active_tag]["superseded_by"] = candidate_tag
        rejected_with_empty_note[candidate_tag]["distribution"] = "rejected"
        rejected_with_empty_note[candidate_tag]["note"] = ""
        with self.assertRaisesRegex(SystemExit, "non-empty rejection note"):
            release_verifier.validate_manifest_transitions(
                registered,
                rejected_with_empty_note,
                resolve_tag=lambda _tag: commit,
            )

    def test_transition_gate_rejects_unscoped_history_and_tag_state_changes(self) -> None:
        names = list(release_verifier.EXPECTED)
        active_tag = "surge-self-v2026.07.27.1"
        candidate_tag = "surge-self-v2026.08.08"
        active = lifecycle_manifest(
            active_tag, "active", names, live_device_validation="passed"
        )
        candidate = lifecycle_manifest(
            candidate_tag,
            "candidate",
            names,
            release_commit=None,
            live_device_validation="pending",
            supersedes=active_tag,
        )

        with self.assertRaisesRegex(SystemExit, "tag already exists"):
            release_verifier.validate_manifest_transitions(
                {active_tag: active},
                {active_tag: active, candidate_tag: candidate},
                resolve_tag=lambda _tag: "4" * 40,
            )

        registered = json.loads(json.dumps(candidate))
        registered["release_commit"] = "4" * 40
        with self.assertRaisesRegex(SystemExit, "tag already exists"):
            release_verifier.validate_manifest_transitions(
                {active_tag: active, candidate_tag: candidate},
                {active_tag: active, candidate_tag: registered},
                resolve_tag=lambda _tag: "4" * 40,
                load_manifest_at_commit=lambda _commit, _tag: candidate,
                is_commit_ancestor=lambda _commit: True,
            )

        with self.assertRaisesRegex(SystemExit, "registration commit is not an ancestor"):
            release_verifier.validate_manifest_transitions(
                {active_tag: active, candidate_tag: candidate},
                {active_tag: active, candidate_tag: registered},
                resolve_tag=lambda _tag: None,
                load_manifest_at_commit=lambda _commit, _tag: candidate,
                is_commit_ancestor=lambda _commit: False,
            )

        with self.assertRaisesRegex(SystemExit, "tag already exists"):
            release_verifier.validate_manifest_transitions(
                {active_tag: active, candidate_tag: candidate},
                {active_tag: active},
                resolve_tag=lambda _tag: "4" * 40,
            )

        historical = lifecycle_manifest(
            "surge-self-v2026.07.27",
            "inactive",
            names,
            live_device_validation="pending",
            superseded_by=active_tag,
        )
        active_with_parent = json.loads(json.dumps(active))
        active_with_parent["supersedes"] = historical["tag"]
        historical_result = json.loads(json.dumps(historical))
        historical_result["live_device_validation"] = "failed"
        historical_result["live_device_evidence"] = (
            "docs/MODULE_STATUS.md#current-ios-rollout-evidence"
        )
        historical_result["live_device_evidence_sha256"] = release_verifier.evidence_sha256(
            historical_result["live_device_evidence"]
        )
        with self.assertRaisesRegex(SystemExit, "single allowed release transaction"):
            release_verifier.validate_manifest_transitions(
                {historical["tag"]: historical, active_tag: active_with_parent},
                {historical["tag"]: historical_result, active_tag: active_with_parent},
            )

    def test_transition_gate_requires_atomic_legacy_failure_rollback(self) -> None:
        names = list(release_verifier.EXPECTED)
        rollback_tag = "surge-self-v2026.07.13.4"
        legacy_tag = release_verifier.LEGACY_UNVALIDATED_ACTIVE_TAG
        rollback = lifecycle_manifest(
            rollback_tag,
            "inactive",
            names,
            live_device_validation="passed",
            rollback_eligible=True,
            superseded_by=legacy_tag,
        )
        legacy = lifecycle_manifest(
            legacy_tag,
            "active",
            names,
            live_device_validation="pending",
            supersedes=rollback_tag,
        )
        legacy["legacy_unvalidated_activation"] = True
        failed_without_rollback = json.loads(json.dumps(legacy))
        failed_without_rollback["live_device_validation"] = "failed"
        failed_without_rollback["live_device_evidence"] = (
            "docs/MODULE_STATUS.md#current-ios-rollout-evidence"
        )
        failed_without_rollback["live_device_evidence_sha256"] = (
            release_verifier.evidence_sha256(
                failed_without_rollback["live_device_evidence"]
            )
        )
        with self.assertRaisesRegex(SystemExit, "legacy failure must be combined with rollback"):
            release_verifier.validate_manifest_transitions(
                {rollback_tag: rollback, legacy_tag: legacy},
                {rollback_tag: rollback, legacy_tag: failed_without_rollback},
                resolve_tag=lambda _tag: legacy["release_commit"],
            )

        rolled_back = json.loads(json.dumps({rollback_tag: rollback, legacy_tag: legacy}))
        rolled_back[rollback_tag]["distribution"] = "active"
        rolled_back[rollback_tag]["rollback_eligible"] = False
        rolled_back[legacy_tag] = failed_without_rollback
        rolled_back[legacy_tag]["distribution"] = "inactive"
        with mock.patch.object(release_verifier, "validate_live_device_evidence"):
            release_verifier.validate_manifest_transitions(
                {rollback_tag: rollback, legacy_tag: legacy},
                rolled_back,
                resolve_tag=lambda _tag: legacy["release_commit"],
            )

    def test_transition_gate_rejects_history_rewrites_and_invalid_candidate_moves(self) -> None:
        names = list(release_verifier.EXPECTED)
        first_tag = "surge-self-v2026.07.13.4"
        active_tag = "surge-self-v2026.07.27.1"
        first = lifecycle_manifest(
            first_tag,
            "inactive",
            names,
            live_device_validation="passed",
            rollback_eligible=True,
            superseded_by=active_tag,
        )
        active = lifecycle_manifest(
            active_tag,
            "active",
            names,
            live_device_validation="passed",
            supersedes=first_tag,
        )
        previous = {first_tag: first, active_tag: active}
        rewrites = {
            "script hash": lambda records: records[first_tag]["scripts"][0].update(
                sha256="f" * 64
            ),
            "release commit": lambda records: records[first_tag].update(
                release_commit="2" * 40
            ),
            "evidence": lambda records: records[first_tag].update(
                live_device_evidence="docs/MODULE_STATUS.md#status-meanings"
            ),
            "forward edge": lambda records: records[first_tag].update(superseded_by=None),
            "back edge": lambda records: records[active_tag].update(supersedes=None),
            "historical note": lambda records: records[first_tag].update(note="rewritten"),
        }
        for name, mutate in rewrites.items():
            with self.subTest(name=name):
                current = json.loads(json.dumps(previous))
                mutate(current)
                with self.assertRaisesRegex(
                    SystemExit, "transaction|transition|immutable|release note"
                ):
                    release_verifier.validate_manifest_transitions(previous, current)

        candidate_tag = "surge-self-v2026.08.08"
        registered = json.loads(json.dumps(previous))
        registered[candidate_tag] = lifecycle_manifest(
            candidate_tag,
            "candidate",
            names,
            release_commit="3" * 40,
            live_device_validation="pending",
            supersedes=active_tag,
        )
        with self.assertRaisesRegex(SystemExit, "registered candidate"):
            release_verifier.validate_manifest_transitions(registered, previous)

        unregistered_new = json.loads(json.dumps(previous))
        unregistered_new[candidate_tag] = lifecycle_manifest(
            candidate_tag,
            "candidate",
            names,
            release_commit="3" * 40,
            live_device_validation="pending",
            supersedes=active_tag,
        )
        with self.assertRaisesRegex(SystemExit, "new manifest.*unregistered"):
            release_verifier.validate_manifest_transitions(previous, unregistered_new)

        preregistered = json.loads(json.dumps(previous))
        preregistered[candidate_tag] = lifecycle_manifest(
            candidate_tag,
            "candidate",
            names,
            release_commit=None,
            live_device_validation="pending",
            supersedes=active_tag,
        )
        bad_registration = json.loads(json.dumps(preregistered))
        bad_registration[candidate_tag]["release_commit"] = "3" * 40
        with self.assertRaisesRegex(SystemExit, "registration commit"):
            release_verifier.validate_manifest_transitions(
                preregistered,
                bad_registration,
                resolve_tag=lambda _tag: None,
                load_manifest_at_commit=lambda _commit, _tag: {},
                is_commit_ancestor=lambda _commit: True,
            )

        premature_edge = json.loads(json.dumps(preregistered))
        premature_edge[active_tag]["superseded_by"] = candidate_tag
        with self.assertRaisesRegex(SystemExit, "superseded_by.*activation|rejection"):
            release_verifier.validate_manifest_transitions(preregistered, premature_edge)

        premature = json.loads(json.dumps(registered))
        premature[active_tag]["distribution"] = "inactive"
        premature[active_tag]["superseded_by"] = candidate_tag
        premature[candidate_tag]["distribution"] = "active"
        with self.assertRaisesRegex(SystemExit, "passed"):
            release_verifier.validate_manifest_transitions(
                registered, premature, resolve_tag=lambda _tag: "3" * 40
            )

        new_active = json.loads(json.dumps(previous))
        new_active[candidate_tag] = lifecycle_manifest(
            candidate_tag,
            "active",
            names,
            live_device_validation="passed",
        )
        with self.assertRaisesRegex(SystemExit, "new manifest.*candidate"):
            release_verifier.validate_manifest_transitions(previous, new_active)

    def test_transition_gate_accepts_exact_schema_one_migration_and_freezes_payloads(self) -> None:
        previous = release_verifier.manifest_records_at_revision(
            "092045fe74f7fb068ff8aed240595d69818f40c1"
        )
        current_registry = release_verifier.current_manifest_records()
        current_registry["surge-self-v2026.08.09"] = {
            "schema_version": 2,
            "tag": "surge-self-v2026.08.09",
        }
        current = {
            tag: current_registry[tag]
            for tag in release_verifier.LEGACY_SCHEMA_ONE_MIGRATION
        }
        self.assertNotIn("surge-self-v2026.08.09", current)
        release_verifier.validate_manifest_transitions(previous, current)

        changed = json.loads(json.dumps(current))
        changed["surge-self-v2026.07.13"]["scripts"][0]["sha256"] = "f" * 64
        with self.assertRaisesRegex(SystemExit, "immutable"):
            release_verifier.validate_manifest_transitions(previous, changed)

        changed = json.loads(json.dumps(current))
        changed["surge-self-v2026.07.13.1"]["live_device_evidence_sha256"] = "f" * 64
        with self.assertRaisesRegex(SystemExit, "unexpected live_device_evidence_sha256"):
            release_verifier.validate_manifest_transitions(previous, changed)

    def test_transition_base_revision_must_be_an_exact_nonzero_ancestor(self) -> None:
        for revision in ("", "HEAD", "origin/main", "A" * 40, "0" * 40, "--help"):
            with self.subTest(revision=revision):
                with self.assertRaisesRegex(SystemExit, "40 lowercase hex|all-zero"):
                    release_verifier.validate_transition_base_revision(revision)

        base = "1" * 40
        head = "2" * 40
        with (
            mock.patch.object(
                release_verifier, "git_commit", side_effect=lambda revision: base if revision == base else head
            ),
            mock.patch.object(release_verifier, "git_is_ancestor", return_value=True),
        ):
            self.assertEqual(release_verifier.validate_transition_base_revision(base), base)

        with (
            mock.patch.object(release_verifier, "git_commit", return_value=head),
            mock.patch.object(release_verifier, "git_is_ancestor", return_value=True),
        ):
            with self.assertRaisesRegex(SystemExit, "does not resolve exactly"):
                release_verifier.validate_transition_base_revision(base)

        with (
            mock.patch.object(
                release_verifier, "git_commit", side_effect=lambda revision: base
            ),
            mock.patch.object(release_verifier, "git_is_ancestor", return_value=True),
        ):
            with self.assertRaisesRegex(SystemExit, "must differ from HEAD"):
                release_verifier.validate_transition_base_revision(base)

        with (
            mock.patch.object(
                release_verifier, "git_commit", side_effect=lambda revision: base if revision == base else head
            ),
            mock.patch.object(release_verifier, "git_is_ancestor", return_value=False),
        ):
            with self.assertRaisesRegex(SystemExit, "is not an ancestor"):
                release_verifier.validate_transition_base_revision(base)

    def test_registration_ancestry_uses_the_trusted_base_commit(self) -> None:
        base = "1" * 40
        registration = "2" * 40
        with (
            mock.patch.object(
                release_verifier, "validate_transition_base_revision", return_value=base
            ),
            mock.patch.object(release_verifier, "manifest_records_at_revision", return_value={}),
            mock.patch.object(release_verifier, "current_manifest_records", return_value={}),
            mock.patch.object(release_verifier, "retired_tag_records_at_revision", return_value={}),
            mock.patch.object(release_verifier, "current_retired_tag_records", return_value={}),
            mock.patch.object(release_verifier, "validate_manifest_transitions") as validate,
            mock.patch.object(release_verifier, "validate_retired_tag_transitions"),
            mock.patch.object(release_verifier, "git_is_ancestor", return_value=True) as ancestry,
        ):
            release_verifier.verify_manifest_transitions(base)
            callback = validate.call_args.kwargs["is_commit_ancestor"]
            self.assertTrue(callback(registration))
            ancestry.assert_called_once_with(registration, base)

    def test_transition_gate_rejects_an_invalid_v2_baseline_even_on_noop(self) -> None:
        names = list(release_verifier.EXPECTED)
        first = lifecycle_manifest(
            "surge-self-v2026.07.13.4",
            "active",
            names,
            live_device_validation="passed",
            superseded_by="surge-self-v2026.07.27.1",
        )
        second = lifecycle_manifest(
            "surge-self-v2026.07.27.1",
            "active",
            names,
            live_device_validation="passed",
            supersedes=first["tag"],
        )
        invalid = {first["tag"]: first, second["tag"]: second}
        with self.assertRaisesRegex(SystemExit, "baseline.*exactly one active"):
            release_verifier.validate_manifest_transitions(invalid, invalid)

    def test_revoked_bundle_cannot_recertify_with_stale_evidence(self) -> None:
        names = list(release_verifier.EXPECTED)
        revoked = lifecycle_manifest(
            "surge-self-v2026.07.13.4",
            "inactive",
            names,
            live_device_validation="passed",
            rollback_eligible=False,
            superseded_by="surge-self-v2026.07.27.1",
        )
        evidence = (
            "docs/MODULE_STATUS.md#rollback-certification-evidence-for-"
            "surge-self-v202607134"
        )
        revoked["rollback_evidence"] = evidence
        revoked["rollback_evidence_sha256"] = release_verifier.evidence_sha256(evidence)
        active = lifecycle_manifest(
            "surge-self-v2026.07.27.1",
            "active",
            names,
            live_device_validation="passed",
            supersedes=revoked["tag"],
        )
        recertified = json.loads(json.dumps({revoked["tag"]: revoked, active["tag"]: active}))
        recertified[revoked["tag"]]["rollback_eligible"] = True
        with self.assertRaisesRegex(SystemExit, "cannot be recertified with stale evidence"):
            release_verifier.validate_manifest_transitions(
                {revoked["tag"]: revoked, active["tag"]: active},
                recertified,
                resolve_tag=lambda _tag: revoked["release_commit"],
            )

    def test_rollback_requires_the_target_tag_at_its_registered_commit(self) -> None:
        names = list(release_verifier.EXPECTED)
        target = lifecycle_manifest(
            "surge-self-v2026.07.13.4",
            "inactive",
            names,
            live_device_validation="passed",
            rollback_eligible=True,
            superseded_by="surge-self-v2026.07.27.1",
        )
        active = lifecycle_manifest(
            "surge-self-v2026.07.27.1",
            "active",
            names,
            live_device_validation="passed",
            supersedes=target["tag"],
        )
        previous = {target["tag"]: target, active["tag"]: active}
        rolled_back = json.loads(json.dumps(previous))
        rolled_back[target["tag"]]["distribution"] = "active"
        rolled_back[target["tag"]]["rollback_eligible"] = False
        rolled_back[active["tag"]]["distribution"] = "inactive"
        resolved: list[str] = []

        def resolve(tag: str) -> str | None:
            resolved.append(tag)
            return None if tag == target["tag"] else active["release_commit"]

        with self.assertRaisesRegex(SystemExit, "tag.*missing"):
            release_verifier.validate_manifest_transitions(
                previous, rolled_back, resolve_tag=resolve
            )
        self.assertEqual(resolved, [target["tag"]])

    def test_legacy_failure_rollback_resolves_source_and_target_tags(self) -> None:
        names = list(release_verifier.EXPECTED)
        target_tag = "surge-self-v2026.07.13.4"
        legacy_tag = release_verifier.LEGACY_UNVALIDATED_ACTIVE_TAG
        target = lifecycle_manifest(
            target_tag,
            "inactive",
            names,
            release_commit="1" * 40,
            live_device_validation="passed",
            rollback_eligible=True,
            superseded_by=legacy_tag,
        )
        legacy = lifecycle_manifest(
            legacy_tag,
            "active",
            names,
            release_commit="2" * 40,
            live_device_validation="pending",
            supersedes=target_tag,
        )
        legacy["legacy_unvalidated_activation"] = True
        previous = {target_tag: target, legacy_tag: legacy}
        current = json.loads(json.dumps(previous))
        current[target_tag]["distribution"] = "active"
        current[target_tag]["rollback_eligible"] = False
        current[legacy_tag]["distribution"] = "inactive"
        current[legacy_tag]["live_device_validation"] = "failed"
        current[legacy_tag]["live_device_evidence"] = (
            "docs/MODULE_STATUS.md#current-ios-rollout-evidence"
        )
        current[legacy_tag]["live_device_evidence_sha256"] = release_verifier.evidence_sha256(
            current[legacy_tag]["live_device_evidence"]
        )
        resolved: list[str] = []

        def resolve(tag: str) -> str | None:
            resolved.append(tag)
            return legacy["release_commit"] if tag == legacy_tag else None

        with self.assertRaisesRegex(SystemExit, "tag.*missing"):
            release_verifier.validate_manifest_transitions(
                previous, current, resolve_tag=resolve
            )
        self.assertEqual(resolved, [legacy_tag, target_tag])

    def test_rollback_certification_evidence_is_bound_to_its_target_tag(self) -> None:
        names = list(release_verifier.EXPECTED)
        target = lifecycle_manifest(
            "surge-self-v2026.07.27",
            "inactive",
            names,
            live_device_validation="passed",
            rollback_eligible=False,
            superseded_by="surge-self-v2026.07.27.1",
        )
        active = lifecycle_manifest(
            "surge-self-v2026.07.27.1",
            "active",
            names,
            live_device_validation="passed",
            supersedes=target["tag"],
        )
        previous = {target["tag"]: target, active["tag"]: active}
        certified = json.loads(json.dumps(previous))
        wrong_evidence = (
            "docs/MODULE_STATUS.md#rollback-certification-evidence-for-"
            "surge-self-v202607134"
        )
        certified[target["tag"]]["rollback_eligible"] = True
        certified[target["tag"]]["rollback_evidence"] = wrong_evidence
        certified[target["tag"]]["rollback_evidence_sha256"] = (
            release_verifier.evidence_sha256(wrong_evidence)
        )
        with self.assertRaisesRegex(SystemExit, "rollback_evidence.*target tag"):
            release_verifier.validate_manifest_transitions(
                previous,
                certified,
                resolve_tag=lambda _tag: target["release_commit"],
            )

    def test_live_device_validation_evidence_cannot_be_reused_across_tags(self) -> None:
        names = list(release_verifier.EXPECTED)
        active_tag = "surge-self-v2026.07.27.1"
        candidate_tag = "surge-self-v2026.08.09"
        commit = "3" * 40
        active = lifecycle_manifest(
            active_tag,
            "active",
            names,
            live_device_validation="passed",
        )
        candidate = lifecycle_manifest(
            candidate_tag,
            "candidate",
            names,
            release_commit=commit,
            live_device_validation="pending",
            supersedes=active_tag,
        )
        previous = {active_tag: active, candidate_tag: candidate}
        validated = json.loads(json.dumps(previous))
        stale_evidence = (
            "CHANGELOG.md#native-domain-set-and-youtube-log-hardening-rollout"
        )
        validated[candidate_tag]["live_device_validation"] = "passed"
        validated[candidate_tag]["live_device_evidence"] = stale_evidence
        validated[candidate_tag]["live_device_evidence_sha256"] = (
            release_verifier.evidence_sha256(stale_evidence)
        )

        with self.assertRaisesRegex(SystemExit, "live_device_evidence.*target tag"):
            release_verifier.validate_manifest_transitions(
                previous,
                validated,
                resolve_tag=lambda _tag: commit,
            )

    def test_live_device_validation_evidence_records_the_release_commit(self) -> None:
        names = list(release_verifier.EXPECTED)
        active_tag = "surge-self-v2026.07.27.1"
        candidate_tag = "surge-self-v2026.08.09"
        commit = "3" * 40
        active = lifecycle_manifest(
            active_tag,
            "active",
            names,
            live_device_validation="passed",
        )
        candidate = lifecycle_manifest(
            candidate_tag,
            "candidate",
            names,
            release_commit=commit,
            live_device_validation="pending",
            supersedes=active_tag,
        )
        previous = {active_tag: active, candidate_tag: candidate}
        validated = json.loads(json.dumps(previous))
        anchor = "live-device-evidence-for-surge-self-v20260809"

        with tempfile.TemporaryDirectory() as temporary:
            evidence_root = Path(temporary)
            evidence_path = evidence_root / "docs/live-evidence.md"
            evidence_path.parent.mkdir()
            evidence_path.write_text(
                f"## Live-device evidence for {candidate_tag}\n\n"
                f"- Release commit: `{'4' * 40}`\n",
                encoding="utf-8",
            )
            reference = f"docs/live-evidence.md#{anchor}"
            with mock.patch.object(release_verifier, "ROOT", evidence_root):
                validated[candidate_tag]["live_device_validation"] = "passed"
                validated[candidate_tag]["live_device_evidence"] = reference
                validated[candidate_tag]["live_device_evidence_sha256"] = (
                    release_verifier.evidence_sha256(reference)
                )
                with self.assertRaisesRegex(
                    SystemExit, "live_device_evidence.*release_commit"
                ):
                    release_verifier.validate_manifest_transitions(
                        previous,
                        validated,
                        resolve_tag=lambda _tag: commit,
                    )

    def test_legacy_live_device_evidence_uses_only_the_closed_allowlist(self) -> None:
        tag = "surge-self-v2026.07.13.4"
        alternate = "docs/MODULE_STATUS.md#live-device-evidence-for-surge-self-v202607134"
        with self.assertRaisesRegex(SystemExit, "legacy.*allowlist"):
            release_verifier.validate_live_device_evidence(
                tag,
                alternate,
                "0" * 64,
                "f235e8b94e207261ec0005043d97a301d62fc337",
            )
        reference = release_verifier.LEGACY_LIVE_DEVICE_EVIDENCE[tag]["reference"]
        with self.assertRaisesRegex(SystemExit, "legacy.*release_commit"):
            release_verifier.validate_live_device_evidence(
                tag,
                reference,
                release_verifier.evidence_sha256(reference),
                None,
            )

    def test_transition_baseline_rollback_target_requires_evidence(self) -> None:
        names = list(release_verifier.EXPECTED)
        target = lifecycle_manifest(
            "surge-self-v2026.07.13.4",
            "inactive",
            names,
            live_device_validation="passed",
            rollback_eligible=True,
            superseded_by="surge-self-v2026.07.27.1",
        )
        target.pop("rollback_evidence")
        target.pop("rollback_evidence_sha256")
        active = lifecycle_manifest(
            "surge-self-v2026.07.27.1",
            "active",
            names,
            live_device_validation="passed",
            supersedes=target["tag"],
        )
        invalid = {target["tag"]: target, active["tag"]: active}
        with self.assertRaisesRegex(SystemExit, "baseline.*rollback evidence"):
            release_verifier.validate_manifest_transitions(invalid, invalid)

    def test_retired_tag_registry_entries_are_append_only(self) -> None:
        entry = retired_entry()
        previous = {entry["tag"]: entry}
        release_verifier.validate_retired_tag_transitions(previous, previous)
        changed = json.loads(json.dumps(previous))
        changed[entry["tag"]]["observed_tag_commit"] = "3" * 40
        with self.assertRaisesRegex(SystemExit, "retired tag.*immutable"):
            release_verifier.validate_retired_tag_transitions(previous, changed)
        with self.assertRaisesRegex(SystemExit, "retired tag.*removed"):
            release_verifier.validate_retired_tag_transitions(previous, {})

        two_additions = {
            **previous,
            "legacy-one-self-v1.0.0": retired_entry("legacy-one-self-v1.0.0"),
            "legacy-two-self-v1.0.0": retired_entry("legacy-two-self-v1.0.0"),
        }
        with self.assertRaisesRegex(SystemExit, "one retired tag.*transaction"):
            release_verifier.validate_retired_tag_transitions(previous, two_additions)

    def test_retired_tag_addition_cannot_share_a_manifest_transaction(self) -> None:
        base = "1" * 40
        previous_manifests = {"old": {"value": 1}}
        current_manifests = {"old": {"value": 2}}
        retired = {"legacy-self-v1.0.0": retired_entry("legacy-self-v1.0.0")}
        with (
            mock.patch.object(
                release_verifier, "validate_transition_base_revision", return_value=base
            ),
            mock.patch.object(
                release_verifier,
                "manifest_records_at_revision",
                return_value=previous_manifests,
            ),
            mock.patch.object(
                release_verifier, "current_manifest_records", return_value=current_manifests
            ),
            mock.patch.object(release_verifier, "validate_manifest_transitions"),
            mock.patch.object(release_verifier, "retired_tag_records_at_revision", return_value={}),
            mock.patch.object(
                release_verifier, "current_retired_tag_records", return_value=retired
            ),
        ):
            with self.assertRaisesRegex(SystemExit, "cannot combine.*retired tag"):
                release_verifier.verify_manifest_transitions(base)


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

    def test_remote_audit_allows_a_preregistered_candidate_without_a_remote_tag(self) -> None:
        candidate_tag = "surge-self-v2026.08.08"
        candidate = lifecycle_manifest(
            candidate_tag,
            "candidate",
            list(release_verifier.EXPECTED),
            release_commit="4" * 40,
            live_device_validation="pending",
        )
        candidate["scripts_by_name"] = {item["name"]: item for item in candidate["scripts"]}
        self.manifests[candidate_tag] = candidate
        self.verify_with_registry(set(self.expected), dict(self.releases))

    def test_remote_candidate_tag_requires_a_registered_commit(self) -> None:
        tag = "surge-self-v2026.08.08"
        candidate = lifecycle_manifest(
            tag,
            "candidate",
            list(release_verifier.EXPECTED),
            release_commit=None,
            live_device_validation="pending",
        )
        candidate["scripts_by_name"] = {item["name"]: item for item in candidate["scripts"]}
        with mock.patch.object(release_verifier, "dereference_remote_tag", return_value="4" * 40):
            with self.assertRaisesRegex(SystemExit, "registered release_commit"):
                release_verifier.verify_manifest_remote_tag(candidate, "owner/repo")

    def test_remote_audit_requires_rejected_tag_but_forbids_its_release(self) -> None:
        active_tag = next(iter(self.manifests))
        rejected_tag = "surge-self-v2026.08.08"
        self.manifests[active_tag]["superseded_by"] = rejected_tag
        rejected = lifecycle_manifest(
            rejected_tag,
            "rejected",
            list(release_verifier.EXPECTED),
            release_commit="4" * 40,
            live_device_validation="failed",
            supersedes=active_tag,
        )
        rejected["scripts_by_name"] = {item["name"]: item for item in rejected["scripts"]}
        self.manifests[rejected_tag] = rejected
        tags = set(self.expected) | {rejected_tag}
        self.verify_with_registry(tags, dict(self.releases))

        releases = {**self.releases, rejected_tag: {"tag_name": rejected_tag}}
        with self.assertRaisesRegex(SystemExit, "Release set mismatch;.*unknown"):
            self.verify_with_registry(tags, releases)

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

    def test_tag_push_accepts_active_and_rejects_retired_or_unknown_tags(self) -> None:
        active_tag = next(iter(self.manifests))
        with (
            mock.patch.object(
                release_verifier,
                "git_commit",
                return_value=self.manifests[active_tag]["release_commit"],
            ),
            mock.patch.object(release_verifier, "verify_manifest_payload") as verify,
        ):
            release_verifier.verify_tag_payload(self.manifests, self.retired, active_tag)
            verify.assert_called_once_with(self.manifests[active_tag], active_tag)

        retired_tag = next(iter(self.retired))
        with self.assertRaisesRegex(SystemExit, "retired and must not be pushed"):
            release_verifier.verify_tag_payload(self.manifests, self.retired, retired_tag)
        with self.assertRaisesRegex(SystemExit, "unregistered release tag"):
            release_verifier.verify_tag_payload(self.manifests, self.retired, "rogue-self-v9")

    def test_tag_push_accepts_a_preregistered_candidate_at_its_recorded_commit(self) -> None:
        tag = "surge-self-v2026.08.08"
        candidate = lifecycle_manifest(
            tag,
            "candidate",
            list(release_verifier.EXPECTED),
            release_commit="4" * 40,
            live_device_validation="pending",
        )
        candidate["scripts_by_name"] = {item["name"]: item for item in candidate["scripts"]}
        with (
            mock.patch.object(release_verifier, "git_commit", return_value="4" * 40) as commit,
            mock.patch.object(release_verifier, "verify_manifest_payload") as verify,
        ):
            release_verifier.verify_tag_payload({tag: candidate}, {}, tag)
        commit.assert_called_once_with(tag)
        verify.assert_called_once_with(candidate, tag)

    def test_tag_push_rejects_a_tag_at_a_commit_other_than_the_registered_commit(self) -> None:
        tag = "surge-self-v2026.08.08"
        candidate = lifecycle_manifest(
            tag,
            "candidate",
            list(release_verifier.EXPECTED),
            release_commit="4" * 40,
            live_device_validation="pending",
        )
        candidate["scripts_by_name"] = {item["name"]: item for item in candidate["scripts"]}
        with mock.patch.object(release_verifier, "git_commit", return_value="5" * 40):
            with self.assertRaisesRegex(SystemExit, "registered commit"):
                release_verifier.verify_tag_payload({tag: candidate}, {}, tag)

    def test_workflow_always_uses_the_default_branch_verifier(self) -> None:
        workflow = (ROOT / ".github/workflows/release-integrity.yml").read_text(encoding="utf-8")
        self.assertIn('      - "*-self-v*"', workflow)
        self.assertIn("  create:", workflow)
        self.assertIn("types: [created, published, prereleased, released, edited, unpublished, deleted]", workflow)
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

    def test_generated_rule_inventory_rejects_nested_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            generated_dir = Path(temporary)
            expected = {
                "README.md",
                "rule-section-managed.conf",
                *repository_checker.GENERATED_COMPATIBILITY_ARTIFACTS,
            }
            for name in expected:
                (generated_dir / name).write_text("", encoding="utf-8")
            nested = generated_dir / "nested"
            nested.mkdir()
            (nested / "unregistered.list").write_text(
                "DOMAIN,example.invalid\n", encoding="utf-8"
            )

            generator = mock.Mock()
            generator.load_manifest.return_value = (generated_dir, [])
            with (
                mock.patch.object(repository_checker, "load_generator", return_value=generator),
                self.assertRaisesRegex(SystemExit, "generated directory must be flat"),
            ):
                repository_checker.check_generated_rules()

    def test_generated_rule_inventory_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            generated_dir = Path(temporary) / "generated"
            generated_dir.mkdir()
            expected = {
                "README.md",
                "rule-section-managed.conf",
                *repository_checker.GENERATED_COMPATIBILITY_ARTIFACTS,
            }
            for name in expected:
                (generated_dir / name).write_text("", encoding="utf-8")
            target = Path(temporary) / "outside.list"
            target.write_text("DOMAIN,example.invalid\n", encoding="utf-8")
            linked = generated_dir / "README.md"
            linked.unlink()
            linked.symlink_to(target)

            generator = mock.Mock()
            generator.load_manifest.return_value = (generated_dir, [])
            with (
                mock.patch.object(repository_checker, "load_generator", return_value=generator),
                self.assertRaisesRegex(SystemExit, "regular files"),
            ):
                repository_checker.check_generated_rules()

    def test_release_docs_state_the_real_integrity_boundary(self) -> None:
        process = (ROOT / "docs/RELEASE_PROCESS.md").read_text(encoding="utf-8")
        manifests = (ROOT / "releases/README.md").read_text(encoding="utf-8")
        combined = process + "\n" + manifests
        self.assertIn("script bundle", combined)
        self.assertIn("not covered by the script release manifest", combined)
        self.assertIn("rejected", combined)
        self.assertIn("release change surface", combined)
        self.assertIn("live_device_evidence", combined)
        self.assertIn("live-device-evidence-for-", combined)
        self.assertIn("exact `release_commit`", combined)
        self.assertIn("must not be reused by another tag", combined)
        self.assertLess(process.index("Create the local tag"), process.index("Push the verified tag"))
        self.assertNotIn("one invalid line invalidates the whole set", combined)

    def test_workflow_contracts_are_checked_from_yaml_structure(self) -> None:
        checker = ROOT / "scripts/check_workflow_contracts.rb"
        self.assertTrue(checker.is_file(), "missing structured workflow contract checker")
        with tempfile.TemporaryDirectory() as temporary:
            workflow_dir = Path(temporary)
            for name in ("ci.yml", "release-integrity.yml", "rules-drift.yml"):
                source = ROOT / ".github/workflows" / name
                (workflow_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

            valid = subprocess.run(
                ["ruby", str(checker), str(workflow_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(valid.returncode, 0, valid.stderr)

            release = workflow_dir / "release-integrity.yml"
            release.write_text(
                release.read_text(encoding="utf-8").replace(
                    "          ref: ${{ github.event.repository.default_branch }}",
                    "          # ref: ${{ github.event.repository.default_branch }}",
                ),
                encoding="utf-8",
            )
            invalid = subprocess.run(
                ["ruby", str(checker), str(workflow_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("default branch", invalid.stderr)

    def test_release_workflow_requires_real_events_conditions_and_commands(self) -> None:
        checker = ROOT / "scripts/check_workflow_contracts.rb"
        source = ROOT / ".github/workflows/release-integrity.yml"
        rules_source = ROOT / ".github/workflows/rules-drift.yml"
        ci_source = ROOT / ".github/workflows/ci.yml"
        mutations = {
            "create event": lambda text: text.replace("  create:\n", "", 1),
            "schedule event": lambda text: text.replace(
                '  schedule:\n    - cron: "43 4 * * *"\n', "", 1
            ),
            "empty schedule": lambda text: text.replace(
                '  schedule:\n    - cron: "43 4 * * *"\n', "  schedule:\n", 1
            ),
            "manual event": lambda text: text.replace("  workflow_dispatch:\n", "", 1),
            "job event filter": lambda text: text.replace(
                "    if: github.event_name != 'create' || (github.event.ref_type == 'tag' && contains(github.event.ref, '-self-v'))",
                "    if: false",
                1,
            ),
            "job permission override": lambda text: text.replace(
                "  verify:\n",
                "  verify:\n    permissions:\n      contents: write\n",
                1,
            ),
            "tag step filter": lambda text: text.replace(
                "        if: github.event_name == 'push' || github.event_name == 'create'",
                "        if: false",
                1,
            ),
            "release step filter": lambda text: text.replace(
                "        if: github.event_name == 'release' && contains(github.event.release.tag_name, '-self-v')",
                "        if: false",
                1,
            ),
            "audit step filter": lambda text: text.replace(
                "        if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'",
                "        if: false",
                1,
            ),
            "commented verifier": lambda text: text.replace(
                '        run: python3 scripts/verify-surge-release.py --tag "$RELEASE_TAG"',
                '        run: |\n          # python3 scripts/verify-surge-release.py --tag "$RELEASE_TAG"',
                1,
            ),
            "early exit before verifier": lambda text: text.replace(
                '        run: python3 scripts/verify-surge-release.py --tag "$RELEASE_TAG"',
                '        run: |\n          exit 0\n          python3 scripts/verify-surge-release.py --tag "$RELEASE_TAG"',
                1,
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                workflow_dir = Path(temporary)
                original = source.read_text(encoding="utf-8")
                changed = mutate(original)
                self.assertNotEqual(changed, original, f"mutation did not apply: {name}")
                (workflow_dir / source.name).write_text(changed, encoding="utf-8")
                (workflow_dir / rules_source.name).write_text(
                    rules_source.read_text(encoding="utf-8"), encoding="utf-8"
                )
                (workflow_dir / ci_source.name).write_text(
                    ci_source.read_text(encoding="utf-8"), encoding="utf-8"
                )
                result = subprocess.run(
                    ["ruby", str(checker), str(workflow_dir)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0, f"accepted mutation: {name}")

    def test_rules_workflow_allows_only_the_isolated_update_branch_push(self) -> None:
        checker = ROOT / "scripts/check_workflow_contracts.rb"
        release_source = ROOT / ".github/workflows/release-integrity.yml"
        rules_source = ROOT / ".github/workflows/rules-drift.yml"
        ci_source = ROOT / ".github/workflows/ci.yml"
        original = rules_source.read_text(encoding="utf-8")
        changed = original.replace(
            '          git push origin "HEAD:refs/heads/$UPDATE_BRANCH"',
            '          git push origin "HEAD:refs/heads/$UPDATE_BRANCH"\n'
            '          git push origin "HEAD:refs/heads/$BASE_BRANCH"',
            1,
        )
        self.assertNotEqual(changed, original)
        with tempfile.TemporaryDirectory() as temporary:
            workflow_dir = Path(temporary)
            (workflow_dir / release_source.name).write_text(
                release_source.read_text(encoding="utf-8"), encoding="utf-8"
            )
            (workflow_dir / rules_source.name).write_text(changed, encoding="utf-8")
            (workflow_dir / ci_source.name).write_text(
                ci_source.read_text(encoding="utf-8"), encoding="utf-8"
            )
            result = subprocess.run(
                ["ruby", str(checker), str(workflow_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0, "accepted an extra default-branch push")

    def test_ci_workflow_runs_transition_checks_against_the_event_baseline(self) -> None:
        checker = ROOT / "scripts/check_workflow_contracts.rb"
        ci_source = ROOT / ".github/workflows/ci.yml"
        expected = 'python3 scripts/verify-surge-release.py --check-transitions "$BASE_REVISION"'
        original = ci_source.read_text(encoding="utf-8")
        self.assertIn(expected, original)
        self.assertIn(
            "  workflow_dispatch:\n"
            "    inputs:\n"
            "      base_revision:\n"
            "        description: Exact 40-character lowercase baseline commit SHA\n"
            "        required: true\n"
            "        type: string\n",
            original,
        )
        self.assertIn(
            "  group: surge-ci-${{ github.workflow }}-${{ github.event_name == "
            "'pull_request' && github.ref || github.run_id }}",
            original,
        )
        self.assertIn(
            "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}", original
        )
        self.assertIn(
            "    if: github.event_name != 'workflow_dispatch' || "
            "github.ref_name == github.event.repository.default_branch",
            original,
        )
        self.assertIn("          persist-credentials: false", original)
        self.assertIn(
            "${{ github.event_name == 'pull_request' && "
            "github.event.pull_request.base.sha || github.event_name == 'push' && "
            "github.event.before || inputs.base_revision }}",
            original,
        )

        with tempfile.TemporaryDirectory() as temporary:
            workflow_dir = Path(temporary)
            for workflow_name in ("release-integrity.yml", "rules-drift.yml"):
                source = ROOT / ".github/workflows" / workflow_name
                (workflow_dir / workflow_name).write_text(
                    source.read_text(encoding="utf-8"), encoding="utf-8"
                )
            (workflow_dir / ci_source.name).write_text(original, encoding="utf-8")
            valid = subprocess.run(
                ["ruby", str(checker), str(workflow_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(valid.returncode, 0, valid.stderr)

        mutations = {
            "dispatch input required": lambda text: text.replace(
                "        required: true\n", "        required: false\n", 1
            ),
            "dispatch default branch": lambda text: text.replace(
                "    if: github.event_name != 'workflow_dispatch' || "
                "github.ref_name == github.event.repository.default_branch",
                "    if: true",
                1,
            ),
            "push event baseline": lambda text: text.replace(
                " || github.event_name == 'push' && github.event.before", "", 1
            ),
            "dispatch baseline": lambda text: text.replace(
                " || inputs.base_revision", "", 1
            ),
            "unique push group": lambda text: text.replace(
                "${{ github.event_name == 'pull_request' && github.ref || github.run_id }}",
                "${{ github.ref }}",
                1,
            ),
            "pr-only cancellation": lambda text: text.replace(
                "${{ github.event_name == 'pull_request' }}", "true", 1
            ),
            "checkout credentials": lambda text: text.replace(
                "          persist-credentials: false",
                "          persist-credentials: true",
                1,
            ),
            "job permissions override": lambda text: text.replace(
                "  validate:\n",
                "  validate:\n    permissions:\n      contents: write\n",
                1,
            ),
            "commented transition": lambda text: text.replace(expected, f"# {expected}", 1),
            "early transition exit": lambda text: text.replace(
                expected, f"exit 0\n          {expected}", 1
            ),
            "extra privileged job": lambda text: text
            + "\n  privileged:\n"
            + "    permissions:\n"
            + "      contents: write\n"
            + "    runs-on: ubuntu-latest\n"
            + "    steps:\n"
            + "      - run: echo privileged\n",
            "extra push branch": lambda text: text.replace(
                "      - main\n", "      - main\n      - attacker\n", 1
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                changed = mutate(original)
                self.assertNotEqual(changed, original, f"mutation did not apply: {name}")
                workflow_dir = Path(temporary)
                for workflow_name in ("release-integrity.yml", "rules-drift.yml"):
                    source = ROOT / ".github/workflows" / workflow_name
                    (workflow_dir / workflow_name).write_text(
                        source.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                (workflow_dir / ci_source.name).write_text(changed, encoding="utf-8")
                result = subprocess.run(
                    ["ruby", str(checker), str(workflow_dir)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0, f"accepted CI mutation: {name}")


if __name__ == "__main__":
    unittest.main()
