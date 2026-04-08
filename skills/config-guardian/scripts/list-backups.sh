#!/usr/bin/env bash
# list-backups.sh — 列出所有配置备份
# 用法: ./list-backups.sh

set -euo pipefail

BACKUPRoot="$HOME/.openclaw/backups"
INDEX="$BACKUPRoot/backup-index.jsonl"

if [ ! -d "$BACKUPRoot" ]; then
  echo "暂无备份。"
  exit 0
fi

echo "📁 OpenClaw 配置备份"
echo "===================="
echo ""

# 如果有索引文件，用索引展示
if [ -f "$INDEX" ]; then
  tail -10 "$INDEX" | tac | while IFS= read -r line; do
    DIR=$(echo "$line" | grep -o '"dir":"[^"]*"' | cut -d'"' -f4)
    TS=$(echo "$line" | grep -o '"timestamp":"[^"]*"' | cut -d'"' -f4)
    FILES=$(echo "$line" | grep -o '"files":[0-9]*' | cut -d':' -f2)
    SIZE=$(echo "$line" | grep -o '"size":"[^"]*"' | cut -d'"' -f4)
    if [ -d "$DIR" ]; then
      echo "  ✅ $TS  |  $FILES files  |  $SIZE"
    else
      echo "  ❌ $TS  |  (已清理)"
    fi
  done
else
  # 回退：直接扫描目录
  for dir in $(ls -d "$BACKUPRoot"/20[0-9]* 2>/dev/null | sort -r | head -10); do
    BASENAME=$(basename "$dir")
    if [ -d "$dir" ]; then
      FILES=$(find "$dir" -type f | wc -l | tr -d ' ')
      SIZE=$(du -sh "$dir" | cut -f1)
      echo "  ✅ $BASENAME  |  $FILES files  |  $SIZE"
    fi
  done
fi

echo ""
echo "使用: ~/.openclaw/workspace/skills/config-guardian/scripts/backup-configs.sh  # 创建备份"
echo "使用: ~/.openclaw/workspace/skills/config-guardian/scripts/restore-configs.sh <timestamp>  # 恢复"
