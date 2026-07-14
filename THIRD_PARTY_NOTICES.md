# Third-party notices

The MIT license in [`LICENSE`](LICENSE) applies to original code and documentation
authored for this repository. It does **not** relicense third-party material or
generated rules derived from third-party sources.

## Generated Surge rules

Files under `rule/Surge/generated/` are generated mirrors or derivative rule
collections. Their immutable source URL or repository snapshot, moving tracking
URL, and SHA-256 are recorded in each `.list` header and adjacent `.list.json`
file. The source manifest is `rule/Surge/sources/managed-rules.yaml`; exact
Sukka publication snapshots are retained under `rule/Surge/upstream/sukka/`.

The currently configured upstream projects include:

| Upstream | Used for | Upstream license |
| --- | --- | --- |
| [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | Rules fetched from one reviewed 40-hex Git commit | [GPL-2.0-only](LICENSES/blackmatrix7-ios_rule_script-GPL-2.0-only.txt) |
| [SukkaW/Surge](https://github.com/SukkaW/Surge) | Exact published `ruleset.skk.moe` bytes vendored as reviewed snapshots | [AGPL-3.0-only](LICENSES/SukkaW-Surge-AGPL-3.0-only.txt) |

The bundled license texts were copied from upstream for redistribution
compliance. Their reviewed provenance is:

- blackmatrix7/ios_rule_script commit
  `597afad2785163a2f5a3eedd86dd605f76bb95c4`, `LICENSE`;
- SukkaW/Surge commit `bf2ae1c23877fa2ee6ebd8afdbab1680f9477466`,
  `LICENSE`.

Use, modification, and redistribution of generated files must comply with all
applicable upstream license terms. Preserve source attribution, provenance
metadata, and license notices. When upstream content is combined, the most
restrictive applicable obligations may govern the resulting file. Consult the
upstream repositories for complete and current license text.

Upstream projects and their maintainers do not endorse this repository. Product
and project names remain the property of their respective owners.
