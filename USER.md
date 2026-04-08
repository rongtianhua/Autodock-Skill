# USER.md - About Your Human

_Learn about the person you're helping. Update this as you go._

- **Name:** 戎天华 (Allen Rong)
- **What to call them:** 老板 / boss (正式场合)，戎哥 / Allen (闲暇场合)
- **Pronouns:** 他 / 他 (可选)
- **Timezone:** 中国标准时间 (UTC+8)
  - macOS 系统时区设为 America/Barbados (UTC-4)，为了方便海外业务
  - OpenClaw 已通过 `TZ=Asia/Shanghai` 环境变量与系统时区脱钩，日志和消息时间都显示北京时间
- **Notes:** 36岁男性医生，在中国北京的一家三级甲等医院骨科工作，专业方向是脊柱外科。我的兴趣点有AI与计算机科学、生物信息学、电子数码、咖啡、摄影摄像、流行音乐、篮球、旅游，我的母语是汉语，第二语言是英语。

## 性格特点（2026-04-01 自述）
- **优点**：
  - 凡事爱刨根问底，注重底层原理
  - 思维逻辑性强，理解能力强
  - 迁移能力不错
  - 计划性强
- **缺点**：
  - 有时思虑过多而行动不足
  - 执行力和韧性不足
  - 随机应变能力不足

## Context

_(What do they care about? What projects are they working on? What annoys them? What makes them laugh? Build this over time.)_

## 配置备忘

### 时区设定（2026-04-05）
- **问题**：macOS 系统时区 UTC-4，导致 OpenClaw 日志/消息时间显示错误
- **解决**：三重配置
  1. `openclaw.json` → `agents.defaults.envelopeTimezone: "Asia/Shanghai"` + `userTimezone: "Asia/Shanghai"`（控制消息/心跳时间逻辑）
  2. `~/Library/LaunchAgents/ai.openclaw.gateway.plist` → `EnvironmentVariables.TZ: "Asia/Shanghai"`（控制日志时间戳）
  3. `/Desktop/reload-openclaw.sh` 重载脚本（`launchctl unload` + `load`）
- **注意**：`launchctl unload/load` 不能通过 OpenClaw 自身执行（会把自己杀掉），必须从终端运行

---

The more you know, the better you can help. But remember — you're learning about a person, not building a dossier. Respect the difference.
