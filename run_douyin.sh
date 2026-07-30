#!/usr/bin/env bash
# 抖音续火定时入口。失败也要写 job end，并尽量推送飞书。
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/cron.log"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] job start"
  set +e
  "$PYTHON_BIN" "$PROJECT_DIR/main.py"
  rc=$?
  set -e
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] job end rc=$rc"
  # 通知失败不影响任务退出码
  "$PYTHON_BIN" "$PROJECT_DIR/notify_run.py" --rc "$rc" || true
  exit "$rc"
} >> "$LOG_FILE" 2>&1
