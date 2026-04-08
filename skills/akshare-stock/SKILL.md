---
name: akshare-stock
description: A股量化数据分析工具，基于AkShare/Baostock获取A股行情、财务数据、板块信息等。用于回答关于A股股票查询、行情数据、财务分析、选股等问题。
---

# A股量化 - AkShare 数据接口

## 数据源架构

东方财富 API 已被反爬机制封锁。当前实际工作架构：

| 层级 | 数据源 | 用途 | 状态 |
|------|--------|------|------|
| 主力 | Baostock | 个股历史K线 | ✅ 稳定 |
| 主力 | AkShare (新浪源) | 指数历史K线 | ✅ 稳定 |
| Fallback | Sina HTTP API | 实时行情 | ✅ 稳定 |
| ❌ 废弃 | 东财源 (ak._em 系列) | 实时行情/资金流等 | 反爬不可用 |

## 快速使用

```python
import sys
sys.path.insert(0, '~/.openclaw/workspace/skills/akshare-stock')
from akshare_stock import get_stock_hist, get_spot_quotes, get_index_hist

# 1. 个股历史K线 (baostock → akshare新浪)
df, source = get_stock_hist("000001", start_date="20260101", end_date="20260404")
print(f"来源: {source}, {len(df)} 条")
print(df.tail())

# 2. A股实时行情 (Sina)
df_spot = get_spot_quotes(top_n=20)
print(df_spot[['代码','名称','最新价','涨跌幅']].head(10))

# 3. 指数历史K线 (AkShare新浪)
df_index = get_index_hist("sh000001", start_date="20260101", end_date="20260404")
print(df_index.tail())
```

## 直接调用底层函数

```python
from akshare_stock import (
    baostock_kline,        # baostock K线
    akshare_index,         # akshare 指数K线
    akshare_stock_daily,   # akshare 个股K线(sina源, may be flaky)
    get_spot_quotes,       # Sina 实时行情
    get_index_hist,        # 指数历史
    get_stock_hist,        # 个股历史 (高层接口, baostock优先)
)
```

## 接口说明

### get_stock_hist(symbol, start_date, end_date, adjust)
- **symbol**: 股票代码 `"000001"` (平安银行)
- **start_date/end_date**: `"20260101"` 格式
- **adjust**: `"qfq"` 前复权 | `"hfq"` 后复权 | `""` 不复权
- **返回**: `(DataFrame, source_name)` — source: `"baostock"` 或 `"akshare_sina"`

### get_spot_quotes(top_n=50)
- 返回按涨跌幅排序的 DataFrame
- 列: 代码, 名称, 最新价, 涨跌额, 涨跌幅, 开盘价, 最高价, 最低价, 昨收, 成交量, 成交额, 市盈率

### get_index_hist(symbol="sh000001", start_date, end_date)
- **symbol**: `"sh000001"` 上证指数 | `"sz399001"` 深证成指 | `"sz399006"` 创业板指
- 返回: DataFrame (日期, 开盘, 最高, 最低, 收盘, 成交量)

## 常用代码
- 平安银行: `000001` | 沪深300: `sh000300`
- 贵州茅台: `600519` | 深证成指: `sz399001`
- 上证50: `sh000016` | 创业板指: `sz399006`

## 注意事项
1. **东财源不可用** — `stock_zh_a_hist`, `stock_zh_a_spot_em`, `stock_board_*` 等 `_em` 后缀接口均被反爬拦截
2. **数据仅供参考** — 不构成投资建议
3. baostock 有登录/登出开销，不宜高频调用

## 依赖
```bash
pip install akshare baostock pandas
```
