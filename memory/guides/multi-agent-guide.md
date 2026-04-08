# 多Agent 配置完整指南

**记录时间**：2026-04-01 by 柱子（agent: main）

## 背景

为 Allen 的妻子新增一个独立 agent（puff），通过她自己的微信账号连接，拥有独立的工作区、记忆、人格，但可以复用相同的 API key。

---

## 核心概念

### 命名层级

| 层级 | 键值 | 示例（puff） | 用途 |
|------|------|-------------|------|
| **Agent ID** | `agents.list[].id` | `puff` | 系统路由标识，唯一 |
| **配置 name** | `agents.list[].name`（可选）| 可不设 | 管理员标签 |
| **Identity name** | `IDENTITY.md` 中的 name | 妮妮的小龙虾（小龙虾） | agent 自我介绍用的"真名" |
| **Persona emoji** | `IDENTITY.md` 中的 emoji | ✨ | 身份标识 |

### 路径映射

| 内容 | main 路径 | puff 路径 |
|------|----------|----------|
| 工作区 | `~/.openclaw/workspace` | `~/.openclaw/workspace-puff` |
| Agent 状态目录 | `~/.openclaw/agents/main/agent` | `~/.openclaw/agents/puff/agent` |
| 会话存储 | `~/.openclaw/agents/main/sessions` | `~/.openclaw/agents/puff/sessions` |
| 认证配置 | `~/.openclaw/agents/main/agent/auth-profiles.json` | `~/.openclaw/agents/puff/agent/auth-profiles.json` |

---

## 完整配置步骤

### 1. 创建 Agent

**方法 A：交互式向导**（推荐）
```bash
openclaw agents add puff
```
交互式提示输入工作区路径。

**方法 B：手动创建**（如果交互卡住）
```bash
# 创建目录结构
mkdir -p ~/.openclaw/workspace-puff
mkdir -p ~/.openclaw/agents/puff/agent ~/.openclaw/agents/puff/sessions

# 手动编辑 openclaw.json
python3 << 'EOF'
import json
with open('/Users/allenrong/.openclaw/openclaw.json') as f:
    data = json.load(f)

data['agents'] = {
    'list': [
        {
            'id': 'main',
            'default': True,
            'workspace': '/Users/allenrong/.openclaw/workspace',
            'sandbox': { 'mode': 'off' },
            'tools': { 'profile': 'coding' }
        },
        {
            'id': 'puff',
            'workspace': '/Users/allenrong/.openclaw/workspace-puff'
        }
    ],
    'defaults': data['agents']['defaults']
}

with open('/Users/allenrong/.openclaw/openclaw.json', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
EOF

# 验证配置
openclaw config validate
```

### 2. 复制基础工作区文件

从 main agent 复制模板文件到新工作区：
```bash
cp ~/.openclaw/workspace/IDENTITY.md ~/.openclaw/workspace-puff/
cp ~/.openclaw/workspace/AGENTS.md ~/.openclaw/workspace-puff/
cp ~/.openclaw/workspace/SOUL.md ~/.openclaw/workspace-puff/
cp ~/.openclaw/workspace/TOOLS.md ~/.openclaw/workspace-puff/
```

然后在 puff 的工作区中编辑 `IDENTITY.md` 和 `USER.md` 来定制 persona。

### 3. 复制认证文件（如需复用 API key）

```bash
cp ~/.openclaw/agents/main/agent/auth-profiles.json ~/.openclaw/agents/puff/agent/auth-profiles.json
```

这样 puff 就有相同的 API key（Kimi + OpenRouter），独立文件但相同内容。

### 4. 配置微信通道

```bash
# 为新微信账号扫码登录
openclaw channels login --channel openclaw-weixin
```

终端会显示二维码，让新用户扫码授权。成功后会自动在 `~/.openclaw/openclaw-weixin/accounts/` 创建新账号条目。

### 5. 绑定微信账号到 Agent

```bash
openclaw agents bind --agent puff --bind "openclaw-weixin:新账号ID-im-bot"
```

