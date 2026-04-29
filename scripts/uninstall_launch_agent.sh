#!/usr/bin/env bash
set -euo pipefail

LABEL="com.joshuagraham.swiss-passport-bot"
WATCHDOG_LABEL="$LABEL.watchdog"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
WATCHDOG_PLIST="$HOME/Library/LaunchAgents/$WATCHDOG_LABEL.plist"

launchctl unload "$PLIST" >/dev/null 2>&1 || true
launchctl unload "$WATCHDOG_PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST"
rm -f "$WATCHDOG_PLIST"

echo "Removed $LABEL"
echo "Removed $WATCHDOG_LABEL"
