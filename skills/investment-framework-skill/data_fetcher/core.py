"""
核心数据获取器

统一接口，多数据源冗余，自动降级
"""

import requests
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

from .config import load_config, DEFAULT_CONFIG_PATH
from .cache import CacheManager
from .exceptions import DataFetchError, ConfigError

# 延迟导入提供者，避免循环依赖
def _import_providers():
    """延迟导入提供者模块"""
    from .providers import tencent, sina, eastmoney
    return tencent, sina, eastmoney


@dataclass
class Quote:
    """股价行情数据"""
    symbol: str
    price: float
    change: float
    change_percent: float
    volume: int
    turnover: float
    market_cap: float
    pe: float
    pb: float
    high: float
    low: float
    open: float
    prev_close: float
    source: str
    timestamp: datetime
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Quote':
        """从字典创建"""
        return cls(
            symbol=data.get('symbol', ''),
            price=data.get('price', 0.0),
            change=data.get('change', 0.0),
            change_percent=data.get('change_percent', 0.0),
            volume=data.get('volume', 0),
            turnover=data.get('turnover', 0.0),
            market_cap=data.get('market_cap', 0.0),
            pe=data.get('pe', 0.0),
            pb=data.get('pb', 0.0),
            high=data.get('high', 0.0),
            low=data.get('low', 0.0),
            open=data.get('open', 0.0),
            prev_close=data.get('prev_close', 0.0),
            source=data.get('source', 'unknown'),
            timestamp=datetime.fromisoformat(data['timestamp']) if 'timestamp' in data else datetime.now(),
        )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'symbol': self.symbol,
            'price': self.price,
            'change': self.change,
            'change_percent': self.change_percent,
            'volume': self.volume,
            'turnover': self.turnover,
            'market_cap': self.market_cap,
            'pe': self.pe,
            'pb': self.pb,
            'high': self.high,
            'low': self.low,
            'open': self.open,
            'prev_close': self.prev_close,
            'source': self.source,
            'timestamp': self.timestamp.isoformat(),
        }


@dataclass
class Financials:
    """财报数据"""
    symbol: str
    report_date: str
    revenue: float
    net_profit: float
    roe: float
    eps: float
    debt_ratio: float
    gross_margin: float
    net_margin: float
    operating_cash_flow: float
    source: str
    timestamp: datetime
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Financials':
        """从字典创建"""
        return cls(
            symbol=data.get('symbol', ''),
            report_date=data.get('report_date', ''),
            revenue=data.get('revenue', 0.0),
            net_profit=data.get('net_profit', 0.0),
            roe=data.get('roe', 0.0),
            eps=data.get('eps', 0.0),
            debt_ratio=data.get('debt_ratio', 0.0),
            gross_margin=data.get('gross_margin', 0.0),
            net_margin=data.get('net_margin', 0.0),
            operating_cash_flow=data.get('operating_cash_flow', 0.0),
            source=data.get('source', 'unknown'),
            timestamp=datetime.fromisoformat(data['timestamp']) if 'timestamp' in data else datetime.now(),
        )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'symbol': self.symbol,
            'report_date': self.report_date,
            'revenue': self.revenue,
            'net_profit': self.net_profit,
            'roe': self.roe,
            'eps': self.eps,
            'debt_ratio': self.debt_ratio,
            'gross_margin': self.gross_margin,
            'net_margin': self.net_margin,
            'operating_cash_flow': self.operating_cash_flow,
            'source': self.source,
            'timestamp': self.timestamp.isoformat(),
        }


