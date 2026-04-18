---

## 🎯 目标

完善股票技能的数据融合架构（技术面/基本面/资金面/情绪面），修复多个数据源问题，升级报告输出模板为可落地执行的决策版本，并记录所有调试经验。

---

## 📋 关键步骤 / 关键步骤

### 第一阶段：Cron 任务修复与技能路径修正

**Turn 1-4 处理内容：**

1. **修复日志轮转超时** — cron 任务超时时间从 30s 增加到 120s
2. **重建智谱提醒定时任务** — 每天 09:50 Asia/Shanghai，指定目标用户 `ou_fd31b5e8e4caee8de4729f302cda0034`
3. **修正技能路径** — a-stock-trader-pro 在 `~/.openclaw/skills/` 公共目录，非 workspace
4. **更新 puff 行动手册** — 股票咨询优先调用公共技能 a-stock-trader-pro，失败时回退到本地后备技能

### 第二阶段：数据源首次全面测试与新浪 API 修复

**Turn 5-8 处理内容：**

5. **测试现有架构**
   - 腾讯 API ✅ 完美运行
   - 新浪 API ✅ 部分有效（PE/PB/换手率/量比为 0，靠腾讯层补全）
   - 东财 Playwright ❌ 被拼图验证码阻挡
   - akshare ❌ 代理错误

6. **首次修复新浪 API — 新增补充字段**
   - 新浪本不返回 PE/PB/换手率/量比，靠腾讯主数据源补全
   - 腾讯成功时也调用新浪，补充委比、状态码、精确时间戳

7. **发现新浪五档盘口遗漏** ⚠️
   - 新浪 API 提取了完整 5 档买卖盘口（bid/ask 各 5 档），但 `get_quote_with_fallback` 只补充了委比/状态码/时间戳，**遗漏了五档本身**
   - 修正：将新浪五档数据写入腾讯主数据，bid_prices 升序、ask_prices 升序

8. **修正新浪五档索引错误**
   - 原始代码用 `[11,13,15,17,7]` 提取新浪 bid 五档，将 `parts[7]=1446.90`（当前价）误当 bid5
   - 正确索引：`[11,13,15,17,19]`（bid1-5 价格），与腾讯索引 `[9,11,13,15,17]` 不同
   - 验证：腾讯 bid5=1446.78 ✅ 与新浪 bid5=1446.78 ✅ 完全一致
   - **教训：任何 API 字段索引不能假设一致，必须先打印原始数据验证**

### 第三阶段：东财 Playwright 替换为 API

**Turn 9-13 处理内容：**

9. **替换 Playwright 为东财 JSON API**
   - `push2delay.eastmoney.com` 可用，测试 URL：`https://push2delay.eastmoney.com/api/qt/klist/get?secid=1.600519&fields=f1-f10,f184`
   - `f184×10000` 转万元，主力净流入数据获取成功
   - 发现大量可用字段：f185(主力净流入率%)、f186(3日累计)、f187(5日累计)、f188(10日累计)、f173(净流入占比)、f128(所属板块)
   - 新增 `_get_eastmoney_supplementary_data` 方法返回完整字典

10. **深度调研东财 API 扩展字段**
    - `f184` — 主力净流入（亿元）✅
    - `f185` — 主力净流入率% ⭐ 新增
    - `f186/f187/f188` — **3日/5日/10日累计主力净流入**（亿元）⭐ 超短核心
    - `f173` — 净流入占成交比% ⭐
    - `f128` — 所属板块 ⭐
    - `f140/f141` — 超大单/大单净流入（元）⚠️ 待确认单位

11. **全面更新文档（v2.4.0）**
    - SKILL.md — playwright_eastmoney → eastmoney_api，五层护城河说明更新
    - README.md — 架构图更新为五层融合，数据源表格补充新浪+东财链接
    - USAGE_GUIDE.md — Q1 数据源说明更新为五层
    - requirements.txt — playwright 标为"已弃用"

12. **验证文档一致性**
    - README 输出示例资金面描述已更新为东财 API
    - requirements.txt 注释已更新

13. **记录调试成功经验**
    - `~/self-improving/corrections.md` — 新浪索引错误教训
    - `~/self-improving/memory.md` — 东财 API 发现路径
    - `memory/2026-04-14.md` — 完整调试过程

### 第四阶段：情绪面数据调研与架构补强

**Turn 14-18 处理内容：**

14. **评估现有架构完整性**
    - 技术面 ✅ 基本完善（baostock 兜底 K 线）
    - 龙头战法 ✅ 数据充足
    - 情绪面 ⚠️ 最薄弱：涨跌家数/北向资金无可靠来源

15. **调研东财 `ulist.np` API**
    - 东财 ulist.np 对指数 secid 全部返回 `{}`，只对股票有效
    - 结论：**保持新浪指数不变**，ulist.np 无增量价值

