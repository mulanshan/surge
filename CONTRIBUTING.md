# Contributing

This is a public, self-maintained Surge repository. Small, auditable changes
with a narrow application boundary are preferred over broad blocking or generic
recursive response mutation.

## Before opening a change

- Do not submit third-party executable scripts or copied script fragments.
- Do not commit credentials, signed-in traffic, cookies, tokens, device IDs,
  LAN inventories, packet captures, or unredacted Surge exports.
- Use synthetic fixtures in tests. If a real response shape informed a fix,
  minimize and anonymize it before committing.
- Preserve account, payment, purchase validation, sync, upload, navigation, and
  other unrelated application behavior.
- Document the exact app/version and endpoint family a behavior was tested on,
  without publishing personal account or device details.

Contributions to repository-authored code and documentation are accepted under
the MIT license. Generated or derived rules remain subject to their upstream
licenses as described in `THIRD_PARTY_NOTICES.md`.

## Local validation

Run the checks relevant to the change. The CI workflow performs the complete
repository gate:

```bash
find rewrite scripts -type f -name '*.js' -exec node --check {} \;
find rewrite -type f -name '*.test.js' -exec node {} \;
python3 -m compileall -q scripts .github/scripts
python3 scripts/check-basic-adblock.py
python3 .github/scripts/check_repository.py
find . -type f -name '*.sh' -not -path './.git/*' -exec bash -n {} \;
```

If the managed-rule generator supports check mode, also run:

```bash
python3 scripts/generate-managed-surge-rules.py --check
```

Rule updates must be reviewed as diffs. Do not regenerate from a moving
upstream and push the result directly to the production channel without
checking source hashes, rule counts, additions, removals, and policy overlap.

## Pull request and release flow

1. Make the change on a branch and add or update regression tests.
2. Let CI validate syntax, tests, module invariants, compatibility aliases, and
   generated-rule provenance.
3. Test the pull-request branch on a non-critical device or profile. Confirm
   both the intended result and core app behavior before merging to `main`.
4. Record the tested Surge version, operating system, app version, module
   version, and result in the pull request or release notes.
5. Pre-register the candidate manifest on protected `main`, register its exact
   payload commit in a second reviewed change, and only then create the immutable
   tag. Test that tag on a non-critical device and record the result before a
   separate activation change switches canonical module pins. New modules stay
   under `rewrite/Surge/candidates/` until activation; feature branches and
   unregistered candidate definitions are not public install channels.

Changes to generated third-party rules, MITM hostnames, URL rewrite patterns,
response size limits, or payment/account-adjacent fields require especially
careful review.
