# Third-party notices

The MIT license in [`LICENSE`](LICENSE) applies to original code and documentation
authored for this repository. It does **not** relicense third-party material or
generated rules derived from third-party sources.

## Generated Surge rules

Files under `rule/Surge/generated/` are generated mirrors or derivative rule
collections. Their source URLs and the SHA-256 of the retrieved source content
are recorded in each `.list` header and adjacent `.list.json` file. The source
manifest is `rule/Surge/sources/managed-rules.yaml`.

The currently configured upstream projects include:

| Upstream | Used for | Upstream license |
| --- | --- | --- |
| [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | Rules fetched from `raw.githubusercontent.com/blackmatrix7/ios_rule_script` | [GPL-2.0](https://github.com/blackmatrix7/ios_rule_script/blob/master/LICENSE) |
| [SukkaW/Surge](https://github.com/SukkaW/Surge) | Rules published through `ruleset.skk.moe` | [AGPL-3.0](https://github.com/SukkaW/Surge/blob/master/LICENSE) |

Use, modification, and redistribution of generated files must comply with all
applicable upstream license terms. Preserve source attribution, provenance
metadata, and license notices. When upstream content is combined, the most
restrictive applicable obligations may govern the resulting file. Consult the
upstream repositories for complete and current license text.

Upstream projects and their maintainers do not endorse this repository. Product
and project names remain the property of their respective owners.
