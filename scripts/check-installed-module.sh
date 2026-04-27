#!/usr/bin/env bash
# Locate the YouTube Self Enhance module that Surge Mac actually loaded,
# print its first 30 lines, and confirm it matches the latest GitHub copy.
set -uo pipefail

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
  if grep -q "YouTube Self Enhance" "$f" 2>/dev/null; then
    echo "    [match] this file is YouTube Self Enhance"
  fi
  head -40 "$f"
done

echo
echo ">>> Latest GitHub copy says:"
curl -fsSL --max-time 10 \
  "https://raw.githubusercontent.com/mulanshan/surge/main/modules/youtube-self-enhance.sgmodule" \
  | head -40
