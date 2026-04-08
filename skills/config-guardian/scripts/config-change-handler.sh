#!/usr/bin/env bash
# config-change-handler.sh — 处理 openclaw.json 配置变更的完整流程
# 自动备份 → 校验 → 判断是否需要重启 → 记录变更历史
# 用法: 通常由文件监听触发，也可手动运行
# 示例: ./config-change-handler.sh "agents.defaults.model.primary" "openrouter/anthropic/claude-opus-4-6"

set -euo pipefail

CONFIG_FILE="$HOME/.openclaw/openclaw.json"
STATE_DIR="$HOME/.openclaw/workspace/memory"
CHANGES_LOG="$STATE_DIR/config-changes.jsonl"
HEARTBEAT_STATE="$STATE_DIR/heartbeat-state.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 如果文件不存在，无法继续
if [ ! -f "$CONFIG_FILE" ]; then
  echo "❌ 配置文件不存在: $CONFIG_FILE"
  exit 1
fi

# 获取配置最后修改时间
CONFIG_MTIME=$(stat -f%m "$CONFIG_FILE" 2>/dev/null || stat -c%Y "$CONFIG_FILE" 2>/dev/null || echo 0)

# 读取上次检查状态
LAST_CHECKED=0
if [ -f "$HEARTBEAT_STATE" ]; then
  LAST_CHECKED=$(jq -r '.configLastChecked // 0' "$HEARTBEAT_STATE" 2>/dev/null || echo 0)
fi

# 如果自上次检查后没有修改，跳过
if [ "$CONFIG_MTIME" -le "$LAST_CHECKED" ]; then
  exit 0
fi

echo "🔄 检测到配置变更，开始处理..."

# 1. 备份
echo "  1. 备份配置..."
"$SCRIPT_DIR/backup-configs.sh" --quiet

# 2. 校验
echo "  2. 校验配置..."
if ! openclaw config validate 2>&1 | grep -q "✅\|valid"; then
  echo "  ❌ 配置校验失败！请检查错误并修复。"
  echo "    已备份，可使用 restore-configs.sh 恢复。"
  exit 1
fi
echo "  ✅ 校验通过"

# 3. 判断是否需要重启（如果传入了变更路径参数）
NEEDS_RESTART=false
if [ "$#" -gt 0 ]; then
  echo "  3. 判断重启需求..."
  RESTART_CHECK=$("$SCRIPT_DIR/check-restart-needed.sh" "$@")
  if [[ "$RESTART_CHECK" == "RESTART_NEEDED" ]]; then
    NEEDS_RESTART=true
    echo "  ⚠️  检测到需要重启的配置变更"
  else
    echo "  ℹ️  仅热重载配置，无需重启"
  fi
else
  # 如果没有传入具体变更路径，标记为需要确认
  echo "  ℹ️  未提供变更路径，假设需要人工确认"
  NEEDS_RESTART=unknown
fi

# 4. 记录变更
echo "  4. 记录变更历史..."
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
CHANGE_ENTRY="{\"timestamp\":\"$TIMESTAMP\",\"config_mtime\":$CONFIG_MTIME,\"restart_needed\":$NEEDS_RESTART,\"paths\":$(printf '%s\n' "$@" | jq -R . | jq -s .)}"
echo "$CHANGE_ENTRY" >> "$CHANGES_LOG"

# 5. 更新心跳状态
if [ -f "$HEARTBEAT_STATE" ]; then
  jq ". + {\"configLastChecked\":$CONFIG_MTIME}" "$HEARTBEAT_STATE" > "$HEARTBEAT_STATE.tmp" && mv "$HEARTBEAT_STATE.tmp" "$HEARTBEAT_STATE"
else
  echo "{\"configLastChecked\":$CONFIG_MTIME}" > "$HEARTBEAT_STATE"
fi

# 6. 输出建议
echo ""
echo "✅ 配置变更处理完成"
if [[ "$NEEDS_RESTART" == "true" ]]; then
  echo "   请执行: openclaw gateway restart"
elif [[ "$NEEDS_RESTART" == "unknown" ]]; then
  echo "   请验证: openclaw config get <path> 确认变更"
else
  echo "   热重载已自动应用，无需额外操作"
fi
