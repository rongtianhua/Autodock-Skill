#!/usr/bin/env bash
# restore-configs.sh — 从备份恢复 OpenClaw 配置文件
# 安全红线：恢复操作会验证配置有效性，但不会将密钥内容输出到控制台
# 用法: ./restore-configs.sh <timestamp> [--dry-run]

set -euo pipefail

BACKUP_DIR="$1"
DRY_RUN=false

if [[ "$#" -lt 1 ]]; then
  echo "用法: $0 <timestamp> [--dry-run]"
  echo ""
  echo "可用备份:"
  ls "$HOME/.openclaw/backups/" | grep "20[0-9]" | tac | head -10
  exit 1
fi

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
  esac
done

BACKUP_PATH="$(echo "$HOME/.openclaw/backups/$BACKUP_DIR" | sed 's/--dry-run$//')"
if [ ! -d "$BACKUP_PATH" ]; then
  echo "❌ 备份不存在: $BACKUP_PATH"
  echo ""
  echo "可用备份:"
  ls "$HOME/.openclaw/backups/" | grep "20[0-9]" | tac | head -10
  exit 1
fi

say() { echo "[restore] $*"; }
run() {
  if [ "$DRY_RUN" = true ]; then
    say "dry-run: $*"
  else
    eval "$@"
  fi
}

say "准备从 $BACKUP_DIR 恢复..."
if [ "$DRY_RUN" = true ]; then
  say "（dry-run 模式，不会实际覆盖文件）"
fi

# 先备份当前配置（以防恢复失败）
RUNNING_BACKUP="$BACKUP_PATH/../pre-restore-$(date -u +%Y%m%dT%H%M%S)"
if [ "$DRY_RUN" = false ]; then
  mkdir -p "$RUNNING_BACKUP"
  cp "$HOME/.openclaw/openclaw.json" "$RUNNING_BACKUP/" 2>/dev/null || true
  cp "$HOME/.openclaw/openclaw-weixin/accounts.json" "$RUNNING_BACKUP/" 2>/dev/null || true
  say "已将当前配置备份到: $RUNNING_BACKUP"
fi

# ========== Tier 1 恢复 ==========
log "恢复核心配置..."
run "cp '$BACKUP_PATH/openclaw.json' '$HOME/.openclaw/openclaw.json'"
log "  ✅ openclaw.json"

run "cp -f '$BACKUP_PATH/launchagents/ai.openclaw.gateway.plist' '$HOME/Library/LaunchAgents/'" 2>/dev/null && log "  ✅ gateway.plist" || log "  ⚠️  gateway.plist (not in backup)"

run "cp -f '$BACKUP_PATH/launchagents/com.ollama.ollama.plist' '$HOME/Library/LaunchAgents/'" 2>/dev/null && log "  ✅ ollama.plist" || log "  ⚠️  ollama.plist (not in backup)"

# Agent auth-profiles 恢复（安全：不输出密钥内容）
if [ -d "$BACKUP_PATH/agents" ]; then
  for agent_dir in "$BACKUP_PATH/agents"/*; do
    if [ -d "$agent_dir" ] && [ -f "$agent_dir/auth-profiles.json" ]; then
      agent_name=$(basename "$agent_dir")
      agent_path="$HOME/.openclaw/agents/$agent_name/agent"
      mkdir -p "$agent_path"
      run "cp '$agent_dir/auth-profiles.json' '$agent_path/'"
      log "  ✅ agents/$agent_name/auth-profiles.json (keys restored)"
    fi
  done
fi

# ========== Tier 2 恢复 ==========
log "恢复通道凭证与设备..."
run "cp -f '$BACKUP_PATH/channels/weixin/'*.json '$HOME/.openclaw/openclaw-weixin/'" 2>/dev/null && log "  ✅ weixin configs" || log "  ⚠️  weixin configs (not in backup)"
run "cp -rf '$BACKUP_PATH/channels/weixin/accounts/'* '$HOME/.openclaw/openclaw-weixin/accounts/'" 2>/dev/null && log "  ✅ weixin/accounts (tokens restored)" || log "  ⚠️  weixin/accounts (not in backup)"

run "cp -f '$BACKUP_PATH/credentials/'* '$HOME/.openclaw/credentials/'" 2>/dev/null && log "  ✅ credentials (secrets restored)" || log "  ⚠️  credentials (not in backup)"
run "cp -f '$BACKUP_PATH/devices/'* '$HOME/.openclaw/devices/'" 2>/dev/null && log "  ✅ devices (tokens restored)" || log "  ⚠️  devices (not in backup)"
run "cp -f '$BACKUP_PATH/identity/device.json' '$HOME/.openclaw/identity/'" 2>/dev/null && log "  ✅ identity/device.json" || log "  ⚠️  identity/device.json (not in backup)"

# 校验配置
if [ "$DRY_RUN" = false ]; then
  say ""
  say "验证恢复的配置..."
  if openclaw config validate 2>/dev/null; then
    say "  ✅ 配置校验通过"
    say ""
    say "⚠️  需要重启生效: openclaw gateway restart"
  else
    say "  ❌ 配置校验失败！已自动将原配置备份到: $RUNNING_BACKUP"
  fi
else
  say ""
  say "（校验将在实际恢复后执行）"
fi

if [ "$DRY_RUN" = false ]; then
  say ""
  say "✅ 恢复完成！"
  say "请执行校验：$0 --validate"
fi