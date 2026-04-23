# HEARTBEAT.md

## Heartbeat vs Cron: When to Use Each

**Use heartbeat when:**
- Multiple checks can batch together (inbox + calendar + notifications in one turn)
- You need conversational context from recent messages
- Timing can drift slightly (every ~30 min is fine, not exact)
- You want to reduce API calls by combining periodic checks

**Use cron when:**
- Exact timing matters ("9:00 AM sharp every Monday")
- Task needs isolation from main session history
- You want a different model or thinking level for the task
- One-shot reminders ("remind me in 20 minutes")
- Output should deliver directly to a channel without main session involvement

**Tip:** Batch similar periodic checks into `HEARTBEAT.md` instead of creating multiple cron jobs. Use cron for precise schedules and standalone tasks.

---

## 定期任务（每 2-3 天执行一次，不要每次心跳都执行）

### Self-Reflection 自查（间隔≥2 天执行）
1. 运行 `self-reflection check` 检查是否需要反射
2. 如果 ALERT：读取最近教训 → 反思 → 写入 `memory/self-review.md`
3. 更新 `~/.openclaw/self-review-state.json`

### Self-Improving 检查（间隔≥2 天执行）
1. 读取 `~/self-improving/corrections.md` 是否有新教训
2. 检查 `~/.openclaw/workspace/.learnings/ERRORS.md` 是否有未解决错误
3. 如有新的纠正记录 → 评估是否需要加入 checklist

### Proactive Agent 检查（间隔≥2 天执行）
1. 读取 `~/proactivity/session-state.md` — 是否有 stale blockers
2. 读取 `~/proactivity/memory/working-buffer.md` — 是否有中断任务需要恢复
3. 读取 `~/self-improving/corrections.md` — 近期教训
4. 如无待办，回复 HEARTBEAT_OK

### Self-Evolve 全面自查（间隔≥7 天执行）
1. 读取最近教训：`~/.openclaw/workspace/.learnings/`
2. 扫描 `~/.openclaw/workspace/skills/` — 是否有技能未激活/未集成
3. 检查 TICKLIST 是否需要更新（每次犯新错后必须检查）
4. 在 `memory/YYYY-MM-DD.md` 记录进化行动

---

## Things to Check（rotate through these, 2-4 times per day）

- **Emails** - Any urgent unread messages?
- **Calendar** - Upcoming events in next 24-48h?
- **Mentions** - Twitter/social notifications?
- **Weather** - Relevant if your human might go out?

**Track your checks** in `memory/heartbeat-state.json`:
```json
{
  "lastChecks": {
    "email": 1703275200,
    "calendar": 1703260800,
    "weather": null
  }
}
```

---

## When to Reach Out（主动上报，不等心跳）

- Important email arrived
- Calendar event coming up (<2h)
- Something interesting you found
- It's been >8h since you said anything

## When to Stay Quiet（HEARTBEAT_OK）

- Late night (23:00-08:00) unless urgent
- Human is clearly busy
- Nothing new since last check
- You just checked <30 minutes ago

---

## Proactive Work（可自行执行）

- Read and organize memory files
- Check on projects (git status, etc.)
- Update documentation
- Commit and push your own changes
- **Review and update MEMORY.md** (see below)

---

## Memory Maintenance（During Heartbeats, every few days）

1. Read through recent `memory/YYYY-MM-DD.md` files
2. Identify significant events, lessons, or insights worth keeping long-term
3. Update `MEMORY.md` with distilled learnings
4. Remove outdated info from `MEMORY.md` that's no longer relevant

Daily files are raw notes; MEMORY.md is curated wisdom.

---

## 注意事项

- 以上维护任务不要每个心跳都跑，标记上次执行日期，间隔 ≥2 天才能再次执行
- 记录上次执行日期在 `memory/heartbeat-state.json` 中
- 维护完成后，在 `memory/YYYY-MM-DD.md` 记下"执行了记忆维护"

## 状态追踪

上次记忆维护：2026-04-21

## 主动上报触发条件（立即通知，不等心跳）

- 发现自己反复犯同一个错（第三次以上）→ 立即通知用户
- 发现 skill 未被触发/未集成 → 立即通知用户

## 今日教训（2026-04-22）

- cron delivery 三字段（mode + channel + target）缺一不可，已加入 checklists/cron.md
- 教训库路径：~/self-improving/corrections.md 和 ~/.openclaw/workspace/.learnings/
