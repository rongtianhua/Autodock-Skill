# HEARTBEAT.md

## 定期任务（每 2-3 天执行一次，不要每次心跳都执行）

### Dreaming 状态检查（每周执行一次）
1. 运行 `openclaw memory status --deep` 查看 Dreaming 是否正常运行
2. 检查 `promoted-today` 数量，确认有内容被自动晋升
3. 如有异常情况，尝试 `openclaw memory promote --limit 5` 手动预览晋升候选
4. 检查 `DREAMS.md`（或 `dreams.md`）是否有新梦境日记
5. 注意：日常记忆维护已由 Dreaming 自动接管（每天凌晨 3 点），不再需要手动执行

### Self-Reflection 自查（每 60 分钟检查一次，间隔≥2 天执行）
1. 运行 self-reflection 逻辑：读取近期教训，反思改进点
2. 将反思结果写入 `memory/self-review.md`
3. 更新 `~/.openclaw/self-review-state.json` 记录上次执行时间

### Self-Improving 心跳（间隔≥2 天执行）
1. 读取 `self-improving` skill 的 `heartbeat-rules.md` 了解流程
2. 扫描 `~/self-improving/` 是否有文件变化
3. 如果有新教训/校正，写入 `corrections.md`
4. 如果无变化，回复 `HEARTBEAT_OK`

### Proactive-Agent 心跳（间隔≥2 天执行）
1. 检查 `~/proactivity/session-state.md` 是否有挂起任务
2. 如果有中断的任务，从 `working-buffer.md` 恢复
3. 读取 `~/self-improving/corrections.md` 近期教训
4. 如无待办，回复 `HEARTBEAT_OK`

## 注意事项
- 以上维护任务不要每个心跳都跑，标记上次执行日期，间隔 ≥2 天再执行
- 记录上次执行日期在 `memory/heartbeat-state.json` 中
- 维护完成后，在 `memory/YYYY-MM-DD.md` 记下"执行了记忆维护"
- 其余心跳如无其他任务，回复 HEARTBEAT_OK

## 状态追踪
每次执行维护后更新此文件中的日期，下次心跳检查是否已过 2 天。

上次记忆维护：2026-04-05
上次配置备份：2026-04-05

## 配置守护与热重载优化

### 核心原则（基于官方文档）
- **热重载模式**：`gateway.reload.mode` 默认 `hybrid`，安全变更自动热应用，关键变更自动重启
- **需要重启的配置类别**：
  - `gateway.*`（端口、绑定、认证、tailscale、TLS、HTTP）
  - `discovery`、`canvasHost`、`plugins`（基础设施）
- **可热应用的配置**：channels、agents、models、hooks、cron、session、tools、skills、bindings 等
- **例外**：`gateway.reload` 和 `gateway.remote` 变更不触发重启

### 智能配置修改 SOP（新）
```
1. 备份 → backup-configs.sh
2. 修改 → 编辑配置文件或运行向导
3. 校验 → openclaw config validate
4. 判断：
   - 如果修改涉及 gateway.* / discovery / canvasHost / plugins → 需重启
   - 否则 → 仅热重载，无需手动重启（网关自动处理）
5. 验证 → 测试通道是否正常
```

### 实现方式
- 使用 `openclaw config get <path>` 获取修改前的值
- 修改后对比变化的路径
- 如果变化的路径以 `gateway.`、`discovery`、`canvasHost`、`plugins` 开头 → 需要重启
- 否则 → 仅热重载（等待 1-2 秒让 chokidar 检测到变化）

示例：
```bash
# 仅热重载（修改模型设置）
openclaw config set agents.defaults.model.primary "openrouter/anthropic/claude-opus-4-6"
# 无需 restart，网关自动应用

# 需要重启（修改端口）
openclaw config set gateway.port 18790
# 必须 restart
```

### 配置变更检查脚本（新增）
位置：`~/.openclaw/workspace/skills/config-guardian/scripts/check-restart-needed.sh`
用法：传递一个或多个配置路径，判断是否需要重启
```bash
~/.openclaw/workspace/skills/config-guardian/scripts/check-restart-needed.sh gateway.port agents.defaults.models
# 输出：RESTART_NEEDED（包含 gateway.）
```

### 配置守护心跳逻辑更新
- 如果检测到 `openclaw.json` 被修改（通过文件时间戳对比）
  - 自动运行 `openclaw config validate`
  - 运行 `check-restart-needed.sh` 判断
  - 如果需要重启 → 记录到 `memory/config-changes.json`，提醒用户手动重启
  - 如果仅热重载 → 记录变更并静默通过
- 不等待执行，每个心跳只检查一次，避免频繁操作

### 配置守护规则（每次心跳/配置变更时检查）

#### 智能判断是否需要重启
基于 OpenClaw 热重载机制（hybrid 模式）：
- **需要重启**的配置：`gateway.*`、`discovery`、`canvasHost`、`plugins`
- **可热重载**：其他所有配置（channels、agents、models、cron、hooks、session、tools、skills、bindings 等）

#### 配置修改 SOP
任何配置修改后必须按此流程：
1. **备份** → 运行 `~/.openclaw/workspace/skills/config-guardian/scripts/backup-configs.sh`
2. **修改** → 编辑文件或运行向导
3. **校验** → `openclaw config validate`
4. **判断** → 运行 `check-restart-needed.sh` 判断修改的字段
   - 如需重启 → `openclaw gateway restart`
   - 如仅热重载 → 无需操作，网关自动应用
5. **验证** → 发消息到各通道确认正常

#### 高危命令拦截
以下命令执行前 **必须先备份并提醒用户**：
- `openclaw onboard` → **初始化向导，会清空所有配置**（用户曾误敲此命令代替 configure）
- `openclaw configure` → **配置向导，会覆盖 channels 字段**
- `openclaw upgrade` → 版本更新可能触发配置迁移
- 直接编辑 `~/.openclaw/openclaw.json` → 需要 validate 后才能 restart

#### 定期备份（每 3 天执行一次）
- 运行 `backup-configs.sh` 创建完整备份
- 备份保留 30 天，自动清理过期备份
- 版本更新后立即触发备份

#### 恢复流程
如配置丢失，按以下步骤恢复：
1. 列出备份：`~/.openclaw/workspace/skills/config-guardian/scripts/list-backups.sh`
2. 恢复配置：`~/.openclaw/workspace/skills/config-guardian/scripts/restore-configs.sh <timestamp>`
3. 校验：`openclaw config validate`
4. 重启：`openclaw gateway restart`

#### 备份索引文件
- 索引位置：`~/.openclaw/backups/backup-index.jsonl`
- 备份根目录：`~/.openclaw/backups/`
- 脚本位置：`~/.openclaw/workspace/skills/config-guardian/scripts/`
