#!/bin/bash
# claude-constellation — one-click Mac setup
# Double-click this file in Finder. It will scan your Claude history and write
# conversation-constellation.html to your Desktop.

set -e

# Resolve the directory this script lives in (the cloned repo).
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

OUTPUT="$HOME/Desktop/conversation-constellation.html"
WEB_EXPORT_ARG=""

echo ""
echo "╭───────────────────────────────────────────────╮"
echo "│   claude-constellation — building your map   │"
echo "╰───────────────────────────────────────────────╯"
echo ""

# Look for the most recent claude.ai export zip in Downloads
LATEST_EXPORT=""
for f in "$HOME/Downloads/"data-*.zip "$HOME/Downloads/"*claude*export*.zip; do
  [ -f "$f" ] && LATEST_EXPORT="$f"
done
if [ -n "$LATEST_EXPORT" ]; then
  echo "▸ Found claude.ai data export: $LATEST_EXPORT"
  WEB_EXPORT_ARG="--web-export $LATEST_EXPORT"
else
  echo "▸ No claude.ai data export found in ~/Downloads"
  echo "  (To include web chats: claude.ai → Settings → Privacy → Export Data,"
  echo "   then drop the zip in ~/Downloads and run this again.)"
fi

echo ""
python3 claude_constellation.py $WEB_EXPORT_ARG --output "$OUTPUT"

echo ""
echo "▸ Opening in your default browser…"
open "$OUTPUT"
echo ""
read -p "Press enter to close this window…"
