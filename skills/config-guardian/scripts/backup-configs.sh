#!/usr/bin/env bash
# backup-configs.sh — 备份 OpenClaw 关键配置文件
# 安全红线：脚本会备份敏感文件，但不会将密钥内容输出到控制台
# 用法: ./backup-configs.sh [--quiet]
# 备份存储在 ~/.openclaw/backups/<timestamp>/

set -euo pipefail

BACKUP_ROOT="$HOME/.openclaw/backups"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H-%M-%S")
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"
QUIET=false

for arg in "$@"; do
  case "$arg" in
    --quiet) QUIET=true ;;
  esac
done

log() { if [ "$QUIET" = false ]; then echo "[backup] $*"; fi; }

# 创建备份目录
mkdir -p "$BACKUP_DIR"/{agents,channels,credentials,devices,identity,launchagents}

# ========== Tier 1 — 核心配置 ==========
log "Tier 1: 核心配置..."

cp "$HOME/.openclaw/openclaw.json" "$BACKUP_DIR/openclaw.json" 2>/dev/null && log "  ✅ openclaw.json" || log "  ❌ openclaw.json (not found)"

cp "$HOME/Library/LaunchAgents/ai.openclaw.gateway.plist" "$BACKUP_DIR/launchagents/" 2>/dev/null && log "  ✅ gateway.plist" || log "  ❌ gateway.plist (not found)"

cp "$HOME/Library/LaunchAgents/com.ollama.ollama.plist" "$BACKUP_DIR/launchagents/" 2>/dev/null && log "  ✅ ollama.plist" || log "  ⚠️  ollama.plist (not found)"

