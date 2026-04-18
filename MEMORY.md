# MEMORY.md — Long-Term Memory

## About the User
- Name: Allen Rong (戎天华)
- Timezone: Asia/Shanghai
- Occupation: Spine surgeon, Beijing

## Projects
- Tushare stock skill (Python 3.14 installed)
- MemOS memory plugin: fully installed 2026-04-10 (bge-m3 embedding + MiniMax-M2-7 summarizer)
- a-stock-trader-pro skill: v2.2/v2.3 released with major data fixes; 周一(04-13)需验证资金流CSS选择器
- **pubmed-pdf-downloader skill** (新建): PMC PDF下载 → DOI → CrossRef API → Springer直链，成功率高于直接抓取；所有PDF存 workspace/Documents/
- **飞书文档读写**：权限已开通（docx:document + drive:drive），可直接写入飞书文档

## Decisions Log
- Switched to local Ollama bge-m3 embeddings for memory (2026-04-08)
- Session-state stored at workspace root
- Git-Notes cold storage enabled for permanent knowledge (2026-04-08)
- MemOS installed as primary memory system (replaces Dreaming/memory-core)
## Lessons Learned
- **2026-04-14: 报告模板标准化** — 确立标准格式：实时行情快照 + 五维特征萃取(含杜邦+YoY) + 综合决策指示(具体价位) + 风险清单(5项) + 仓位速查表
- **2026-04-14: Sina bid/ask索引** — 验证方法：直接print raw parts array，用已知好价格确认索引位置
- **2026-04-14: 两处dataclass同步bug** — 加新字段时，RawMarketData和MarketSentiment两处都要改，容易遗漏
- **2026-04-14: baostock季度回溯** — 4月中旬2025年报未发布，必须回溯到Q3/Q2
- **2026-04-12: cron 定时任务必须指定 target** — `--target <user_open_id>`，isolated模式下不指定会报错
- **2026-04-08: Never restart gateway without checking active tasks** — 今天的飞书会话损坏教训
- **Check ≠ Fix** — 用户说"检查"时只检查，修复前必须询问
- **Assess impact before destructive operations** — 配置守护脚本进行变更影响评估

## 安全实践（2026-04-18）
- Keychain 条目管理密码（条目名："Mac sudo"，用户：allenrong）
- sudo NOPASSWD 已配置（/etc/sudoers.d/allenrong）
- 绝不在聊天中明文传输密码；用 Keychain 管理

## Mac mini 稳定在线（2026-04-18）
- 自动登录：已配置（`/Library/Preferences/com.apple.loginwindow autoLoginUser`）
- sudo免密：已配置（/etc/sudoers.d/allenrong）
- Keychain："Mac sudo"管理 sudo 密码
- 重启排查：`last reboot` / `pmset -g log`
- Limitation：突然断电后需等 fsck 完成；电源恢复设置可能导致循环重启

## 技能安装记录
详见 `memory/YYYY-MM-DD.md` 每日日志

## Preferences
- Use local models where possible
- Context: workspace /Users/allenrong/.openclaw/workspace

---
*Curated memory — distill insights from daily logs here*