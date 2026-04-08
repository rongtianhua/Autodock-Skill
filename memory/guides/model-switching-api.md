# 模型切换与 API 问题排查指南

**记录时间**：2026-03-30 ~ 2026-04-01 | **整理时间**：2026-04-01 by 柱子

## 问题一：模型切换断连

### 症状
- 尝试切换模型后会话中断
- 发送消息无响应

### 解决方案
- 使用自然语言请求切换："帮我把模型换成更稳定的那个"
- 如果命令方式失败，尝试通过 `/model list` 查看可用模型
- 确认模型标识格式正确（需要完整路径，如 `openrouter/qwen/qwen3.6-plus-preview:free`）

### 预防措施
- 在不确定模型标识时，先查看配置或询问可用选项
- 优先使用自然语言描述需求，让助手处理技术细节

## 问题二：模型不可用 / Unknown model

### 症状
- `FailoverError: Unknown model: xxx`
- Fallback 链全部失败

### 原因
OpenRouter 的免费模型经常上下架。配置中的某些模型可能已从 OpenRouter 移除。

### 解决方案
1. 检查当前可用模型：
   ```bash
   openclaw config validate
   ```
2. 从配置中移除不可用模型
3. 更新 fallback 链，使用已知可用的模型

### 当前已知可用模型（2026-04-01）
- `openrouter/qwen/qwen3.6-plus-preview:free`（主力）
- `kimi/kimi-code`（自有 API key）
- `ollama/kimi-k2.5:cloud`（本地 Ollama）
- `openrouter/free`（OpenRouter 免费池）
- `openrouter/stepfun/step-3.5-flash:free`
- `openrouter/minimax/minimax-m2.5:free`
- `openrouter/openai/gpt-oss-120b:free`
- `openrouter/z-ai/glm-4.5-air:free`

### 当前配置中的 Fallback 链
```
primary: openrouter/qwen/qwen3.6-plus-preview:free
fallbacks:
  1. openrouter/free
  2. kimi/kimi-code
  3. ollama/kimi-k2.5:cloud
```

## 问题三：速率限制（429 错误）

### 症状
- `⚠️ API rate limit reached. Please try again later.`
- 免费模型频繁触发

### 已知的不稳定模型
- `stepfun/step-3.5-flash:free` - 频繁 429

### 解决方案
- 优先使用 qwen3.6-plus-preview:free（体感最稳定）
- 或使用 kimi/kimi-code（有自有 API key，不受 OpenRouter 限制）
- 如需长时间使用，建议切换到付费模型

## 问题四：Thinking 默认级别配置

### 症状
- 新会话/cron 任务出现 thinking off 导致推理异常
- 免费模型要求 reasoning 开启

### 解决方案
```bash
# 设置 thinking 默认级别为 medium
openclaw config set agents.defaults.thinkingDefault "medium"
openclaw config validate
openclaw gateway restart
```

### 注意
- 配置 key 是 `agents.defaults.thinkingDefault`（不是 thinking/think/thinkLevel）
- `openclaw config validate` 是唯一可靠的验证命令

## 问题排查命令清单

```bash
# 检查会话和通道状态
openclaw status
openclaw status --deep

# 查看模型配置
cat ~/.openclaw/openclaw.json | python3 -m json.tool | grep -A 20 "model"

# 检查最近错误日志
tail -20 /tmp/openclaw/openclaw-*.log | grep -iE "rate|429|reasoning|error|failed|unknown model"

# 验证配置
openclaw config validate

# 重启网关
openclaw gateway restart
```
