---

📋 Key Steps / 关键步骤

**1. CausaMem 开源项目评估**

- GitHub: MaiHHConnect/MHH-Causality-Memory，2026-04-18 创建，Star=1
- 四层结构（事件→时间线→关系链→抽象）+ 13维因果推理
- 结论：过新，无社区验证，star 关注即可，暂不集成

**2. memos-dreaming 技能排查**

原 cron 状态为 error，实际脚本运行正常，但有两个 bug：

**Bug 1：永远 dry run（不写 MEMORY.md）**

```python
# 脚本末尾 argparse 逻辑
dry_run = args.dry_run or not args.apply
# cron 未传 --apply → args.apply=False → dry_run=True → 不写入
```

修复：新建入口脚本 `memos_dreaming_cron.py`，默认 `apply=True`：

```python
# skills/memos-dreaming/scripts/memos_dreaming_cron.py
if __name__ == "__main__":
    sys.argv.extend(["--apply"])
    sys.exit(main())
```

重建 cron，ID: `69b54256-6f88-482a-9b73-67713af130db`，每日 3:00 运行。

**Bug 2：投递失败（heartbeat channel 不支持）**

原 cron delivery 配置无 `--to` 参数，飞书推送失败。
修复：在 cron trigger 调用时加上 `--to [REDACTED]`，确保结果送达飞书。

验证修复后：Status: ok, Delivery: delivered ✅

**3. 双来源记忆提炼确认**

- Source 1: MemOS SQLite（skills 表 quality_score≥0.5，tasks 表 promoted 任务）
- Source 2: memory/YYYY-MM-DD.md（提取 Decisions/Lessons Learned/Projects）
- 今天测试结果：MemOS candidates: 2，Daily memory candidates: 0

**4. V2RayN + ISP 代理 CDN 连通性问题排查**

完整链路：

```
Mac (V2RayN TUN) → VPS (Mack-a) → ISP SOCKS5 代理 → CDN 边缘节点
 [跳1]              [跳2]            [跳3]              [跳4]
```

关键澄清：

- 第4跳是 ISP 代理独立发起连接，走 ISP 代理自己的路由
- 不是 VPS 直连 CDN，也不是 IP 泄露
- 廉价 VPS（你用的）的路由质量差，到某些 CDN 边缘超时

**代理服务商对比：**

| | Proxy Cheap | Proxy Seller |
|---|---|---|
| 出口 IP | AS10753 Level 3（数据中心骨干）| AS701 Verizon Business（ISP 骨干）|
| 定位 | 低端，用数据中心 IP 冒充 ISP | 中端偏上 |
| CDN 路由 | 不稳定 | 部分 CDN（brew.sh/OrbStack CDN）仍不通 |

**绕行规则结论：必须保留**

- `orbstack.dev` 和 `brew.sh` 需要直连（不走代理）
- 其他网站（OpenAI、Anthropic、GitHub）走代理链正常
- 绕行规则暴露中国联通 IP，但下载站无风险，美国 AI 服务不受影响

**5. 反思：为何之前未发现 cron dry run 问题**

- 看到 "error" 状态后注意力在"状态报告"上，未去读脚本 argparse 代码
- 过于信任已有配置，总觉得"之前能跑就没问题"
- 两次看到"没有新条目"时接受了表面结果，没有追问"为什么一直没有"

---

✅ Result / 结果

1. **memos-dreaming cron 已修复**：新建 `memos_dreaming_cron.py` 入口脚本，默认 apply=True；cron 投递加上 `--to` 参数，结果正常送达飞书。
2. **ISP 代理 CDN 路由问题**：Proxy Seller（AS701 Verizon）到部分 CDN（brew.sh/Akamai、OrbStack/Fastly）路由质量差，绕行规则（orbstack.dev + brew.sh）是正确解法。
3. **双来源确认**：MemOS DB + 每日记忆文件均已覆盖。

💡 Key Details / 关键细节

- cron trigger ID: `69b54256-6f88-482a-9b73-67713af130db`
- 当前代理出口 IP: 65.195.107.245（AS701 Verizon Business，纽约）
- 绕行规则域名：`orbstack.dev`、`brew.sh`

## Companion files

- `references/memos-dreaming-cron-debug.md` — reference documentation
- `references/proxy-cdn-routing-troubleshooting.md` — reference documentation