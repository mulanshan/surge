#!/usr/bin/env python3
"""Syntax gate for every distributed ruleset file.

Surge validates DOMAIN-SET and RULE-SET resources strictly: a single invalid
line invalidates the entire rule set (not just the offending line). Because
`main` is the live distribution channel, one bad hand edit could silently kill
a whole ruleset on every subscribed device.

`surge-cli --check` does not close this gap: verified empirically on Surge Mac
6.7.0 (build 11730), it validates profile syntax only and returns OK even when
a referenced local rule-set file contains invalid lines or does not exist.
This test is therefore the authoritative syntax gate for rule payloads.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

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
IPV4_CIDR_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?$")


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
                    # USER-AGENT / PROCESS-NAME / URL-REGEX arguments are free-form
                    # matchers (spaces are legal, e.g. "USER-AGENT,Prime Video*");
                    # skip the strict shape checks for them.
                    if rule_type in {"USER-AGENT", "PROCESS-NAME", "URL-REGEX"}:
                        continue
                    self.assertNotIn(" ", argument, f"{where}: whitespace in argument: {line!r}")
                    for option in parts[2:]:
                        self.assertIn(option, ALLOWED_OPTIONS, f"{where}: unknown option: {line!r}")
                    if rule_type in {"DOMAIN", "DOMAIN-SUFFIX"}:
                        self.assertRegex(argument, HOSTNAME_RE, f"{where}: invalid domain argument: {line!r}")
                    # DOMAIN-KEYWORD is a substring matcher: leading dots or
                    # dashes (".tmall.com", "-spotify-com") are legitimate.
                    if rule_type == "IP-CIDR":
                        self.assertRegex(argument, IPV4_CIDR_RE, f"{where}: invalid IPv4 CIDR: {line!r}")
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


if __name__ == "__main__":
    unittest.main()
