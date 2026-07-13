# Security policy

## Supported versions

Protected `main` is the supported public module and ruleset channel. Scripted
modules on `main` must reference an immutable `surge-self-vYYYY.MM.DD` tag, so a
normal branch commit cannot silently replace production JavaScript. Security
fixes are released through a reviewed `main` change and a new immutable tag;
existing tags are never moved.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose credentials,
traffic contents, account data, or a remotely exploitable configuration. Use
GitHub's private vulnerability reporting for this repository when available,
or contact the maintainer privately through the contact method on the GitHub
profile.

Include only the minimum information needed to reproduce the problem. Redact:

- Surge controller passwords and HTTP API keys;
- proxy credentials, cookies, authorization headers, tokens, and account IDs;
- complete request or response bodies from signed-in applications;
- private LAN inventory, public IP addresses, device identifiers, and precise
  location data.

Do not attach raw Surge request exports or packet captures to public issues.
Prefer a small synthetic fixture that reproduces the behavior. If real traffic
is essential, ask the maintainer for a private transfer method first.

## Security boundaries

Repository-authored response scripts must not make outbound requests, upload
traffic, read authentication material unless strictly required and documented,
or execute dynamically downloaded code. Module script paths must use this
repository's GitHub Raw origin and an immutable stable tag.

External Controller and HTTP API credentials are runtime secrets. Examples in
this repository use placeholders and environment variables; never commit real
profile credentials or replace the examples with live values.
