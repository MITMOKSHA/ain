#!/bin/sh
# Generate and install a launchd agent for this checkout.
#
# launchd requires absolute paths and does not expand shell variables, so the
# plist cannot be portable. Rather than committing a plist with someone else's
# home directory baked in, this script generates one for wherever the repo
# currently lives.
#
# Usage:
#   sh scripts/install-launchd.sh          # install (08:30 + 20:30 daily)
#   sh scripts/install-launchd.sh --uninstall
#   sh scripts/install-launchd.sh --hours "9,21" --minute 0

set -eu

SCRIPT="$0"
while [ -L "$SCRIPT" ]; do
  LINK=$(readlink "$SCRIPT")
  case "$LINK" in
    /*) SCRIPT="$LINK" ;;
    *)  SCRIPT="$(dirname "$SCRIPT")/$LINK" ;;
  esac
done
ROOT="$(cd "$(dirname "$SCRIPT")/.." && pwd)"

LABEL="com.ain.daily"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
HOURS="8,20"
MINUTE="30"

while [ $# -gt 0 ]; do
  case "$1" in
    --uninstall)
      launchctl unload "$DEST" 2>/dev/null || true
      rm -f "$DEST"
      echo "已卸载 $LABEL"
      exit 0
      ;;
    --hours)  HOURS="$2"; shift 2 ;;
    --minute) MINUTE="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

if [ ! -f "$ROOT/scripts/daily.sh" ]; then
  echo "找不到 $ROOT/scripts/daily.sh，脚本位置不对？" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"

# Build the StartCalendarInterval array from --hours / --minute.
INTERVALS=""
OLD_IFS="$IFS"; IFS=','
for h in $HOURS; do
  INTERVALS="$INTERVALS
        <dict>
            <key>Hour</key><integer>$h</integer>
            <key>Minute</key><integer>$MINUTE</integer>
        </dict>"
done
IFS="$OLD_IFS"

cat > "$DEST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>$ROOT/scripts/daily.sh</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$ROOT</string>

    <key>StartCalendarInterval</key>
    <array>$INTERVALS
    </array>

    <key>RunAtLoad</key>
    <false/>

    <key>StandardOutPath</key>
    <string>$ROOT/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$ROOT/logs/launchd.err.log</string>
</dict>
</plist>
PLIST

# Validate before loading, so a broken plist never reaches launchd.
if command -v plutil >/dev/null 2>&1; then
  plutil -lint "$DEST" >/dev/null || { echo "生成的 plist 无效: $DEST" >&2; exit 1; }
fi

launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"

echo "已安装 $LABEL"
echo "  项目路径: $ROOT"
echo "  运行时间: 每天 $HOURS 点的第 $MINUTE 分"
echo "  plist:    $DEST"
echo
echo "常用命令:"
echo "  launchctl start $LABEL       # 立刻试跑一次"
echo "  launchctl list | grep ain    # 查看状态"
echo "  tail -f $ROOT/logs/fetch.log # 看日志"
echo "  sh scripts/install-launchd.sh --uninstall   # 卸载"
