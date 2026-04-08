"""
Tushare Pro API

免费财经数据，需注册获取 token
官网：https://tushare.pro/

注意：
- 注册送 100 积分
- 基础接口需要 100 积分
- 高频数据需要更多积分（签到/付费）
"""

import tushare as ts
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from ..core import Quote, Financials
from ..exceptions import APIKeyError, ProviderError
from ..config import get_api_key, load_config


def check_tushare_permissions(token: str) -> Dict:
    """
    检查 Tushare 权限
    
    Args:
        token: API token
    
    Returns:
        权限信息字典
    """
    try:
        ts.set_token(token)
        pro = ts.pro_api()
        
        # 尝试获取用户信息
        try:
            user = pro.user()
            if len(user) > 0:
                return {
                    'valid': True,
                    'name': user.iloc[0].get('name', 'Unknown'),
                    'points': user.iloc[0].get('total_pts', 0) if 'total_pts' in user.columns else 0,
                    'message': f"用户：{user.iloc[0].get('name', 'Unknown')}, 积分：{user.iloc[0].get('total_pts', 0)}"
                }
        except Exception:
            pass
        
        # 尝试基础接口（100 积分即可）
        try:
            df = pro.trade_cal(exchange='SSE', start_date='20260319', end_date='20260319', is_open='1')
            return {
                'valid': True,
                'name': 'Unknown',
                'points': '>=100',
                'message': '基础接口可用（100+ 积分）'
            }
        except Exception:
            pass
        
        return {
            'valid': False,
            'message': 'Token 无效或积分不足'
        }
    
    except Exception as e:
        return {
            'valid': False,
            'message': f'检查失败：{e}'
        }


def init_tushare(config: dict = None) -> ts.pro_api:
    """
    初始化 Tushare Pro
    
    Args:
        config: 配置字典，None 则自动加载
    
    Returns:
        pro_api 实例
    """
    token = get_api_key('tushare', config)
    
    if not token:
        raise APIKeyError(
            "Tushare API Key 未配置。\n"
            "请在配置文件中设置：~/.investment_framework/config.yaml\n"
            "或访问 https://tushare.pro/user/token 获取 token"
        )
    
    ts.set_token(token)
    return ts.pro_api()


def fetch_tushare_quote(symbol: str, timeout: int = 5, config: dict = None) -> Quote:
    """
    获取 Tushare 实时行情
    
    Args:
        symbol: 股票代码（如：000001.SZ, 600519.SH）
        timeout: 超时时间（秒）
        config: 配置字典
    
    Returns:
        Quote 对象
    """
    try:
        pro = init_tushare(config)
        
        ts_code = symbol.upper().strip()
        today = datetime.now()
        start_date = today.strftime('%Y%m%d')
        
        # 获取日线数据
        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=start_date)
        
        if df is None or len(df) == 0:
            # 尝试获取前一天数据
            yesterday = today - timedelta(days=1)
            start_date = yesterday.strftime('%Y%m%d')
            df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=start_date)
        
        if df is None or len(df) == 0:
            raise ProviderError('tushare', f'未找到 {symbol} 的行情数据')
        
        row = df.iloc[0]
        
        # 获取基本面数据（需要 300+ 积分）
        pe, pb, market_cap = 0.0, 0.0, 0.0
        try:
            basic = pro.stock_basic(ts_code=ts_code, fields='ts_code,name,pe,pb,total_mv')
            if basic is not None and len(basic) > 0:
                pe_val = basic.iloc[0].get('pe', None)
                pb_val = basic.iloc[0].get('pb', None)
                mv_val = basic.iloc[0].get('total_mv', None)
                pe = float(pe_val) if pe_val else 0.0
                pb = float(pb_val) if pb_val else 0.0
                market_cap = float(mv_val) if mv_val else 0.0
        except Exception:
            # 积分不足时返回 0，会降级到其他数据源
            pass
        
        return Quote(
            symbol=symbol,
            price=float(row['close']),
            change=float(row['close']) - float(row['pre_close']),
            change_percent=(float(row['close']) - float(row['pre_close'])) / float(row['pre_close']) * 100 if row['pre_close'] > 0 else 0.0,
            volume=int(row['vol']),
            turnover=float(row['amount']),
            market_cap=market_cap,
            pe=pe,
            pb=pb,
            high=float(row['high']),
            low=float(row['low']),
            open=float(row['open']),
            prev_close=float(row['pre_close']),
            source='tushare',
            timestamp=datetime.now(),
        )
    
    except APIKeyError:
        raise
    except Exception as e:
        raise ProviderError('tushare', f'获取行情失败：{e}')


