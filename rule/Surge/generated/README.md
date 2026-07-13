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

Refresh upstream hashes and snapshots only on a review branch. Inspect the complete diff
and merge it through a PR; this command does not publish anything by itself:

```bash
scripts/generate-managed-surge-rules.py --refresh-sources
```

| ID | File | Suggested policy | Unique rules |
| --- | --- | --- | ---: |
| microsoft | `microsoft.list` | `DIRECT` | 671 |
| china-direct | `china-direct.list` | `DIRECT` | 3752 |
| private-tracker | `private-tracker.list` | `DIRECT` | 248 |
| apple | `apple.list` | `DIRECT` | 78 |
| google | `google.list` | `自动` | 698 |
| openai | `openai.list` | `自动` | 35 |
| telegram | `telegram.list` | `Proxy` | 30 |
| apple-tv | `apple-tv.list` | `流媒体` | 10 |
| youtube | `youtube.list` | `自动` | 190 |
| netflix | `netflix.list` | `绿云` | 1157 |
| bahamut | `bahamut.list` | `流媒体` | 8 |
| disney | `disney.list` | `流媒体` | 173 |
| hbo-usa | `hbo-usa.list` | `流媒体` | 11 |
| prime-video | `prime-video.list` | `流媒体` | 18 |
| streaming | `streaming.list` | `自动` | 321 |
| paypal | `paypal.list` | `自动` | 248 |
| global | `global.list` | `Proxy` | 1265 |
