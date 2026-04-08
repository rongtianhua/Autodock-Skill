# OpenClaw 心跳与记忆维护配置指南

**记录时间**：2026-04-01 by 柱子

---

## 背景

OpenClaw 的心跳（heartbeat）机制是实现自动化后台维护的基础，但默认配置下心跳不会做任何事。这篇指南整理了心跳机制的原理、记忆维护的配置方法，以及相关的坑。

---

## 心跳机制原理

### 基本流程

1. **心跳触发**：Gateway 每隔固定间隔（默认 30 分钟）向当前 agent 发送心跳轮询消息
2. **读取 HEARTBEAT.md**：agent 会读取工作区根目录的 `HEARTBEAT.md` 文件
3. **判断是否有任务**：
   - 如果 HEARTBEAT.md 有任务清单 → 执行任务
   - 如果 HEARTBEAT.md 为空或只有注释 → 回复 `HEARTBEAT_OK`（不做事）
4. **心跳完成**：agent 回复结果

### 关键设计

- `AGENTS.md` 是通用行为指南，可以写"建议做记忆维护"
- `HEARTBEAT.md` 是心跳的**实际任务清单**
- **如果 HEARTBEAT.md 是空的，即使 AGENTS.md 里写了建议，心跳也不会执行**

这就是为什么默认情况下记忆维护从来没有被自动执行过。

---

## 默认配置的问题

### 默认 HEARTBEAT.md 内容

```markdown
# HEARTBEAT.md Template

# Keep this file empty (or with only comments) to skip heartbeat API calls.

# Add tasks below when you want the agent to check something periodically.
```

### 后果

- 心跳每 30 分钟触发一次 → 看到空文件 → HEARTBEAT_OK
- AGENTS.md 里建议的"定期维护记忆"永远不会被触发
- `MEMORY.md` 会积累噪音（小模型写的 raw log、命令输出、状态快照）

### 这是一个坑

AGENTS.md 和 HEARTBEAT.md 的分离设计是合理的（一个管行为，一个管任务），但默认模板里没有引导用户把 AGENTS.md 里的建议搬运到 HEARTBEAT.md 中。大多数新用户不会意识到这一点。

---

## 记忆维护的正确配置

### 1. 编辑 HEARTBEAT.md

```markdown
# HEARTBEAT.md

## 定期任务（每 2-3 天执行一次，不要每次心跳都执行）

### 记忆维护
1. 检查 `memory/YYYY-MM-DD.md` 中最近 2-3 天的笔记
2. 将重要决策、故障排查经验、配置变更等提炼到 `MEMORY.md`
3. 清理 MEMORY.md 中的噪音和过时信息
4. 如有新积累的指南级内容，写入 `memory/guides/` 并更新 MEMORY.md 的 Guides 索引

## 注意事项
- 以上维护任务不要每个心跳都跑，标记上次执行日期，间隔 ≥2 天再执行
- 记录上次执行日期在 `memory/heartbeat-state.json` 中
- 维护完成后，在 `memory/YYYY-MM-DD.md` 记下"执行了记忆维护"
- 其余心跳如无其他任务，回复 HEARTBEAT_OK

## 状态追踪
每次执行维护后更新此文件中的日期，下次心跳检查是否已过 2 天。

上次记忆维护：2026-04-01
```

### 2. 创建 heartbeat-state.json

```json
{
  "lastChecks": {
    "email": null,
    "calendar": null,
    "weather": null
  },
  "maintenance": {
    "lastMemoryReview": "2026-04-01"
  }
}
```

### 3. 心跳执行逻辑

每当心跳触发时：
1. 读取 HEARTBEAT.md → 看到有任务
2. 读取 heartbeat-state.json → 检查上次维护日期
3. 如果距离上次维护 ≥ 2 天 → 执行维护 → 更新 state.json → 在当日笔记记一笔
4. 如果 < 2 天 → 跳过维护 → HEARTBEAT_OK

---

## 心跳可以做哪些事

- **记忆维护**（本文主题）
- **检查邮件**：`openclaw email` 或 himalaya CLI
- **检查日历**：gog CLI
- **检查天气**：wttr.in
- **检查社交媒体通知**：xurl CLI
- **执行后台任务**：git commit、文档更新、配置同步

---

## 心跳 vs Cron

| | 心跳 | Cron |
|---|---|---|
| **触发时机** | 固定间隔（如 30 分钟） | 精确时间或间隔 |
| **执行环境** | 当前会话（有上下文） | 隔离会话（无上下文） |
| **适合场景** | 多项检查批量执行 | 精确定时任务、一次性提醒 |
| **API 消耗** | 每次心跳都消耗 token | 只在触发时消耗 |

### 建议
- **批量检查类任务** → 心跳
- **精确定时任务** → Cron（如"周一 9:00 提醒"）
- **一次性任务** → Cron（执行后可以删掉）

---

## 记忆文件组织

```
~/.openclaw/workspace/
├── MEMORY.md                    # 长期记忆（精炼版）
├── HEARTBEAT.md                 # 心跳任务清单
└── memory/
    ├── YYYY-MM-DD.md            # 每日笔记（事件驱动写入）
    ├── heartbeat-state.json     # 心跳状态追踪
    └── guides/                  # 系统性指南
        ├── multi-agent-guide.md
        ├── feishu-zombie-connection.md
        ├── model-switching-api.md
        └── heartbeat-memory.md  # ← 本文件
```

### 各级用途

| 文件 | 用途 | 写入方式 |
|---|---|---|
| `memory/YYYY-MM-DD.md` | 当天发生的事 | 对话中事件驱动 |
| `MEMORY.md` | 长期记忆（精华版） | 心跳维护期间提炼 |
| `memory/guides/*.md` | 系统性教程/指南 | 有结构化价值时写入 |
| `heartbeat-state.json` | 心跳状态追踪 | 心跳维护后更新 |

### 重要原则
- **所有 memory/ 目录下的文件都会被 memory_search 检索到**（包括子目录 guides/）
- 所以只要放在 memory/ 下，不管是每日笔记还是指南，下次会话都能通过搜索找到
- MEMORY.md 不需要包含所有信息——它更像索引+精华

---

## 经验教训

1. **HEARTBEAT.md 默认是空的** → 心跳不做事 → 必须手动激活
2. **AGENTS.md 里的"建议"不是自动执行的** → 需要搬到 HEARTBEAT.md
3. **记忆质量与模型能力相关** → 小模型会写入 raw log 和噪音
4. **定期清理很重要** → MEMORY.md 积累噪音后会影响检索质量
5. **guides/ 目录适合存放系统性经验** → 日常笔记太零散，长期记忆太精炼，guides 介于两者之间，适合放"教程级"内容

---

## 命令速查

```bash
# 查看心跳配置
cat ~/.openclaw/workspace/HEARTBEAT.md
cat ~/.openclaw/workspace/memory/heartbeat-state.json

# 手动触发心跳（测试）
# 心跳是自动触发的，无法手动触发
# 但可以通过发送心跳消息模拟：
# "Read HEARTBEAT.md if it exists..."

# 检查记忆文件
cat ~/.openclaw/workspace/MEMORY.md
ls ~/.openclaw/workspace/memory/guides/

# 查看当前会话状态
openclaw status
openclaw agents list
```
