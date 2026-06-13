#!/bin/sh
# Hydra HQ leadwatch — 20s loop (0-token, host-side, notify-only).
# Run as a systemd service (hq-leadwatch.service). Sequential: never overlaps a run; a single
# crashed run goes to the log and the loop continues; Restart=always covers the wrapper itself.
# Pings each room's LEAD on a worker's done/stuck transition (no auto-dispatch). --drive sends;
# without it, dry-run logs only. Set HQ_LEADWATCH_DRIVE=1 in the unit to go live.
export PATH=/home/user/.local/bin:/usr/bin:/bin
LOG=/home/user/.hq-leadwatch.log
while true; do
    /usr/bin/python3 /home/user/.local/bin/hq-leadwatch.py >> "$LOG" 2>&1
    sleep 20
done
