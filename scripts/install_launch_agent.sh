#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
LABEL="com.joshuagraham.swiss-passport-bot"
WATCHDOG_LABEL="$LABEL.watchdog"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
WATCHDOG_PLIST="$HOME/Library/LaunchAgents/$WATCHDOG_LABEL.plist"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python at $PYTHON"
  echo "Run: python3 -m venv .venv && . .venv/bin/activate && python -m pip install -r requirements.txt"
  exit 1
fi

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Missing $ROOT/.env"
  echo "Run: cp .env.example .env, then fill in your session URL and Telegram details."
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-m</string>
    <string>swiss_passport_bot</string>
    <string>check</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>7</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$ROOT/logs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$ROOT/logs/launchd.err.log</string>
</dict>
</plist>
PLIST

cat > "$WATCHDOG_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$WATCHDOG_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-m</string>
    <string>swiss_passport_bot</string>
    <string>watchdog</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>900</integer>
  <key>StandardOutPath</key>
  <string>$ROOT/logs/watchdog.out.log</string>
  <key>StandardErrorPath</key>
  <string>$ROOT/logs/watchdog.err.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" >/dev/null 2>&1 || true
launchctl unload "$WATCHDOG_PLIST" >/dev/null 2>&1 || true
launchctl load "$PLIST"
launchctl load "$WATCHDOG_PLIST"

echo "Installed $LABEL"
echo "Installed $WATCHDOG_LABEL"
echo "Logs:"
echo "  $ROOT/logs/launchd.out.log"
echo "  $ROOT/logs/launchd.err.log"
echo "  $ROOT/logs/watchdog.out.log"
echo "  $ROOT/logs/watchdog.err.log"