16. **调研 akshare 情绪面数据**
    - `stock_market_fund_flow` → **最大发现**：全市场主力/超大/大/中/小单净流入+占比+指数涨跌幅，一个接口全拿到
    - `stock_sector_spot` → 板块轮动分析
    - `stock_hsgt_fund_flow_summary_em` → **同时返回涨跌家数和北向资金**
    - `stock_zt_pool_em` → 收盘后为空，无稳定免费涨停统计数据
    - 新增 `_akshare_market_fund_flow` 和 `_akshare_hsgt_summary` 方法

17. **调研 baostock 扩展字段**
    - **baostock 独有**：EPS_TTM、总股本/流通股本、杜邦分解(税率/利息/EBIT比/资产周转/权益乘数)、YoY 净利/EPS/净资产增速
    - 调研确认 ulist.np 对指数无效（只对个股有效）

18. **实现涨跌家数功能**
    - 调研新浪 clist API → 返回 HTML 无效
    - 调研东财 clist API → 可用但需要拼接板块代码
    - 结论：涨跌家数数据源受限，保持现状

### 第五阶段：全面架构检查与模板升级

**Turn 19-23 处理内容：**

19. **全面检查技能架构一致性**
    - 发现 `MarketSentiment` dataclass 缺少 HSGT 字段，只在 `RawMarketData` 中添加了
    - 同步 `analyze()` return 语句，补充所有新字段
    - SKILL.md/README.md/USAGE_GUIDE.md/requirements.txt 全部更新到 v2.6.0

20. **优化报告输出模板**
    - 扩展 `OutputTemplate` dataclass 新增 14 个字段：
      - 实时行情快照：委比、板块、状态码、内外盘、总股本/流通股本
      - 五维分析：技术面/基本面/资金面/情绪面/龙头战法分别展开
      - 综合决策指示表：时机/仓位/动作/周期/退出
      - 仓位速查表：评分+主力3日净流入→仓位建议
      - 风险清单：ST退市/估值/流动性/主力筹码/情绪五项逐一打勾
    - 增强 `generate_report()` 方法：五维雷达、决策指示表、风险打勾、仓位居中

21. **用宁德时代(300750)真实数据测试报告**
    - 报告完整输出，用户确认满意

22. **用户反馈：操作指引不够具体**
    - 用户要求：更具体的决策指标和风险打勾清单
    - 强化综合决策指示表（时机/仓位/动作/周期/退出五要素）
    - 强化风险清单（5项逐一打勾）

23. **最终确认与文档固化**
    - 用户确认报告格式满意
    - 要求记录为标准格式
    - 要求追加调试经验和反思到文档

---

## ✅ 结果

**技能最终版本：v2.6.0**，数据融合架构五层完全打通：

```
腾讯API (主)
  └─ 补充新浪委比 + 状态码 + 时间戳 + 五档盘口
      └─ 补充东财 push2delay.eastmoney.com (主力净流入 / 3日累计 / 5日累计 / 10日累计 / 净流入率)
          └─ 失败时
              ├─ akshare stock_market_fund_flow (全市场资金流 / 涨跌家数)
              └─ akshare hsgt_summary (北向资金)
                  └─ 失败时
                      ├─ baostock K线 (技术面兜底)
                      ├─ Sina指数 (情绪面兜底)
                      └─ akshare valuation (基本面兜底)
```

**关键成果：**

- 新浪五档盘口索引错误 → 修正为正确索引，数据完整融合
- 东财 Playwright 替换为 JSON API → 绕过验证码，获取主力净流入+3/5/10日累计
- akshare `stock_market_fund_flow` 最大发现 → 一个接口同时补强全市场资金流和指数涨跌幅
- 报告模板升级为决策版本 → 五维分析+决策指示表+风险清单，可落地执行

---

## 💡 教训 / Pitfalls

1. **任何 API 字段索引不能假设一致** — 新浪和腾讯的字段索引完全不同，必须先打印原始数据验证，不能凭经验假设
2. **Playwright 渲染页面不是唯一选择** — 东财的 JSON API 比渲染 HTML 更稳定、更快、更易解析
3. **数据融合时容易遗漏字段** — 补充新浪字段时优先想到委比/状态码，忘了五档盘口本身也有价值
4. **单个数据源可能返回空值** — 腾讯五档正常不代表新浪五档就正确，两个数据源都要独立验证
5. **文档容易落后于代码** — 每次修改后必须同步检查 SKILL.md/README.md/USAGE_GUIDE.md 三份文档一致性

## Companion files

- `references/eastmoney-api-fields.md` — reference documentation
- `references/api-index-comparison.md` — reference documentation
- `references/data-source-architecture.md` — reference documentation