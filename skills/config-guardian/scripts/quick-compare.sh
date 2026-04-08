#!/usr/bin/env bash
# quick-compare.sh — 对比两个备份或备份与当前配置
# 用法: ./quick-compare.sh <backup1> <backup2|current>

set -euo pipefail

BACKUP_ROOT="$HOME/.openclaw/backups"

if [[ "$#" -lt 1 ]]; then
  echo "用法: $0 <backup-timestamp> [<other-backup-timestamp|current>]"
  echo ""
  ls "$BACKUP_ROOT" | grep "20[0-9]" | tac | head -5
  exit 1
fi

FILE1="$BACKUP_ROOT/$1"
if [[ "$#" -ge 2 && "$2" != "current" ]]; then
  FILE2="$BACKUP_ROOT/$2"
else
  FILE2="$HOME/.openclaw/openclaw.json"
fi

echo "对比: $1 vs $([[ "$#" -ge 2 && "$2" != "current" ]] && echo "$2" || echo "current")"
echo "======================================="

for key in "openclaw.json"; do
  if [ -f "$FILE1/$key" ] && [ -f "$FILE2" ]; then
    if diff -q "$FILE1/$key" "$FILE2" >/dev/null 2>&1; then
      echo "  ✓ $key — 完全相同"
    else
      echo "  ✗ $key — 有差异:"
      diff "$FILE1/$key" "$FILE2" | head -30 | sed 's/^/    /'
    fi
  fi
done
