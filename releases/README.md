# Surge release manifests

Each `surge-self-v*.json` file records the exact five script payloads associated
with a public release tag.

- `active` identifies the one bundle that current script-backed modules must use.
- `retired-moved` records a historical tag whose ref no longer matches its
  published Release payload. It must never be referenced or reused.

Before opening a release pull request, update the active manifest and run:

```bash
python3 scripts/verify-surge-release.py
```

After pushing the tag and publishing the Release, run:

```bash
python3 scripts/verify-surge-release.py --tag <tag> --github-release
python3 scripts/verify-surge-release.py --check-remote
```
