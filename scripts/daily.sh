#!/bin/sh
# Daily fetch entry point used by launchd (macOS) or cron.
#
# Portable by design: the repo root is derived from this script's own location,
# so the same checkout works on any machine and in any directory. A hardcoded
# path here would break the moment you clone this somewhere else.
#
# launchd does not inherit your shell PATH, so python3 is resolved explicitly
# with fallbacks.

set -u

# Root = parent directory of this script (resolves symlinks where possible).
SCRIPT="$0"
while [ -L "$SCRIPT" ]; do
  LINK=$(readlink "$SCRIPT")
  case "$LINK" in
    /*) SCRIPT="$LINK" ;;
    *)  SCRIPT="$(dirname "$SCRIPT")/$LINK" ;;
  esac
done
ROOT="$(cd "$(dirname "$SCRIPT")/.." && pwd)"

# Prefer an explicit override, then common python3 locations.
if [ -n "${AIN_PYTHON:-}" ]; then
  PYTHON="$AIN_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
elif [ -x /usr/bin/python3 ]; then
  PYTHON="/usr/bin/python3"
else
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] 找不到 python3，请设置 AIN_PYTHON" >> "$ROOT/logs/fetch.log" 2>/dev/null
  exit 127
fi

LOG_DIR="$ROOT/logs"
LOCK="$ROOT/data/.lock"

mkdir -p "$LOG_DIR" "$ROOT/data" "$ROOT/reports"
cd "$ROOT" || exit 1

# Skip if a run is already in progress (lock is created by ain itself).
if [ -f "$LOCK" ]; then
  age=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || echo 0) ))
  if [ "$age" -lt 3600 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 已有运行中的抓取（锁 age=${age}s），跳过" >> "$LOG_DIR/fetch.log"
    exit 0
  fi
  rm -f "$LOCK"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== 开始抓取 =====" >> "$LOG_DIR/fetch.log"
"$PYTHON" -m ain fetch -n 40 >> "$LOG_DIR/fetch.log" 2>&1
code=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== 结束 (exit=$code) =====" >> "$LOG_DIR/fetch.log"

# Keep the log from growing without bound.
if [ -f "$LOG_DIR/fetch.log" ]; then
  lines=$(wc -l < "$LOG_DIR/fetch.log")
  if [ "$lines" -gt 4000 ]; then
    tail -2000 "$LOG_DIR/fetch.log" > "$LOG_DIR/fetch.log.tmp" && mv "$LOG_DIR/fetch.log.tmp" "$LOG_DIR/fetch.log"
  fi
fi

exit $code