def fetch_tushare_financials(symbol: str, timeout: int = 5, config: dict = None) -> Financials:
    """
    获取 Tushare 财报数据
    
    Args:
        symbol: 股票代码
        timeout: 超时时间（秒）
        config: 配置字典
    
    Returns:
        Financials 对象
    """
    try:
        pro = init_tushare(config)
        ts_code = symbol.upper().strip()
        
        # 获取财务指标数据
        df = pro.fina_indicator(ts_code=ts_code)
        
        if df is None or len(df) == 0:
            raise ProviderError('tushare', f'未找到 {symbol} 的财报数据')
        
        latest = df.iloc[0]
        
        report_date = latest.get('ann_date', '')
        if isinstance(report_date, (int, float)):
            report_date = str(int(report_date))
        
        return Financials(
            symbol=symbol,
            report_date=str(report_date),
            revenue=0.0,  # 需要额外接口
            net_profit=0.0,
            roe=float(latest.get('roe', 0) or 0),
            eps=float(latest.get('basic_eps', 0) or 0),
            debt_ratio=0.0,
            gross_margin=float(latest.get('grossmargin', 0) or 0),
            net_margin=float(latest.get('netmargin', 0) or 0),
            operating_cash_flow=0.0,
            source='tushare',
            timestamp=datetime.now(),
        )
    
    except APIKeyError:
        raise
    except Exception as e:
        raise ProviderError('tushare', f'获取财报失败：{e}')


def fetch_tushare_indices(symbols: List[str], timeout: int = 5, config: dict = None) -> List[Quote]:
    """
    获取 Tushare 大盘指数
    
    Args:
        symbols: 指数代码列表
        timeout: 超时时间（秒）
        config: 配置字典
    
    Returns:
        Quote 对象列表
    """
    try:
        pro = init_tushare(config)
        
        index_map = {
            '000001.SH': '000001.SH',
            '399001.SZ': '399001.SZ',
            '399006.SZ': '399006.SZ',
        }
        
        quotes = []
        today = datetime.now()
        start_date = today.strftime('%Y%m%d')
        
        for symbol in symbols:
            ts_code = index_map.get(symbol.upper(), symbol.upper())
            
            try:
                df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=start_date)
                
                if df is None or len(df) == 0:
                    yesterday = today - timedelta(days=1)
                    start_date = yesterday.strftime('%Y%m%d')
                    df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=start_date)
                
                if df is None or len(df) == 0:
                    continue
                
                row = df.iloc[0]
                
                quote = Quote(
                    symbol=symbol,
                    price=float(row['close']),
                    change=float(row['close']) - float(row['pre_close']),
                    change_percent=(float(row['close']) - float(row['pre_close'])) / float(row['pre_close']) * 100 if row['pre_close'] > 0 else 0.0,
                    volume=0,
                    turnover=0.0,
                    market_cap=0.0,
                    pe=0.0,
                    pb=0.0,
                    high=float(row['high']),
                    low=float(row['low']),
                    open=float(row['open']),
                    prev_close=float(row['pre_close']),
                    source='tushare',
                    timestamp=datetime.now(),
                )
                quotes.append(quote)
            
            except Exception:
                continue
        
        return quotes
    
    except APIKeyError:
        raise
    except Exception as e:
        raise ProviderError('tushare', f'获取指数失败：{e}')
