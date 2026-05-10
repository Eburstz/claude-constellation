#!/bin/bash
# claude-constellation — refresh
#
# Double-click this file. It will:
#   1. If a recent (<14 days old) claude.ai data export already lives in ~/Downloads,
#      just rebuild your constellation from it.
#   2. Otherwise: open claude.ai's privacy settings in your browser so you can click
#      "Export data", then wait in the background for the new zip to land and
#      auto-rebuild the constellation when it does.
#
# In both cases it also picks up any new Claude Code / Cowork sessions on disk.

set -e

# ── paths ────────────────────────────────────────────────────────────────────
REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
HOME_DIR="$HOME"
DOWNLOADS="$HOME_DIR/Downloads"
OUTPUT="$HOME_DIR/Desktop/conversation-constellation.html"
SETTINGS_URL="https://claude.ai/settings/data-privacy-controls"
FRESH_DAYS=14
WATCH_TIMEOUT_MIN=60   # stop watching after this many minutes

cd "$REPO_DIR"

echo ""
echo "╭───────────────────────────────────────────────╮"
echo "│   claude-constellation — refresh              │"
echo "╰───────────────────────────────────────────────╯"
echo ""

# ── helper ───────────────────────────────────────────────────────────────────
latest_zip() {
  ls -t "$DOWNLOADS"/data-*.zip 2>/dev/null | head -1
}

zip_age_days() {
  local f="$1"; [ -z "$f" ] && return 1
  echo $(( ( $(date +%s) - $(stat -f %m "$f") ) / 86400 ))
}

run_pipeline() {
  local zip="$1"
  if [ -n "$zip" ] && [ -f "$zip" ]; then
    echo "▸ Rebuilding constellation with web export:"
    echo "    $zip"
    python3 claude_constellation.py --web-export "$zip" --output "$OUTPUT"
  else
    echo "▸ Rebuilding constellation (local sessions only — no web export)"
    python3 claude_constellation.py --output "$OUTPUT"
  fi
}

# ── (1) check for a recent existing export ──────────────────────────────────
EXISTING="$(latest_zip)"
if [ -n "$EXISTING" ]; then
  AGE=$(zip_age_days "$EXISTING")
  echo "▸ Latest export: $EXISTING"
  echo "  age: ${AGE} day(s)"
  if [ "$AGE" -lt "$FRESH_DAYS" ]; then
    echo "  fresh enough — using as-is."
    echo ""
    run_pipeline "$EXISTING"
    echo ""
    echo "✓ Done. Opening $OUTPUT"
    open "$OUTPUT"
    echo ""
    read -p "Press enter to close…"
    exit 0
  fi
  echo "  older than ${FRESH_DAYS} days — triggering a fresh export."
else
  echo "▸ No claude.ai export found in ~/Downloads."
fi

# ── (2) open the export page in the user's browser ──────────────────────────
echo ""
echo "▸ Opening claude.ai privacy settings…"
echo "  → Click the \"Export data\" button on the page."
echo "  → You'll get an email with a download link in a few minutes."
echo "  → Click that link — the zip lands in ~/Downloads automatically."
open "$SETTINGS_URL"
echo ""
echo "▸ Watching ~/Downloads for the new export zip… (timeout: ${WATCH_TIMEOUT_MIN} min)"
echo "  Leave this window open. Press Ctrl-C to cancel."
echo ""

# Snapshot the existing zips so we can detect the truly new one.
BEFORE_LIST="$(mktemp)"
ls "$DOWNLOADS"/data-*.zip 2>/dev/null > "$BEFORE_LIST" || true

START=$(date +%s)
NEW_ZIP=""
while true; do
  ELAPSED=$(( $(date +%s) - START ))
  if [ "$ELAPSED" -ge $(( WATCH_TIMEOUT_MIN * 60 )) ]; then
    echo "  (timed out — no new export detected)"
    rm -f "$BEFORE_LIST"
    exit 1
  fi
  CURRENT_LIST="$(mktemp)"
  ls "$DOWNLOADS"/data-*.zip 2>/dev/null > "$CURRENT_LIST" || true
  NEW_LINE="$(comm -23 <(sort "$CURRENT_LIST") <(sort "$BEFORE_LIST") | head -1)"
  rm -f "$CURRENT_LIST"
  if [ -n "$NEW_LINE" ] && [ -f "$NEW_LINE" ]; then
    # Wait briefly so the file finishes writing
    sleep 2
    NEW_ZIP="$NEW_LINE"
    break
  fi
  printf "."
  sleep 5
done
rm -f "$BEFORE_LIST"

echo ""
echo ""
echo "▸ New export detected: $NEW_ZIP"
echo ""
run_pipeline "$NEW_ZIP"
echo ""
echo "✓ Done. Opening $OUTPUT"
open "$OUTPUT"
echo ""
read -p "Press enter to close…"
