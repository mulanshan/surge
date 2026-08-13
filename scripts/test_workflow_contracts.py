#!/usr/bin/env python3
"""Regression tests for the structured GitHub workflow contracts."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_workflow_contracts.rb"
WORKFLOW_NAMES = (
    "ci.yml",
    "pinned-upstream-drift.yml",
    "release-integrity.yml",
    "rules-drift.yml",
)


class WorkflowContractTests(unittest.TestCase):
    def workflow_step_run(self, step_name: str) -> str:
        workflow = ROOT / ".github" / "workflows" / "pinned-upstream-drift.yml"
        ruby = """
require "yaml"
data = YAML.safe_load(File.read(ARGV.fetch(0)), permitted_classes: [], permitted_symbols: [], aliases: false)
step = data.fetch("jobs").fetch("check").fetch("steps").find { |item| item["name"] == ARGV.fetch(1) }
abort "missing workflow step" unless step
print step.fetch("run")
"""
        result = subprocess.run(
            ["ruby", "-e", ruby, str(workflow), step_name],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def run_checker(self, mutations: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            workflow_dir = Path(temporary)
            for name in WORKFLOW_NAMES:
                source = ROOT / ".github" / "workflows" / name
                content = source.read_text(encoding="utf-8")
                (workflow_dir / name).write_text(
                    (mutations or {}).get(name, content),
                    encoding="utf-8",
                )
            return subprocess.run(
                ["ruby", str(CHECKER), str(workflow_dir)],
                capture_output=True,
                text=True,
                check=False,
            )

    def assert_rejected(self, workflow_name: str, changed: str, original: str) -> None:
        self.assertNotEqual(changed, original, "test mutation did not apply")
        result = self.run_checker({workflow_name: changed})
        self.assertNotEqual(
            result.returncode,
            0,
            f"checker accepted unsafe {workflow_name} mutation:\n{changed}",
        )

    def test_current_workflows_satisfy_contracts(self) -> None:
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pinned_upstream_drift_tracks_drift_without_masking_errors(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "pinned-upstream-drift.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("issues: write", workflow)
        self.assertIn('"$status" -ne 0', workflow)
        self.assertIn('"$status" -ne 3', workflow)
        self.assertIn('exit "$status"', workflow)
        self.assertIn(
            'details_file="$RUNNER_TEMP/pinned-upstream-drift-details.txt"',
            workflow,
        )
        self.assertIn('> "$details_file" 2>&1', workflow)
        self.assertIn('sha256sum "$details_file"', workflow)
        self.assertIn("gh api --paginate --method GET", workflow)
        self.assertIn('sort -n -o "$issue_numbers_file" "$issue_numbers_file"', workflow)
        self.assertIn('for duplicate in "${issues[@]:1}"', workflow)
        self.assertIn('for stale_issue in "${issues[@]}"', workflow)
        self.assertIn("gh issue view", workflow)
        self.assertIn("gh issue create", workflow)
        self.assertIn("gh issue close", workflow)
        self.assertNotIn("gh issue list", workflow)
        self.assertNotIn("details<<EOF", workflow)
        self.assertNotIn("DRIFT_DETAILS:", workflow)
        self.assertNotIn("continue-on-error", workflow)

    def test_pinned_upstream_drift_rejects_status_capture_bypasses(self) -> None:
        name = "pinned-upstream-drift.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        command = (
            "          python3 scripts/generate-managed-surge-rules.py "
            '--check-upstream --timeout 60 > "$details_file" 2>&1\n'
        )
        mutations = {
            "or true": original.replace(command, command.rstrip() + " || true\n", 1),
            "pipeline": original.replace(command, command.rstrip() + " | cat\n", 1),
            "trailing continuation": original.replace(
                command,
                command.rstrip() + " \\\n",
                1,
            ),
            "command before status": original.replace(
                command + "          status=$?\n",
                command + "          true\n          status=$?\n",
                1,
            ),
        }
        for mutation_name, changed in mutations.items():
            with self.subTest(mutation=mutation_name):
                self.assert_rejected(name, changed, original)

    def test_pinned_upstream_drift_rejects_issue_error_bypasses(self) -> None:
        name = "pinned-upstream-drift.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        mutations = {
            "list failure": original.replace(
                '            > "$issue_numbers_file"\n',
                '            > "$issue_numbers_file" || true\n',
                1,
            ),
            "edit failure": original.replace(
                '                gh issue edit "$issue" --body-file "$body"\n',
                '                gh issue edit "$issue" --body-file "$body" || true\n',
                1,
            ),
            "close failure": original.replace(
                '              gh issue close "$duplicate" --comment ',
                '              gh issue close "$duplicate" --comment ',
                1,
            ).replace(
                ' as the canonical upstream drift issue."\n',
                ' as the canonical upstream drift issue." || true\n',
                1,
            ),
        }
        for mutation_name, changed in mutations.items():
            with self.subTest(mutation=mutation_name):
                self.assert_rejected(name, changed, original)

    def test_pinned_upstream_drift_propagates_real_generator_errors(self) -> None:
        run = self.workflow_step_run("Compare tracking URLs with reviewed immutable pins")
        for generator_status, expected_status in ((0, 0), (3, 0), (1, 1), (2, 2)):
            with self.subTest(generator_status=generator_status), tempfile.TemporaryDirectory() as temp:
                temporary = Path(temp)
                fake_bin = temporary / "bin"
                fake_bin.mkdir()
                fake_python = fake_bin / "python3"
                fake_python.write_text(
                    "#!/bin/bash\n"
                    "printf 'simulated generator status %s\\n' \"$FAKE_GENERATOR_STATUS\"\n"
                    "exit \"$FAKE_GENERATOR_STATUS\"\n",
                    encoding="utf-8",
                )
                fake_python.chmod(0o755)
                output_file = temporary / "github-output"
                environment = os.environ.copy()
                environment.update(
                    {
                        "FAKE_GENERATOR_STATUS": str(generator_status),
                        "GITHUB_OUTPUT": str(output_file),
                        "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                        "RUNNER_TEMP": str(temporary),
                    }
                )
                result = subprocess.run(
                    ["bash", "-c", run],
                    cwd=ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, expected_status, result.stderr)
                self.assertEqual(output_file.read_text(encoding="utf-8"), f"status={generator_status}\n")

    def run_issue_step(
        self,
        drift_status: int,
        open_issue_numbers: str,
        existing_body: str = "",
    ) -> list[str]:
        run = self.workflow_step_run("Maintain one upstream drift issue")
        with tempfile.TemporaryDirectory() as temp:
            temporary = Path(temp)
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_gh = fake_bin / "gh"
            fake_gh.write_text(
                "#!/bin/bash\n"
                "set -euo pipefail\n"
                "printf '%s\\n' \"$*\" >> \"$FAKE_GH_LOG\"\n"
                "if [[ \"$1\" == api ]]; then\n"
                "  printf '%s' \"${FAKE_OPEN_ISSUES:-}\"\n"
                "elif [[ \"$1 $2\" == 'issue view' ]]; then\n"
                "  printf '%s\\n' \"${FAKE_ISSUE_BODY:-}\"\n"
                "elif [[ \"$1 $2\" =~ ^issue\\ (create|edit|close)$ ]]; then\n"
                "  :\n"
                "else\n"
                "  exit 90\n"
                "fi\n",
                encoding="utf-8",
            )
            fake_gh.chmod(0o755)
            details = b"simulated drift\n"
            (temporary / "pinned-upstream-drift-details.txt").write_bytes(details)
            log_file = temporary / "gh.log"
            environment = os.environ.copy()
            environment.update(
                {
                    "DRIFT_STATUS": str(drift_status),
                    "FAKE_GH_LOG": str(log_file),
                    "FAKE_ISSUE_BODY": existing_body,
                    "FAKE_OPEN_ISSUES": open_issue_numbers,
                    "GH_TOKEN": "test-token",
                    "GITHUB_REPOSITORY": "mulanshan/surge",
                    "GITHUB_RUN_ID": "123",
                    "GITHUB_SERVER_URL": "https://github.com",
                    "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                    "RUNNER_TEMP": str(temporary),
                }
            )
            result = subprocess.run(
                ["bash", "-c", run],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return log_file.read_text(encoding="utf-8").splitlines()

    def test_pinned_upstream_drift_issue_lifecycle_converges(self) -> None:
        created = self.run_issue_step(3, "")
        self.assertTrue(any(line.startswith("issue create ") for line in created))

        details = b"simulated drift\n"
        marker = f"<!-- upstream-drift:{hashlib.sha256(details).hexdigest()} -->"
        unchanged = self.run_issue_step(3, "17\n4\n", marker)
        self.assertIn("issue view 4 --json body --jq .body", unchanged)
        self.assertFalse(any(line.startswith("issue edit ") for line in unchanged))
        self.assertTrue(any(line.startswith("issue close 17 ") for line in unchanged))

        recovered = self.run_issue_step(0, "17\n4\n")
        self.assertTrue(any(line.startswith("issue close 4 ") for line in recovered))
        self.assertTrue(any(line.startswith("issue close 17 ") for line in recovered))

    def test_rules_workflow_rejects_an_extra_step(self) -> None:
        name = "rules-drift.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        changed = original.replace(
            "      - name: Create isolated update branch\n",
            "      - name: Unexpected privileged step\n"
            "        run: echo unexpected\n\n"
            "      - name: Create isolated update branch\n",
            1,
        )
        self.assert_rejected(name, changed, original)

    def test_rules_workflow_rejects_an_extra_push_command(self) -> None:
        name = "rules-drift.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        changed = original.replace(
            '          git push origin "HEAD:refs/heads/$UPDATE_BRANCH"\n',
            '          git push origin "HEAD:refs/heads/$UPDATE_BRANCH"\n'
            "          echo unexpected\n",
            1,
        )
        self.assert_rejected(name, changed, original)

    def test_rules_workflow_rejects_an_extra_refresh_command(self) -> None:
        name = "rules-drift.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        changed = original.replace(
            '          python3 scripts/generate-managed-surge-rules.py "${args[@]}"\n',
            '          python3 scripts/generate-managed-surge-rules.py "${args[@]}"\n'
            "          echo unexpected\n",
            1,
        )
        self.assert_rejected(name, changed, original)

    def test_rules_workflow_rejects_an_extra_pull_request_command(self) -> None:
        name = "rules-drift.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        changed = original.replace(
            '            --body-file "$body_file"\n',
            '            --body-file "$body_file"\n'
            "          echo unexpected\n",
            1,
        )
        self.assert_rejected(name, changed, original)

    def test_rules_workflow_rejects_execution_context_bypasses(self) -> None:
        name = "rules-drift.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        mutations = {
            "untrusted checkout action": original.replace(
                "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                "uses: attacker/action@1111111111111111111111111111111111111111",
                1,
            ),
            "untrusted setup action": original.replace(
                "uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                "uses: attacker/action@2222222222222222222222222222222222222222",
                1,
            ),
            "checkout repository override": original.replace(
                "          fetch-depth: 0\n",
                "          fetch-depth: 0\n          repository: attacker/repository\n",
                1,
            ),
            "BASH_ENV injection": original.replace(
                "      SOURCE_COMMIT: ${{ inputs.source_commit }}\n",
                "      SOURCE_COMMIT: ${{ inputs.source_commit }}\n"
                "      BASH_ENV: ./untrusted.sh\n",
                1,
            ),
            "custom shell": original.replace(
                "      - name: Create isolated update branch\n        shell: bash\n",
                "      - name: Create isolated update branch\n        shell: bash -n {0}\n",
                1,
            ),
            "job continue-on-error": original.replace(
                "  refresh:\n",
                "  refresh:\n    continue-on-error: true\n",
                1,
            ),
        }
        for mutation_name, changed in mutations.items():
            with self.subTest(mutation=mutation_name):
                self.assert_rejected(name, changed, original)

    def test_ci_workflow_rejects_execution_context_bypasses(self) -> None:
        name = "ci.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        mutations = {
            "workflow BASH_ENV": original.replace(
                "permissions:\n",
                "env:\n  BASH_ENV: ./untrusted.sh\n\npermissions:\n",
                1,
            ),
            "job continue-on-error": original.replace(
                "  validate:\n",
                "  validate:\n    continue-on-error: true\n",
                1,
            ),
            "checkout repository override": original.replace(
                "          persist-credentials: false\n",
                "          persist-credentials: false\n"
                "          repository: attacker/repository\n",
                1,
            ),
            "untrusted setup action": original.replace(
                "uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                "uses: attacker/action@3333333333333333333333333333333333333333",
                1,
            ),
            "transition custom shell": original.replace(
                "          BASE_REVISION: ${{ github.event_name == 'pull_request' && github.event.pull_request.base.sha || github.event_name == 'push' && github.event.before || inputs.base_revision }}\n"
                "        shell: bash\n",
                "          BASE_REVISION: ${{ github.event_name == 'pull_request' && github.event.pull_request.base.sha || github.event_name == 'push' && github.event.before || inputs.base_revision }}\n"
                "        shell: bash -n {0}\n",
                1,
            ),
        }
        for mutation_name, changed in mutations.items():
            with self.subTest(mutation=mutation_name):
                self.assert_rejected(name, changed, original)

    def test_release_workflow_rejects_an_extra_trigger(self) -> None:
        name = "release-integrity.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        changed = original.replace(
            "  workflow_dispatch:\n",
            "  workflow_dispatch:\n  pull_request:\n",
            1,
        )
        self.assert_rejected(name, changed, original)

    def test_release_workflow_rejects_action_identity_or_checkout_scope_changes(self) -> None:
        name = "release-integrity.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        mutations = {
            "untrusted checkout action": original.replace(
                "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                "uses: attacker/action@4444444444444444444444444444444444444444",
                1,
            ),
            "untrusted setup action": original.replace(
                "uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                "uses: attacker/action@5555555555555555555555555555555555555555",
                1,
            ),
            "checkout repository override": original.replace(
                "          fetch-depth: 0\n",
                "          fetch-depth: 0\n          repository: attacker/repository\n",
                1,
            ),
        }
        for mutation_name, changed in mutations.items():
            with self.subTest(mutation=mutation_name):
                self.assert_rejected(name, changed, original)

    def test_release_workflow_rejects_an_extra_release_lifecycle_type(self) -> None:
        name = "release-integrity.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        changed = original.replace(
            "types: [created, published, prereleased, released, edited, unpublished, deleted]",
            "types: [created, published, prereleased, released, edited, unpublished, deleted, requested]",
            1,
        )
        self.assert_rejected(name, changed, original)

    def test_release_workflow_rejects_continue_on_error_for_a_verifier(self) -> None:
        name = "release-integrity.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        changed = original.replace(
            "      - name: Verify tag payload\n",
            "      - name: Verify tag payload\n        continue-on-error: true\n",
            1,
        )
        self.assert_rejected(name, changed, original)

    def test_release_workflow_rejects_job_level_continue_on_error(self) -> None:
        name = "release-integrity.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        changed = original.replace(
            "  verify:\n",
            "  verify:\n    continue-on-error: true\n",
            1,
        )
        self.assert_rejected(name, changed, original)

    def test_release_workflow_rejects_execution_environment_injection(self) -> None:
        name = "release-integrity.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        mutations = {
            "workflow BASH_ENV": original.replace(
                "permissions:\n",
                "env:\n  BASH_ENV: ./untrusted.sh\n\npermissions:\n",
                1,
            ),
            "job defaults": original.replace(
                "    runs-on: ubuntu-latest\n",
                "    runs-on: ubuntu-latest\n"
                "    defaults:\n      run:\n        shell: bash -n {0}\n",
                1,
            ),
        }
        for mutation_name, changed in mutations.items():
            with self.subTest(mutation=mutation_name):
                self.assert_rejected(name, changed, original)

    def test_release_workflow_rejects_changed_verifier_environments(self) -> None:
        name = "release-integrity.yml"
        original = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        mutations = {
            "fixed tag": original.replace(
                "RELEASE_TAG: ${{ github.event_name == 'create' && github.event.ref || github.ref_name }}",
                'RELEASE_TAG: "surge-self-v2026.07.13.4"',
                1,
            ),
            "missing release token": original.replace(
                "        env:\n          GITHUB_TOKEN: ${{ github.token }}\n"
                "          RELEASE_TAG: ${{ github.event.release.tag_name }}\n",
                "        env:\n          RELEASE_TAG: ${{ github.event.release.tag_name }}\n",
                1,
            ),
            "missing audit token": original.replace(
                "        env:\n          GITHUB_TOKEN: ${{ github.token }}\n"
                "        run: python3 scripts/verify-surge-release.py --check-remote\n",
                "        run: python3 scripts/verify-surge-release.py --check-remote\n",
                1,
            ),
        }
        for mutation_name, changed in mutations.items():
            with self.subTest(mutation=mutation_name):
                self.assert_rejected(name, changed, original)


if __name__ == "__main__":
    unittest.main()
