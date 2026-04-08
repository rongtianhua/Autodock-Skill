# Config Guardian — 配置文件守护技能

守护 OpenClaw 关键配置文件，防止因误操作、版本更新、向导覆盖等原因导致配置丢失。

## ⚠️ 安全红线

**绝对禁止泄露配置文件中的以下内容**：
- API Key / App Secret / Access Token（任何密钥）
- 用户个人信息（电话号码、姓名、密码等）
- 设备配对凭证 / Bootstrap Token
- Gateway 认证密码

**执行原则**：
- 备份脚本会对关键文件做完整性校验，但不会明文打印敏感字段
- 恢复时校验配置有效性，但不输出密钥内容
- 任何涉及密钥的操作，只验证存在性，不展示内容

## 遗漏项自查清单

以下文件在备份脚本中已覆盖，但需留意未来可能新增的：

| 类别 | 路径模式 | 说明 |
|------|----------|------|
| FreeRide 缓存 | `~/.openclaw/.freeride-cache.json` | 可能含 API Key，已备份 |
| Self-reflection | `~/.openclaw/self-reflection.json` | 状态文件，已备份 |
| Self-review | `~/.openclaw/self-review-state.json` | 定时任务状态，已备份 |
| Feishu 去重 | `~/.openclaw/feishu/` 目录 | 飞书消息去重状态，已备份 |
| **Tavily 配置** | **`plugins.entries.tavily`** in `openclaw.json` | **搜索插件配置，已备份** |
| Update check | `~/.openclaw/update-check.json` | 版本检查缓存，已备份 |
| 设备身份 | `~/.openclaw/identity/device-auth.json` | 额外认证状态，已备份 |

## 守护范围（关键文件清单）

### Tier 1 — 核心配置（必须保护）
| 文件 | 作用 |
|------|------|
| `~/.openclaw/openclaw.json` | 全局主配置（gateway, agents, channels, bindings） |
| `~/Library/LaunchAgents/ai.openclaw.gateway.plist` | 系统服务配置（环境变量、TZ 等） |
| `~/Library/LaunchAgents/com.ollama.ollama.plist` | Ollama 云代理配置（如存在） |
| `~/.openclaw/agents/*/agent/auth-profiles.json` | 各 Agent 的 API Key 配置 |

### Tier 2 — 通道凭证、插件 API Key 与设备信息（必须保护）
| 文件/配置 | 作用 |
|-----------|------|
| `~/.openclaw/openclaw-weixin/accounts.json` | 微信账号注册表 |
| `~/.openclaw/openclaw-weixin/accounts/*.json` | 各微信账号配置（含 token） |
| `~/.openclaw/credentials/feishu-*` | 飞书凭证和权限配置 |
| **`plugins.entries.tavily.config.webSearch.apiKey`** | **Tavily 搜索 API Key** |
| `~/.openclaw/devices/*.json` | 设备配对信息（含 bootstrap token） |
| `~/.openclaw/identity/device.json` | 设备身份标识 |

### Tier 3 — 状态与运行时数据（选择性保护）
| 文件 | 作用 |
|------|------|
| `~/.openclaw/cron/jobs.json` | Cron 任务列表 |
| `~/.openclaw/subagents/runs.json` | 子 Agent 运行状态 |
| `~/.openclaw/exec-approvals.json` | 命令审批记录 |

## 标准操作流程

### 自动备份（Cron Job）

已设置 `openclaw-config-backup` cron job：
- **频率**：每 3 天（259,200,000 ms）
- **方式**：isolated session 静默执行
- **命令**：`backup-configs.sh --quiet`
- **验证**：`openclaw cron list` 查看

如需手动执行备份：
```bash
~/.openclaw/workspace/skills/config-guardian/scripts/backup-configs.sh
```

### 1. 手动备份/恢复/列出

```bash
# 执行备份
~/.openclaw/workspace/skills/config-guardian/scripts/backup-configs.sh

# 手动恢复（选择某个备份）
~/.openclaw/workspace/skills/config-guardian/scripts/restore-configs.sh <timestamp>

# 列出所有备份
~/.openclaw/workspace/skills/config-guardian/scripts/list-backups.sh
```

### 2. 校验（任何配置修改之后必须执行）

```bash
openclaw config validate
```

**红线**：
- 修改 `openclaw.json` 后 **必须** 立即执行 `openclaw config validate`
- 校验失败 → **不要** 重启 gateway，先修复配置
- 校验通过 → 执行 `openclaw gateway restart`

### 3. 高危操作拦截

以下操作在执行前 **必须** 先备份并提醒用户：
- `openclaw configure` → 会覆盖 channels 字段
- `openclaw onboard` → 会重置整个配置
- `openclaw upgrade` → 可能触发配置迁移
- 直接编辑 `openclaw.json` → 需要 validate 后才能 restart

### 4. 恢复（`scripts/restore-configs.sh`）

```bash
# 列出可用备份
~/.openclaw/workspace/skills/config-guardian/scripts/list-backups.sh

# 恢复到指定时间点
~/.openclaw/workspace/skills/config-guardian/scripts/restore-configs.sh 2026-04-05T18-00-00

# 恢复后校验
openclaw config validate
openclaw gateway restart
```

## 配置变更规则（写入 HEARTBEAT.md 的工作流规则）

### 配置修改 SOP
1. **备份** → 运行 `backup-configs.sh`
2. **修改** → 编辑文件或运行向导
3. **校验** → `openclaw config validate`
4. **重启** → `openclaw gateway restart`
5. **验证** → 发消息到各通道确认正常

### 高危命令别名提醒
- `openclaw onboard` = 初始化向导 = **会清空现有配置**
- `openclaw configure` = 配置向导 = **会覆盖 channels 字段**
- 用户混淆这两个命令时，**必须拦截提醒**

## 定期维护

- **每次心跳检查**：无（避免噪音）
- **每 3 天**：执行一次自动备份
- **版本更新后**：立即触发完整备份
- **配置修改后**：立即触发备份

## 参考

- `scripts/backup-configs.sh` — 完整备份脚本
- `scripts/restore-configs.sh` — 恢复脚本
- `scripts/list-backups.sh` — 列出备份
- `scripts/quick-compare.sh` — 对比两个备份配置差异
