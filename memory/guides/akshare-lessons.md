# Skill 安装规范

## 教训来源
2026-04-04 akshare-stock 技能安装过程

## 核心原则

**技能安装 ≠ 下载文件。** 标准技能安装流程应做到「装完即跑」。

## 标准安装流程

### 1. 下载文件
- 从 ClawHub/GitHub 拉取技能文件到 `~/.openclaw/workspace/skills/<skill-name>/`

### 2. 安装依赖
- 检查 `requirements.txt` 或文档提到的 pip 包
- `pip install` 或逐个安装
- 验证安装成功（`python3 -c "import xxx"`）

### 3. 初始化配置
- 创建必要的目录结构（如 `memory/`, `data/` 等）
- 如果技能需要配置文件，检查并填写
- 如果技能有自检测试，**必须运行并确认通过**

### 4. 设置心跳（如适用）
- 如果技能需要定期运行，写入 `HEARTBEAT.md`
- 设置合理的执行间隔（不要每个心跳都跑）
- 记录上次执行日期在 `memory/heartbeat-state.json`

### 5. 端到端验证
- **关键步骤：** 运行一个实际用例验证整个链路通不通
- 比如 akshare-stock 技能应该实际查一支股票，确认数据能返回
- 不要仅看"文件下载成功"就认为是安装完成

## 红线
- ❌ 只下载技能文件不做配置
- ❌ 安装失败就跳过依赖，不告知用户
- ❌ 自测不过就放弃，不排查原因
- ✅ 需要外部 API/账号认证的（如 cheapproxy token），应明确告诉用户需要什么、去哪获取

---

# 网络调试：VPN 与直连协调

## 核心问题
国内用户同时访问海外服务（OpenClaw/ChatGPT/OpenRouter/ClawHub/AI 模型 API）和国内服务（东方财富/新浪财经/同花顺/baostock/AKShare），需要：
- **海外服务** → 走 VPN
- **国内服务** → 直连（不 VPN，否则可能被识别为境外 IP 被封或降速）

## 解决方案

### 方式一：系统代理 + 环境变量（推荐）
```bash
# 查看当前代理设置（macOS）
networksetup -getwebproxy Wi-Fi
networksetup -getsecurewebproxy Wi-Fi

# 临时取消代理（需要直连国内服务时）
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY no_proxy NO_PROXY

# 查看 Python requests 库是否受代理影响
python3 -c "import os; print({k:v for k,v in os.environ.items() if 'proxy' in k.lower()})"
```

### 方式二：v2rayN 路由规则
- v2rayN 自带 PAC/路由规则功能
- 把国内域名（`*.eastmoney.com`, `*.sina.com.cn`, `*.baostock.com` 等）加入直连列表
- 其他流量走代理

### 方式三：Python 代码级控制
- `requests` 库默认读取环境变量代理
- `curl_cffi` 同理
- 需要直连时：在代码中设置 `proxies=None` 或 `proxies={}`
- 强制不走代理：`os.environ['NO_PROXY'] = '*'`

## 常见症状
- 国内 API 返回 403/404/空响应 → 可能走了代理被识别为境外 IP
- 国内 TLS 握手成功但返回空 → 反爬 + 代理 IP 被拉黑
- 同一个 API 有时通有时断 → VPN 切换导致 IP 变化

## 排查步骤
1. `curl -v <url>` 看看网络层是否通
2. 检查环境变量：`env | grep -i proxy`
3. 对比直连 vs 代理的行为差异
4. 确认 VPN 的路由规则（国内域名是否在直连列表）
5. 如果怀疑 IP 被识别为境外：访问 `http://ip.cn` 看真实出口 IP

## 注意事项
- Mac 的系统代理和终端代理是两回事
- 终端可能继承 shell 的 proxy 环境变量
- V2Ray 的路由规则按域名/IP 匹配，不是按进程
- 如果 akshare 或 requests 库不走代理也通，说明是反爬问题；走代理不通，说明是 IP 识别问题

---

# AkShare 包调壁记录

## 日期
2026-04-04

## 核心问题
东方财富（Eastmoney）API 全面封锁了 Python 自动化请求。

