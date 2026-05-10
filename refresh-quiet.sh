#!/bin/bash
# Non-interactive refresh — meant for launchd / cron.
# Picks up the most recent claude.ai export zip in ~/Downloads and rebuilds
# the constellation. Logs to ~/.claude-constellation.log.

REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOG="$HOME/.claude-constellation.log"

{
  echo ""
  echo "─── $(date) ───"
  cd "$REPO_DIR"

  LATEST=""
  for f in "$HOME/Downloads/"data-*.zip; do
    [ -f "$f" ] && LATEST="$f"
  done
  # Pick most-recent by mtime
  LATEST=$(ls -t "$HOME/Downloads/"data-*.zip 2>/dev/null | head -1)

  if [ -n "$LATEST" ]; then
    AGE=$(( ( $(date +%s) - $(stat -f %m "$LATEST") ) / 86400 ))
    echo "▸ Using web export: $LATEST (${AGE}d old)"
    python3 claude_constellation.py \
      --web-export "$LATEST" \
      --output "$HOME/Desktop/conversation-constellation.html"
  else
    echo "▸ No export zip in ~/Downloads — local sessions only"
    python3 claude_constellation.py \
      --output "$HOME/Desktop/conversation-constellation.html"
  fi
  echo "  done"
} >> "$LOG" 2>&1
