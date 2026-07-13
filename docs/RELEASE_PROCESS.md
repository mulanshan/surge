# Release Process

The repository is a production distribution source. A push to `main` can change
the module or ruleset consumed by an installed Surge instance, so changes must go
through a branch, CI, review, and an immutable release tag.

## Channels

- `main`: latest reviewed module definitions, documentation, and generated rule
  snapshots. Public install URLs point here so module metadata can move to a new
  stable script pin without reinstalling the module.
- `surge-self-vYYYY.MM.DD`: immutable stable bundle. Script-backed modules pin
  `script-path` to this tag.
- feature branches: development only. Do not reference a feature branch from a
  public module.

## Required gates

1. Run the repository CI suite locally.
2. Review generated-rule source hashes and normalized rule diffs. Never accept an
   upstream drift only because generation succeeded.
3. Verify that response scripts do not issue network requests, read credentials,
   or log raw request/response bodies.
4. Check the shared Surge profile with `surge-cli --check`.
5. Open a pull request and wait for every required check to pass.
6. Create and push the immutable stable tag from the reviewed pull-request head.
7. Verify every tagged script URL returns HTTP 200 and matches the local SHA-256.
8. Merge the pull request and publish the GitHub Release. This order prevents
   `main` from briefly referencing a tag that does not exist yet.
9. Update external resources on the target iOS device and confirm `ready=1`.
10. Record the live-device evidence in `docs/MODULE_STATUS.md`.

## Generated rules

`scripts/generate-managed-surge-rules.py --check` is the non-mutating CI mode.
It must fail when the checked-in files do not match the reviewed source hashes or
normalized output. Updating a source is an explicit maintenance operation:

1. Update the reviewed source hash in the manifest.
2. Run the generator in update mode.
3. Review source-level and normalized diffs.
4. Commit the manifest, generated lists, and metadata together.

Scheduled automation may open a pull request showing drift, but must never push
new upstream content directly to `main`.

## Rollback

- Revert the module definition on `main` to the previous stable script tag.
- Refresh external resources on affected devices.
- Do not move or overwrite an existing stable tag.
- Keep the previous stable release available until the new release completes a
  live-device regression pass.
