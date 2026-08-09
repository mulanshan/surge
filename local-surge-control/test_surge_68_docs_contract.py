#!/usr/bin/env python3
"""Contract tests for the Surge Mac 6.8 remote-control documentation."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent
DOCUMENTS = {
    "skill": ROOT / "SKILL.md",
    "reference": ROOT / "references" / "surge-control-reference.md",
}
HELPER = ROOT / "scripts" / "surge-status.sh"
AGENT_METADATA = ROOT / "agents" / "openai.yaml"


class Surge68DocumentationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.docs = {name: path.read_text() for name, path in DOCUMENTS.items()}

    def test_remote_password_transport_never_uses_argv(self) -> None:
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertNotRegex(text, r"--remote\s+password@host:port")
                self.assertNotIn("no safe non-argv credential input", text.lower())
                self.assertIn("secure terminal prompt", text.lower())
                self.assertIn("--password-stdin", text)
                self.assertIn("SURGE_CLI_PASSWORD", text)
                self.assertRegex(text.lower(), r"(?:never|do not|must not)[^.\n]*argv")

    def test_remote_endpoint_syntax_includes_bracketed_ipv6(self) -> None:
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertIn("--remote host:port", text)
                self.assertIn("[addr]:port", text)

    def test_expanded_read_only_diagnostics_are_documented(self) -> None:
        required_commands = (
            "status",
            "version",
            "dump summary",
            "profile",
            "module",
            "feature",
            "log",
            "logbook",
            "proxy-runtime-status",
        )
        for name, text in self.docs.items():
            with self.subTest(document=name):
                for command in required_commands:
                    self.assertRegex(text, rf"`[^`]*\b{re.escape(command)}\b[^`]*`")

    def test_remaining_surge_68_commands_are_documented(self) -> None:
        required_commands = (
            "device",
            "reconnect-device",
            "script list",
            "script run",
            "script-log",
            "log watch",
            "benchmark encryption",
            "managed-profile update",
            "test-policy-bandwidth",
        )
        for name, text in self.docs.items():
            with self.subTest(document=name):
                for command in required_commands:
                    self.assertRegex(text, rf"`{re.escape(command)}`")

    def test_platform_and_remote_scope_is_explicit(self) -> None:
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertIn("Surge iOS 5.21.0", text)
                self.assertIn("Surge tvOS 5.21.0", text)
                self.assertRegex(
                    text,
                    r"(?s)Surge iOS 5\.21\.0.{0,240}Surge tvOS 5\.21\.0"
                    r".{0,240}`--remote`",
                )
                for command in ("device", "reconnect-device"):
                    self.assertRegex(
                        text,
                        rf"(?s)`{re.escape(command)}`.{{0,240}}"
                        r"(?:macOS-only|on macOS)",
                    )

    def test_execution_and_sensitive_output_boundaries_are_explicit(self) -> None:
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertRegex(
                    text,
                    r"(?s)`script run`.{0,320}(?:explicitly requested|explicit approval)",
                )
                self.assertRegex(
                    text,
                    r"(?s)`reconnect-device`.{0,320}"
                    r"(?:explicitly requested|explicit approval)",
                )
                self.assertRegex(
                    text,
                    r"(?s)`script-log`.{0,320}(?:read-only|does not run|do not rerun)",
                )
                self.assertRegex(
                    text,
                    r"(?s)`reconnect-device`.{0,640}`device`.{0,160}"
                    r"(?:read back|re-query|verify)",
                )
                self.assertRegex(
                    text,
                    r"(?s)`managed-profile update`.{0,480}"
                    r"(?:explicitly requested|explicit approval).{0,480}"
                    r"(?:profile current|status|read back|re-query|verify)",
                )
                self.assertRegex(
                    text,
                    r"(?s)`test-policy-bandwidth`.{0,360}"
                    r"(?:explicitly requested|explicit approval).{0,240}"
                    r"(?:bandwidth|traffic|data)",
                )
                self.assertRegex(text.lower(), r"unfiltered logs[^.]*sensitive")
                self.assertRegex(
                    text.lower(),
                    r"(?:device identifiers|mac addresses)[^.]*sensitive",
                )

    def test_mutations_require_resulting_state_verification(self) -> None:
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertIn("resulting state", text.lower())
                self.assertRegex(
                    text.lower(),
                    r"(?:re-query|query again|read back|verify)[^.\n]*(?:resulting state|state)",
                )

    def test_helper_does_not_claim_remote_auth_requires_argv(self) -> None:
        helper = HELPER.read_text()
        self.assertNotIn("exposes its credential in process arguments", helper)
        self.assertIn("HTTPS API only", helper)
        self.assertIn("--password-stdin", helper)

    def test_atv_default_profile_and_all_semantics_are_documented(self) -> None:
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertIn("DMIT-ATV.conf", text)
                self.assertIn("SURGE_ATV_PROFILE", text)
                self.assertRegex(
                    text,
                    r"A\s+missing\s+`SURGE_ATV_HOST`\s+is\s+an\s+intentional\s+"
                    r"`SKIP`\s+and\s+does\s+not\s+make\s+`all`\s+fail\.",
                )
                self.assertRegex(
                    text,
                    r"(?s)(?:Mac|macOS).{0,320}iOS.{0,320}"
                    r"(?:Apple TV|tvOS).{0,320}(?:matching|separate)"
                    r"[^.\n]*credential",
                )

    def test_ntp_warning_documents_the_confirmed_upstream_boundary(self) -> None:
        skill = self.docs["skill"]
        reference = self.docs["reference"]
        self.assertIn("SGNTPClient", skill)
        for address in (
            "17.253.114.125",
            "17.253.84.251",
            "17.253.114.253",
            "17.253.84.125",
            "17.253.84.123",
        ):
            self.assertIn(address, reference)
        for timing in ("15 seconds", "3600 seconds", "5 seconds"):
            self.assertIn(timing, reference)
        self.assertIn("time.apple.com", reference)
        self.assertIn("cannot be shown to fix", reference)
        self.assertIn("Do not patch the signed Surge app", reference)

    def test_agent_default_prompt_exposes_cli_and_https_control_paths(self) -> None:
        metadata = AGENT_METADATA.read_text(encoding="utf-8")
        self.assertIn("$local-surge-control", metadata)
        self.assertIn("Surge CLI 6.8", metadata)
        self.assertIn("HTTPS API", metadata)

    def test_cli_transport_and_interactive_diagnostics_are_documented(self) -> None:
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertRegex(text, r"(?i)quoted arguments")
                self.assertRegex(text, r"(?i)backslash escaping")
                self.assertRegex(text, r"(?i)(stalled|finite operations).{0,180}timeout")

    def test_command_option_contracts_cover_the_expanded_behaviors(self) -> None:
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertRegex(text, r"(?s)`policy-group[^`]*`.{0,320}`auto`")
                self.assertRegex(text, r"(?s)`module (?:enable|disable)[^`]*`.{0,240}multiple")
                self.assertRegex(text, r"`script-log <log-name> <session-id>`")
                self.assertIn("10,000", text)
                self.assertRegex(text, r"(?s)persistent.{0,240}memory|memory.{0,240}persistent")

    def test_mutation_readback_is_not_gated_on_mutation_success(self) -> None:
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertIn(
                    "Do not gate the read-back on the mutation's exit status",
                    text,
                )
        self.assertNotRegex(
            self.docs["reference"],
            r'(?m)^\s*"\$SURGE_CLI"[^\n]*&&',
        )

    def test_multi_instance_mutations_require_an_explicit_target(self) -> None:
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertIn("more than one Surge instance", text)
                self.assertRegex(
                    text,
                    r"(?s)more than one Surge instance.{0,320}exact target",
                )

    def test_script_log_identifiers_must_come_from_known_execution_metadata(self) -> None:
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertRegex(
                    text,
                    r"(?s)`script-log <log-name> <session-id>`.{0,480}"
                    r"(?:returned|provided).{0,160}(?:metadata|identifiers)",
                )
                self.assertRegex(text, r"(?i)do not guess[^.]*session")

    def test_unfiltered_logs_do_not_enter_the_agent_transcript(self) -> None:
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertRegex(
                    text,
                    r"(?s)(?:bare|directly).{0,120}`log (?:file|memory)"
                    r".{0,480}(?:trusted local summarizer|aggregate counts)"
                    r".{0,320}transcript",
                )


if __name__ == "__main__":
    unittest.main()
