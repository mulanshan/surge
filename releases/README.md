# Surge release manifests

Each `surge-self-v*.json` file records the exact script payloads associated with
a public release tag. Historical manifests keep the script set that actually
existed at that tag; the active manifest must cover every current script-backed
module.

- `active` identifies the one bundle that current script-backed modules must use.
- `superseded` records an intact older bundle that remains available for rollback.
- `retired-moved` records a historical tag whose ref no longer matches its
  published Release payload. It must never be referenced or reused.

The pre-manifest `camscanner-self-v1.0.0` tag is also `retired-moved`. Its frozen
remote commit and GitHub Release metadata are recorded in `retired-tags.json`,
while its migration is documented in `docs/RELEASE_PROCESS.md`. CamScanner now
ships only inside the unified release manifests.

Remote integrity is a closed-set audit: every remote `*-self-v*` tag and GitHub
Release must be represented by either a `surge-self-v*.json` manifest or the
explicit retired allowlist. Unknown and missing tags or Releases both fail.

Before opening a release pull request, update the active manifest and run:

```bash
python3 scripts/verify-surge-release.py
```

After pushing the tag and publishing the Release, run:

```bash
python3 scripts/verify-surge-release.py --tag <tag> --github-release
GITHUB_TOKEN="$(gh auth token)" python3 scripts/verify-surge-release.py --check-remote
```

The token is required so the audit can enumerate draft Releases as well as
published Releases. CI supplies its repository-scoped token automatically.