这会自动在 `openclaw.json` 中添加 bindings 配置：
```json
{
  "bindings": [
    {
      "type": "route",
      "agentId": "puff",
      "match": {
        "channel": "openclaw-weixin",
        "accountId": "新账号ID-im-bot"
      }
    }
  ]
}
```

### 6. 配置 Agent 权限

在 `openclaw.json` 的 `agents.list[].tools` 中定义权限：

```json
{
  "id": "puff",
  "workspace": "/Users/allenrong/.openclaw/workspace-puff",
  "tools": {
    "allow": ["read", "write", "edit", "apply_patch", "web_search", "web_fetch", "sessions_list", "sessions_send", "sessions_history", "session_status", "memory_search", "memory_get", "skill_search", "skill_read"],
    "deny": ["process", "gateway"]
  }
}
```

### 7. 写入安全边界红线（软约束）

在 puff 工作区的三个文件中写入约束：

**AGENTS.md - Red Lines**

- **Workspace boundary**: 所有文件操作必须在 `~/.openclaw/workspace-puff` 内
- **System safety**: 禁止修改网关配置、进程管理、系统服务
- **No cross-agent access**: 禁止访问、检查或修改其他 agent 的工作区

**SOUL.md - Boundaries**

- "This workspace is your home. Keep all work within it. Don't wander into other agents' spaces or mess with system configuration — those aren't your business."

**IDENTITY.md**

- 标注 puff 的运行工作区和系统边界信息
- 与主 agent（main）共享同一网关，但身份、记忆、会话完全独立

### 8. 验证并重启

```bash
# 验证配置
openclaw config validate

# 查看 agent 列表和绑定
openclaw agents list --bindings

# 重启网关
openclaw gateway restart

# 检查状态
openclaw status
```

---

## 完整配置示例

最终的 `openclaw.json` 中 agents 部分：
```json
{
  "agents": {
    "list": [
      {
        "id": "main",
        "default": true,
        "workspace": "/Users/allenrong/.openclaw/workspace",
        "sandbox": { "mode": "off" },
        "tools": { "profile": "coding" }
      },
      {
        "id": "puff",
        "workspace": "/Users/allenrong/.openclaw/workspace-puff",
        "sandbox": { "mode": "off" },
        "tools": {
          "allow": ["read", "write", "edit", "apply_patch", "web_search", "web_fetch", "sessions_list", "sessions_send", "sessions_history", "session_status", "memory_search", "memory_get", "skill_search", "skill_read"],
          "deny": ["process", "gateway"]
        }
      }
    ],
    "defaults": {
      "model": {
        "primary": "openrouter/qwen/qwen3.6-plus-preview:free",
        "fallbacks": ["openrouter/free", "kimi/kimi-code", "ollama/kimi-k2.5:cloud"]
      },
      "compaction": { "mode": "safeguard" },
      "thinkingDefault": "medium"
    }
  },
  "bindings": [
    {
      "type": "route",
      "agentId": "puff",
      "match": {
        "channel": "openclaw-weixin",
        "accountId": "c34be62a65ea-im-bot"
      }
    }
  ]
}
```

---

## 后续调整

### 给新 Agent 独立模型配置

```json
{
  "id": "puff",
  "workspace": "/Users/allenrong/.openclaw/workspace-puff",
  "model": {
    "primary": "kimi/kimi-code",
    "fallbacks": ["openrouter/free"]
  }
}
```

### 更强的安全隔离（硬件级）

如果后续需要更强隔离，开启 sandbox：
```json
{
  "id": "puff",
  "sandbox": {
    "mode": "all",
    "scope": "agent"
  },
  "tools": {
    "allow": ["read"],
    "deny": ["exec", "write", "edit", "apply_patch", "process", "browser", "gateway"]
  }
}
```

这会启动 Docker 容器，文件系统操作受限在工作区内。代价是性能略降和需要 Docker。

### 添加新通道绑定

```bash
openclaw agents bind --agent puff --bind telegram:puff-bot
openclaw agents bind --agent puff --bind whatsapp:secondary
```

---

## 常见问题

