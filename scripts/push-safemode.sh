#!/usr/bin/env bash
# Commit & push everything in the repo, EXCEPT files we never want public:
# - captures/  (raw token-bearing dumps, blocked by .gitignore)
# - captures-redacted/ (even redacted dumps stay local)
set -euo pipefail
cd "$(dirname "$0")/.."

echo ">>> Removing stale lock files (if any)…"
rm -f .git/index.lock .git/HEAD.lock 2>/dev/null || true

# Make sure the gitignore really blocks the dangerous dirs.
touch .gitignore
for line in "captures/" "captures-redacted/"; do
  if ! grep -qxF "$line" .gitignore; then
    echo "$line" >> .gitignore
  fi
done

echo ">>> Status before staging:"
git status -s

echo ">>> Staging everything that's not in .gitignore…"
git add -A

# Belt & braces: if any captures/ slipped in, rip them back out.
git reset -q -- 'captures/*' 'captures-redacted/*' 2>/dev/null || true

echo ">>> Final staged set:"
git diff --cached --name-status

if git diff --cached --quiet; then
  echo "    Nothing staged. Aborting."
  exit 0
fi

echo ">>> Committing…"
git commit -m "Update YouTube self-enhance toolchain"

echo ">>> Pushing…"
git push origin main

echo ">>> Done. Sanity-check the module on GitHub:"
echo
curl -fsSL --max-time 10 \
  "https://raw.githubusercontent.com/mulanshan/surge/main/modules/youtube-self-enhance.sgmodule" \
  | head -10
