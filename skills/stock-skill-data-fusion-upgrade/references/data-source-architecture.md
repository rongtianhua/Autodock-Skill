# 数据源架构总结

## 五层数据融合架构（v2.6.0）

```
腾讯 API (主数据源)
  │  提供：现价/PE/PB/换手率/量比/市值/52周高低
  │
  └─→ 新浪 API (补充层)
       │  提供：委比/状态码/精确时间戳/五档盘口
       │
       └─→ 东财 push2delay.eastmoney.com (资金面层)
            │  提供：主力净流入/3日累计/5日累计/10日累计/净流入率
            │
            └─→ akshare (备用层)
                 │  提供：全市场资金流向/北向资金
                 │
                 └─→ baostock (兜底层)
                      提供：K线数据/基本面数据/EPS/杜邦分解
```

## 各数据源职责

| 数据源 | 角色 | 核心字段 |
|-------|------|---------|
| **腾讯 API** | 主数据源 | 价格/PE/PB/换手率/量比/市值/五档（部分） |
| **新浪 API** | 补充层 | 委比/状态码/精确时间戳/五档（完整） |
| **东财 API** | 资金面 | 主力净流入/3日累计/5日累计/10日累计 |
| **akshare** | 情绪面 | 全市场资金/北向资金/涨跌家数 |
| **baostock** | 兜底 | K线/基本面/杜邦分析 |

## 东财 Playwright 替换记录

### 问题
- 东财网页触发拼图验证码
- Playwright 无法提取数据

### 解决方案
- 改用 `push2delay.eastmoney.com` JSON API
- 字段 `f184 × 10000` 转万元

### 新增方法
```python
_get_eastmoney_supplementary_data(secid) -> dict
```

返回字段：
- `main_net_flow`（元）
- `main_net_flow_rate`（%）
- `flow_3day` / `flow_5day` / `flow_10day`（元）
- `net_flow_ratio`（%）
- `sector`（板块）

## 数据融合代码模式

```python
def get_quote_with_fallback(code):
    # 1. 腾讯主数据源
    raw = get_tencent_quote(code)
    if raw:
        # 2. 腾讯成功时，补充新浪字段
        sina = get_sina_quote(code)
        if sina:
            raw.buy_ratio = sina.buy_ratio
            raw.status = sina.status
            raw.timestamp = sina.timestamp
            raw.bid_prices = sina.bid_prices  # 新浪五档覆盖腾讯
            raw.ask_prices = sina.ask_prices
        
        # 3. 东财主力资金
        eastmoney = get_eastmoney_fund_flow(code)
        if eastmoney:
            raw.main_net_flow = eastmoney.main_net_flow
            # ...
        
        return raw
    
    # 4. 降级到 baostock
    return get_baostock_data(code)
```

## 经验教训

1. **API 索引必须分别验证**，不同数据源的字段位置不同
2. **优先使用 JSON API**，比 Playwright 更快更稳定
3. **主力资金用东财 API**，f184 × 10000 转万元
4. **五档盘口以新浪为准**，腾讯只有部分档位
5. **涨跌家数数据源受限**，东财/新浪/akshare 均有局限