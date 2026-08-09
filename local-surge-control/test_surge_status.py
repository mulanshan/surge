#!/usr/bin/env python3
"""Behavior tests for the safe Surge status helper."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
HELPER = ROOT / "scripts" / "surge-status.sh"


class SurgeStatusTest(unittest.TestCase):
    def run_helper(
        self,
        *,
        profiles: dict[str, str],
        hosts: dict[str, str],
        expected_keys: dict[str, str],
        profile_overrides: dict[str, str] | None = None,
        fail_host: str = "",
        target: str = "all",
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            profile_dir = (
                temporary_path
                / "Library"
                / "Mobile Documents"
                / "iCloud~com~nssurge~inc"
                / "Documents"
            )
            bin_path = temporary_path / "bin"
            profile_dir.mkdir(parents=True)
            bin_path.mkdir()

            for filename, key in profiles.items():
                (profile_dir / filename).write_text(
                    f"http-api = {key}@0.0.0.0:1132\n",
                    encoding="utf-8",
                )

            fake_curl = bin_path / "curl"
            fake_curl.write_text(
                "#!/bin/sh\n"
                "config=\"$(cat)\"\n"
                "case \"$*\" in\n"
                "  *mac-surge.local*) expected=$TEST_MAC_KEY ;;\n"
                "  *ios-surge.local*) expected=$TEST_IOS_KEY ;;\n"
                "  *atv-surge.local*) expected=$TEST_ATV_KEY ;;\n"
                "  *) expected=unmatched ;;\n"
                "esac\n"
                "actual=\"$(printf '%s\\n' \"$config\" | "
                "sed -n 's/^header = \"X-Key: \\(.*\\)\"$/\\1/p')\"\n"
                "case \"$*\" in\n"
                "  *\"$TEST_FAIL_HOST\"*) selected_for_failure=1 ;;\n"
                "  *) selected_for_failure=0 ;;\n"
                "esac\n"
                "if [ \"$actual\" != \"$expected\" ]; then\n"
                "  printf '%s\\n' '{}' '418'\n"
                "elif [ -n \"$TEST_FAIL_HOST\" ] && "
                "[ \"$selected_for_failure\" = 1 ]; then\n"
                "  printf '%s\\n' '{}' '403'\n"
                "else\n"
                "  printf '%s\\n' '{\"events\":[]}' '200'\n"
                "fi\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o700)

            env = {
                name: value
                for name, value in os.environ.items()
                if not name.startswith("SURGE_")
            }
            env.update(
                {
                    "HOME": str(temporary_path),
                    "PATH": f"{bin_path}:{env['PATH']}",
                    "TEST_MAC_KEY": expected_keys.get("mac", "unused-mac-key"),
                    "TEST_IOS_KEY": expected_keys.get("ios", "unused-ios-key"),
                    "TEST_ATV_KEY": expected_keys.get("atv", "unused-atv-key"),
                    "TEST_FAIL_HOST": fail_host,
                }
            )
            env.update(hosts)
            for variable, filename in (profile_overrides or {}).items():
                env[variable] = str(profile_dir / filename)

            return subprocess.run(
                [str(HELPER), target],
                cwd=ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

    def test_all_uses_each_devices_default_profile(self) -> None:
        keys = {
            "mac": "test-mac-key",
            "ios": "test-ios-key",
            "atv": "test-atv-key",
        }
        result = self.run_helper(
            profiles={
                "DMIT-Mac.conf": keys["mac"],
                "DMIT.conf": keys["ios"],
                "DMIT-ATV.conf": keys["atv"],
            },
            hosts={
                "SURGE_MAC_HOST": "mac-surge.local",
                "SURGE_IOS_HOST": "ios-surge.local",
                "SURGE_ATV_HOST": "atv-surge.local",
            },
            expected_keys=keys,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        for device in ("mac", "ios", "atv"):
            with self.subTest(device=device):
                self.assertRegex(
                    result.stdout,
                    rf"(?m)^{device}\s+https-http-api\s+OK:",
                )

    def test_legacy_profile_remains_the_fallback_for_all_devices(self) -> None:
        legacy_key = "legacy-shared-key"
        result = self.run_helper(
            profiles={"legacy.conf": legacy_key},
            hosts={
                "SURGE_MAC_HOST": "mac-surge.local",
                "SURGE_IOS_HOST": "ios-surge.local",
                "SURGE_ATV_HOST": "atv-surge.local",
            },
            expected_keys={
                "mac": legacy_key,
                "ios": legacy_key,
                "atv": legacy_key,
            },
            profile_overrides={"SURGE_PROFILE": "legacy.conf"},
        )

        self.assertEqual(result.returncode, 0, result.stdout)

    def test_explicit_atv_profile_overrides_the_legacy_profile(self) -> None:
        legacy_key = "legacy-shared-key"
        atv_key = "explicit-atv-key"
        result = self.run_helper(
            profiles={"legacy.conf": legacy_key, "atv.conf": atv_key},
            hosts={
                "SURGE_MAC_HOST": "mac-surge.local",
                "SURGE_IOS_HOST": "ios-surge.local",
                "SURGE_ATV_HOST": "atv-surge.local",
            },
            expected_keys={
                "mac": legacy_key,
                "ios": legacy_key,
                "atv": atv_key,
            },
            profile_overrides={
                "SURGE_PROFILE": "legacy.conf",
                "SURGE_ATV_PROFILE": "atv.conf",
            },
        )

        self.assertEqual(result.returncode, 0, result.stdout)

    def test_all_skips_atv_when_no_explicit_host_is_set(self) -> None:
        keys = {"mac": "test-mac-key", "ios": "test-ios-key"}
        result = self.run_helper(
            profiles={
                "DMIT-Mac.conf": keys["mac"],
                "DMIT.conf": keys["ios"],
            },
            hosts={
                "SURGE_MAC_HOST": "mac-surge.local",
                "SURGE_IOS_HOST": "ios-surge.local",
            },
            expected_keys=keys,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertRegex(
            result.stdout,
            r"(?m)^atv\s+host\s+SKIP: set SURGE_ATV_HOST explicitly",
        )
        self.assertNotRegex(result.stdout, r"(?m)^atv\s+https-http-api")

    def test_all_requires_an_explicit_ios_host(self) -> None:
        keys = {"mac": "test-mac-key", "ios": "test-ios-key"}
        result = self.run_helper(
            profiles={
                "DMIT-Mac.conf": keys["mac"],
                "DMIT.conf": keys["ios"],
            },
            hosts={"SURGE_MAC_HOST": "mac-surge.local"},
            expected_keys=keys,
        )

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertRegex(
            result.stdout,
            r"(?m)^ios\s+host\s+FAIL: set SURGE_IOS_HOST explicitly",
        )
        self.assertRegex(
            result.stdout,
            r"(?m)^atv\s+host\s+SKIP: set SURGE_ATV_HOST explicitly",
        )

    def test_atv_authentication_failure_does_not_print_credentials(self) -> None:
        keys = {
            "mac": "sensitive-mac-test-key",
            "ios": "sensitive-ios-test-key",
            "atv": "sensitive-atv-test-key",
        }
        result = self.run_helper(
            profiles={
                "DMIT-Mac.conf": keys["mac"],
                "DMIT.conf": keys["ios"],
                "DMIT-ATV.conf": keys["atv"],
            },
            hosts={
                "SURGE_MAC_HOST": "mac-surge.local",
                "SURGE_IOS_HOST": "ios-surge.local",
                "SURGE_ATV_HOST": "atv-surge.local",
            },
            expected_keys=keys,
            fail_host="atv-surge.local",
        )

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertRegex(
            result.stdout,
            r"(?m)^atv\s+https-http-api\s+FAIL: authentication denied",
        )
        combined_output = result.stdout + result.stderr
        for key in keys.values():
            with self.subTest(key=key):
                self.assertNotIn(key, combined_output)


if __name__ == "__main__":
    unittest.main()