### 被封锁的接口（东财源 _em 后缀）
- `stock_zh_a_hist` — 个股历史K线（东财源）❌
- `stock_zh_a_spot_em` — 实时行情 ❌
- `stock_board_industry_name_em` — 行业板块 ❌
- `stock_individual_fund_flow` — 资金流向 ❌
- 所有 `_em` 后缀的接口 ❌

### 反爬机制分析
1. **不是 TLS 指纹问题** — `curl_cffi` 模拟 Chrome 110~131 所有版本 TLS 握手都通过，但 API 返回空或断连
2. **不是 User-Agent 问题** — 改 UA 无效
3. **不是 IP 问题** — 直连和代理都失败
4. **可能是行为检测** — 首页（`quote.eastmoney.com`）返回 200，但 API 端点（`push2.eastmoney.com`, `push2his.eastmoney.com`）识别非浏览器客户端后：
   - TLS 握手正常
   - HTTP 请求发送成功
   - 服务器直接返回空响应（Empty Reply from Server）

### 可用数据源

#### ✅ Baostock — 个股历史K线（主力）
- `pip install baostock`
- 需要 `bs.login()` / `bs.logout()`
- **噪音输出**：login/logout 会打印到 stdout，需要 `sys.stdout = io.StringIO()` 压制
- **Errno 9 误报**：baostock 会打印 `[Errno 9] Bad file descriptor` 到 stderr，但不影响功能
- API 对日期格式要求严格（`YYYY-MM-DD`）
- `rs.next()` 必须调用才能读取第一条记录

#### ✅ AkShare 新浪源 — 指数历史K线（主力）
- `ak.stock_zh_index_daily(symbol="sh000001")`
- 工作稳定，日期范围广

#### ⚠️ AkShare 新浪源 — 个股K线（不可靠）
- `ak.stock_zh_a_daily(symbol="sz000001")`
- **问题**：新浪的 `hisdata_klc2/klc_kl.js` 端点返回加密数据，akshare 1.18.49 解析不稳定
- 有时返回正确 DataFrame（带 'date' 列），有时抛出 `KeyError: 'date'`
- **不能作为主力数据源**，只能兜底

#### ✅ Sina HTTP API — 实时行情
- 直接 `urllib.request` 调用
- `https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData`
- 需要加延时避免限流（每批次间隔 0.3s+）
- 返回 GBK 编码，需要 `.decode('gbk')`

#### ✅ Sina KLine API — 个股K线补充
- `https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData`
- JSONP 格式，需正则提取
- 每次最多返回 ~100 条（近期交易）
- UTF-8 编码
- 有频率限制，连续请求会限流返回 `null`

### akshare-proxy-patch 插件
- **是什么**：cheapproxy.net 官方插件，注入动态 UA + nid18 Cookie + 代理 IP
- **怎么用**：`pip install akshare-proxy-patch` → 去 cheapproxy.net 注册获取 token → `install_patch("127.0.0.1", auth_token="TOKEN")`
- **限制**：绑定 cheapproxy 官方服务，其他代理不兼容
- **费用**：付费服务，价格较贵
- **结论**：暂时不用

### 关键教训

1. **不要轻易断定"服务器停止服务"**
   - 第一次测 baostock 返回 0 条就断言"baostock 停了"
   - 实际是测试方法有问题
   - **正确做法**：跑最小用例（`bs.login()` + 简单查询）验证连通性

2. **stdout 重定向要正确恢复**
   - baostock 的 `login()`/`logout()` 打印很多噪音
   - 用 `sys.stdout = io.StringIO()` 压制，必须用 `finally` 块确保恢复
   - 否则后续函数调用会读到 `StringIO` 而不是真正的 stdout

3. **Python 的 requests 库不走代理≠直连**
   - akshare 内部用 `requests.get()` 调东财
   - 东财在应用层识别 requests 库（不管是否有代理）
   - 单纯改代理设置没用，需要换数据源

4. **测试必须在隔离环境下做**
   - 同一个 Python 进程里，baostock 的 socket 操作可能干扰后续的 requests 调用
   - 测试一个数据源时，确保其他数据源的环境干净
