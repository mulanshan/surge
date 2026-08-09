#!/usr/bin/env python3
"""Verify current Surge scripts while retaining historical release manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / "releases"
MODULES = ROOT / "rewrite/Surge"
TAG_RE = re.compile(r"surge-self-v[0-9]{4}\.[0-9]{2}\.[0-9]{2}(?:\.[0-9]+)?")
SELF_TAG_RE = re.compile(r".*-self-v.*")
SHA_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SCRIPT_URL_RE = re.compile(r"(?:^|,)script-path=([^,\s]+)")
MANIFEST_SCHEMA_VERSION = 2
INTEGRITY_STATES = frozenset({"intact", "retired-moved"})
DISTRIBUTION_STATES = frozenset({"candidate", "active", "inactive", "rejected", "retired"})
LIVE_DEVICE_STATES = frozenset({"pending", "passed", "failed", "not-recorded"})
LEGACY_UNVALIDATED_ACTIVE_TAG = "surge-self-v2026.07.27.1"
MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "tag",
        "integrity",
        "distribution",
        "live_device_validation",
        "live_device_evidence",
        "live_device_evidence_sha256",
        "rollback_eligible",
        "rollback_evidence",
        "rollback_evidence_sha256",
        "release_commit",
        "observed_tag_commit",
        "supersedes",
        "superseded_by",
        "legacy_unvalidated_activation",
        "note",
        "scripts",
    }
)
EXPECTED = {
    "YouTube": ("youtube-self.sgmodule", "rewrite/Surge/scripts/youtube/youtube-self.response.js"),
    "Instagram": ("instagram-self.sgmodule", "rewrite/Surge/scripts/instagram/instagram-self.response.js"),
    "Amap": ("amap-self.sgmodule", "rewrite/Surge/scripts/amap/amap-self.response.js"),
    "CamScanner": ("camscanner-self.sgmodule", "rewrite/Surge/scripts/camscanner/camscanner-self.response.js"),
    "JD": ("jd-self.sgmodule", "rewrite/Surge/scripts/jd/jd-self.response.js"),
    "WeChat": ("wechat-self.sgmodule", "rewrite/Surge/scripts/wechat/wechat-self.response.js"),
}
LEGACY_FIVE_SCRIPT_NAMES = frozenset(EXPECTED) - {"WeChat"}
LEGACY_SCHEMA_ONE_MIGRATION = {
    "surge-self-v2026.07.13": {
        "status": "retired-moved",
        "integrity": "retired-moved",
        "distribution": "retired",
        "live_device_validation": "not-recorded",
        "rollback_eligible": False,
        "supersedes": None,
        "superseded_by": "surge-self-v2026.07.13.1",
    },
    "surge-self-v2026.07.13.1": {
        "status": "superseded",
        "integrity": "intact",
        "distribution": "inactive",
        "live_device_validation": "passed",
        "live_device_evidence": "CHANGELOG.md#protected-patch-release-and-final-ios-regression",
        "live_device_evidence_sha256": "ef1ae012610b653785479c9badaeec6063bd52c9cebfae9ce48deee8f15828f2",
        "rollback_eligible": False,
        "supersedes": "surge-self-v2026.07.13",
        "superseded_by": "surge-self-v2026.07.13.2",
    },
    "surge-self-v2026.07.13.2": {
        "status": "superseded",
        "integrity": "intact",
        "distribution": "inactive",
        "live_device_validation": "not-recorded",
        "rollback_eligible": False,
        "supersedes": "surge-self-v2026.07.13.1",
        "superseded_by": "surge-self-v2026.07.13.3",
    },
    "surge-self-v2026.07.13.3": {
        "status": "superseded",
        "integrity": "intact",
        "distribution": "inactive",
        "live_device_validation": "not-recorded",
        "rollback_eligible": False,
        "supersedes": "surge-self-v2026.07.13.2",
        "superseded_by": "surge-self-v2026.07.13.4",
    },
    "surge-self-v2026.07.13.4": {
        "status": "superseded",
        "integrity": "intact",
        "distribution": "inactive",
        "live_device_validation": "passed",
        "live_device_evidence": "CHANGELOG.md#native-domain-set-and-youtube-log-hardening-rollout",
        "live_device_evidence_sha256": "206233667d2fc28087b26024821eb4ecf96dca46921de3b53adc32ec8c91cce5",
        "rollback_eligible": True,
        "rollback_evidence": "docs/MODULE_STATUS.md#rollback-certification-evidence-for-surge-self-v202607134",
        "rollback_evidence_sha256": "8bac14c827804334df8e1582874761fd737fd7c7f5591c5fadddc137b1edca01",
        "supersedes": "surge-self-v2026.07.13.3",
        "superseded_by": "surge-self-v2026.07.27",
    },
    "surge-self-v2026.07.27": {
        "status": "superseded",
        "integrity": "intact",
        "distribution": "inactive",
        "live_device_validation": "pending",
        "rollback_eligible": False,
        "supersedes": "surge-self-v2026.07.13.4",
        "superseded_by": "surge-self-v2026.07.27.1",
    },
    "surge-self-v2026.07.27.1": {
        "status": "active",
        "integrity": "intact",
        "distribution": "active",
        "live_device_validation": "pending",
        "rollback_eligible": False,
        "legacy_unvalidated_activation": True,
        "supersedes": "surge-self-v2026.07.27",
        "superseded_by": None,
    },
}
LEGACY_LIVE_DEVICE_EVIDENCE = {
    "surge-self-v2026.07.13.1": {
        "reference": "CHANGELOG.md#protected-patch-release-and-final-ios-regression",
        "release_commit": "c68d328a16e759c65dcf935fe51cb672a22b148e",
    },
    "surge-self-v2026.07.13.4": {
        "reference": "CHANGELOG.md#native-domain-set-and-youtube-log-hardening-rollout",
        "release_commit": "f235e8b94e207261ec0005043d97a301d62fc337",
    },
}


def fail(message: str) -> None:
    raise SystemExit(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_bytes(revision: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        fail(f"cannot read {path} at {revision}: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def git_commit(revision: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    commit = result.stdout.strip()
    if result.returncode or not COMMIT_RE.fullmatch(commit):
        fail(f"cannot resolve {revision} to a commit: {result.stderr.strip()}")
    return commit


def git_tag_commit(tag: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if result.returncode == 1:
        return None
    commit = result.stdout.strip()
    if result.returncode or not COMMIT_RE.fullmatch(commit):
        fail(f"cannot resolve release tag {tag}: {result.stderr.strip()}")
    return commit


def git_is_ancestor(ancestor: str, descendant: str = "HEAD") -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    fail(
        f"cannot compare release transition ancestry {ancestor}..{descendant}: "
        f"{result.stderr.strip()}"
    )


def validate_transition_base_revision(base_revision: str) -> str:
    if not isinstance(base_revision, str) or not COMMIT_RE.fullmatch(base_revision):
        fail("release transition base must be exactly 40 lowercase hex characters")
    if set(base_revision) == {"0"}:
        fail("release transition base must not be the all-zero commit")
    resolved = git_commit(base_revision)
    if resolved != base_revision:
        fail("release transition base does not resolve exactly to the supplied commit")
    head = git_commit("HEAD")
    if base_revision == head:
        fail("release transition base must differ from HEAD")
    if not git_is_ancestor(base_revision, head):
        fail(f"release transition base is not an ancestor of HEAD: {base_revision}")
    return base_revision


def markdown_sections(path: Path) -> dict[str, bytes]:
    lines = path.read_text(encoding="utf-8").splitlines()
    headings: list[tuple[int, int, str]] = []
    occurrences: dict[str, int] = {}
    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", line)
        if not match:
            continue
        heading = match.group(2).strip().casefold()
        base = re.sub(r"\s+", "-", re.sub(r"[^\w\- ]", "", heading))
        occurrence = occurrences.get(base, 0)
        occurrences[base] = occurrence + 1
        anchor = base if occurrence == 0 else f"{base}-{occurrence}"
        headings.append((index, len(match.group(1)), anchor))

    sections: dict[str, bytes] = {}
    for position, (start, level, anchor) in enumerate(headings):
        end = len(lines)
        for next_start, next_level, _next_anchor in headings[position + 1 :]:
            if next_level <= level:
                end = next_start
                break
        sections[anchor] = ("\n".join(lines[start:end]).rstrip() + "\n").encode("utf-8")
    return sections


def evidence_sha256(reference: str) -> str:
    relative, anchor = reference.split("#", 1)
    evidence_path = (ROOT / relative).resolve()
    sections = markdown_sections(evidence_path)
    if anchor not in sections:
        fail(f"live device evidence anchor does not exist: {reference}")
    return sha256(sections[anchor])


def validate_repository_evidence(
    tag: str,
    field: str,
    reference: object,
    expected_sha256: object,
) -> bytes:
    if not isinstance(reference, str) or not re.fullmatch(
        r"(?:CHANGELOG\.md|docs/[A-Za-z0-9._/-]+\.md)#[a-z0-9][a-z0-9-]*",
        reference,
    ):
        fail(f"{tag} {field} must be a repository Markdown anchor")
    relative, anchor = reference.split("#", 1)
    evidence_path = (ROOT / relative).resolve()
    try:
        evidence_path.relative_to(ROOT.resolve())
    except ValueError:
        fail(f"{tag} {field} escapes the repository")
    if not evidence_path.is_file():
        fail(f"{tag} {field} file does not exist: {relative}")
    sections = markdown_sections(evidence_path)
    if anchor not in sections:
        fail(f"{tag} {field} anchor does not exist: {reference}")
    if not isinstance(expected_sha256, str) or not SHA_RE.fullmatch(expected_sha256):
        fail(f"{tag} {field}_sha256 must be 64 lowercase hex characters")
    section = sections[anchor]
    actual = sha256(section)
    if actual != expected_sha256:
        fail(f"{tag} {field}_sha256 mismatch: {actual}")
    return section


def validate_live_device_evidence(
    tag: str,
    reference: object,
    expected_sha256: object,
    release_commit: object,
) -> None:
    legacy = LEGACY_LIVE_DEVICE_EVIDENCE.get(tag)
    legacy_reference = legacy["reference"] if legacy is not None else None
    expected_anchor = "live-device-evidence-for-" + re.sub(
        r"[^a-z0-9-]", "", tag.lower()
    )
    if legacy_reference is not None:
        if reference != legacy_reference:
            fail(f"{tag} live_device_evidence must use the closed legacy allowlist")
    elif not isinstance(reference, str) or not reference.endswith(f"#{expected_anchor}"):
        fail(
            f"{tag} live_device_evidence must identify its target tag with "
            f"the {expected_anchor} heading"
        )
    section = validate_repository_evidence(
        tag, "live_device_evidence", reference, expected_sha256
    )
    if legacy is not None:
        if release_commit != legacy["release_commit"]:
            fail(f"{tag} live_device_evidence requires the legacy release_commit")
        return
    if not isinstance(release_commit, str) or not COMMIT_RE.fullmatch(release_commit):
        fail(f"{tag} live_device_evidence requires a full release_commit")
    if release_commit.encode("ascii") not in section:
        fail(
            f"{tag} live_device_evidence must record release_commit {release_commit}"
        )


def validate_rollback_evidence(tag: str, reference: object, expected_sha256: object) -> None:
    expected_anchor = "rollback-certification-evidence-for-" + re.sub(
        r"[^a-z0-9-]", "", tag.lower()
    )
    if not isinstance(reference, str) or not reference.endswith(f"#{expected_anchor}"):
        fail(
            f"{tag} rollback_evidence must identify its target tag with "
            f"the {expected_anchor} heading"
        )
    validate_repository_evidence(tag, "rollback_evidence", reference, expected_sha256)


def current_manifest_records() -> dict[str, dict]:
    records: dict[str, dict] = {}
    for path in sorted(RELEASES.glob("surge-self-v*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        records[item["tag"]] = item
    return records


def manifest_records_at_revision(revision: str) -> dict[str, dict]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", revision, "--", "releases"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        fail(f"cannot list release manifests at {revision}: {result.stderr.strip()}")
    records: dict[str, dict] = {}
    for name in result.stdout.splitlines():
        if not re.fullmatch(
            r"releases/surge-self-v[0-9]{4}\.[0-9]{2}\.[0-9]{2}(?:\.[0-9]+)?\.json",
            name,
        ):
            continue
        item = json.loads(git_bytes(revision, name))
        records[item["tag"]] = item
    if not records:
        fail(f"no release manifests found at {revision}")
    return records


def current_retired_tag_records() -> dict[str, dict]:
    payload = json.loads((RELEASES / "retired-tags.json").read_text(encoding="utf-8"))
    return {item["tag"]: item for item in payload["tags"]}


def retired_tag_records_at_revision(revision: str) -> dict[str, dict]:
    payload = json.loads(git_bytes(revision, "releases/retired-tags.json"))
    return {item["tag"]: item for item in payload["tags"]}


def validate_retired_tag_transitions(
    previous: dict[str, dict], current: dict[str, dict]
) -> set[str]:
    removed = sorted(set(previous) - set(current))
    if removed:
        fail(f"retired tag registry entry removed: {', '.join(removed)}")
    for tag, item in previous.items():
        if current[tag] != item:
            fail(f"retired tag registry entry is immutable: {tag}")
    added = set(current) - set(previous)
    if len(added) > 1:
        fail("only one retired tag may be registered in a release transaction")
    return added


def _validate_schema_one_migration(previous: dict[str, dict], current: dict[str, dict]) -> None:
    expected_tags = set(LEGACY_SCHEMA_ONE_MIGRATION)
    if set(previous) != expected_tags or set(current) != expected_tags:
        fail("schema 1 transition must match the exact seven-manifest legacy registry")

    immutable_fields = (
        "tag",
        "scripts",
        "release_commit",
        "observed_tag_commit",
        "note",
    )
    for tag, expected in LEGACY_SCHEMA_ONE_MIGRATION.items():
        old = previous[tag]
        new = current[tag]
        if old.get("schema_version") != 1 or old.get("status") != expected["status"]:
            fail(f"schema 1 transition has an unexpected legacy state for {tag}")
        if new.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            fail(f"schema 1 transition did not migrate {tag} to schema 2")
        for field in immutable_fields:
            if new.get(field) != old.get(field):
                fail(f"immutable legacy field changed during transition: {tag} {field}")
        for field in (
            "integrity",
            "distribution",
            "live_device_validation",
            "rollback_eligible",
            "supersedes",
            "superseded_by",
        ):
            if new.get(field) != expected.get(field):
                fail(f"schema 1 transition has an unexpected {field} for {tag}")
        if old.get("supersedes") != expected.get("supersedes"):
            fail(f"schema 1 transition changed the legacy supersedes edge for {tag}")
        old_following = old.get("superseded_by")
        if old_following is not None and old_following != expected.get("superseded_by"):
            fail(f"schema 1 transition changed the legacy superseded_by edge for {tag}")
        for field in (
            "live_device_evidence",
            "live_device_evidence_sha256",
            "rollback_evidence",
            "rollback_evidence_sha256",
            "legacy_unvalidated_activation",
        ):
            if new.get(field) != expected.get(field):
                fail(f"schema 1 transition has an unexpected {field} for {tag}")


def _require_tag_commit(
    tag: str,
    expected_commit: object,
    resolve_tag: Callable[[str], str | None] | None,
) -> None:
    if resolve_tag is None:
        fail(f"release transition requires an authoritative tag resolver: {tag}")
    actual = resolve_tag(tag)
    if actual is None:
        fail(f"release transition tag {tag} is missing")
    if actual != expected_commit:
        fail(f"release transition tag {tag} points to {actual}, expected {expected_commit}")


def _require_tag_absent(
    tag: str,
    resolve_tag: Callable[[str], str | None] | None,
) -> None:
    if resolve_tag is None:
        fail(f"release transition requires an authoritative tag resolver: {tag}")
    actual = resolve_tag(tag)
    if actual is not None:
        fail(f"release transition tag already exists: {tag}")


_MISSING = object()


def _changed_fields(old: dict, new: dict) -> set[str]:
    fields = set(old) | set(new)
    return {
        field
        for field in fields
        if old.get(field, _MISSING) != new.get(field, _MISSING)
    }


def _changed_manifests(
    previous: dict[str, dict], current: dict[str, dict]
) -> dict[str, set[str]]:
    return {
        tag: _changed_fields(previous[tag], current[tag])
        for tag in sorted(set(previous) & set(current))
        if _changed_fields(previous[tag], current[tag])
    }


def _repository_evidence_added(
    tag: str, item: dict, field: str, reference_field: str, digest_field: str
) -> None:
    reference = item.get(reference_field)
    digest = item.get(digest_field)
    if reference is None or digest is None:
        fail(f"{field} transaction is missing {reference_field} for {tag}")
    if field == "live-device validation":
        validate_live_device_evidence(tag, reference, digest, item.get("release_commit"))
    else:
        validate_rollback_evidence(tag, reference, digest)


def _validate_transition_baseline(records: dict[str, dict]) -> None:
    if not records:
        fail("release transition baseline must contain release manifests")
    active = []
    for tag, item in records.items():
        if item.get("tag") != tag or not TAG_RE.fullmatch(tag):
            fail(f"release transition baseline has an invalid tag record: {tag}")
        if item.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            fail(f"release transition baseline has an unsupported schema: {tag}")
        if item.get("integrity") not in INTEGRITY_STATES:
            fail(f"release transition baseline has invalid integrity: {tag}")
        distribution = item.get("distribution")
        validation = item.get("live_device_validation")
        if distribution not in DISTRIBUTION_STATES:
            fail(f"release transition baseline has invalid distribution: {tag}")
        if validation not in LIVE_DEVICE_STATES:
            fail(f"release transition baseline has invalid live-device state: {tag}")
        if not isinstance(item.get("rollback_eligible"), bool):
            fail(f"release transition baseline has invalid rollback eligibility: {tag}")
        if distribution == "active":
            active.append(tag)
            legacy_pending = (
                tag == LEGACY_UNVALIDATED_ACTIVE_TAG
                and item.get("legacy_unvalidated_activation") is True
                and validation == "pending"
            )
            if validation != "passed" and not legacy_pending:
                fail(f"release transition baseline active distribution is not passed: {tag}")
        if item.get("rollback_eligible") and (
            item.get("integrity") != "intact"
            or distribution != "inactive"
            or validation != "passed"
        ):
            fail(f"release transition baseline has an invalid rollback target: {tag}")
        if item.get("rollback_eligible"):
            evidence = item.get("rollback_evidence")
            digest = item.get("rollback_evidence_sha256")
            if evidence is None or digest is None:
                fail(f"release transition baseline rollback evidence is missing: {tag}")
            validate_rollback_evidence(tag, evidence, digest)
    if len(active) != 1:
        fail(
            "release transition baseline must contain exactly one active distribution; "
            f"found {len(active)}"
        )
    validate_supersession_chain(records)


def validate_manifest_transitions(
    previous: dict[str, dict],
    current: dict[str, dict],
    *,
    resolve_tag: Callable[[str], str | None] | None = None,
    load_manifest_at_commit: Callable[[str, str], dict] | None = None,
    is_commit_ancestor: Callable[[str], bool] | None = None,
) -> None:
    """Allow exactly one release-state transaction between two snapshots.

    This is intentionally transaction-oriented rather than field-oriented. A
    valid final snapshot is not enough: a pull request must not combine
    registration, validation, activation, rejection, or rollback operations.
    """
    if previous and all(item.get("schema_version") == 1 for item in previous.values()):
        _validate_schema_one_migration(previous, current)
        return
    if any(item.get("schema_version") != MANIFEST_SCHEMA_VERSION for item in previous.values()):
        fail("release transition baseline mixes unsupported manifest schemas")
    _validate_transition_baseline(previous)

    removed = sorted(set(previous) - set(current))
    added = sorted(set(current) - set(previous))
    changed = _changed_manifests(previous, current)

    if added or removed:
        if added and removed:
            fail("release manifest changes do not match a single allowed release transaction")
        if added:
            if len(added) != 1 or changed:
                fail("release manifest changes do not match a single allowed release transaction")
            tag = added[0]
            item = current[tag]
            previous_heads = [
                candidate
                for candidate, record in previous.items()
                if record.get("distribution") != "candidate"
                and record.get("superseded_by") is None
            ]
            if any(record.get("distribution") == "candidate" for record in previous.values()):
                fail("release manifest changes do not match a single allowed release transaction")
            if (
                item.get("schema_version") != MANIFEST_SCHEMA_VERSION
                or item.get("integrity") != "intact"
                or item.get("distribution") != "candidate"
                or item.get("live_device_validation") != "pending"
                or item.get("release_commit") is not None
                or item.get("live_device_evidence") is not None
                or item.get("live_device_evidence_sha256") is not None
                or item.get("rollback_eligible") is not False
                or item.get("rollback_evidence") is not None
                or item.get("rollback_evidence_sha256") is not None
                or item.get("superseded_by") is not None
                or item.get("legacy_unvalidated_activation", False)
                or item.get("note") is not None
            ):
                fail(f"new manifest must be an unregistered pending candidate: {tag}")
            if len(previous_heads) != 1 or item.get("supersedes") != previous_heads[0]:
                fail(f"new candidate {tag} must supersede the prior release-chain head")
            _require_tag_absent(tag, resolve_tag)
            return

        if len(removed) != 1 or changed:
            fail("release manifest changes do not match a single allowed release transaction")
        tag = removed[0]
        item = previous[tag]
        if (
            item.get("distribution") != "candidate"
            or item.get("release_commit") is not None
            or item.get("live_device_validation") != "pending"
        ):
            fail(f"registered candidate or historical manifest cannot be removed: {tag}")
        _require_tag_absent(tag, resolve_tag)
        return

    if not changed:
        return

    def changed_exact(tag: str, fields: set[str]) -> bool:
        return changed.get(tag) == fields

    common_tags = set(previous) & set(current)

    registrations = [
        tag
        for tag in common_tags
        if previous[tag].get("distribution") == "candidate"
        and current[tag].get("distribution") == "candidate"
        and previous[tag].get("release_commit") is None
        and current[tag].get("release_commit") is not None
    ]
    if registrations:
        if len(registrations) != 1 or set(changed) != set(registrations):
            fail("release manifest changes do not match a single allowed release transaction")
        tag = registrations[0]
        old = previous[tag]
        new = current[tag]
        if not changed_exact(tag, {"release_commit"}):
            fail(f"release commit registration is not a single allowed transaction: {tag}")
        if not isinstance(new.get("release_commit"), str) or not COMMIT_RE.fullmatch(
            new["release_commit"]
        ):
            fail(f"release commit registration is invalid for {tag}")
        _require_tag_absent(tag, resolve_tag)
        if load_manifest_at_commit is None:
            fail(f"registration commit cannot be verified for {tag}")
        if is_commit_ancestor is None or not is_commit_ancestor(new["release_commit"]):
            fail(f"registration commit is not an ancestor of the checked revision: {tag}")
        registered = load_manifest_at_commit(new["release_commit"], tag)
        if registered != old:
            fail(f"registration commit does not contain the preregistered manifest: {tag}")
        return

    validations = [
        tag
        for tag in common_tags
        if previous[tag].get("distribution") == "candidate"
        and current[tag].get("distribution") == "candidate"
        and previous[tag].get("live_device_validation") == "pending"
        and current[tag].get("live_device_validation") in {"passed", "failed"}
    ]
    if validations:
        if len(validations) != 1 or set(changed) != set(validations):
            fail("release manifest changes do not match a single allowed release transaction")
        tag = validations[0]
        old = previous[tag]
        new = current[tag]
        expected_fields = {
            "live_device_validation",
            "live_device_evidence",
            "live_device_evidence_sha256",
        }
        if not changed_exact(tag, expected_fields):
            fail(f"candidate validation is not a single allowed transaction: {tag}")
        if old.get("release_commit") is None:
            fail(f"candidate {tag} must register its commit before validation")
        _require_tag_commit(tag, old["release_commit"], resolve_tag)
        _repository_evidence_added(
            tag,
            new,
            "live-device validation",
            "live_device_evidence",
            "live_device_evidence_sha256",
        )
        return

    legacy_results = [
        tag
        for tag in common_tags
        if tag == LEGACY_UNVALIDATED_ACTIVE_TAG
        and previous[tag].get("legacy_unvalidated_activation") is True
        and previous[tag].get("live_device_validation") == "pending"
        and current[tag].get("live_device_validation") in {"passed", "failed"}
        and current[tag].get("distribution") == previous[tag].get("distribution")
    ]
    if legacy_results and len(changed) == 1:
        tag = legacy_results[0]
        old = previous[tag]
        new = current[tag]
        if new.get("distribution") == "active" and new.get("live_device_validation") == "failed":
            fail("legacy failure must be combined with rollback")
        expected_fields = {
            "live_device_validation",
            "live_device_evidence",
            "live_device_evidence_sha256",
        }
        if changed_exact(tag, expected_fields):
            _require_tag_commit(tag, old.get("release_commit"), resolve_tag)
            _repository_evidence_added(
                tag,
                new,
                "live-device validation",
                "live_device_evidence",
                "live_device_evidence_sha256",
            )
            return

    # A legacy failed result can only be recorded atomically with a rollback.
    if LEGACY_UNVALIDATED_ACTIVE_TAG in common_tags:
        legacy_tag = LEGACY_UNVALIDATED_ACTIVE_TAG
        old_legacy = previous[legacy_tag]
        new_legacy = current[legacy_tag]
        if (
            old_legacy.get("legacy_unvalidated_activation") is True
            and old_legacy.get("distribution") == "active"
            and old_legacy.get("live_device_validation") == "pending"
            and new_legacy.get("distribution") == "inactive"
            and new_legacy.get("live_device_validation") == "failed"
        ):
            targets = [
                tag
                for tag in common_tags
                if tag != legacy_tag
                and previous[tag].get("distribution") == "inactive"
                and previous[tag].get("rollback_eligible") is True
                and current[tag].get("distribution") == "active"
                and current[tag].get("rollback_eligible") is False
            ]
            expected_legacy_fields = {
                "distribution",
                "live_device_validation",
                "live_device_evidence",
                "live_device_evidence_sha256",
            }
            if (
                len(targets) == 1
                and set(changed) == {legacy_tag, targets[0]}
                and changed_exact(legacy_tag, expected_legacy_fields)
                and changed_exact(targets[0], {"distribution", "rollback_eligible"})
            ):
                _require_tag_commit(legacy_tag, old_legacy.get("release_commit"), resolve_tag)
                _require_tag_commit(
                    targets[0], previous[targets[0]].get("release_commit"), resolve_tag
                )
                _repository_evidence_added(
                    legacy_tag,
                    new_legacy,
                    "live-device validation",
                    "live_device_evidence",
                    "live_device_evidence_sha256",
                )
                if current[targets[0]].get("supersedes") != previous[targets[0]].get("supersedes"):
                    fail("legacy failure rollback must preserve supersession edges")
                return
            fail("legacy failure must be combined with rollback")

    # Candidate activation is a three-party transaction. The old active and
    # the chain head are separate concepts after a rollback.
    activating = [
        tag
        for tag in common_tags
        if previous[tag].get("distribution") == "candidate"
        and current[tag].get("distribution") == "active"
    ]
    if activating:
        if len(activating) != 1:
            fail("release manifest changes do not match a single allowed release transaction")
        candidate_tag = activating[0]
        candidate_old = previous[candidate_tag]
        if candidate_old.get("live_device_validation") != "passed":
            fail(f"candidate {candidate_tag} cannot activate before a prior passed result")
        active_tags = [
            tag for tag, item in previous.items() if item.get("distribution") == "active"
        ]
        heads = [
            tag
            for tag, item in previous.items()
            if item.get("distribution") != "candidate" and item.get("superseded_by") is None
        ]
        if len(active_tags) != 1 or len(heads) != 1:
            fail("release manifest changes do not match a single allowed release transaction")
        old_active_tag = active_tags[0]
        head_tag = heads[0]
        if candidate_old.get("supersedes") != head_tag:
            fail("candidate activation must target the current release-chain head")
        expected_tags = {candidate_tag, old_active_tag, head_tag}
        if set(changed) != expected_tags:
            fail("release manifest changes do not match a single allowed release transaction")
        if not changed_exact(candidate_tag, {"distribution"}):
            fail("release manifest changes do not match a single allowed release transaction")
        active_fields = {"distribution"}
        if old_active_tag == head_tag:
            active_fields.add("superseded_by")
        if not changed_exact(old_active_tag, active_fields):
            fail("release manifest changes do not match a single allowed release transaction")
        if old_active_tag != head_tag and not changed_exact(head_tag, {"superseded_by"}):
            fail("release manifest changes do not match a single allowed release transaction")
        if current[old_active_tag].get("distribution") != "inactive":
            fail("candidate activation has an invalid old active state")
        if current[candidate_tag].get("distribution") != "active":
            fail("candidate activation has an invalid candidate state")
        if current[head_tag].get("superseded_by") != candidate_tag:
            fail("candidate activation must append one superseded_by edge")
        _require_tag_commit(candidate_tag, candidate_old.get("release_commit"), resolve_tag)
        return

    rejecting = [
        tag
        for tag in common_tags
        if previous[tag].get("distribution") == "candidate"
        and current[tag].get("distribution") == "rejected"
    ]
    if rejecting:
        if len(rejecting) != 1:
            fail("release manifest changes do not match a single allowed release transaction")
        candidate_tag = rejecting[0]
        candidate_old = previous[candidate_tag]
        head_tag = candidate_old.get("supersedes")
        if not isinstance(head_tag, str) or head_tag not in previous:
            fail("candidate rejection must target the current release-chain head")
        if set(changed) != {candidate_tag, head_tag}:
            fail("release manifest changes do not match a single allowed release transaction")
        candidate_fields = {"distribution"}
        if previous[candidate_tag].get("note") is None and current[candidate_tag].get("note") is not None:
            candidate_fields.add("note")
        note = current[candidate_tag].get("note")
        if note is not None and (not isinstance(note, str) or not note.strip()):
            fail(f"candidate rejection requires a non-empty rejection note: {candidate_tag}")
        if not changed_exact(candidate_tag, candidate_fields) or not changed_exact(
            head_tag, {"superseded_by"}
        ):
            fail("release manifest changes do not match a single allowed release transaction")
        if current[candidate_tag].get("live_device_validation") != candidate_old.get(
            "live_device_validation"
        ):
            fail("candidate rejection must preserve live-device validation state")
        if current[head_tag].get("superseded_by") != candidate_tag:
            fail("candidate rejection must append one superseded_by edge")
        _require_tag_commit(candidate_tag, candidate_old.get("release_commit"), resolve_tag)
        return

    # Rollback is deliberately limited to the active distribution and one
    # previously certified target. Supersession edges and evidence are frozen.
    from_active = [
        tag
        for tag in common_tags
        if previous[tag].get("distribution") == "active"
        and current[tag].get("distribution") == "inactive"
    ]
    to_active = [
        tag
        for tag in common_tags
        if previous[tag].get("distribution") == "inactive"
        and previous[tag].get("rollback_eligible") is True
        and current[tag].get("distribution") == "active"
        and current[tag].get("rollback_eligible") is False
    ]
    if from_active or to_active:
        if (
            len(from_active) != 1
            or len(to_active) != 1
            or set(changed) != {from_active[0], to_active[0]}
            or not changed_exact(from_active[0], {"distribution"})
            or not changed_exact(to_active[0], {"distribution", "rollback_eligible"})
        ):
            fail("release manifest changes do not match a single allowed release transaction")
        if current[from_active[0]].get("distribution") != "inactive":
            fail("rollback has an invalid previous active state")
        if current[to_active[0]].get("distribution") != "active":
            fail("rollback has an invalid certified target state")
        _require_tag_commit(
            to_active[0], previous[to_active[0]].get("release_commit"), resolve_tag
        )
        return

    # Certification and revocation are intentionally separate from activation
    # and rollback. Evidence is retained after revocation for provenance.
    certifying = [
        tag
        for tag in common_tags
        if previous[tag].get("rollback_eligible") is False
        and current[tag].get("rollback_eligible") is True
    ]
    if certifying:
        if len(certifying) != 1 or set(changed) != set(certifying):
            fail("release manifest changes do not match a single allowed release transaction")
        tag = certifying[0]
        old = previous[tag]
        new = current[tag]
        evidence_present = old.get("rollback_evidence") is not None
        if evidence_present:
            fail(f"revoked bundle cannot be recertified with stale evidence: {tag}")
        expected_fields = {"rollback_eligible"}
        expected_fields |= {"rollback_evidence", "rollback_evidence_sha256"}
        if not changed_exact(tag, expected_fields):
            fail("rollback certification is not a single allowed transaction")
        if (
            old.get("integrity") != "intact"
            or old.get("distribution") != "inactive"
            or old.get("live_device_validation") != "passed"
        ):
            fail(f"rollback certification target is not an inactive passed bundle: {tag}")
        _repository_evidence_added(
            tag,
            new,
            "rollback certification",
            "rollback_evidence",
            "rollback_evidence_sha256",
        )
        _require_tag_commit(tag, old.get("release_commit"), resolve_tag)
        return

    revoking = [
        tag
        for tag in common_tags
        if previous[tag].get("rollback_eligible") is True
        and current[tag].get("rollback_eligible") is False
    ]
    if revoking:
        if len(revoking) == 1 and set(changed) == set(revoking) and changed_exact(
            revoking[0], {"rollback_eligible"}
        ):
            return
        fail("release manifest changes do not match a single allowed release transaction")

    if any("superseded_by" in fields for fields in changed.values()):
        fail("superseded_by edge requires a single allowed activation or rejection transaction")
    fail("release manifest changes do not match a single allowed release transaction")


def verify_manifest_transitions(base_revision: str) -> None:
    base_commit = validate_transition_base_revision(base_revision)
    previous = manifest_records_at_revision(base_commit)
    current = current_manifest_records()

    def load_at_commit(commit: str, tag: str) -> dict:
        return json.loads(git_bytes(commit, f"releases/{tag}.json"))

    validate_manifest_transitions(
        previous,
        current,
        resolve_tag=git_tag_commit,
        load_manifest_at_commit=load_at_commit,
        is_commit_ancestor=lambda commit: git_is_ancestor(commit, base_commit),
    )
    retired_added = validate_retired_tag_transitions(
        retired_tag_records_at_revision(base_commit), current_retired_tag_records()
    )
    if previous != current and retired_added:
        fail("release transition cannot combine manifest changes with a retired tag addition")
    print(f"release manifest transitions OK against {base_commit}")


def validate_supersession_chain(manifests: dict[str, dict]) -> None:
    distributed = {
        tag: item for tag, item in manifests.items() if item["distribution"] != "candidate"
    }

    for tag, item in distributed.items():
        previous = item.get("supersedes")
        following = item.get("superseded_by")
        for field, linked_tag in (("supersedes", previous), ("superseded_by", following)):
            if linked_tag is not None and (
                not isinstance(linked_tag, str) or not TAG_RE.fullmatch(linked_tag)
            ):
                fail(f"{tag} has an invalid {field} tag")
            if linked_tag == tag:
                fail(f"{tag} cannot {field} itself")
            if linked_tag is not None and linked_tag not in distributed:
                fail(f"{tag} {field} unknown distributed manifest {linked_tag}")

        if previous is not None and distributed[previous].get("superseded_by") != tag:
            fail(f"supersession edge is not reciprocal: {tag} supersedes {previous}")
        if following is not None and distributed[following].get("supersedes") != tag:
            fail(f"supersession edge is not reciprocal: {tag} superseded_by {following}")
    roots = [tag for tag, item in distributed.items() if item.get("supersedes") is None]
    if len(roots) != 1:
        fail(f"supersession chain must have exactly one root, found {len(roots)}")

    visited: list[str] = []
    tag: str | None = roots[0]
    while tag is not None:
        if tag in visited:
            fail(f"supersession chain contains a cycle at {tag}")
        visited.append(tag)
        tag = distributed[tag].get("superseded_by")
    if set(visited) != set(distributed):
        missing = ", ".join(sorted(set(distributed) - set(visited)))
        fail(f"supersession chain is disconnected: {missing}")
    head_tag = visited[-1]

    candidates = [item for item in manifests.values() if item["distribution"] == "candidate"]
    if len(candidates) > 1:
        fail(f"expected at most one candidate release manifest, found {len(candidates)}")
    if candidates:
        candidate = candidates[0]
        if candidate.get("supersedes") != head_tag:
            fail(f"candidate {candidate['tag']} must supersede release-chain head {head_tag}")
        if candidate.get("superseded_by") is not None:
            fail(f"candidate {candidate['tag']} must not have superseded_by")


def load_manifests() -> dict[str, dict]:
    manifests: dict[str, dict] = {}
    for path in sorted(RELEASES.glob("surge-self-v*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        tag = data.get("tag", "")
        if not TAG_RE.fullmatch(tag) or path.stem != tag:
            fail(f"invalid tag/filename in {path.name}")
        if data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            fail(f"unsupported manifest schema: {path.name}")
        unexpected = sorted(set(data) - MANIFEST_FIELDS)
        if unexpected:
            fail(f"{tag or path.name} has unexpected manifest fields: {', '.join(unexpected)}")
        if tag in manifests:
            fail(f"duplicate release manifest: {tag}")
        if "status" in data:
            fail(f"{tag} must use integrity and distribution instead of legacy status")

        integrity = data.get("integrity")
        distribution = data.get("distribution")
        live_validation = data.get("live_device_validation")
        live_evidence = data.get("live_device_evidence")
        live_evidence_sha256 = data.get("live_device_evidence_sha256")
        rollback_eligible = data.get("rollback_eligible")
        rollback_evidence = data.get("rollback_evidence")
        rollback_evidence_sha256 = data.get("rollback_evidence_sha256")
        if integrity not in INTEGRITY_STATES:
            fail(f"unsupported integrity state in {path.name}: {integrity}")
        if distribution not in DISTRIBUTION_STATES:
            fail(f"unsupported distribution state in {path.name}: {distribution}")
        if live_validation not in LIVE_DEVICE_STATES:
            fail(f"unsupported live_device_validation in {path.name}: {live_validation}")
        if not isinstance(rollback_eligible, bool):
            fail(f"{tag} rollback_eligible must be a boolean")
        if live_validation in {"passed", "failed"}:
            validate_live_device_evidence(
                tag, live_evidence, live_evidence_sha256, data.get("release_commit")
            )
        elif live_evidence is not None or live_evidence_sha256 is not None:
            fail(
                f"{tag} must not record live_device_evidence or its SHA-256 "
                f"for {live_validation} validation"
            )
        if (rollback_evidence is None) != (rollback_evidence_sha256 is None):
            fail(f"{tag} must record rollback_evidence and its SHA-256 together")
        if rollback_evidence is not None:
            validate_rollback_evidence(
                tag, rollback_evidence, rollback_evidence_sha256
            )
            if (
                integrity != "intact"
                or distribution not in {"active", "inactive"}
                or live_validation != "passed"
            ):
                fail(
                    f"{tag} rollback_evidence requires an intact, passed, "
                    "active or inactive distribution"
                )
        if rollback_eligible and rollback_evidence is None:
            fail(f"{tag} rollback_eligible requires rollback_evidence")
        note = data.get("note")
        if note is not None and (not isinstance(note, str) or not note.strip()):
            fail(f"{tag} note must be non-empty text when present")

        release_commit = data.get("release_commit")
        observed_commit = data.get("observed_tag_commit")
        legacy_unvalidated = data.get("legacy_unvalidated_activation", False)
        if not isinstance(legacy_unvalidated, bool):
            fail(f"{tag} legacy_unvalidated_activation must be a boolean")
        if legacy_unvalidated and tag != LEGACY_UNVALIDATED_ACTIVE_TAG:
            fail(f"{tag} cannot use the legacy unvalidated activation exception")
        if integrity == "retired-moved":
            if distribution != "retired":
                fail(f"{tag} retired-moved integrity requires retired distribution")
            if not COMMIT_RE.fullmatch(observed_commit or ""):
                fail(f"{tag} must record a full observed_tag_commit")
            if release_commit is not None and not COMMIT_RE.fullmatch(release_commit):
                fail(f"{tag} release_commit must be a full commit when present")
        else:
            if distribution == "retired":
                fail(f"{tag} retired distribution requires retired-moved integrity")
            if observed_commit is not None:
                fail(f"{tag} intact integrity must not record observed_tag_commit")
            if distribution in {"active", "inactive", "rejected"} and not COMMIT_RE.fullmatch(
                release_commit or ""
            ):
                fail(f"{tag} must record a full release_commit")
            if distribution == "candidate" and release_commit is not None and not COMMIT_RE.fullmatch(
                release_commit
            ):
                fail(f"{tag} candidate release_commit must be a full commit when present")

        if distribution == "candidate":
            if live_validation == "not-recorded":
                fail(f"candidate {tag} must record a live_device_validation result")
            if live_validation != "pending" and release_commit is None:
                fail(f"candidate {tag} device result requires release_commit registration")
            if rollback_eligible:
                fail(f"candidate {tag} cannot be rollback eligible")
        if distribution == "active" and live_validation != "passed" and not (
            legacy_unvalidated and live_validation == "pending"
        ):
            fail(f"{tag} active distribution requires live_device_validation passed")
        if distribution == "rejected":
            if live_validation == "not-recorded":
                fail(f"rejected {tag} must retain its candidate validation state")
            if rollback_eligible:
                fail(f"rejected {tag} cannot be rollback eligible")
        if distribution in {"active", "retired"} and rollback_eligible:
            fail(f"{distribution} distribution {tag} cannot be rollback eligible")
        if rollback_eligible and (
            integrity != "intact"
            or distribution != "inactive"
            or live_validation != "passed"
        ):
            fail(
                f"{tag} rollback eligibility requires intact, inactive, "
                "live-device-validated distribution"
            )
        records = data.get("scripts")
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            fail(f"{tag} scripts must be a list of records")
        record_names = [item.get("name") for item in records]
        if not all(isinstance(name, str) for name in record_names):
            fail(f"{tag} script names must be strings")
        by_name = dict(zip(record_names, records, strict=True))
        if len(by_name) != len(records):
            fail(f"{tag} has duplicate script names")
        script_names = frozenset(by_name)
        current_script_names = frozenset(EXPECTED)
        if distribution in {"active", "candidate"}:
            if script_names != current_script_names:
                fail(
                    f"{tag} {distribution} manifest must list exactly "
                    f"{len(EXPECTED)} current scripts"
                )
        elif script_names not in {LEGACY_FIVE_SCRIPT_NAMES, current_script_names}:
            fail(f"{tag} has an unexpected historical script set")
        if rollback_eligible and script_names != current_script_names:
            fail(f"{tag} rollback-eligible manifest must list every current script")
        for name in script_names:
            _, expected_path = EXPECTED[name]
            item = by_name[name]
            if item.get("path") != expected_path or not SHA_RE.fullmatch(item.get("sha256", "")):
                fail(f"invalid {name} entry in {tag}")
        data["scripts_by_name"] = by_name
        manifests[tag] = data
    if not manifests:
        fail("no release manifests found")
    active = [tag for tag, item in manifests.items() if item.get("distribution") == "active"]
    if len(active) != 1:
        fail(f"expected exactly one active distribution manifest, found {len(active)}")
    validate_supersession_chain(manifests)
    return manifests


def load_retired_tags() -> dict[str, dict]:
    path = RELEASES / "retired-tags.json"
    if not path.is_file():
        fail("missing releases/retired-tags.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"schema_version", "tags"}:
        fail("retired-tags.json must contain only schema_version and tags")
    if data.get("schema_version") != 1:
        fail("unsupported retired-tags.json schema")
    records = data.get("tags")
    if not isinstance(records, list):
        fail("retired-tags.json tags must be a list")

    retired: dict[str, dict] = {}
    for index, item in enumerate(records, 1):
        context = f"retired-tags.json entry #{index}"
        if not isinstance(item, dict) or set(item) != {
            "tag",
            "status",
            "observed_tag_commit",
            "release",
        }:
            fail(f"{context} has unexpected fields")
        tag = item.get("tag")
        if not isinstance(tag, str) or not SELF_TAG_RE.fullmatch(tag):
            fail(f"{context} has an invalid *-self-v* tag")
        if tag in retired:
            fail(f"duplicate retired tag: {tag}")
        if item.get("status") != "retired-moved":
            fail(f"{tag} allowlist status must be retired-moved")
        if not COMMIT_RE.fullmatch(item.get("observed_tag_commit", "")):
            fail(f"{tag} must record a full observed_tag_commit")

        release = item.get("release")
        if not isinstance(release, dict) or set(release) != {
            "name",
            "draft",
            "prerelease",
            "required_marker",
            "body_sha256",
        }:
            fail(f"{tag} retired Release metadata has unexpected fields")
        if not isinstance(release.get("name"), str) or not release["name"]:
            fail(f"{tag} retired Release name must be non-empty")
        if not isinstance(release.get("draft"), bool) or not isinstance(release.get("prerelease"), bool):
            fail(f"{tag} retired Release draft/prerelease values must be booleans")
        if not isinstance(release.get("required_marker"), str) or not release["required_marker"]:
            fail(f"{tag} retired Release marker must be non-empty")
        if not SHA_RE.fullmatch(release.get("body_sha256", "")):
            fail(f"{tag} retired Release body_sha256 must be 64 lowercase hex characters")
        retired[tag] = item
    return retired


def validate_release_registry(manifests: dict[str, dict], retired: dict[str, dict]) -> None:
    overlap = set(manifests) & set(retired)
    if overlap:
        fail("tags cannot appear in both release manifests and retired allowlist: " + ", ".join(sorted(overlap)))


def verify_manifest_payload(manifest: dict, revision: str | None) -> None:
    for name, item in manifest["scripts_by_name"].items():
        path = item["path"]
        data = git_bytes(revision, path) if revision else (ROOT / path).read_bytes()
        actual = sha256(data)
        if actual != item["sha256"]:
            source = revision or "worktree"
            fail(f"{manifest['tag']} {name} SHA-256 mismatch at {source}: {actual}")


def module_tag_and_path(module_name: str) -> tuple[str, str]:
    matches = []
    for line in (MODULES / module_name).read_text(encoding="utf-8").splitlines():
        match = SCRIPT_URL_RE.search(line)
        if match:
            matches.append(match.group(1))
    if len(matches) != 1:
        fail(f"{module_name} must contain exactly one script-path")
    parsed = urllib.parse.urlparse(matches[0])
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme != "https" or parsed.netloc != "raw.githubusercontent.com":
        fail(f"unsafe script-path in {module_name}")
    if len(parts) < 4 or parts[:2] != ["mulanshan", "surge"] or not TAG_RE.fullmatch(parts[2]):
        fail(f"invalid immutable release script-path in {module_name}")
    return parts[2], "/".join(parts[3:])


def verify_worktree(manifests: dict[str, dict]) -> str:
    active_tag = next(
        tag for tag, item in manifests.items() if item.get("distribution") == "active"
    )
    active = manifests[active_tag]
    candidate_tags = [
        tag for tag, item in manifests.items() if item.get("distribution") == "candidate"
    ]
    chain_heads = [
        tag
        for tag, item in manifests.items()
        if item.get("distribution") != "candidate" and item.get("superseded_by") is None
    ]
    worktree_tag = candidate_tags[0] if candidate_tags else chain_heads[0]
    verify_manifest_payload(manifests[worktree_tag], None)
    for name, (module_name, expected_path) in EXPECTED.items():
        tag, path = module_tag_and_path(module_name)
        if tag != active_tag:
            state = manifests.get(tag, {}).get("distribution", "unregistered")
            fail(f"{module_name} references {tag} ({state}); expected active tag {active_tag}")
        if path != expected_path:
            fail(f"{module_name} references unexpected script {path}")
        if active["scripts_by_name"][name]["path"] != path:
            fail(f"manifest/module path mismatch for {name}")
    for item in manifests.values():
        revision = item.get("release_commit")
        if revision:
            verify_manifest_payload(item, revision)
    print(
        f"release worktree OK: distribution={active_tag}, payload={worktree_tag}, "
        f"{len(EXPECTED)} scripts and {len(EXPECTED)} module pins"
    )
    return active_tag


def github_json(repository: str, endpoint: str) -> dict | list:
    url = f"https://api.github.com/repos/{repository}/{endpoint.lstrip('/')}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "surge-release-verifier"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        fail(f"GitHub API request failed for {endpoint}: HTTP {exc.code}")
    except urllib.error.URLError as exc:
        fail(f"GitHub API request failed for {endpoint}: {exc.reason}")


def github_list(repository: str, endpoint: str) -> list[dict]:
    items: list[dict] = []
    for page in range(1, 1001):
        separator = "&" if "?" in endpoint else "?"
        result = github_json(repository, f"{endpoint}{separator}per_page=100&page={page}")
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            fail(f"GitHub API list response is invalid for {endpoint}")
        items.extend(result)
        if len(result) < 100:
            return items
    fail(f"GitHub API pagination exceeded safety limit for {endpoint}")


def verify_release_body(manifest: dict, release: dict) -> None:
    body = release.get("body") or ""
    if not isinstance(body, str):
        fail(f"GitHub Release body is not text for {manifest['tag']}")
    found: dict[str, str] = {}
    for name, digest in re.findall(r"^-\s*([^:\n]+):\s*([0-9a-f]{64})\s*$", body, re.MULTILINE):
        if name in found:
            fail(f"GitHub Release has duplicate SHA-256 entry for {manifest['tag']} {name}")
        found[name] = digest
    for name, item in manifest["scripts_by_name"].items():
        if found.get(name) != item["sha256"]:
            fail(f"GitHub Release SHA-256 mismatch or missing for {manifest['tag']} {name}")
    print(f"GitHub Release body OK: {manifest['tag']}")


def verify_manifest_release(manifest: dict, release: dict) -> None:
    tag = manifest["tag"]
    if release.get("tag_name") != tag:
        fail(f"GitHub Release tag mismatch for {tag}")
    if release.get("draft") is not False:
        fail(f"GitHub Release must not be a draft: {tag}")
    if release.get("prerelease") is not False:
        fail(f"GitHub Release must not be a prerelease: {tag}")
    verify_release_body(manifest, release)


def dereference_remote_tag(repository: str, tag: str) -> str:
    result = github_json(repository, f"git/ref/tags/{urllib.parse.quote(tag, safe='')}")
    if not isinstance(result, dict):
        fail(f"cannot resolve remote tag {tag}")
    obj = result.get("object", {})
    while obj.get("type") == "tag":
        result = github_json(repository, f"git/tags/{obj['sha']}")
        if not isinstance(result, dict):
            fail(f"cannot resolve annotated remote tag {tag}")
        obj = result.get("object", {})
    if obj.get("type") != "commit" or not COMMIT_RE.fullmatch(obj.get("sha", "")):
        fail(f"cannot resolve remote tag {tag} to a commit")
    return obj["sha"]


def verify_manifest_remote_tag(manifest: dict, repository: str) -> None:
    tag = manifest["tag"]
    remote_commit = dereference_remote_tag(repository, tag)
    if manifest["integrity"] == "retired-moved":
        if remote_commit != manifest["observed_tag_commit"]:
            fail(f"retired tag {tag} moved again: {remote_commit}")
        return

    expected_commit = manifest.get("release_commit")
    if not expected_commit:
        fail(f"candidate tag {tag} exists without a registered release_commit")
    if remote_commit != expected_commit:
        fail(f"immutable tag {tag} moved: expected {expected_commit}, got {remote_commit}")
    for name, item in manifest["scripts_by_name"].items():
        url = f"https://raw.githubusercontent.com/{repository}/{tag}/{item['path']}"
        with urllib.request.urlopen(url, timeout=30) as response:
            actual = sha256(response.read())
        if actual != item["sha256"]:
            fail(f"remote tag payload mismatch for {tag} {name}: {actual}")


def verify_retired_release(entry: dict, release: dict, repository: str) -> None:
    tag = entry["tag"]
    remote_commit = dereference_remote_tag(repository, tag)
    if remote_commit != entry["observed_tag_commit"]:
        fail(f"retired tag {tag} moved again: {remote_commit}")
    expected = entry["release"]
    if release.get("tag_name") != tag:
        fail(f"GitHub Release tag mismatch for retired tag {tag}")
    for field in ("name", "draft", "prerelease"):
        if release.get(field) != expected[field]:
            fail(f"retired GitHub Release {field} changed for {tag}")
    body = release.get("body") or ""
    if not isinstance(body, str):
        fail(f"retired GitHub Release body is not text for {tag}")
    if expected["required_marker"] not in body:
        fail(f"retired GitHub Release marker missing for {tag}")
    actual_hash = sha256(body.encode("utf-8"))
    if actual_hash != expected["body_sha256"]:
        fail(f"retired GitHub Release body changed for {tag}: {actual_hash}")
    print(f"retired tag and Release metadata OK: {tag}")


def require_remote_set(
    kind: str,
    actual: set[str],
    required: set[str],
    allowed: set[str] | None = None,
) -> None:
    allowed = required if allowed is None else allowed
    missing = sorted(required - actual)
    unknown = sorted(actual - allowed)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        fail(f"remote {kind} set mismatch; " + "; ".join(details))


def remote_release_registry(repository: str) -> tuple[set[str], dict[str, dict]]:
    remote_tags = {
        item["name"]
        for item in github_list(repository, "tags")
        if isinstance(item.get("name"), str) and SELF_TAG_RE.fullmatch(item["name"])
    }
    releases: dict[str, dict] = {}
    for release in github_list(repository, "releases"):
        tag = release.get("tag_name")
        if not isinstance(tag, str) or not SELF_TAG_RE.fullmatch(tag):
            continue
        if tag in releases:
            fail(f"duplicate remote GitHub Release for {tag}")
        releases[tag] = release
    return remote_tags, releases


def verify_remote(manifests: dict[str, dict], retired: dict[str, dict], repository: str) -> None:
    if not os.environ.get("GITHUB_TOKEN"):
        fail("--check-remote requires GITHUB_TOKEN to enumerate draft Releases")
    remote_tags, releases = remote_release_registry(repository)
    released = {
        tag
        for tag, manifest in manifests.items()
        if manifest["distribution"] in {"active", "inactive"}
    }
    candidates = {
        tag for tag, manifest in manifests.items() if manifest["distribution"] == "candidate"
    }
    rejected = {
        tag for tag, manifest in manifests.items() if manifest["distribution"] == "rejected"
    }
    retired_tags = set(retired) | {
        tag for tag, manifest in manifests.items() if manifest["distribution"] == "retired"
    }
    required_tags = released | rejected | retired_tags
    required_releases = released | retired_tags
    require_remote_set(
        "*-self-v* tag", remote_tags, required_tags, required_tags | candidates
    )
    require_remote_set("*-self-v* Release", set(releases), required_releases)

    for tag in sorted(released | rejected | (candidates & remote_tags)):
        manifest = manifests[tag]
        verify_manifest_remote_tag(manifest, repository)
        if tag in candidates or tag in rejected:
            continue
        verify_manifest_release(manifest, releases[tag])
    for tag, manifest in sorted(manifests.items()):
        if manifest["distribution"] == "retired":
            verify_manifest_remote_tag(manifest, repository)
            verify_manifest_release(manifest, releases[tag])
    for tag, entry in sorted(retired.items()):
        verify_retired_release(entry, releases[tag], repository)
    print(
        f"remote tag and Release integrity OK: {len(required_releases)} released entries, "
        f"{len(rejected)} rejected tags, {len(candidates)} candidate registrations"
    )


def verify_tag_payload(manifests: dict[str, dict], retired: dict[str, dict], tag: str) -> None:
    if tag in retired:
        fail(f"tag {tag} is retired and must not be pushed or reused")
    manifest = manifests.get(tag)
    if not manifest:
        fail(f"unregistered release tag: {tag}")
    distribution = manifest["distribution"]
    if distribution not in {"candidate", "active"}:
        fail(f"tag {tag} is {distribution} and must not be pushed or reused")
    expected_commit = manifest.get("release_commit")
    if not expected_commit:
        fail(f"tag {tag} has not registered a release_commit on the default branch")
    actual_commit = git_commit(tag)
    if actual_commit != expected_commit:
        fail(
            f"tag {tag} points to {actual_commit}, not registered commit {expected_commit}"
        )
    verify_manifest_payload(manifest, tag)
    print(f"tag payload OK: {tag}")


def verify_selected_release(
    manifests: dict[str, dict],
    retired: dict[str, dict],
    tag: str,
    repository: str,
) -> None:
    result = github_json(repository, f"releases/tags/{urllib.parse.quote(tag, safe='')}")
    if not isinstance(result, dict):
        fail(f"GitHub Release response is invalid for {tag}")
    manifest = manifests.get(tag)
    if manifest:
        if manifest["distribution"] in {"candidate", "rejected"}:
            fail(
                f"{manifest['distribution']} {tag} must not have a GitHub Release"
            )
        verify_manifest_remote_tag(manifest, repository)
        verify_manifest_release(manifest, result)
        return
    entry = retired.get(tag)
    if entry:
        verify_retired_release(entry, result, repository)
        return
    fail(f"unregistered GitHub Release tag: {tag}")


def print_sha_block(manifest: dict) -> None:
    print("Tagged script SHA-256:")
    for name in EXPECTED:
        print(f"- {name}: {manifest['scripts_by_name'][name]['sha256']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="verify a registered tag or GitHub Release")
    parser.add_argument("--github-release", action="store_true", help="also verify the selected GitHub Release body")
    parser.add_argument("--check-remote", action="store_true", help="verify all known remote tags and Releases")
    parser.add_argument(
        "--check-transitions",
        metavar="BASE_REVISION",
        help="verify append-only manifest transitions against a trusted base revision",
    )
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "mulanshan/surge"))
    parser.add_argument("--print-release-body", action="store_true", help="print the active SHA-256 release block")
    args = parser.parse_args()

    manifests = load_manifests()
    retired = load_retired_tags()
    validate_release_registry(manifests, retired)
    active_tag = verify_worktree(manifests)
    if args.check_transitions:
        verify_manifest_transitions(args.check_transitions)
    if args.print_release_body:
        print_sha_block(manifests[active_tag])
    if args.tag:
        if args.github_release:
            verify_selected_release(manifests, retired, args.tag, args.repository)
        else:
            verify_tag_payload(manifests, retired, args.tag)
    elif args.github_release:
        fail("--github-release requires --tag")
    if args.check_remote:
        verify_remote(manifests, retired, args.repository)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
