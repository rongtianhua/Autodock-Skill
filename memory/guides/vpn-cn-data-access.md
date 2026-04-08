# VPN 与国内数据源共存指南

**记录时间**：2026-04-03 by 柱子（agent: main）

## 问题描述

用户挂 v2rayN 代理访问国外网站（Claude、Gemini、GitHub 等），同时需要直连国内数据源（东方财富 A股 API、akshare）。
**矛盾**：TUN 模式下所有流量走代理 → 国内域名被带到国外节点 → 无法访问/被阻断 → akshare 报 `ProxyError`。

## 根因

| 模式 | 国内站点 (eastmoney) | 国外站点 (Claude) | 终端工具 (brew/git) |
|------|---------------------|-------------------|---------------------|
| TUN | ❌ 走代理失败 | ✅ 正常 | ❌ 无法区分 |
| Manual + no_proxy | ✅ 直连 | ✅ 走代理 | ⚠️ 需 env 变量 |

## 解决方案：关 TUN + Manual + no_proxy 白名单

### 1. v2rayN 设置
- 出站模式：`Manual`（规则模式）
- 勾选"系统代理"（HTTP: `127.0.0.1:10809`）
- 路由规则：包含 `geosite:cn → direct`
- ❌ 关闭 TUN 模式

### 2. 终端环境变量（`~/.zshrc`）
```bash
export http_proxy="http://127.0.0.1:10809"
export https_proxy="http://127.0.0.1:10809"
export all_proxy="socks5://127.0.0.1:10808"
export no_proxy="localhost,127.0.0.1,::1,.cn,.com.cn,.net.cn,.org.cn,.gov.cn,.edu.cn,.eastmoney.com,push2.eastmoney.com,push2his.eastmoney.com"
```

### 3. akshare 测试命令
```bash
python3 -c "import akshare as ak; print(ak.stock_zh_a_spot_em().head())"
```

### 4. 备选方案
- **baostock**：数据源不同（baidu），对代理不敏感，已测试成功
- **Fallback 机制**：已写入 `akshare-stock SKILL.md`，akshare 失败自动切换 baostock

## no_proxy 白名单（核心域名）

| 域名/模式 | 用途 |
|-----------|------|
| `.eastmoney.com` | 东方财富 API（推流、K线、板块等） |
| `push2.eastmoney.com` | 实时行情 |
| `push2his.eastmoney.com` | 历史K线 |
| `.cn` / `.com.cn` / `.gov.cn` / `.edu.cn` | 通用国内域名 |
| `localhost` / `127.0.0.1` / `::1` | 本地+环回（避免循环代理）|

## 常见问题排查

| 症状 | 可能原因 | 解决 |
|------|---------|------|
| `ProxyError` on eastmoney | TUN 模式全流量代理 | 关 TUN + 改 Manual |
| 终端国内站点慢 | no_proxy 未包含目标域名 | 加 `.cn` / 具体域名 |
| `curl` 通国外但不通国内 | no_proxy 配置错误 | 检查格式（逗号分隔，无空格） |
| `akshare` 历史K线OK但实时失败 | API 域名不一致 | 确认 `.eastmoney.com` 在白名单 |
| `baostock` 不通 | baidu 域名不在白名单 | `.cn` 已涵盖，一般没问题 |

## 注意事项
- `no_proxy` 用逗号分隔，**不要有空格**
- 通配符 `.domain.com` 匹配当前域名和所有子域名
- 环境变量仅影响终端工具，不影响 GUI 浏览器
- macOS 默认启用 IPv6，建议 no_proxy 加上 `::1`
- `all_proxy` 端口是 SOCKS（默认 10808），`http_proxy` 端口是 HTTP（默认 10809），两者不同
