#!/bin/bash
# One-click push: commits any uncommitted changes and pushes to GitHub.
# Double-click this file in Finder.

set -e

REPO="$HOME/Desktop/claude-constellation"
cd "$REPO" || { echo "✗ Can't find $REPO"; read -p "Press enter…"; exit 1; }

# One-time setup: init git + add remote if missing.
if [ ! -d .git ]; then
  echo "▸ First-time setup: initializing local git repo…"
  git init -b main
  git remote add origin https://github.com/Eburstz/claude-constellation.git
  # Fetch what's on the remote so we don't overwrite history.
  echo "▸ Fetching remote main…"
  git fetch origin main
  # Reset our working tree to match remote, but keep your edits as uncommitted changes.
  git reset --soft origin/main 2>/dev/null || git reset --soft FETCH_HEAD
fi

# Make sure remote is set.
git remote get-url origin >/dev/null 2>&1 || \
  git remote add origin https://github.com/Eburstz/claude-constellation.git

# Show what's about to be committed.
echo ""
echo "▸ Changes detected:"
git status --short
echo ""

if [ -z "$(git status --porcelain)" ]; then
  echo "✓ Nothing to commit — working tree clean."
  read -p "Press enter to close…"
  exit 0
fi

# Default commit message based on changed files.
CHANGED_FILES=$(git status --porcelain | awk '{print $2}' | xargs basename -a 2>/dev/null | head -3 | tr '\n' ',' | sed 's/,$//' | sed 's/,/, /g')
DEFAULT_MSG="Update $CHANGED_FILES"

echo ""
read -p "Commit message [$DEFAULT_MSG]: " MSG
MSG="${MSG:-$DEFAULT_MSG}"

git add -A
git commit -m "$MSG"

echo ""
echo "▸ Pushing to GitHub…"
git push -u origin main

echo ""
echo "✓ Done. https://github.com/Eburstz/claude-constellation"
echo ""
read -p "Press enter to close…"
