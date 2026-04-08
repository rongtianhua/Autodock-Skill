# 投资框架数据获取层

> 统一数据接口，免费优先，付费可选

---

## 快速开始

### 1. 安装依赖

```bash
pip install requests pyyaml
```

### 2. 基本使用

```python
from data_fetcher import DataFetcher

# 初始化（自动加载配置文件）
fetcher = DataFetcher()

# 获取股价
quote = fetcher.get_quote('600519.SH')
print(f"贵州茅台：¥{quote.price} ({quote.change_percent}%)")

# 获取财报
financials = fetcher.get_financials('600519.SH')
print(f"ROE: {financials.roe}%")
```

### 3. 配置文件

首次运行会自动创建 `~/.investment_framework/config.yaml`

```yaml
data_sources:
  priority:
    - tencent
    - sina
    - eastmoney

api_keys:
  tushare:
    token: ""  # 可选，https://tushare.pro/user/token
    enabled: false
```

---

## 支持的数据源

### 免费（无需 API Key）

| 数据源 | 数据类型 | 状态 |
|--------|---------|------|
| 腾讯财经 | 股价、大盘 | ✅ |
| 新浪财经 | 股价、大盘 | ✅ |
| 东方财富 | 股价、财报 | ✅ |

### 注册免费（需 API Key）

| 数据源 | 数据类型 | 状态 |
|--------|---------|------|
| Tushare Pro | 股价、财报、基本面 | ⏳ |
| 聚宽 | 历史行情、财务 | ⏳ |

### 付费（可选）

| 数据源 | 价格 | 数据类型 | 状态 |
|--------|------|---------|------|
| 理杏仁 | ¥299/年 | 估值分位、行业 | ⏳ |

---

## API 文档

### DataFetcher

```python
class DataFetcher:
    """统一数据获取接口"""
    
    def __init__(self, config_path: str = None)
    
    def get_quote(self, symbol: str) -> Quote
        """获取股价行情"""
    
    def get_financials(self, symbol: str) -> Financials
        """获取财报数据"""
    
    def get_indices(self, symbols: list) -> list
        """获取大盘指数"""
```

### 数据模型

```python
@dataclass
class Quote:
    symbol: str
    price: float
    change: float
    change_percent: float
    volume: int
    turnover: float
    market_cap: float
    pe: float
    pb: float
    source: str
    timestamp: datetime

@dataclass
class Financials:
    symbol: str
    report_date: str
    revenue: float
    net_profit: float
    roe: float
    eps: float
    debt_ratio: float
    gross_margin: float
    source: str
```

---

## 降级策略

1. **缓存**：API 失败时使用缓存（5 分钟 TTL）
2. **多源冗余**：腾讯→新浪→东方财富
3. **手动输入**：全部失败时可手动输入

---

*版本：v1.0.0*  
*创建：2026-03-20*
