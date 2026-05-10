#!/bin/bash
# claude-constellation — fully-automatic refresh
#
# Drives Chrome via AppleScript to click "Export data" on claude.ai for you,
# then watches ~/Downloads and rebuilds the constellation when the zip arrives.
#
# One-time setup: enable "Allow JavaScript from Apple Events" in Chrome →
#   View menu → Developer → Allow JavaScript from Apple Events.
# (We try the click anyway and fall back to "click it yourself" if it fails.)

set -e

REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
DOWNLOADS="$HOME/Downloads"
OUTPUT="$HOME/Desktop/conversation-constellation.html"
SETTINGS_URL="https://claude.ai/settings/data-privacy-controls"
WATCH_TIMEOUT_MIN=60

cd "$REPO_DIR"

echo ""
echo "╭───────────────────────────────────────────────╮"
echo "│   claude-constellation — auto-refresh         │"
echo "╰───────────────────────────────────────────────╯"
echo ""

# ── snapshot current zips ────────────────────────────────────────────────────
BEFORE_LIST="$(mktemp)"
ls "$DOWNLOADS"/data-*.zip 2>/dev/null > "$BEFORE_LIST" || true

# ── drive Chrome via AppleScript ─────────────────────────────────────────────
echo "▸ Asking Chrome to open claude.ai settings and click Export data…"

CLICK_RESULT=$(osascript <<APPLESCRIPT 2>&1 || true
tell application "Google Chrome"
  activate
  delay 0.3
  set newTab to make new tab at end of tabs of window 1 with properties {URL:"$SETTINGS_URL"}
  delay 4
end tell

-- Find the settings tab and click "Export data"
set clickAttempts to 0
repeat with i from 1 to 8
  delay 1.5
  tell application "Google Chrome"
    set theTabs to tabs of window 1
    repeat with t in theTabs
      if URL of t contains "data-privacy-controls" then
        try
          set js to "(function(){var bs=Array.from(document.querySelectorAll('button'));var b=bs.find(function(x){return x.textContent.trim()==='Export data';});if(b){b.click();return 'clicked';}return 'not_found';})()"
          set rv to execute t javascript js
          return rv as string
        on error errMsg
          return "error:" & errMsg
        end try
      end if
    end repeat
  end tell
end repeat
return "no_tab"
APPLESCRIPT
)

echo "  result: $CLICK_RESULT"
echo ""

if [[ "$CLICK_RESULT" == *"clicked"* ]]; then
  echo "  ✓ Clicked Export data automatically. Waiting for the zip to land…"
elif [[ "$CLICK_RESULT" == *"error"* ]] || [[ "$CLICK_RESULT" == *"execute javascript"* ]]; then
  echo "  Chrome didn't allow scripting (one-time setup needed)."
  echo ""
  echo "  Enable: Chrome menu → View → Developer → Allow JavaScript from Apple Events"
  echo "  Then re-run this script. For now, click \"Export data\" yourself in the open tab."
  echo ""
elif [[ "$CLICK_RESULT" == *"not_found"* ]]; then
  echo "  Couldn't find the Export data button on the page."
  echo "  Click it yourself in the open Chrome tab — I'll wait for the zip."
  echo ""
else
  echo "  AppleScript output:"
  echo "  $CLICK_RESULT"
  echo "  Click \"Export data\" yourself in the open Chrome tab if needed."
  echo ""
fi

# ── watch for new zip ────────────────────────────────────────────────────────
echo "▸ Watching ~/Downloads for the new export zip…"
echo "  (timeout: ${WATCH_TIMEOUT_MIN} minutes — leave this window open)"
echo ""

START=$(date +%s)
NEW_ZIP=""
DOTS=0
while true; do
  ELAPSED=$(( $(date +%s) - START ))
  if [ "$ELAPSED" -ge $(( WATCH_TIMEOUT_MIN * 60 )) ]; then
    echo ""
    echo "  (timed out — no new export detected in ${WATCH_TIMEOUT_MIN} minutes)"
    rm -f "$BEFORE_LIST"
    exit 1
  fi
  CURRENT_LIST="$(mktemp)"
  ls "$DOWNLOADS"/data-*.zip 2>/dev/null > "$CURRENT_LIST" || true
  NEW_LINE="$(comm -23 <(sort "$CURRENT_LIST") <(sort "$BEFORE_LIST") | head -1)"
  rm -f "$CURRENT_LIST"
  if [ -n "$NEW_LINE" ] && [ -f "$NEW_LINE" ]; then
    sleep 2  # let the file finish writing
    NEW_ZIP="$NEW_LINE"
    break
  fi
  DOTS=$(( (DOTS + 1) % 60 ))
  if [ "$DOTS" -eq 0 ]; then printf "\n  "; fi
  printf "."
  sleep 5
done
rm -f "$BEFORE_LIST"

echo ""
echo ""
echo "▸ Got it: $NEW_ZIP"
echo ""
echo "▸ Rebuilding constellation…"
python3 claude_constellation.py --web-export "$NEW_ZIP" --output "$OUTPUT"
echo ""
echo "✓ Opening $OUTPUT"
open "$OUTPUT"
echo ""
read -p "Press enter to close…"