# Agent auth-profiles.json（各工作区的 API Key 配置）
for auth_file in "$HOME/.openclaw/agents"/*/agent/auth-profiles.json; do
  if [ -f "$auth_file" ]; then
    agent_name=$(basename "$(dirname "$(dirname "$auth_file")")")
    mkdir -p "$BACKUP_DIR/agents/$agent_name"
    cp "$auth_file" "$BACKUP_DIR/agents/$agent_name/"
    log "  ✅ agents/$agent_name/auth-profiles.json (keys protected)"
  fi
done

# ========== Tier 2 — 通道凭证与设备 ==========
log "Tier 2: 通道凭证与设备..."

mkdir -p "$BACKUP_DIR/channels/weixin/accounts"
cp "$HOME/.openclaw/openclaw-weixin/accounts.json" "$BACKUP_DIR/channels/weixin/" 2>/dev/null && log "  ✅ weixin/accounts.json" || log "  ⚠️  weixin/accounts.json (not found)"
cp "$HOME/.openclaw/openclaw-weixin/accounts/"*.json "$BACKUP_DIR/channels/weixin/accounts/" 2>/dev/null && log "  ✅ weixin/accounts/* (tokens protected)" || log "  ⚠️  weixin/accounts/* (not found)"

# Feishu 相关
cp "$HOME/.openclaw/credentials/"* "$BACKUP_DIR/credentials/" 2>/dev/null && log "  ✅ credentials/* (secrets protected)" || log "  ⚠️  credentials/* (not found)"
if [ -d "$HOME/.openclaw/feishu" ]; then
  mkdir -p "$BACKUP_DIR/channels/feishu"
  cp -r "$HOME/.openclaw/feishu/"* "$BACKUP_DIR/channels/feishu/" 2>/dev/null && log "  ✅ feishu/*" || true
fi

# 设备与身份
cp "$HOME/.openclaw/devices/"*.json "$BACKUP_DIR/devices/" 2>/dev/null && log "  ✅ devices/* (tokens protected)" || log "  ⚠️  devices/* (not found)"
cp "$HOME/.openclaw/identity/"*.json "$BACKUP_DIR/identity/" 2>/dev/null && log "  ✅ identity/* (auth protected)" || log "  ⚠️  identity/* (not found)"

# FreeRide cache（可能包含 API Key 缓存）
if [ -f "$HOME/.openclaw/.freeride-cache.json" ]; then
  cp "$HOME/.openclaw/.freeride-cache.json" "$BACKUP_DIR/" && log "  ✅ .freeride-cache.json (keys protected)" || log "  ⚠️  .freeride-cache.json (not found)"
fi

# Self-improving / Self-reflection 数据
if [ -f "$HOME/.openclaw/self-reflection.json" ]; then
  cp "$HOME/.openclaw/self-reflection.json" "$BACKUP_DIR/" && log "  ✅ self-reflection.json"
fi
if [ -f "$HOME/.openclaw/self-review-state.json" ]; then
  cp "$HOME/.openclaw/self-review-state.json" "$BACKUP_DIR/" && log "  ✅ self-review-state.json"
fi

# ========== Tier 2b — 插件 API Key 配置检查 ==========
log "Tier 2b: 插件 API Key 配置..."

# Tavily 配置检查（API Key 存在性验证，不输出内容）
if command -v jq &>/dev/null; then
  tavily_exists=$(jq -r '.plugins.entries.tavily.enabled // false' "$HOME/.openclaw/openclaw.json" 2>/dev/null || echo "false")
  if [ "$tavily_exists" = "true" ]; then
    tavily_key_present=$(jq -r '.plugins.entries.tavily.config.webSearch.apiKey // empty' "$HOME/.openclaw/openclaw.json" 2>/dev/null | wc -c)
    if [ "$tavily_key_present" -gt 10 ]; then
      log "  ✅ tavily: 配置存在，API Key 已设置 (protected)"
    else
      log "  ⚠️  tavily: 插件启用但 API Key 缺失或无效"
    fi
  else
    log "  ℹ️  tavily: 未启用"
  fi
else
  log "  ⚠️  jq 未安装，跳过 Tavily 配置验证"
fi

# ========== Tier 3 — 状态数据 ==========
log "Tier 3: 状态数据..."

cp "$HOME/.openclaw/cron/jobs.json" "$BACKUP_DIR/cron-jobs.json" 2>/dev/null && log "  ✅ cron/jobs.json" || log "  ⚠️  cron/jobs.json (not found)"

cp "$HOME/.openclaw/subagents/runs.json" "$BACKUP_DIR/subagents-runs.json" 2>/dev/null && log "  ✅ subagents/runs.json" || log "  ⚠️  subagents/runs.json (not found)"

cp "$HOME/.openclaw/exec-approvals.json" "$BACKUP_DIR/" 2>/dev/null && log "  ✅ exec-approvals.json" || log "  ⚠️  exec-approvals.json (not found)"

# ========== 生成校验和（敏感文件也生成，但只校验文件完整性，不输出内容） ==========
cd "$BACKUP_DIR"
find . -type f \( -name "*.json" -o -name "*.plist" \) | sort | while read -r f; do
  if command -v shasum &>/dev/null; then
    shasum -a 256 "$f" >> checksums.sha256 2>/dev/null
  elif command -v md5sum &>/dev/null; then
    md5sum "$f" >> checksums.md5 2>/dev/null
  fi
done

# ========== 统计 ==========
TOTAL_FILES=$(find "$BACKUP_DIR" -type f | wc -l | tr -d ' ')
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)

log ""
log "✅ 备份完成: $BACKUP_DIR"
log "   文件数: $TOTAL_FILES"
log "   大小: $TOTAL_SIZE"
log ""
log "⚠️  安全提示: 备份包含 API Key 和凭证，仅限本地使用"
log ""

# 清理 30 天前的旧备份（只保留最近 30 天）
log "清理 30 天前的旧备份..."
deleted=0
for old_dir in "$BACKUP_ROOT"/*; do
  if [ -d "$old_dir" ] && [ "$old_dir" != "$BACKUP_DIR" ]; then
    dir_mtime=$(stat -f%m "$old_dir" 2>/dev/null || stat -c%Y "$old_dir" 2>/dev/null || echo 0)
    cutoff=$(date -v-30d +%s 2>/dev/null || date -d '30 days ago' +%s 2>/dev/null || echo 0)
    if [ "$dir_mtime" -lt "$cutoff" ]; then
      rm -rf "$old_dir"
      deleted=$((deleted+1))
    fi
  fi
done
REMAINING=$(find "$BACKUP_ROOT" -maxdepth 1 -type d | wc -l | tr -d ' ')
log "   清理旧备份: $deleted 个"
log "   保留备份数: $((REMAINING-1))"  # 减去 backups 根目录本身

# 更新备份索引（索引中不记录密钥内容）
INDEX_FILE="$HOME/.openclaw/backups/backup-index.jsonl"
echo "{\"timestamp\":\"$TIMESTAMP\",\"dir\":\"$BACKUP_DIR\",\"files\":$TOTAL_FILES,\"size\":\"$TOTAL_SIZE\",\"date\":\"$(date -u)\"}" >> "$INDEX_FILE"
