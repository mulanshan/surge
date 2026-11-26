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
            "auth.meta.com", "accountscenter.meta.com",
            "www.facebook.com", "accountscenter.facebook.com", "www.instagram.com", "x.com", "twitter.com",
            "www.threads.net", "web.whatsapp.com", "www.reddit.com", "discord.com", "cdn.discordapp.com",
            "www.google.com", "www.youtube.com",
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

    def test_social_list_uses_exact_suffixes_without_keyword_rules(self):
        rules = payload(ROOT / "rule/Surge/social.list")
        self.assertTrue(rules)
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertTrue(rule.startswith(("DOMAIN,", "DOMAIN-SUFFIX,")))

    def test_shopping_list_routes_storefront_and_payment_chain_to_ziliudi(self):
        rules = payload(ROOT / "rule/Surge/shopping.list")
        self.assertTrue(rules)
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertTrue(rule.startswith(("DOMAIN,", "DOMAIN-SUFFIX,")))
        for host in (
            "www.oyunfor.com",
            "node2.oyunfor.com",
            "www.paytr.com",
            "acs.bkm.com.tr",
            "3dsecure.isbank.com.tr",
        ):
            with self.subTest(host=host):
                self.assertEqual(template_policy(host), "自留地")

    def test_web_video_list_routes_sites_and_media_cdns_to_us(self):
        rules = payload(ROOT / "rule/Surge/web-video.list")
        self.assertTrue(rules)
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertTrue(rule.startswith(("DOMAIN,", "DOMAIN-SUFFIX,")))
        for host in (
            "www.pornhub.com",
            "ev.phncdn.com",
            "di.phprcdn.com",
            "madou.club",
            "www.xvideos.com",
            "jable.tv",
            "missav.ws",
            "www.twitch.tv",
            "usher.ttvnw.net",
            "player.vimeo.com",
        ):
            with self.subTest(host=host):
                self.assertEqual(template_policy(host), "us")

    def test_hbo_asia_and_bahamut_sanitization_routing(self):
        for host in (
            "www.max.com",
            "play.hbomax.com",
            "www.hbogoasia.com",
            "api.hbogoasia.hk",
            "hbolb.onwardsmg.com",
            "hbounify-prod.evergent.com",
            "cdn.warnermediacdn.com",
        ):
            with self.subTest(host=host):
                self.assertEqual(template_policy(host), "流媒体")
        for host in ("ani.gamer.com.tw", "bahamut.akamaized.net", "www.douban.com", "movie.douban.com"):
            with self.subTest(host=host):
                self.assertEqual(template_policy(host), "hinet")
        self.assertNotEqual(template_policy("ocsp.digicert.com"), "hinet")
        self.assertNotEqual(template_policy("ocsp.digicert.com"), "流媒体")

    def test_cookie_sync_hosts_match_mulanshan_sing_box_exits(self):
        # Cookie-bearing hosts must leave through the same exit as the
        # mulanshan sing-box gateway (X-Ins-Fixed -> dmit-us == Surge `us`).
        for host in ("x.com", "pbs.twimg.com", "t.co", "www.instagram.com", "ig.me", "scontent.cdninstagram.com"):
            with self.subTest(host=host):
                self.assertEqual(template_policy(host), "us")
        # The cookieless douban image CDN stays DIRECT on both gateways.
        douban_rules = payload(ROOT / "rule/Surge/douban.list")
        self.assertFalse(any(matches(rule, "img1.doubanio.com") for rule in douban_rules))
        self.assertEqual(template_policy("img1.doubanio.com"), "DIRECT")


if __name__ == "__main__":
    unittest.main()
