# 飞书 WebSocket 僵尸连接排查指南

**记录时间**：2026-03-29 | **整理时间**：2026-04-01 by 柱子

## 问题现象
- 飞书会话时断时续、消息丢失
- 微信等其他通道稳定，仅飞书不稳定
- 同一飞书机器人连接了多个 OpenClaw 实例（新旧实例共存）

## 根因分析
- 同一飞书应用可建立最多 50 个 WebSocket 长连接
- 旧实例（云服务器）虽已退订，但飞书服务器仍认为其连接"活着"（僵尸连接）
- 飞书采用集群负载均衡，消息随机推送给任一连接
- 当消息被路由到僵尸连接时，用户端表现为"消息无响应"

## 排查步骤

### 1. 检查当前实例日志
```bash
openclaw logs --follow | grep feishu
```
查看是否有重复的 "Connected to Feishu WebSocket" 日志。

### 2. 检查网络连接
```bash
lsof -i TCP:443 | grep ESTABLISHED
```

### 3. 确认是否只有一个实例在接收消息
日志中应只有一个来源的 dispatch 记录。

### 4. 查看网关状态
```bash
openclaw status
openclaw status --deep
```

## 解决方案

### 首选：重置飞书 App Secret
1. 飞书开放平台 → 重置 App Secret
2. 这会强制断开所有现存连接（含僵尸）
3. 更新本地 `openclaw.json` 中的 `appSecret`
4. 重启 OpenClaw：`openclaw gateway restart`

### 备选：切换模式
临时切换为 Webhook 模式再切回 WebSocket，触发服务器断开所有长连接。

### 确认
连续发送多条测试消息，观察回复稳定性。

## 预防措施
- 停用旧实例前，先优雅停机（`openclaw stop` 或 `Ctrl+C`）发送 WebSocket Close Frame
- 避免同一飞书应用在多个环境中同时使用（测试/生产应分开）
- 如有多实例需求，启用共享 session 存储（Redis）并明确负载均衡策略
- 定期检查飞书开放平台的事件推送状态和连接数

## 关键要点
- WebSocket 模式下，飞书不会自动清理僵尸连接（除非凭证变更或应用重启）
- 同一 App ID 的多实例会导致消息路由随机化，表现为不一致的可用性
- `allowlist` 配置只影响消息是否转发给 agent，不解决底层连接竞争问题

## 相关命令
```bash
openclaw status                                    # 查看网关状态
openclaw status --deep                             # 查看通道详情
tail -f /tmp/openclaw/openclaw-*.log | grep feishu # 实时日志检查
lsof -i TCP:443 | grep ESTABLISHED                 # 检查 443 端口连接
```
