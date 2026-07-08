# Surge Control Reference

## Official Docs

- External Controller: https://manual.nssurge.com/others/external-controller.html
- Surge Mac CLI: https://manual.nssurge.com/others/cli.html
- HTTP API: https://manual.nssurge.com/others/http-api.html

## Profile Lines

```ini
external-controller-access = password@0.0.0.0:6170
http-api = key@0.0.0.0:1132
http-api-tls = true
```

Use `127.0.0.1` for local-only access. Use `0.0.0.0` only when LAN access is intended and the credential is strong.

## External Controller Examples

```bash
surge-cli --raw --remote "$CTRL_PASS@<device-ip>:6170" environment
surge-cli --raw --remote "$CTRL_PASS@<device-ip>:6170" dump event
surge-cli --raw --remote "$CTRL_PASS@<device-ip>:6170" dump request
surge-cli --remote "$CTRL_PASS@<device-ip>:6170" reload
```

Common useful commands: `environment`, `dump event`, `dump request`, `dump dns`, `dump policy`, `dump rule`, `dump profile original`, `reload`, `set-log-level`, `test-network`, `test-policy`, `external-resource update all`.

## HTTPS HTTP API Examples

```bash
curl -k -fsS -H "X-Key: $HTTP_KEY" https://<device-ip>:1132/v1/events
curl -k -fsS -H "X-Key: $HTTP_KEY" https://<device-ip>:1132/v1/requests/recent
curl -k -fsS -H "X-Key: $HTTP_KEY" "https://<device-ip>:1132/v1/profiles/current?sensitive=0"
curl -k -fsS -X POST -H "X-Key: $HTTP_KEY" https://<device-ip>:1132/v1/profiles/reload
```

Use `X-Key` for authentication. Query parameter `x-key` is acceptable only for special browser cases such as downloading the MITM CA certificate.

## Endpoint Notes

- `/v1/events`: event center.
- `/v1/requests/recent`: recent requests.
- `/v1/requests/active`: active requests.
- `/v1/profiles/current?sensitive=0`: current profile with secrets masked.
- `/v1/profiles/reload`: reload current profile.
- `/v1/policies`, `/v1/policy_groups`: policy and policy-group inspection.
- `/v1/features/mitm`, `/v1/features/rewrite`, `/v1/features/scripting`, `/v1/features/capture`: feature state and toggles.

## Known Local Quirks

- Local macOS `surge-cli --raw ...` may return `(null)` in some situations. Cross-check with `lsof`, proxy listeners, route state, and `curl` probes.
- `watch request` only captures traffic that traverses the monitored Surge instance.
- Apple TV can lag behind shared iCloud profile edits. Verify the active endpoint rather than trusting file contents.
