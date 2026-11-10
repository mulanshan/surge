#!/usr/bin/env python3
"""Check representative AI requests against the distributed rule order."""

from pathlib import Path
import unittest
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def payload(path):
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "["))
    ]


def matches(rule, host):
    kind, _, value = rule.partition(",")
    value = value.split(",")[0]
    if kind == "DOMAIN":
        return host == value
    if kind == "DOMAIN-SUFFIX":
        return host == value or host.endswith("." + value)
    if kind == "DOMAIN-KEYWORD":
        return value in host
    return False


def template_policy(host):
    for line in payload(ROOT / "rule/Surge/generated/rule-section-managed.conf"):
        parts = line.split(",")
        if parts[0] not in {"RULE-SET", "DOMAIN-SET"}:
            if len(parts) > 2 and matches(line, host):
                return parts[2]
            continue
        remote_path = urlsplit(parts[1]).path
        marker = "/rule/Surge/"
        if marker not in remote_path:
            continue
        path = ROOT / "rule/Surge" / remote_path.split(marker, 1)[1]
        for rule in payload(path):
            if parts[0] == "DOMAIN-SET":
                rule = ("DOMAIN-SUFFIX," + rule[1:]) if rule.startswith(".") else "DOMAIN," + rule
            if matches(rule, host):
                return parts[2]
    return None


class AIRoutingTests(unittest.TestCase):
    def test_ai_requests_use_us_before_broad_vendor_or_china_rules(self):
        for host in (
            "muse.ai", "api.muse.ai", "www.meta.ai", "vm.metaaivm.com",
            "api.anthropic.com", "claude.ai", "claude.com", "files.claudeusercontent.com",
            "chatgpt.com", "api.openai.com", "cdn.oaistatic.com", "files.oaiusercontent.com",
            "copilot.microsoft.com", "api.githubcopilot.com", "copilot-proxy.githubusercontent.com",
            "gemini.google.com", "generativelanguage.googleapis.com", "notebooklm-pa.googleapis.com",
            "cloudaicompanion.googleapis.com", "cursor.com", "api.openrouter.ai", "api.groq.com",
            "manus.im", "midjourney.com", "api.elevenlabs.io", "api.deepseek.com", "chat.qwen.ai",
            "kimi.com", "doubao.com", "open.bigmodel.cn", "yuanbao.tencent.com",
        ):
            with self.subTest(host=host):
                self.assertEqual(template_policy(host), "us")

    def test_expanded_ai_list_does_not_claim_whole_vendors_or_ai_tld(self):
        rules = payload(ROOT / "rule/Surge/ai.list")
        for host in ("google.com", "mail.google.com", "microsoft.com", "login.microsoftonline.com", "github.com", "ordinary.ai", "notmuse.ai"):
            with self.subTest(host=host):
                self.assertFalse(any(matches(rule, host) for rule in rules))


if __name__ == "__main__":
    unittest.main()