class DataFetcher:
    """统一数据获取接口"""
    
    def __init__(self, config_path: str = None):
        """
        初始化数据获取器
        
        Args:
            config_path: 配置文件路径，默认 ~/.investment_framework/config.yaml
        """
        self.config = load_config(config_path)
        self.cache = CacheManager(
            ttl=self.config['fallback']['cache_ttl'],
            use_file_cache=False,  # 默认不使用文件缓存
        )
        self.timeout = self.config['fallback']['timeout']
        
        # 数据源优先级
        # Tushare 需要 API Key，如果配置了则优先使用
        api_keys = self.config.get('api_keys', {})
        tushare_enabled = api_keys.get('tushare', {}).get('enabled', False) and api_keys.get('tushare', {}).get('token', '')
        
        if tushare_enabled:
            self.quote_providers = ['tushare', 'tencent', 'sina', 'eastmoney']
            self.financials_providers = ['tushare', 'eastmoney']
        else:
            self.quote_providers = ['tencent', 'sina', 'eastmoney']
            self.financials_providers = ['eastmoney']
    
    def get_quote(self, symbol: str, use_cache: bool = True) -> Quote:
        """
        获取股价行情
        
        Args:
            symbol: 股票代码（如：600519.SH, 000001.SZ）
            use_cache: 是否使用缓存
        
        Returns:
            Quote 对象
        """
        cache_key = f"quote:{symbol}"
        
        # 检查缓存
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached:
                return Quote.from_dict(cached)
        
        # 延迟导入提供者
        tencent, sina, eastmoney = _import_providers()
        
        # 检查是否启用 Tushare
        api_keys = self.config.get('api_keys', {})
        tushare_enabled = api_keys.get('tushare', {}).get('enabled', False) and api_keys.get('tushare', {}).get('token', '')
        
        # 按优先级尝试数据源
        last_error = None
        
        for provider in self.quote_providers:
            try:
                if provider == 'tushare' and tushare_enabled:
                    from .providers.tushare import fetch_tushare_quote
                    quote = fetch_tushare_quote(symbol, self.timeout, self.config)
                elif provider == 'tencent':
                    quote = tencent.fetch_tencent_quote(symbol, self.timeout)
                elif provider == 'sina':
                    quote = sina.fetch_sina_quote(symbol, self.timeout)
                elif provider == 'eastmoney':
                    quote = eastmoney.fetch_eastmoney_quote(symbol, self.timeout)
                else:
                    continue
                
                # 保存到缓存
                self.cache.set(cache_key, quote.to_dict())
                
                return quote
            
            except Exception as e:
                last_error = e
                continue
        
        # 全部失败
        raise DataFetchError(
            f"无法获取 {symbol} 的行情数据，所有数据源均失败。"
            f"最后错误：{last_error}"
        )
    
    def get_financials(self, symbol: str, use_cache: bool = True) -> Financials:
        """
        获取财报数据
        
        Args:
            symbol: 股票代码
            use_cache: 是否使用缓存
        
        Returns:
            Financials 对象
        """
        cache_key = f"financials:{symbol}"
        
        # 检查缓存
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached:
                return Financials.from_dict(cached)
        
        # 延迟导入提供者
        tencent, sina, eastmoney = _import_providers()
        
        # 检查是否启用 Tushare
        api_keys = self.config.get('api_keys', {})
        tushare_enabled = api_keys.get('tushare', {}).get('enabled', False) and api_keys.get('tushare', {}).get('token', '')
        
        # 尝试数据源
        last_error = None
        
        for provider in self.financials_providers:
            try:
                if provider == 'tushare' and tushare_enabled:
                    from .providers.tushare import fetch_tushare_financials
                    financials = fetch_tushare_financials(symbol, self.timeout, self.config)
                elif provider == 'eastmoney':
                    financials = eastmoney.fetch_eastmoney_financials(symbol, self.timeout)
                else:
                    continue
                
                # 保存到缓存
                self.cache.set(cache_key, financials.to_dict())
                
                return financials
            
            except Exception as e:
                last_error = e
                continue
        
        # 全部失败
        raise DataFetchError(
            f"无法获取 {symbol} 的财报数据，所有数据源均失败。"
            f"最后错误：{last_error}"
        )
    
    def get_indices(self, symbols: List[str] = None, use_cache: bool = True) -> List[Quote]:
        """
        获取大盘指数
        
        Args:
            symbols: 指数代码列表，默认 ['000001.SH', '399001.SZ', '399006.SZ']
            use_cache: 是否使用缓存
        
        Returns:
            Quote 对象列表
        """
        if symbols is None:
            symbols = ['000001.SH', '399001.SZ', '399006.SZ']
        
        # 延迟导入提供者
        tencent, sina, eastmoney = _import_providers()
        
        results = []
        
        # 尝试腾讯
        try:
            quotes = tencent.fetch_tencent_indices(symbols, self.timeout)
            return quotes
        except Exception:
            pass
        
        # 尝试新浪
        try:
            quotes = sina.fetch_sina_indices(symbols, self.timeout)
            return quotes
        except Exception:
            pass
        
        # 全部失败，逐个获取
        for symbol in symbols:
            try:
                quote = self.get_quote(symbol, use_cache)
                results.append(quote)
            except Exception:
                # 创建空数据
                results.append(Quote(
                    symbol=symbol,
                    price=0.0,
                    change=0.0,
                    change_percent=0.0,
                    volume=0,
                    turnover=0.0,
                    market_cap=0.0,
                    pe=0.0,
                    pb=0.0,
                    high=0.0,
                    low=0.0,
                    open=0.0,
                    prev_close=0.0,
                    source='none',
                    timestamp=datetime.now(),
                ))
        
        return results
    
    def clear_cache(self) -> None:
        """清空缓存"""
        self.cache.clear()
    
    def get_cache_stats(self) -> dict:
        """获取缓存统计"""
        return self.cache.stats()
