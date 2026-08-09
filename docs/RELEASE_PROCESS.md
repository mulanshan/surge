# Release Process

The repository is a production distribution source. A push to `main` can change
the module or ruleset consumed by an installed Surge instance, so every change
must go through a branch, CI, and review. Immutable release manifests protect
the script bundle pinned by script-backed modules. Mutable `main` module
definitions and generated rules are not covered by the script release manifest;
they are protected separately by repository invariants, source hashes, generated
byte comparison, and live profile validation.

## Channels

- `main`: latest reviewed module definitions, documentation, and generated rule
  snapshots. Public install URLs point here so module metadata can move to a
  different active distribution without reinstalling the module.
- `surge-self-vYYYY.MM.DD[.N]`: immutable release bundle. Use the optional patch
  suffix when a release on the same date supersedes an earlier bundle. A tag is
  not called stable merely because it exists or is the active distribution.
- candidate manifest: a release payload registered on protected `main` before
  its tag is created. Canonical modules continue to use the current active
  distribution while the candidate is tagged and tested.
- feature branches: development only. Do not reference a feature branch from a
  public module.

## Manifest state

Schema version 2 records independent facts instead of overloading `active`:

- `integrity`: `intact` or `retired-moved`.
- `distribution`: `candidate`, `active`, `inactive`, `rejected`, or
  `retired`. Exactly one manifest is active; this means only that canonical
  module pins use it.
- `live_device_validation`: `pending`, `passed`, `failed`, or `not-recorded`.
- `live_device_evidence`: required for `passed` or `failed`; it must point to a
  real heading in `docs/*.md` or `CHANGELOG.md` named
  `Live-device evidence for <tag>`. Its generated anchor must begin with
  `live-device-evidence-for-` and identify that exact manifest tag. The section
  must contain the exact `release_commit`, device, Surge version, time,
  exercised release change surface, and result. Evidence for one tag must not be
  reused by another tag.
- `live_device_evidence_sha256`: SHA-256 of that complete Markdown heading
  section. The verifier recomputes it so preserving an anchor while rewriting
  the evidence cannot silently change a historical result.
- `rollback_eligible`: an explicit boolean. It may be true only for an intact,
  inactive, live-device-validated bundle that contains every current script and
  has been reviewed for compatibility with the current modules.
- `rollback_evidence` and `rollback_evidence_sha256`: a dedicated, append-only
  Markdown heading and its complete-section hash. They are required when
  `rollback_eligible` is true and remain as provenance after revocation.

The two pre-schema-2 passed results, `surge-self-v2026.07.13.1` and
`surge-self-v2026.07.13.4`, retain their exact historical `CHANGELOG.md`
references as a closed legacy allowlist. No future tag may use those headings.

`passed` covers the documented release change surface, not every unrelated
module in the bundle. Module-level stability remains in `docs/MODULE_STATUS.md`.
The reciprocal `supersedes` / `superseded_by` fields form one immutable,
connected, acyclic release history. Distribution rollback changes which node is
active; it does not rewrite that history. A bundle with pending or failed live
validation must not be described as stable.

CI runs `verify-surge-release.py --check-transitions <base-sha>` against the PR
base or pre-push commit. Manual runs require an exact 40-character base commit
and execute only from the default branch. The verifier rejects all-zero,
unresolved, current-HEAD, and non-ancestor baselines. Published payload fields,
evidence sections, completed results, existing edges, notes, and retired-tag
records are append-only.

Every pull request must match exactly one state transaction: candidate creation,
commit registration, device validation, activation, rejection, deletion of an
untagged pre-registration, rollback certification, rollback revocation,
distribution rollback, or the documented legacy result path. Registration and
validation cannot be combined; validation and rejection cannot be combined;
activation cannot grant rollback eligibility. A retired-tag addition is also a
standalone transaction.

## Required gates

### A. Prepare the payload on protected main

1. Run the repository CI suite locally.
2. Review generated-rule source hashes and normalized rule diffs. Never accept an
   upstream drift only because generation succeeded.
3. Verify that response scripts do not issue network requests, read credentials,
   or log raw request/response bodies.
4. Validate the shared Surge profile with `surge-cli profile check <name>`, and run
   `python3 scripts/test_rule_list_syntax.py` (also enforced by CI) for the
   rule payloads. Surge skips an invalid RULE-SET line with a warning, which can
   silently remove intended routing coverage. `surge-cli --check` does not
   validate the contents of referenced remote payloads, so the repository sweep
   remains the authoritative gate for distributed list files.
