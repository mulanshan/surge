# Surge release manifests

Each `surge-self-v*.json` file records the exact script payloads associated with
a release tag. When a release introduces a script-backed module, its candidate
module path and SHA-256 are recorded too. Historical manifests keep the script
set that actually existed at that tag. Schema version 2 keeps four independent
decisions explicit:

- `integrity`: whether the tag is `intact` or `retired-moved`.
- `distribution`: `candidate`, `active`, `inactive`, `rejected`, or
  `retired`. Only `active` means that canonical module files currently pin
  this tag; it is not a stability claim.
- `live_device_validation`: `pending`, `passed`, `failed`, or `not-recorded`.
- `live_device_evidence`: a repository Markdown heading required for `passed`
  and `failed`. Future evidence headings use
  `Live-device evidence for <tag>` / `live-device-evidence-for-...`, identify the
  exact manifest tag, and record the exact `release_commit`. Evidence for one
  tag must not be reused by another tag. Validation covers the documented
  release change surface rather than asserting that every unrelated module in
  the bundle is stable.
- `live_device_evidence_sha256`: the immutable hash of that complete heading
  section, checked against the repository text.
- `rollback_eligible`: whether an intact, inactive and validated bundle has also
  been reviewed as compatible with every current script-backed module.
- `rollback_evidence` and `rollback_evidence_sha256`: an append-only repository
  heading and complete-section hash required before `rollback_eligible` can be
  true. The evidence remains after revocation as provenance and cannot be reused
  to recertify the same bundle.

The exact historical evidence references for `surge-self-v2026.07.13.1` and
`surge-self-v2026.07.13.4` are the only legacy exceptions to the tag-specific
heading format. They remain hash-checked and cannot be used by a future tag.

The manifest validator requires one active distribution, at most one candidate,
and a complete reciprocal `supersedes` / `superseded_by` chain. A rollback can
select an older eligible distribution without rewriting that release history.
Pending or failed live validation must never be presented as stable.
PR and `main` CI also compare these records with the event's trusted base SHA;
manual CI runs require an explicit base SHA and are limited to the default
branch. Historical records and existing retired-tag entries cannot be removed
or rewritten into a different but still internally consistent snapshot. Each
change must match exactly one lifecycle transaction: create, register, validate,
activate, reject, delete an untagged candidate, certify or revoke rollback,
rollback, or record the legacy result. A retired-tag addition is separate too.

These manifests protect the immutable script bundle and the exact candidate
module bytes for newly introduced scripts. Existing mutable canonical module
definitions and generated rule assets on `main` retain the independent gates
documented in `docs/RELEASE_PROCESS.md`.

When a candidate adds script-backed modules that are absent from the active
distribution, their non-public definitions live under `rewrite/Surge/candidates/`
and pin the candidate tag. Their manifest `modules` records freeze the reviewed
path and SHA-256 at the same `release_commit` as the scripts. The worktree verifier
requires a closed module inventory, existing canonical modules to keep the active
tag, and candidate pins only for names missing from that active manifest. After
passed device evidence, activation moves the new definitions to canonical
top-level paths, updates the verifier mapping, and removes the staged copies. A
historical rollback bundle remains eligible only while its inventory matches the
current active script inventory.

`surge-self-v2026.07.27.1` is the sole recorded legacy exception: it became
active before live validation and therefore remains explicitly pending. New
active distributions must have `live_device_validation: passed`. Its
`legacy_unvalidated_activation` flag remains as provenance after any later
validation or rollback.

The pre-manifest `camscanner-self-v1.0.0` tag is also `retired-moved`. Its frozen
remote commit and GitHub Release metadata are recorded in `retired-tags.json`,
while its migration is documented in `docs/RELEASE_PROCESS.md`. CamScanner now
ships only inside the unified release manifests.

Remote integrity is a closed-set audit: every released `*-self-v*` tag and
GitHub Release must be represented by either a `surge-self-v*.json` manifest or
the explicit retired allowlist. A pre-registered candidate may have no remote
tag yet; if its tag exists, its commit and payload are verified. A candidate
must be activated before a GitHub Release is created. Unknown tags and Releases,
and missing released entries, fail.

First merge the candidate payload manifest without `release_commit`. In a second
pull request, record the exact payload commit and merge that registration to the
protected default branch. Run after each phase:

```bash
python3 scripts/verify-surge-release.py
```

Only then create the tag locally at the registered commit and run the tag
verifier before pushing the immutable remote tag. Complete candidate-device
validation before switching canonical module pins and the active distribution.
After activation and GitHub Release publication, run:

```bash
python3 scripts/verify-surge-release.py --tag <tag> --github-release
GITHUB_TOKEN="$(gh auth token)" python3 scripts/verify-surge-release.py --check-remote
```

The token is required so the audit can enumerate draft Releases as well as
published Releases. CI supplies its repository-scoped token automatically.
