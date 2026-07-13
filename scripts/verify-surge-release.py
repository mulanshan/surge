#!/usr/bin/env python3
"""Verify the five self-hosted Surge scripts against release manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / "releases"
MODULES = ROOT / "rewrite/Surge"
TAG_RE = re.compile(r"surge-self-v\d{4}\.\d{2}\.\d{2}(?:\.\d+)?")
SHA_RE = re.compile(r"[0-9a-f]{64}")
SCRIPT_URL_RE = re.compile(r"(?:^|,)script-path=([^,\s]+)")
EXPECTED = {
    "YouTube": ("youtube-self.sgmodule", "rewrite/Surge/scripts/youtube/youtube-self.response.js"),
    "Instagram": ("instagram-self.sgmodule", "rewrite/Surge/scripts/instagram/instagram-self.response.js"),
    "Amap": ("amap-self.sgmodule", "rewrite/Surge/scripts/amap/amap-self.response.js"),
    "CamScanner": ("camscanner-self.sgmodule", "rewrite/Surge/scripts/camscanner/camscanner-self.response.js"),
    "JD": ("jd-self.sgmodule", "rewrite/Surge/scripts/jd/jd-self.response.js"),
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
        records = data.get("scripts")
        if not isinstance(records, list) or len(records) != len(EXPECTED):
            fail(f"{tag} must list exactly five scripts")
        by_name = {item.get("name"): item for item in records if isinstance(item, dict)}
        if set(by_name) != set(EXPECTED):
            fail(f"{tag} has an unexpected script set")
        for name, (_, expected_path) in EXPECTED.items():
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
    print(f"release worktree OK: {active_tag}, five scripts and five module pins")
    return active_tag


def github_json(repository: str, endpoint: str) -> dict:
    url = f"https://api.github.com/repos/{repository}/{endpoint.lstrip('/')}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "surge-release-verifier"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return json.load(response)


def verify_release_body(manifest: dict, repository: str) -> None:
    release = github_json(repository, f"releases/tags/{urllib.parse.quote(manifest['tag'], safe='')}")
    body = release.get("body") or ""
    found = dict(re.findall(r"^-\s*([^:\n]+):\s*([0-9a-f]{64})\s*$", body, re.MULTILINE))
    for name, item in manifest["scripts_by_name"].items():
        if found.get(name) != item["sha256"]:
            fail(f"GitHub Release SHA-256 mismatch or missing for {manifest['tag']} {name}")
    print(f"GitHub Release body OK: {manifest['tag']}")


def dereference_remote_tag(repository: str, tag: str) -> str:
    obj = github_json(repository, f"git/ref/tags/{urllib.parse.quote(tag, safe='')}").get("object", {})
    while obj.get("type") == "tag":
        obj = github_json(repository, f"git/tags/{obj['sha']}").get("object", {})
    if obj.get("type") != "commit" or not re.fullmatch(r"[0-9a-f]{40}", obj.get("sha", "")):
        fail(f"cannot resolve remote tag {tag} to a commit")
    return obj["sha"]


def verify_remote(manifests: dict[str, dict], repository: str) -> None:
    for tag, manifest in manifests.items():
        remote_commit = dereference_remote_tag(repository, tag)
        if manifest.get("status") == "retired-moved":
            if remote_commit != manifest.get("observed_tag_commit"):
                fail(f"retired tag {tag} moved again: {remote_commit}")
        else:
            expected_commit = manifest.get("release_commit")
            if expected_commit and remote_commit != expected_commit:
                fail(f"active tag {tag} moved: expected {expected_commit}, got {remote_commit}")
            for name, item in manifest["scripts_by_name"].items():
                url = f"https://raw.githubusercontent.com/{repository}/{tag}/{item['path']}"
                with urllib.request.urlopen(url, timeout=30) as response:
                    actual = sha256(response.read())
                if actual != item["sha256"]:
                    fail(f"remote tag payload mismatch for {tag} {name}: {actual}")
        verify_release_body(manifest, repository)
    print("remote tag and Release integrity OK")


def print_sha_block(manifest: dict) -> None:
    print("Tagged script SHA-256:")
    for name in EXPECTED:
        print(f"- {name}: {manifest['scripts_by_name'][name]['sha256']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="verify this active tag's committed payload")
    parser.add_argument("--github-release", action="store_true", help="also verify the selected GitHub Release body")
    parser.add_argument("--check-remote", action="store_true", help="verify all known remote tags and Releases")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "mulanshan/surge"))
    parser.add_argument("--print-release-body", action="store_true", help="print the active SHA-256 release block")
    args = parser.parse_args()

    manifests = load_manifests()
    active_tag = verify_worktree(manifests)
    if args.print_release_body:
        print_sha_block(manifests[active_tag])
    if args.tag:
        manifest = manifests.get(args.tag)
        if not manifest:
            fail(f"no manifest for tag {args.tag}")
        if manifest.get("status") != "active":
            fail(f"tag {args.tag} is retired and must not be reused or published")
        verify_manifest_payload(manifest, args.tag)
        print(f"tag payload OK: {args.tag}")
        if args.github_release:
            verify_release_body(manifest, args.repository)
    elif args.github_release:
        fail("--github-release requires --tag")
    if args.check_remote:
        verify_remote(manifests, args.repository)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
