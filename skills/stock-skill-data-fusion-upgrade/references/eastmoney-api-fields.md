# 东方财富 API 字段参考

## 主力资金数据 API

**基础 URL**：`https://push2delay.eastmoney.com/api/qt/klist/get`

**必需参数**：
- `secid`：股票代码（格式：`市场代码.股票代码`）
  - 上交所：`1.600519`（贵州茅台）
  - 深交所：`0.000858`（平安银行）
  - 创业板：`0.300750`（宁德时代）
- `fields`：指定返回字段，用 `-` 分隔

**重要字段代码**：

| 字段代码 | 含义 | 单位/说明 |
|---------|------|----------|
| `f184` | 主力净流入 | 元（需 ×10000 转万元） |
| `f185` | 主力净流入率 | % |
| `f186` | 3日累计主力净流入 | 元（需 ×10000 转万元）⭐ 超短核心 |
| `f187` | 5日累计主力净流入 | 元（需 ×10000 转万元）⭐ 超短核心 |
| `f188` | 10日累计主力净流入 | 元（需 ×10000 转万元）⭐ 超短核心 |
| `f173` | 净流入占成交比 | % |
| `f128` | 所属板块 | 字符串 |
| `f140` | 超大单净流入 | ⚠️ 待确认单位 |
| `f141` | 大单净流入 | ⚠️ 待确认单位 |

**代码示例**：
```python
import requests

def get_eastmoney_fund_flow(secid: str) -> dict:
    url = "https://push2delay.eastmoney.com/api/qt/klist/get"
    params = {
        "secid": secid,
        "fields": "f1-f10,f173,f184-f188"
    }
    resp = requests.get(url, params=params)
    data = resp.json()["data"]["klines"][0].split(",")
    
    # f184 在索引位置，×10000 转万元
    main_net_flow = int(data[23]) * 10000  # f184
    main_net_flow_rate = data[24]  # f185
    flow_3day = int(data[25]) * 10000  # f186
    flow_5day = int(data[26]) * 10000  # f187
    flow_10day = int(data[27]) * 10000  # f188
    
    return {
        "main_net_flow_yuan": main_net_flow,
        "main_net_flow_rate": main_net_flow_rate,
        "flow_3day": flow_3day,
        "flow_5day": flow_5day,
        "flow_10day": flow_10day
    }
```

## 市场情绪 API（akshare）

**全市场资金流向**（一个接口获取全部）：
```python
import akshare as ak
df = ak.stock_market_fund_flow()
# 返回：全市场主力/超大/大/中/小单净流入+占比+指数涨跌幅
```

**北向资金+涨跌家数**：
```python
df = ak.stock_hsgt_fund_flow_summary_em()
# 同时返回涨跌家数和北向资金
```

## 注意事项

- 东财 `ulist.np` API 对指数 secid 全部返回 `{}`，**只对股票有效**
- 东财涨停板数据（`stock_zt_pool_em`）收盘后为空，无稳定免费接口
- akshare 在某些网络环境下可能被反爬拦截