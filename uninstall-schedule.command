#!/bin/bash
# Removes the launchd job installed by install-schedule.command.

set -e
PLIST_LABEL="com.claude-constellation.refresh"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

if [ -f "$PLIST_PATH" ]; then
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  rm "$PLIST_PATH"
  echo "✓ Removed scheduled job: $PLIST_LABEL"
else
  echo "(no scheduled job installed)"
fi

echo ""
read -p "Press enter to close…"