5. Add `releases/<tag>.json` with `integrity: intact`, `distribution: candidate`,
   `live_device_validation: pending`, `rollback_eligible: false`, the exact
   script SHA-256 values, and `supersedes` pointing to the release-chain head.
   Omit `release_commit`. The candidate tag must not already exist locally or in
   the fetched authoritative tag set. Do not change canonical module pins yet.
6. Run `python3 scripts/verify-surge-release.py`, open the payload pull request,
   wait for every required check, and merge it. The merge commit containing the
   candidate payload is the future tag target.

### B. Register and create the tag

7. In a second pull request, add the exact 40-character payload merge commit as
   the candidate manifest's `release_commit`. The verifier reconstructs every
   manifest hash from that commit, requires the commit to be an ancestor of the
   trusted PR base, and requires the tag to remain absent. Merge this registration
   to `main` and wait for required CI before creating the tag.
8. Confirm the repository tag ruleset blocks updates and deletions for
   `refs/tags/surge-self-v*` while still allowing new tag creation.
9. Create the local tag at the already registered `release_commit`, never at the
   registration commit. Run `python3 scripts/verify-surge-release.py --tag
   <tag>` while the tag is still local. If verification fails, delete only that
   unpushed local tag and correct the candidate under review.
10. Push the verified tag. The `create` and tag `push` workflows
   run the verifier from the protected default branch, resolve the tag, and
   require its commit to equal the pre-registered value.
11. Verify every
   tagged script URL returns HTTP 200 with the manifest SHA-256.

This order removes the impossible requirement for a commit to contain its own
hash and ensures a new tag is known to the default-branch verifier before either
GitHub tag event runs.

### C. Validate before activation

12. Create a temporary local copy of each affected module and replace only its
    immutable `script-path` tag with the candidate tag. Install those test-only
    module definitions on the target device without publishing them under
    canonical `main` URLs. Confirm the candidate tag and script paths before
    testing. Refresh external resources,
    confirm every required resource reports `ready=1`, exercise the documented
    feature paths, and inspect script errors and rejected/failed requests.
13. Under `docs/MODULE_STATUS.md`, create a heading named exactly
    `Live-device evidence for <tag>` and record the exact `release_commit`,
    concrete device, Surge version, time, tests, and results. Change the candidate manifest's
    `live_device_validation` to `passed` or `failed` and set
    `live_device_evidence` to that exact heading plus
    `live_device_evidence_sha256` to its verifier-computed section hash in a
    reviewed pull request.
    Leave it `pending` when the run has not occurred or evidence is incomplete.
14. Do not activate a failed or pending candidate. If an untagged pre-registration
    is abandoned, remove it in review only after confirming the tag is absent.
    If the immutable tag exists, use a separate rejection pull request: change
    its distribution to `rejected`, retain the already recorded truthful
    `pending`, `passed`, or `failed` device state, add an optional non-empty
    `note` explaining a non-device rejection, and complete the reciprocal edge
    from the previous chain head. Never publish a GitHub Release for it. Only
    then may a new patch candidate supersede the rejected tag and repeat this
    process.

### D. Activate and publish

15. For a passed candidate, open an activation pull request that changes the old
    active distribution to `inactive`, changes the candidate to `active`, keeps
    `rollback_eligible: false` on the active bundle, updates the reciprocal
    supersession edge, and switches every canonical module pin together. Do not
    grant rollback eligibility to the old active bundle in this transaction.
16. Merge only after required CI passes. Generate the checksum block with
    `python3 scripts/verify-surge-release.py --print-release-body`, then create
    and publish the GitHub Release. The workflow checks `created`, `published`,
    `prereleased`, `released`, `edited`, `unpublished`, and `deleted` events;
    candidate distributions are rejected as premature Releases.
17. Run `python3 scripts/verify-surge-release.py --tag <tag> --github-release`
    and an authenticated `--check-remote` closed-set audit after publication.
18. Refresh the canonical `main` subscriptions on production devices and repeat
    the readiness and regression checks. Record any difference from candidate
    validation before calling the active distribution stable.

