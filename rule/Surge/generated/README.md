# Generated Surge Rules

These files are generated mirrors of selected upstream rulesets. Each source is pinned
by SHA-256 in `../sources/managed-rules.yaml`; generated lists contain no policy field.

Check the pinned sources and committed snapshots without writing:

```bash
scripts/generate-managed-surge-rules.py --check
```

Regenerate from already-reviewed, pinned sources:

```bash
scripts/generate-managed-surge-rules.py --update
```

Compare all moving tracking URLs with the reviewed build inputs:

```bash
scripts/generate-managed-surge-rules.py --check-upstream
```

Refresh one reviewed snapshot on a branch, or atomically repin every remote source
to an explicitly reviewed GitHub commit. Both modes require a rule-set scope:

```bash
scripts/generate-managed-surge-rules.py --refresh-sources --only global
scripts/generate-managed-surge-rules.py --refresh-sources --only microsoft --source-commit <40hex>
```

| ID | Compatibility file | Optimized files | Suggested policy | Unique rules |
| --- | --- | --- | --- | ---: |
| microsoft | `microsoft.list` | `microsoft.domainset` (664) + `microsoft.non-domain.list` (7) | `DIRECT` | 671 |
| china-direct | `china-direct.list` | `china-direct.domainset` (3691) + `china-direct.non-domain.list` (61) | `DIRECT` | 3752 |
| private-tracker | `private-tracker.list` | `private-tracker.domainset` (241) + `private-tracker.non-domain.list` (7) | `DIRECT` | 248 |
| apple-bm7 | `apple-bm7.list` | - | `DIRECT` | 53 |
| apple-sukka | `apple-sukka.list` | - | `DIRECT` | 35 |
| google | `google.list` | `google.domainset` (685) + `google.non-domain.list` (13) | `自动` | 698 |
| openai | `openai.list` | - | `自动` | 35 |
| telegram | `telegram.list` | - | `Proxy` | 29 |
| apple-tv | `apple-tv.list` | - | `流媒体` | 10 |
| youtube | `youtube.list` | `youtube.domainset` (179) + `youtube.non-domain.list` (11) | `自动` | 190 |
| netflix | `netflix.list` | - | `绿云` | 1157 |
| bahamut | `bahamut.list` | - | `流媒体` | 8 |
| disney | `disney.list` | `disney.domainset` (172) + `disney.non-domain.list` (1) | `流媒体` | 173 |
| hbo-usa | `hbo-usa.list` | - | `流媒体` | 11 |
| prime-video | `prime-video.list` | - | `流媒体` | 18 |
| streaming | `streaming.list` | `streaming.domainset` (258) + `streaming.non-domain.list` (63) | `自动` | 321 |
| paypal | `paypal.list` | `paypal.domainset` (246) + `paypal.non-domain.list` (2) | `自动` | 248 |
| global | `global.list` | `global.domainset` (1255) + `global.non-domain.list` (10) | `Proxy` | 1265 |
