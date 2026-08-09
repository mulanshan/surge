#!/usr/bin/env python3
"""Syntax gate for every distributed ruleset file.

Surge skips invalid RULE-SET lines with a warning. Because `main` is the live
distribution channel, a bad hand edit could silently remove intended routing
coverage on every subscribed device even though the rest of the set loads.

`surge-cli --check` does not close this gap: verified empirically on Surge Mac
6.7.0 (build 11730), it validates profile syntax only and returns OK even when
a referenced local rule-set file contains invalid lines or does not exist.
This test is therefore the authoritative syntax gate for rule payloads.
"""

from __future__ import annotations

import ipaddress
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent

# Rule types allowed inside RULE-SET payload files. Keep this list tight and
# grow it deliberately: an unknown type is more likely a typo than a feature.
ALLOWED_RULE_TYPES = {
    "DOMAIN",
    "DOMAIN-SUFFIX",
    "DOMAIN-KEYWORD",
    "DOMAIN-WILDCARD",
    "PROCESS-NAME",
    "USER-AGENT",
    "URL-REGEX",
    "IP-CIDR",
    "IP-CIDR6",
    "IP-ASN",
    "GEOIP",
    "DEST-PORT",
    "SRC-IP",
    "PROTOCOL",
}

# Rule-set payload lines never carry a policy; trailing entries after the
# argument must come from this option vocabulary.
ALLOWED_OPTIONS = {"no-resolve", "extended-matching", "pre-matching"}

HOSTNAME_RE = re.compile(r"^[A-Za-z0-9*?][A-Za-z0-9.*?_-]*$")
DOMAINSET_LINE_RE = re.compile(r"^\.?[A-Za-z0-9][A-Za-z0-9._-]*$")


def iter_rule_files():
    patterns = ("rule/Surge/*.list", "rule/Surge/generated/*.list", "rule/Loon/*.list")
    for pattern in patterns:
        yield from sorted(ROOT.glob(pattern))


def iter_domainset_files():
    yield from sorted(ROOT.glob("rule/Surge/generated/*.domainset"))


def payload_lines(path: Path):
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        if stripped != line:
            yield lineno, line, "leading or trailing whitespace"
            continue
        yield lineno, line, None


class RuleListSyntaxTests(unittest.TestCase):
    def test_rule_list_files_contain_only_valid_rule_lines(self):
        checked = 0
        for path in iter_rule_files():
            checked += 1
            for lineno, line, complaint in payload_lines(path):
                where = f"{path.relative_to(ROOT)}:{lineno}"
                with self.subTest(location=where):
                    self.assertIsNone(complaint, f"{where}: {complaint}: {line!r}")
                    parts = line.split(",")
                    self.assertGreaterEqual(len(parts), 2, f"{where}: not a TYPE,argument rule: {line!r}")
                    rule_type, argument = parts[0], parts[1]
                    self.assertIn(rule_type, ALLOWED_RULE_TYPES, f"{where}: unknown rule type: {line!r}")
                    self.assertTrue(argument, f"{where}: empty argument: {line!r}")
                    for option in parts[2:]:
                        self.assertIn(option, ALLOWED_OPTIONS, f"{where}: unknown option: {line!r}")
                    # USER-AGENT / PROCESS-NAME / URL-REGEX arguments are free-form
                    # matchers (spaces are legal, e.g. "USER-AGENT,Prime Video*");
                    # skip only their argument shape checks, not trailing fields.
                    if rule_type in {"USER-AGENT", "PROCESS-NAME", "URL-REGEX"}:
                        continue
                    self.assertNotIn(" ", argument, f"{where}: whitespace in argument: {line!r}")
                    if rule_type in {"DOMAIN", "DOMAIN-SUFFIX"}:
                        self.assertRegex(argument, HOSTNAME_RE, f"{where}: invalid domain argument: {line!r}")
                    # DOMAIN-KEYWORD is a substring matcher: leading dots or
                    # dashes (".tmall.com", "-spotify-com") are legitimate.
                    if rule_type in {"IP-CIDR", "IP-CIDR6"}:
                        family = 4 if rule_type == "IP-CIDR" else 6
                        label = "IPv4" if family == 4 else "IPv6"
                        try:
                            network = ipaddress.ip_network(argument, strict=False)
                        except ValueError:
                            self.fail(f"{where}: invalid {label} CIDR: {line!r}")
                        self.assertIn("/", argument, f"{where}: invalid {label} CIDR: {line!r}")
                        self.assertEqual(
                            network.version,
                            family,
                            f"{where}: invalid {label} CIDR: {line!r}",
                        )
        self.assertGreaterEqual(checked, 10, "rule list sweep found suspiciously few files")

    def test_domainset_files_contain_only_domains(self):
        checked = 0
        for path in iter_domainset_files():
            checked += 1
            for lineno, line, complaint in payload_lines(path):
                where = f"{path.relative_to(ROOT)}:{lineno}"
                with self.subTest(location=where):
                    self.assertIsNone(complaint, f"{where}: {complaint}: {line!r}")
                    self.assertNotIn(",", line, f"{where}: DOMAIN-SET lines must be bare domains: {line!r}")
                    self.assertRegex(line, DOMAINSET_LINE_RE, f"{where}: invalid domain-set entry: {line!r}")
        self.assertGreaterEqual(checked, 5, "domain-set sweep found suspiciously few files")


class RuleListSyntaxRegressionTests(unittest.TestCase):
    def assert_rule_sweep_rejects(self, invalid_line: str, expected_message: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            rules_dir = temporary_root / "rule/Surge"
            rules_dir.mkdir(parents=True)
            for index in range(10):
                payload = f"DOMAIN,fixture-{index}.example\n"
                if index == 0:
                    payload += invalid_line + "\n"
                (rules_dir / f"fixture-{index}.list").write_text(payload, encoding="utf-8")

            case = RuleListSyntaxTests("test_rule_list_files_contain_only_valid_rule_lines")
            result = unittest.TestResult()
            with mock.patch.object(sys.modules[__name__], "ROOT", temporary_root):
                case.run(result)

        failures = "\n".join(message for _case, message in [*result.failures, *result.errors])
        self.assertFalse(result.wasSuccessful(), f"syntax sweep accepted {invalid_line!r}")
        self.assertIn(expected_message, failures)

    def test_free_form_matchers_cannot_hide_a_policy_or_unknown_option(self):
        for rule_type in ("USER-AGENT", "PROCESS-NAME", "URL-REGEX"):
            with self.subTest(rule_type=rule_type):
                self.assert_rule_sweep_rejects(
                    f"{rule_type},fixture matcher,DIRECT",
                    "unknown option",
                )

    def test_ipv4_cidr_requires_a_valid_network_and_prefix(self):
        for argument in ("999.999.999.999/99", "192.0.2.0/33", "192.0.2.1"):
            with self.subTest(argument=argument):
                self.assert_rule_sweep_rejects(
                    f"IP-CIDR,{argument},no-resolve",
                    "invalid IPv4 CIDR",
                )

    def test_ipv6_cidr_requires_a_valid_network_and_prefix(self):
        for argument in ("not-an-ipv6/64", "2001:db8::/129", "2001:db8::1"):
            with self.subTest(argument=argument):
                self.assert_rule_sweep_rejects(
                    f"IP-CIDR6,{argument},no-resolve",
                    "invalid IPv6 CIDR",
                )


if __name__ == "__main__":
    unittest.main()
