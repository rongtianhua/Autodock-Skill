# 数据获取层使用指南

> **版本**：v1.0.0  
> **创建**：2026-03-20  
> **状态**：✅ 核心功能完成

---

## 快速开始

### 1. 安装依赖

```bash
pip install requests pyyaml
```

### 2. 基本使用

```python
from data_fetcher import DataFetcher

# 初始化（自动创建配置文件）
fetcher = DataFetcher()

# 获取股价
quote = fetcher.get_quote('600519.SH')
print(f"贵州茅台：¥{quote.price} ({quote.change_percent}%)")

# 获取财报
financials = fetcher.get_financials('600519.SH')
print(f"ROE: {financials.roe}%")

# 获取大盘指数
indices = fetcher.get_indices()
for idx in indices:
    print(f"{idx.symbol}: {idx.price} ({idx.change_percent}%)")
```

### 3. 配置文件

首次运行自动创建 `~/.investment_framework/config.yaml`

```yaml
data_sources:
  priority:
    - tencent      # 腾讯（免费，优先）
    - sina         # 新浪（免费，备用）
    - eastmoney    # 东方财富（免费，财报）

api_keys:
  tushare:
    token: ""      # 可选，https://tushare.pro/user/token
    enabled: false
```

---

## 支持的数据源

### ✅ 已实现（免费）

| 数据源 | 数据类型 | 需要 API Key | 状态 |
|--------|---------|-------------|------|
| 腾讯财经 | 股价、大盘 | ❌ | ✅ 完成 |
| 新浪财经 | 股价、大盘 | ❌ | ✅ 完成 |
| 东方财富 | 股价、财报 | ❌ | ✅ 完成 |

### ⏳ 计划中

| 数据源 | 数据类型 | 需要 API Key | 状态 |
|--------|---------|-------------|------|
| Tushare Pro | 股价、财报、基本面 | ✅（免费） | 待实现 |
| 理杏仁 | 估值分位、行业 | ✅（付费） | 待实现 |

---

## API 参考

### DataFetcher

```python
class DataFetcher:
    def __init__(self, config_path: str = None)
        """初始化，自动加载配置"""
    
    def get_quote(self, symbol: str, use_cache: bool = True) -> Quote
        """获取股价行情"""
    
    def get_financials(self, symbol: str, use_cache: bool = True) -> Financials
        """获取财报数据"""
    
    def get_indices(self, symbols: list = None, use_cache: bool = True) -> list
        """获取大盘指数"""
    
    def clear_cache(self)
        """清空缓存"""
    
    def get_cache_stats(self) -> dict
        """获取缓存统计"""
```

### 数据模型

```python
# 股价行情
@dataclass
class Quote:
    symbol: str           # 股票代码
    price: float          # 当前价
    change: float         # 涨跌额
    change_percent: float # 涨跌幅
    volume: int           # 成交量
    turnover: float       # 成交额
    market_cap: float     # 总市值
    pe: float             # 市盈率
    pb: float             # 市净率
    source: str           # 数据来源
    timestamp: datetime   # 时间戳

# 财报数据
@dataclass
class Financials:
    symbol: str           # 股票代码
    report_date: str      # 报告期
    revenue: float        # 营业收入
    net_profit: float     # 净利润
    roe: float            # ROE
    eps: float            # 每股收益
    debt_ratio: float     # 资产负债率
    gross_margin: float   # 毛利率
    source: str           # 数据来源
    timestamp: datetime   # 时间戳
```

---

## 股票代码格式

```python
# A 股
'600519.SH'  # 贵州茅台（沪市）
'000001.SZ'  # 平安银行（深市）
'300750.SZ'  # 宁德时代（创业板）

# 大盘指数
'000001.SH'  # 上证指数
'399001.SZ'  # 深证成指
'399006.SZ'  # 创业板指
```

---

## 降级策略

### 1. 多源冗余

```
腾讯财经 → 新浪财经 → 东方财富
   ↓          ↓          ↓
 失败       失败       手动输入
```

### 2. 缓存机制

- 默认缓存 5 分钟
- 减少 API 请求
- 提高响应速度

### 3. 手动输入

所有 API 失败时，可提示用户手动输入数据

---

## 测试

```bash
cd investment-framework-skill
python3 workflows/scripts/test-data-fetcher.py
```

---

## 集成到技能

### value-analyzer 示例

```python
from data_fetcher import DataFetcher, DataFetchError

def analyze_stock(symbol: str):
    """价值分析"""
    fetcher = DataFetcher()
    
    try:
        # 获取数据
        quote = fetcher.get_quote(symbol)
        financials = fetcher.get_financials(symbol)
        
        # 分析
        result = {
            'price': quote.price,
            'pe': quote.pe,
            'pb': quote.pb,
            'roe': financials.roe,
        }
        
        return graham_analysis(result)
        
    except DataFetchError as e:
        return {
            'error': str(e),
            'fallback': 'manual_input'
        }
```

---

## 常见问题

### Q: 数据不准确？
A: 免费数据源可能有延迟，建议交叉验证

### Q: API 失败？
A: 检查网络，使用缓存或手动输入

### Q: 如何添加新数据源？
A: 在 `data_fetcher/providers/` 创建新模块

---

## 下一步

### 阶段 1（P0）✅ 完成
- [x] 腾讯财经集成
- [x] 新浪财经集成
- [x] 东方财富集成
- [x] 缓存管理
- [x] 配置管理

### 阶段 2（P1）⏳ 进行中
- [ ] Tushare Pro 集成
- [ ] API Key 安全存储
- [ ] 配置向导

### 阶段 3（P2）⏳ 计划
- [ ] 理杏仁集成
- [ ] 行业数据
- [ ] 宏观数据

---

*文档版本：v1.0.0*  
*更新时间：2026-03-20*
