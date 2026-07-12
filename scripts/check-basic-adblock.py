#!/usr/bin/env python3
"""Validate the canonical and legacy Basic AdBlock Surge modules."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "rewrite/Surge/basic-adblock.sgmodule"
LEGACY = ROOT / "rewrite/Surge/fanqie-novel-adblock.sgmodule"
README = ROOT / "README.md"
CAMSCANNER = ROOT / "rewrite/Surge/camscanner-self.sgmodule"
FANQIE_SELF = ROOT / "rewrite/Surge/fanqie-novel-self.sgmodule"

FORBIDDEN_SECTIONS = {"[Script]", "[MITM]", "[URL Rewrite]", "[Map Local]"}
FORBIDDEN_TOKENS = {
    "fqnovel.com",
    "fanqienovel.com",
    "fqnovelpic.com",
    "fqnovelvod.com",
    "bytegecko.com",
    "douyinpic.com",
    "ecombdapi.com",
    "ecombdimg.com",
    "ydycdn.com",
    "manlaxycloud.com",
    "amap.com",
    "intsig.net",
    "camscanner.com",
    "jd.com",
    "youtube.com",
    "instagram.com",
    "appsflyer.com",
    "adjust.com",
    "app-measurement.com",
}


def module_rules(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    sections = {line.strip() for line in lines if line.startswith("[")}
    forbidden = sorted(sections & FORBIDDEN_SECTIONS)
    if forbidden:
        raise SystemExit(f"{path}: forbidden section(s): {', '.join(forbidden)}")
    if "[Rule]" not in sections:
        raise SystemExit(f"{path}: missing [Rule]")

    rules: list[str] = []
    in_rule = False
    for raw in lines:
        line = raw.strip()
        if line == "[Rule]":
            in_rule = True
            continue
        if in_rule and line.startswith("["):
            break
        if in_rule and line and not line.startswith("#"):
            rules.append(line)
    return rules


def main() -> int:
    canonical_text = CANONICAL.read_text(encoding="utf-8")
    legacy_text = LEGACY.read_text(encoding="utf-8")
    if not canonical_text.startswith("#!name=基础去广告模块\n"):
        raise SystemExit("canonical module name must be 基础去广告模块")
    if "旧“番茄小说去广告”订阅地址" not in legacy_text:
        raise SystemExit("legacy module must explain its compatibility role")

    canonical_rules = module_rules(CANONICAL)
    legacy_rules = module_rules(LEGACY)
    if canonical_rules != legacy_rules:
        raise SystemExit("legacy and canonical module rule bodies differ")
    if len(canonical_rules) < 25:
        raise SystemExit(f"unexpectedly small rule set: {len(canonical_rules)}")
    if len(canonical_rules) != len(set(canonical_rules)):
        raise SystemExit("duplicate rules found")

    for rule in canonical_rules:
        parts = [part.strip() for part in rule.split(",")]
        if len(parts) != 3 or parts[0] not in {"DOMAIN", "DOMAIN-SUFFIX"}:
            raise SystemExit(f"unsupported rule shape: {rule}")
        if parts[2] != "REJECT":
            raise SystemExit(f"module policy must be REJECT: {rule}")
        if any(token in parts[1] for token in FORBIDDEN_TOKENS):
            raise SystemExit(f"app-specific or high-risk domain in base module: {rule}")

    readme = README.read_text(encoding="utf-8")
    if "RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/fanqie-novel-adblock.list" in readme:
        raise SystemExit("README still recommends the legacy advertising RULE-SET")

    camscanner = CAMSCANNER.read_text(encoding="utf-8")
    if not camscanner.startswith("#!name=扫描全能王 Self v2\n"):
        raise SystemExit("current CamScanner module must use the v2 display name")
    migrated_tokens = {
        "doubleclick.net",
        "googleadservices.com",
        "googlesyndication.com",
        "a.gdt.qq.com",
        "sdk.e.qq.com",
        "apmplus.volces.com",
        "appsflyer.com",
        "app-measurement.com",
        "adjust.com",
    }
    leftovers = sorted(token for token in migrated_tokens if token in camscanner)
    if leftovers:
        raise SystemExit(f"generic third-party rules remain in CamScanner module: {', '.join(leftovers)}")

    fanqie_self = FANQIE_SELF.read_text(encoding="utf-8")
    for required in ("#!name=番茄小说 Self", "[Rule]", "[URL Rewrite]", "[MITM]", "log0-applog-lq.fqnovel.com"):
        if required not in fanqie_self:
            raise SystemExit(f"Fanqie Self missing required content: {required}")
    for risky in ("bytegecko.com", "douyinpic.com", "ecombdapi.com", "ecombdimg.com", "minigame", "webcast-open.douyin.com"):
        if risky in fanqie_self:
            raise SystemExit(f"high-risk mixed content domain remains in Fanqie Self: {risky}")

    exporter = (ROOT / "rule/Surge/scripts/export-fanqie-candidates.sh").read_text(encoding="utf-8")
    for required_path in ("basic-adblock.sgmodule", "fanqie-novel-self.sgmodule"):
        if required_path not in exporter:
            raise SystemExit(f"Fanqie candidate exporter does not load {required_path}")

    print(f"basic-adblock OK: {len(canonical_rules)} rules; no script, MITM, rewrite, or app-specific domains")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
