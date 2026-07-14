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
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / "releases"
MODULES = ROOT / "rewrite/Surge"
TAG_RE = re.compile(r"surge-self-v\d{4}\.\d{2}\.\d{2}(?:\.\d+)?")
SELF_TAG_RE = re.compile(r".*-self-v.*")
SHA_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SCRIPT_URL_RE = re.compile(r"(?:^|,)script-path=([^,\s]+)")
MANIFEST_STATUSES = frozenset({"active", "superseded", "retired-moved"})
EXPECTED = {
    "YouTube": ("youtube-self.sgmodule", "rewrite/Surge/scripts/youtube/youtube-self.response.js"),
    "Instagram": ("instagram-self.sgmodule", "rewrite/Surge/scripts/instagram/instagram-self.response.js"),
    "Amap": ("amap-self.sgmodule", "rewrite/Surge/scripts/amap/amap-self.response.js"),
    "CamScanner": ("camscanner-self.sgmodule", "rewrite/Surge/scripts/camscanner/camscanner-self.response.js"),
    "JD": ("jd-self.sgmodule", "rewrite/Surge/scripts/jd/jd-self.response.js"),
    "WeChat": ("wechat-self.sgmodule", "rewrite/Surge/scripts/wechat/wechat-self.response.js"),
}
LEGACY_FIVE_SCRIPT_NAMES = frozenset(EXPECTED) - {"WeChat"}


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


def load_manifests() -> dict[str, dict]:
    manifests: dict[str, dict] = {}
    for path in sorted(RELEASES.glob("surge-self-v*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        tag = data.get("tag", "")
        if not TAG_RE.fullmatch(tag) or path.stem != tag:
            fail(f"invalid tag/filename in {path.relative_to(ROOT)}")
        if data.get("schema_version") != 1:
            fail(f"unsupported manifest schema: {path.relative_to(ROOT)}")
        if tag in manifests:
            fail(f"duplicate release manifest: {tag}")
        status = data.get("status")
        if status not in MANIFEST_STATUSES:
            fail(f"unsupported release status in {path.relative_to(ROOT)}: {status}")
        if status in {"active", "superseded"} and not COMMIT_RE.fullmatch(data.get("release_commit", "")):
            fail(f"{tag} must record a full release_commit")
        if status == "retired-moved" and not COMMIT_RE.fullmatch(data.get("observed_tag_commit", "")):
            fail(f"{tag} must record a full observed_tag_commit")
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
        if status == "active":
            if script_names != current_script_names:
                fail(f"{tag} active manifest must list exactly {len(EXPECTED)} current scripts")
        elif script_names not in {LEGACY_FIVE_SCRIPT_NAMES, current_script_names}:
            fail(f"{tag} has an unexpected historical script set")
        for name in script_names:
            _, expected_path = EXPECTED[name]
            item = by_name[name]
            if item.get("path") != expected_path or not SHA_RE.fullmatch(item.get("sha256", "")):
                fail(f"invalid {name} entry in {tag}")
        data["scripts_by_name"] = by_name
        manifests[tag] = data
    if not manifests:
        fail("no release manifests found")
    active = [tag for tag, item in manifests.items() if item.get("status") == "active"]
    if len(active) != 1:
        fail(f"expected exactly one active release manifest, found {len(active)}")
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
        fail(f"invalid stable script-path in {module_name}")
    return parts[2], "/".join(parts[3:])


def verify_worktree(manifests: dict[str, dict]) -> str:
    active_tag = next(tag for tag, item in manifests.items() if item.get("status") == "active")
    active = manifests[active_tag]
    verify_manifest_payload(active, None)
    for name, (module_name, expected_path) in EXPECTED.items():
        tag, path = module_tag_and_path(module_name)
        if tag != active_tag:
            state = manifests.get(tag, {}).get("status", "unregistered")
            fail(f"{module_name} references {tag} ({state}); expected active tag {active_tag}")
        if path != expected_path:
            fail(f"{module_name} references unexpected script {path}")
        if active["scripts_by_name"][name]["path"] != path:
            fail(f"manifest/module path mismatch for {name}")
    for item in manifests.values():
        revision = item.get("release_commit")
        if revision:
            verify_manifest_payload(item, revision)
    print(f"release worktree OK: {active_tag}, {len(EXPECTED)} scripts and {len(EXPECTED)} module pins")
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
    if manifest["status"] == "retired-moved":
        if remote_commit != manifest["observed_tag_commit"]:
            fail(f"retired tag {tag} moved again: {remote_commit}")
        return

    expected_commit = manifest["release_commit"]
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


def require_exact_remote_set(kind: str, actual: set[str], expected: set[str]) -> None:
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
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
    expected = set(manifests) | set(retired)
    remote_tags, releases = remote_release_registry(repository)
    require_exact_remote_set("*-self-v* tag", remote_tags, expected)
    require_exact_remote_set("*-self-v* Release", set(releases), expected)

    for tag, manifest in sorted(manifests.items()):
        verify_manifest_remote_tag(manifest, repository)
        verify_manifest_release(manifest, releases[tag])
    for tag, entry in sorted(retired.items()):
        verify_retired_release(entry, releases[tag], repository)
    print(f"remote tag and Release integrity OK: {len(expected)} closed-set entries")


def verify_tag_payload(manifests: dict[str, dict], retired: dict[str, dict], tag: str) -> None:
    if tag in retired:
        fail(f"tag {tag} is retired and must not be pushed or reused")
    manifest = manifests.get(tag)
    if not manifest:
        fail(f"unregistered release tag: {tag}")
    if manifest["status"] != "active":
        fail(f"tag {tag} is {manifest['status']} and must not be pushed or reused")
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
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "mulanshan/surge"))
    parser.add_argument("--print-release-body", action="store_true", help="print the active SHA-256 release block")
    args = parser.parse_args()

    manifests = load_manifests()
    retired = load_retired_tags()
    validate_release_registry(manifests, retired)
    active_tag = verify_worktree(manifests)
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
