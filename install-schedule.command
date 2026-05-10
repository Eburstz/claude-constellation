#!/bin/bash
# Installs a Mac launchd job that runs refresh-quiet.sh once a day at noon.
# After installing, the constellation HTML auto-rebuilds whenever a new export
# zip lands in ~/Downloads — no further action needed from you.

set -e

REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PLIST_LABEL="com.claude-constellation.refresh"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${REPO_DIR}/refresh-quiet.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>12</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${HOME}/.claude-constellation.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME}/.claude-constellation.log</string>
</dict>
</plist>
EOF

# Make refresh-quiet executable
chmod +x "${REPO_DIR}/refresh-quiet.sh"

# (Re)load the agent
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo ""
echo "✓ Scheduled job installed."
echo "  Plist: $PLIST_PATH"
echo "  Runs:  daily at 12:00 + on login"
echo "  Log:   $HOME/.claude-constellation.log"
echo ""
echo "It will rebuild your constellation any time a fresh claude.ai export zip"
echo "lands in ~/Downloads. To remove: double-click uninstall-schedule.command."
echo ""
read -p "Press enter to close…"
