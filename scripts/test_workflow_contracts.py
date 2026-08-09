#!/usr/bin/env python3
"""Regression tests for the structured GitHub workflow contracts."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_workflow_contracts.rb"
WORKFLOW_NAMES = ("ci.yml", "release-integrity.yml", "rules-drift.yml")


class WorkflowContractTests(unittest.TestCase):
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