**Q: Agent ID 可以改吗？**
A: Agent ID 是底层标识，涉及会话存储路径。不建议修改，除非愿意迁移数据。

**Q: Auth profiles 必须复制吗？**
A: 不是必须的。每个 agent 有独立的 `auth-profiles.json`。如果想用不同的 API key（比如她有自己的 OpenRouter 账户），可以在 puff 的 auth 文件中只放她的 key。

**Q: 软约束 vs 硬约束？**
- 软约束（AGENTS.md 红线）：适合家庭场景，有效但可绕过
- 硬约束（Sandbox）：技术层面限制，无法绕过，但性能有影响

**Q: 多 agent 共享同一微信通道？**
A: 不行，微信账号是一一对应的。每个 agent 需要有独立的微信 bot 账号。

**Q: 新 agent 能访问 main 的工作区吗？**
A: 在软约束模式下，技术上可以但被禁止。在 sandbox 模式下，技术上就不可能。

---

## puff 工具权限配置记录

**记录时间**：2026-04-02 by 柱子（agent: main）

### 初始状态（创建时）

puff 创建时使用白名单模式（`tools.allow`），默认只开了文件操作、WEB搜索、会话管理、记忆检索、技能搜索等基础权限，禁用了 `process` 和 `gateway`。

### 权限修改历史

| 时间 | 变更 | 原因 |
|------|------|------|
| 2026-04-02 06:05 | 新增 `exec`、`cron` | 需要执行 shell 命令和定时任务 |
| 2026-04-02 11:09 | 新增 `image`、`image_generate` | 微信截图/照片识别、图片生成 |

### 当前权限清单（2026-04-02）

**已打开（18个）：**

| 分组 | 工具 | 用途 |
|------|------|------|
| group:fs | read, write, edit, apply_patch | 文件读写编辑 |
| group:runtime | exec | 执行 shell 命令 |
| group:web | web_search, web_fetch | 网页搜索与抓取 |
| group:sessions | sessions_list, sessions_send, sessions_history, session_status | 会话管理 |
| group:memory | memory_search, memory_get | 记忆检索 |
| group:automation | cron | 定时任务 |
| skills | skill_search, skill_read | 技能搜索读取 |
| 图片 | image, image_generate | 图片分析与生成 |

**未打开（14个）：**

| 分组 | 工具 | 未打开原因 |
|------|------|-----------|
| group:runtime | bash | 与 exec 功能重叠 |
| group:runtime | code_execution | exec 可直接跑 Python |
| group:runtime | process | deny 明确禁止 |
| group:web | x_search | 暂时不需要搜 X |
| group:sessions | sessions_spawn, sessions_yield, subagents, agents_list | 不需要派生子 agent |
| group:automation | gateway | deny 明确禁止 |
| group:ui | browser, canvas | Playwright 已覆盖浏览器需求 |
| group:messaging | message | 通过 sessions_send 间接实现 |
| group:nodes | nodes | 不需要设备管理 |

### 权限配置最佳实践

1. **用白名单模式（allow）比黑名单更安全** — puff 已采用
2. **deny 优先于 allow** — 即使 allow 里有，deny 也会否决
3. **bash 和 exec 二选一即可** — bash 和 exec 同属 runtime 组，功能重叠
4. **code_execution 不是必需的** — 调用 xAI 远程跑 Python，本地有 exec 就能跑
5. **Playwright 不需要 browser 内置工具** — Playwright 通过 exec 执行，不依赖内置 browser

---

**相关命令速查**

```bash
# 管理
openclaw agents list --bindings     # 查看 agents 和绑定
openclaw channels status --probe    # 检查通道状态
openclaw config validate            # 验证配置
openclaw gateway restart            # 重启生效

# 微信相关
openclaw channels login --channel openclaw-weixin  # 扫码登录新账号
openclaw agents bind --agent <id> --bind <channel:account>

# 调试
openclaw logs --follow             # 实时查看日志
tail -20 /tmp/openclaw/openclaw-*.log | grep -i "routing|wechat|agent"
```