The existing `surge-self-v2026.07.27.1` distribution predates this activation
gate. Its manifest records `legacy_unvalidated_activation: true` together with
`live_device_validation: pending`. The verifier permits that exact tag as the
only exception; no future active distribution may use the exception or activate
before a recorded `passed` result. The legacy flag is immutable provenance and
remains even if a later reviewed regression records `passed` or `failed`.
Recording `passed` is a standalone evidence transaction. Recording `failed`
while this legacy bundle is active must be combined atomically with rollback to
an already certified target, so the repository never records an active failed
distribution.

### E. Certify or revoke a rollback target

19. In a separate pull request, review an intact, inactive, passed bundle against
    every current script-backed module. Record the decision under a dedicated,
    version-specific Markdown heading, add `rollback_evidence` and its verifier-
    computed section hash, and change only `rollback_eligible` from false to true.
20. Revoke eligibility in another standalone pull request by changing only the
    boolean to false. Preserve the evidence fields as historical provenance. A
    revoked bundle cannot be recertified from the same scalar evidence; use a new
    release or a future append-only evidence schema after a fresh review.

## Retired moved tag

`surge-self-v2026.07.13` was published before commit `144f112`, but the tag was
later moved to that newer commit. Its GitHub Release records Instagram SHA-256
`21b5cec6...`, while the moved tag serves a different Instagram script. The tag
is therefore recorded as `retired-moved` in `releases/` and must never be used by
an active module, republished, moved again, or treated as an immutable release.

The replacement bundle is `surge-self-v2026.07.13.1`. The release-integrity
workflow checks both intact bundles and the frozen observed state of the retired
tag.

### Legacy CamScanner tag

`camscanner-self-v1.0.0` predates the repository-wide release manifests and was
later moved remotely. It is classified as `retired-moved`, must not be used as
an install or rollback URL, and must not be moved again. Do not try to repair it
in place: tag immutability cannot be restored after consumers have observed two
different commits under the same name.

Migration is one-way:

1. Remove any module subscription that directly references
   `camscanner-self-v1.0.0`.
2. Install or refresh `rewrite/Surge/camscanner-self.sgmodule` from `main`.
3. Confirm its `script-path` uses the one active
   `surge-self-vYYYY.MM.DD[.N]` bundle and that the matching JSON manifest
   verifies the CamScanner payload.
4. Use only a manifest with `rollback_eligible: true`; never reuse the legacy
   tag.

All future CamScanner releases are part of the repository-wide bundle, tag
protection, release manifest, checksum, and remote-integrity workflow.

## Generated rules

`scripts/generate-managed-surge-rules.py --check` is the non-mutating CI mode.
It must fail when the checked-in files do not match the reviewed source hashes or
normalized output. Updating a source is an explicit maintenance operation:

1. Run `--check-upstream` to compare all 22 moving tracking URLs with the
   reviewed inputs. Tracking URLs are monitoring inputs only.
2. For a commit-backed source, resolve and review the exact upstream commit.
   Refresh with `--only <set> --source-commit <40hex>`; the generator atomically
   repins every Blackmatrix source to that one commit and verifies every file
   against its moving tracking URL.
3. For a vendored Sukka source, refresh only the reviewed set with
   `--only <set>`. The exact published bytes are stored under
   `rule/Surge/upstream/` and their SHA-256 remains the build gate.
4. Review source bytes, normalized rules, routing overlap, rule counts,
   licenses, the full generated index, and manifest changes.
5. Commit the manifest, upstream snapshots, generated lists, and metadata
   together through a pull request.

The daily tracking workflow is read-only. The write-capable managed-source
workflow is manual and requires an explicit rule-set id plus the reviewed
commit when applicable; it may update a review branch and PR but never writes
directly to `main`.

## Rollback

- Select an intact, inactive manifest with `live_device_validation: passed` and
  `rollback_eligible: true`, `rollback_evidence`, and a matching
  `rollback_evidence_sha256`. `inactive` by itself is not sufficient.
- In a reviewed pull request, switch every canonical module pin to that tag,
  mark it as the active distribution and clear its rollback flag, and mark the
  failed distribution inactive. Do not alter the reciprocal supersession chain:
  version history remains forward-only even when distribution moves backward.
- Refresh external resources on affected devices and repeat the documented live
  checks. Record the rollback evidence.
- Do not move or overwrite any tag, and never reuse a tag with
  `integrity: retired-moved`.
- Build the durable fix under a new patch tag through the candidate process.
  Keep at least one validated rollback bundle available until its replacement
  has passed production-device regression.
