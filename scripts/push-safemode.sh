#!/usr/bin/env bash
# Commit & push current Safe-mode YouTube changes.
set -euo pipefail
cd "$(dirname "$0")/.."

echo ">>> Removing stale lock files (if any)…"
rm -f .git/index.lock .git/HEAD.lock 2>/dev/null || true

echo ">>> Adding all changes (modified + untracked) under tracked safe paths…"
git add modules/youtube-self-enhance.sgmodule
git add scripts/youtube/youtube-self.response.js
[ -f .gitignore ] && git add .gitignore || true
[ -f scripts/check-installed-module.sh ] && git add scripts/check-installed-module.sh || true
[ -f scripts/push-safemode.sh ] && git add scripts/push-safemode.sh || true

echo ">>> Status:"
git status -s

if git diff --cached --quiet; then
  echo "    Nothing staged after add. Something is wrong."
  exit 1
fi

echo ">>> Committing…"
git commit -m "Safe mode v2: passthrough protobuf, narrow JSON ad-removal, inject PiP+background"

echo ">>> Pushing…"
git push origin main

echo ">>> Done. Sanity-check what GitHub now serves:"
echo
curl -fsSL --max-time 10 \
  "https://raw.githubusercontent.com/mulanshan/surge/main/modules/youtube-self-enhance.sgmodule" \
  | head -20
