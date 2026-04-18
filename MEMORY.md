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
- Dreaming 历史结论（2026-04-16）：Dreaming 从未实际运行；"每天凌晨3点"系文档误导；MemOS 整理为每轮对话后异步进行，无固定时间任务；HEARTBEAT.md 已清除遗留注释
- hot vs hybrid: keep hybrid, hot is too aggressive

## Lessons Learned
- **2026-04-14: 报告模板标准化** — 确立标准格式：实时行情快照 + 五维特征萃取(含杜邦+YoY) + 综合决策指示(具体价位) + 风险清单(5项) + 仓位速查表；从此输出报告照此格式执行
- **2026-04-14: Sina bid/ask索引** — Sina五档索引不同于腾讯，验证方法：直接print raw parts array，用已知好价格确认索引位置
- **2026-04-14: 两处dataclass同步bug** — 加新字段时，RawMarketData和MarketSentiment两处都要改，analyze()的返回语句也要改，容易遗漏后者
- **2026-04-14: baostock无query_valuation_data** — 方法不存在；PE/PB由腾讯API提供，baostock只补充EPS_TTM/杜邦/YoY/股本
- **2026-04-14: baostock季度回溯** — 4月中旬2025年报未发布，必须回溯到Q3/Q2
- **2026-04-14: 东财push2delay API** — JSON API稳定可靠，替换Playwright；不支持指数secid
- **2026-04-12: cron 定时任务必须指定 target** — 创建飞书定时任务时必须加 `--target <user_open_id>`，cron 在 isolated 模式下没有用户上下文，不指定 target 会导致 `Action send requires a target` 错误
- Config loss after update; now using config-guardian backups
- Always verify memorySearch config matches provider capabilities
- **2026-04-08: Never restart gateway without checking active tasks** —今天的飞书会话损坏教训
- **Check ≠ Fix** —用户说"检查"时只检查，修复前必须询问
- **Assess impact before destructive operations** —新增配置守护脚本进行变更影响评估
- **2026-04-10: Gateway restart loop root cause** — gateway.err.log膨胀到762MB导致I/O压力，而非config-guardian
- **2026-04-10: a-stock-trader-pro数据架构** — akshare东财接口会被反爬，应使用Playwright抓取东财网页；数据三层兜底：腾讯API(主) → 新浪API → baostock
- **2026-04-12: a-stock-trader-pro修复** — 基本面财务数据全为0的bug已修复（新浪API参数/字段名错误）；Playwright东财超时问题已优化等待逻辑，需周一交易日验证完整资金流数据
- **2026-04-12: PMC PDF下载新流程** — DOI → CrossRef API → Springer直链，绕过Cloudflare；Documents/文件夹作为用户文档的默认存储位置
- **飞书文档导出** — feishu_doc工具目前不支持export action，需手动在飞书界面导出docx

## 安全实践（2026-04-18）
- 系统密码已改用 Keychain 管理（条目名："Mac sudo"，用户：allenrong）
- sudo NOPASSWD 已配置（/etc/sudoers.d/allenrong），无需密码即可提权
- 绝不在聊天中明文传输密码；用 `security find-generic-password` 从 Keychain 读取
- 新密码不再记录在 MEMORY.md 或任何明文文件

## Mac mini 自我修复与稳定在线配置（2026-04-18）

### 目标
让 OpenClaw 在 Mac mini 重启后无需人工干预即可自动恢复服务。

### 已完成的配置

**1. 自动登录**
- 配置：`defaults write /Library/Preferences/com.apple.loginwindow autoLoginUser -string "allenrong"`
- 验证：`defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser` → `allenrong`
- 注意：FileVault 关闭时有效；突然断电后可能需等 fsck 完成后才能进入系统

**2. sudo 免密提权**
- 配置：/etc/sudoers.d/allenrong → `allenrong ALL=(ALL) NOPASSWD: ALL`
- 验证：sudo -n id → uid=0(root)
- Keychain 条目："Mac sudo"（用户：allenrong），用于程序化 sudo 操作

**3. Keychain 管理密码**
- 存储：`security add-generic-password -a allenrong -s "Mac sudo" -w '<password>' -U`
- 读取：`security find-generic-password -a allenrong -s "Mac sudo" -w`
- 应用：程序化 sudo 操作，避免明文密码出现在聊天记录

**4. 系统日志监控**
- 重启原因排查：`last reboot` / `last shutdown`
- 电源事件：`pmset -g log`
- 故障诊断：`/Library/Logs/DiagnosticReports/ResetCounter-*.diag`
- Keychain 路径：Spotlight 搜索 "keychain" 或 /System/Library/CoreServices/Applications/Keychain Access.app

### 已知 limitations
- 突然断电（跳闸）后，macOS 可能触发 fsck 文件系统检查，自动登录恢复需要等检查完成
- 电源恢复场景："在电源恢复后重启"设置可能导致循环重启，需人工介入

## Preferences
- Use local models where possible
- Context: workspace /Users/allenrong/.openclaw/workspace

---
*Curated memory — distill insights from daily logs here*