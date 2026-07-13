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
    return {
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
