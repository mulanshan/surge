#!/usr/bin/env bash
# Locate the YouTube Self Local module copies and confirm the iCloud local
# module matches the repository copy.
set -uo pipefail
cd "$(dirname "$0")/.."

REPO_MODULE="modules/youtube-self-local.sgmodule"
ICLOUD_MODULE="$HOME/Library/Mobile Documents/iCloud~com~nssurge~inc/Documents/modules/youtube-self-local.sgmodule"

echo ">>> Searching Surge sandbox for sgmodule files…"
HITS=$(find \
  "$HOME/Library/Containers" \
  "$HOME/Library/Application Support" \
  "$HOME/Library/Group Containers" \
  -name "*.sgmodule" 2>/dev/null)

if [ -z "$HITS" ]; then
  echo "    No .sgmodule found in usual Surge locations."
  echo "    Try: open 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'"
  exit 1
fi

echo "$HITS" | while IFS= read -r f; do
  echo
  echo "=== $f ==="
  if grep -q "YouTube Self Local" "$f" 2>/dev/null; then
    echo "    [match] this file is YouTube Self Local"
  fi
  head -40 "$f"
done

echo
echo ">>> Repository module:"
head -40 "$REPO_MODULE"

echo
echo ">>> iCloud local module:"
if [ -f "$ICLOUD_MODULE" ]; then
  head -40 "$ICLOUD_MODULE"
  echo
  echo ">>> SHA-256 comparison:"
  shasum -a 256 "$REPO_MODULE" "$ICLOUD_MODULE"
else
  echo "    Missing: $ICLOUD_MODULE"
fi
