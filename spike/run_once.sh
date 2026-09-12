#!/bin/bash
# One spike call: start the bot, drive it with the fake user, wait for teardown, prove the room
# is gone. Room expiry is forced to 10 minutes so a crashed run cannot leak Daily minutes.
set -u
LABEL="$1"; shift
LOG=/tmp/spike-$LABEL
rm -f "$LOG-bot.log" "$LOG-drive.log"

ROOM_EXPIRY_SECS=600 PYTHONPATH=. "$@" uv run python spike/spike_bot.py > "$LOG-bot.log" 2>&1 &
BOT=$!
for _ in $(seq 1 60); do grep -q "SPIKE ROOM" "$LOG-bot.log" && break; sleep 1; done
ROOM=$(grep -o 'https://[^ ]*daily.co/[A-Za-z0-9]*' "$LOG-bot.log" | head -1)
# Rooms are private; the bot prints a guest token beside the URL for the fake user.
TOKEN=$(grep -o 'SPIKE GUEST TOKEN: [^ ]*' "$LOG-bot.log" | head -1 | cut -d' ' -f4)
echo "[$LABEL] room=$ROOM token=${#TOKEN} chars"
[ -z "$ROOM" ] || [ -z "$TOKEN" ] && { kill $BOT 2>/dev/null; exit 1; }

PYTHONPATH=. uv run python spike/drive.py "$ROOM" "$TOKEN" > "$LOG-drive.log" 2>&1
echo "[$LABEL] driver done"

for _ in $(seq 1 30); do kill -0 $BOT 2>/dev/null || break; sleep 1; done
if kill -0 $BOT 2>/dev/null; then
  echo "[$LABEL] bot still running, sending SIGINT"
  kill -INT $BOT; sleep 8; kill -9 $BOT 2>/dev/null
fi
grep "room DELETE" "$LOG-bot.log" || echo "[$LABEL] NO DELETE LINE"
