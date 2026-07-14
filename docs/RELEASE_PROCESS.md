# Release Process

The repository is a production distribution source. A push to `main` can change
the module or ruleset consumed by an installed Surge instance, so changes must go
through a branch, CI, review, and an immutable release tag.

## Channels

- `main`: latest reviewed module definitions, documentation, and generated rule
  snapshots. Public install URLs point here so module metadata can move to a new
  stable script pin without reinstalling the module.
- `surge-self-vYYYY.MM.DD[.N]`: immutable stable bundle. Use the optional patch
  suffix when a release on the same date supersedes an earlier bundle.
  Script-backed modules pin `script-path` to exactly one active tag.
- feature branches: development only. Do not reference a feature branch from a
  public module.

## Required gates

1. Run the repository CI suite locally.
2. Review generated-rule source hashes and normalized rule diffs. Never accept an
   upstream drift only because generation succeeded.
3. Verify that response scripts do not issue network requests, read credentials,
   or log raw request/response bodies.
4. Check the shared Surge profile with `surge-cli --check`.
5. Update `releases/<tag>.json` with the exact current script SHA-256 values, then
   run `python3 scripts/verify-surge-release.py`.
6. Open a pull request and wait for every required check to pass.
7. Confirm the repository tag ruleset blocks updates and deletions for
   `refs/tags/surge-self-v*` while still allowing new tag creation.
8. Create and push the immutable stable tag from the reviewed pull-request head.
9. Add the resulting tag commit to the active manifest as `release_commit`,
   commit that metadata on the same pull-request branch, and wait for CI again.
10. Run `python3 scripts/verify-surge-release.py --tag <tag>` and verify every
   tagged script URL returns HTTP 200 with the manifest SHA-256.
11. Merge the pull request and publish the GitHub Release. Generate the checksum
   block with `python3 scripts/verify-surge-release.py --print-release-body`.
   This order prevents
   `main` from briefly referencing a tag that does not exist yet.
12. Run `python3 scripts/verify-surge-release.py --tag <tag> --github-release`
    after publication.
13. Update the existing modules from their original `main` install URLs on the
    target iOS device, refresh external resources, and confirm `ready=1`.
14. Record the live-device evidence in `docs/MODULE_STATUS.md`.

## Retired moved tag

`surge-self-v2026.07.13` was published before commit `144f112`, but the tag was
later moved to that newer commit. Its GitHub Release records Instagram SHA-256
`21b5cec6...`, while the moved tag serves a different Instagram script. The tag
is therefore recorded as `retired-moved` in `releases/` and must never be used by
an active module, republished, moved again, or treated as an immutable release.

The replacement bundle is `surge-self-v2026.07.13.1`. The release-integrity
workflow checks both the active bundle and the frozen observed state of the
retired tag.

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
4. Use an intact `superseded` bundle for rollback; never reuse the legacy tag.

All future CamScanner releases are part of the repository-wide bundle, tag
protection, release manifest, checksum, and remote-integrity workflow.

## Generated rules

`scripts/generate-managed-surge-rules.py --check` is the non-mutating CI mode.
It must fail when the checked-in files do not match the reviewed source hashes or
normalized output. Updating a source is an explicit maintenance operation:

1. Run `--check-upstream` to compare all 21 moving tracking URLs with the
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

- Revert the module definition on `main` to the previous stable script tag.
- Refresh external resources on affected devices.
- Do not move or overwrite an existing stable tag.
- Never reuse a tag marked `retired-moved`; publish a new patch tag instead.
- Keep the previous stable release available until the new release completes a
  live-device regression pass.
