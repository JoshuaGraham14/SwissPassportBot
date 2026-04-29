#!/usr/bin/env bash
set -euo pipefail

trap 'kill 0' TERM INT

start_watchdog_loop() {
  local interval="${WATCHDOG_INTERVAL_SECONDS:-900}"
  while true; do
    if ! python -m swiss_passport_bot watchdog; then
      echo "Watchdog run failed; retrying after ${interval}s" >&2
    fi
    sleep "$interval"
  done
}

xvfb-run -a python -m swiss_passport_bot run &
run_pid=$!

start_watchdog_loop &
watchdog_pid=$!

wait -n "$run_pid" "$watchdog_pid"