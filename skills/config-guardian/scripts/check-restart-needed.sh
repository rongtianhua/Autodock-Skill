#!/usr/bin/env bash
# check-restart-needed.sh — 判断配置修改是否需要重启网关
# 基于 OpenClaw 官方文档的热重载指南
# 用法: ./check-restart-needed.sh <config_path1> [config_path2 ...]
# 返回: 如果任何路径需要重启，退出码 1 并输出 RESTART_NEEDED
#       如果全部可热重载，退出码 0 并输出 HOT_RELOAD_ONLY

set -euo pipefail

# 需要重启的配置前缀（来自官方文档）
RESTART_PREFIXES=(
  "gateway."
  "discovery"
  "canvasHost"
  "plugins"
)

# 例外：这些即使在 gateway.* 下也不触发重启（官方文档）
# gateway.reload 和 gateway.remote 变更不触发重启
EXCEPTIONS=(
  "gateway.reload"
  "gateway.remote"
)

needs_restart=false

for path in "$@"; do
  # 清理路径（移除前导点、斜杠）
  clean_path="${path#.}"
  clean_path="${clean_path#/}"

  # 检查例外
  is_exception=false
  for exception in "${EXCEPTIONS[@]}"; do
    if [[ "$clean_path" == "$exception" ]]; then
      is_exception=true
      break
    fi
  done
  if [[ "$is_exception" == true ]]; then
    continue
  fi

  # 检查是否需要重启
  for prefix in "${RESTART_PREFIXES[@]}"; do
    if [[ "$clean_path" == "$prefix"* ]] || [[ "$clean_path" == "$prefix" ]]; then
      needs_restart=true
      break 2
    fi
  done
done

if [[ "$needs_restart" == true ]]; then
  echo "RESTART_NEEDED"
  exit 1
else
  echo "HOT_RELOAD_ONLY"
  exit 0
fi
