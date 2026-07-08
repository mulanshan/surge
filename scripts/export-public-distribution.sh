#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-}"

if [[ -z "$DEST" ]]; then
  echo "Usage: $0 <public-repo-checkout>" >&2
  exit 2
fi

DEST="$(cd "$DEST" && pwd)"

if [[ ! -d "$DEST/.git" ]]; then
  echo "Destination must be an existing git checkout: $DEST" >&2
  exit 1
fi

if [[ "$DEST" == "$ROOT" ]]; then
  echo "Destination cannot be the source repository." >&2
  exit 1
fi

rm -rf "$DEST/rewrite" "$DEST/rule"
mkdir -p "$DEST/rewrite/Surge" "$DEST/rule/Surge"

cp "$ROOT/public/README.md" "$DEST/README.md"
printf '.DS_Store\n' > "$DEST/.gitignore"
: > "$DEST/.nojekyll"

find "$ROOT/rewrite/Surge" -maxdepth 1 -type f -name '*.sgmodule' -exec cp {} "$DEST/rewrite/Surge/" \;
cp -R "$ROOT/rewrite/Surge/scripts" "$DEST/rewrite/Surge/scripts"

find "$ROOT/rule/Surge" -maxdepth 1 -type f \( -name '*.list' -o -name '*.conf' \) -exec cp {} "$DEST/rule/Surge/" \;
cp -R "$ROOT/rule/Surge/generated" "$DEST/rule/Surge/generated"

echo "Exported public Surge distribution to $DEST"
