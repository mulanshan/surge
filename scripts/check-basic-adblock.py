#!/usr/bin/env python3
"""Validate the canonical and legacy Basic AdBlock Surge modules."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "rewrite/Surge/basic-adblock.sgmodule"
LEGACY = ROOT / "rewrite/Surge/fanqie-novel-adblock.sgmodule"
README = ROOT / "README.md"
CAMSCANNER = ROOT / "rewrite/Surge/camscanner-self.sgmodule"

FORBIDDEN_SECTIONS = {"[Script]", "[MITM]", "[URL Rewrite]", "[Map Local]"}
FORBIDDEN_TOKENS = {
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
EXPECTED_FANQIE_RULES = {
    "log0-applog-lq.fqnovel.com",
    "log3-applog.fqnovel.com",
    "log3-applog-lq.fqnovel.com",
    "log5-applog.fqnovel.com",
    "log5-applog-lq.fqnovel.com",
    "rtlog3-applog.fqnovel.com",
    "rtlog3-applog-lq.fqnovel.com",
    "rtlog5-applog.fqnovel.com",
    "rtlog5-applog-lq.fqnovel.com",
    "mon11-misc-lq.fqnovel.com",
    "mon11-misc.fqnovel.com",
    "mon3-misc-lq.fqnovel.com",
    "mon3-misc.fqnovel.com",
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

    actual_fanqie_rules = set()
    for rule in canonical_rules:
        parts = [part.strip() for part in rule.split(",")]
        if len(parts) != 3 or parts[0] not in {"DOMAIN", "DOMAIN-SUFFIX"}:
            raise SystemExit(f"unsupported rule shape: {rule}")
        if parts[2] != "REJECT":
            raise SystemExit(f"module policy must be REJECT: {rule}")
        if any(token in parts[1] for token in FORBIDDEN_TOKENS):
            raise SystemExit(f"app-specific or high-risk domain in base module: {rule}")
        if parts[1].endswith(".fqnovel.com"):
            if parts[0] != "DOMAIN" or parts[1] not in EXPECTED_FANQIE_RULES:
                raise SystemExit(f"unsafe Fanqie rule in base module: {rule}")
            actual_fanqie_rules.add(parts[1])

    if actual_fanqie_rules != EXPECTED_FANQIE_RULES:
        missing = sorted(EXPECTED_FANQIE_RULES - actual_fanqie_rules)
        extra = sorted(actual_fanqie_rules - EXPECTED_FANQIE_RULES)
        raise SystemExit(f"Fanqie allowlist mismatch; missing={missing}, extra={extra}")

    readme = README.read_text(encoding="utf-8")
    if "RULE-SET,https://raw.githubusercontent.com/mulanshan/surge/main/rule/Surge/fanqie-novel-adblock.list" in readme:
        raise SystemExit("README still recommends the legacy advertising RULE-SET")

    camscanner = CAMSCANNER.read_text(encoding="utf-8")
    if not camscanner.startswith("#!name=扫描全能王\n"):
        raise SystemExit("current CamScanner module must use the canonical display name")
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

    exporter = (ROOT / "rule/Surge/scripts/export-fanqie-candidates.sh").read_text(encoding="utf-8")
    removed_fanqie_module = "fanqie-novel-" + "self.sgmodule"
    if "basic-adblock.sgmodule" not in exporter or removed_fanqie_module in exporter:
        raise SystemExit("Fanqie candidate exporter must use only the Basic AdBlock module")

    print(f"basic-adblock OK: {len(canonical_rules)} rules; no script, MITM, rewrite, or mixed business domains")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
