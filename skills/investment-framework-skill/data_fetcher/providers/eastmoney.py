"""
东方财富 API

无需 API Key，支持股价和财报数据
接口：https://push2.eastmoney.com/, https://datacenter.eastmoney.com/
"""

import requests
from typing import List
from datetime import datetime
from ..core import Quote, Financials
from ..exceptions import ProviderError


def convert_to_eastmoney_secid(symbol: str) -> str:
    """
    转换股票代码为东方财富 secid 格式
    
    Args:
        symbol: 股票代码（如：600519.SH）
    
    Returns:
        secid 格式（如：1.600519）
    
    市场代码：
    - 1: 沪市（600xxx, 688xxx）
    - 0: 深市（000xxx, 002xxx, 300xxx）
    """
    symbol = symbol.upper().strip()
    
    # 提取代码部分
    code = symbol.replace('.SH', '').replace('.SZ', '')
    
    # 判断市场
    if symbol.startswith('6') or symbol.startswith('1'):
        # 沪市
        return f"1.{code}"
    else:
        # 深市
        return f"0.{code}"


def convert_to_eastmoney_secucode(symbol: str) -> str:
    """
    转换股票代码为东方财富 secucode 格式
    
    Args:
        symbol: 股票代码（如：600519.SH）
    
    Returns:
        secucode 格式（如：600519.SH）
    """
    symbol = symbol.upper().strip()
    
    if '.SH' in symbol or '.SZ' in symbol:
        return symbol
    else:
        # 默认沪市
        return f"{symbol}.SH" if symbol.startswith('6') else f"{symbol}.SZ"


def fetch_eastmoney_quote(symbol: str, timeout: int = 5) -> Quote:
    """
    获取东方财富行情
    
    Args:
        symbol: 股票代码
        timeout: 超时时间（秒）
    
    Returns:
        Quote 对象
    """
    secid = convert_to_eastmoney_secid(symbol)
    
    # 请求字段
    fields = [
        'f43',  # 最新价
        'f44',  # 涨跌幅
        'f45',  # 涨跌额
        'f46',  # 成交量
        'f47',  # 成交额
        'f48',  # 总市值
        'f49',  # 市盈率
        'f50',  # 市净率
        'f44',  # 最高
        'f45',  # 最低
        'f46',  # 开盘
        'f60',  # 昨收
    ]
    
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        'secid': secid,
        'fields': ','.join(fields),
    }
    
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get('rc') != 0 or not data.get('data'):
            raise ProviderError('eastmoney', '返回数据为空或错误')
        
        stock_data = data['data']
        
        # 解析数据
        price = stock_data.get('f43', 0.0) / 100  # 转换为元
        change_percent = stock_data.get('f44', 0.0)
        change = stock_data.get('f45', 0.0) / 100
        volume = stock_data.get('f46', 0)
        turnover = stock_data.get('f47', 0.0)
        market_cap = stock_data.get('f48', 0.0)
        pe = stock_data.get('f49', 0.0)
        pb = stock_data.get('f50', 0.0)
        
        return Quote(
            symbol=symbol,
            price=price,
            change=change,
            change_percent=change_percent,
            volume=volume,
            turnover=turnover,
            market_cap=market_cap,
            pe=pe,
            pb=pb,
            high=0.0,  # 东方财富字段映射复杂，暂不解析
            low=0.0,
            open=0.0,
            prev_close=0.0,
            source='eastmoney',
            timestamp=datetime.now(),
        )
    
    except requests.RequestException as e:
        raise ProviderError('eastmoney', f'请求失败：{e}')
    except (KeyError, ValueError, TypeError) as e:
        raise ProviderError('eastmoney', f'解析数据失败：{e}')


def fetch_eastmoney_financials(symbol: str, timeout: int = 5) -> Financials:
    """
    获取东方财富财报数据
    
    Args:
        symbol: 股票代码
        timeout: 超时时间（秒）
    
    Returns:
        Financials 对象
    """
    secucode = convert_to_eastmoney_secucode(symbol)
    
    url = "https://datacenter.eastmoney.com/securities/api/data/get"
    params = {
        'type': 'RPT_F10_FINANCE_MAINFINADATA',
        'source': 'HSSF10',
        'client_pc': '1',
        'secucode': secucode,
        'fields': 'SECUCODE,SECURITY_CODE,REPORT_DATE,EPS,OPERATE_INCOME,NET_PROFIT,ROE,DEBT_RATIO,GROSS_MARGIN,NET_MARGIN',
        'st': 'REPORT_DATE',
        'sr': '-1',
        'start': '0',
        'limit': '4',  # 获取最近 4 期
    }
    
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        
        if not data.get('result') or not data['result'].get('data'):
            raise ProviderError('eastmoney', '返回数据为空')
        
        # 获取最新一期财报
        latest = data['result']['data'][0]
        
        # 解析数据
        report_date = latest.get('REPORT_DATE', '')
        eps = float(latest.get('EPS', 0) or 0)
        revenue = float(latest.get('OPERATE_INCOME', 0) or 0)
        net_profit = float(latest.get('NET_PROFIT', 0) or 0)
        roe = float(latest.get('ROE', 0) or 0)
        debt_ratio = float(latest.get('DEBT_RATIO', 0) or 0)
        gross_margin = float(latest.get('GROSS_MARGIN', 0) or 0)
        net_margin = float(latest.get('NET_MARGIN', 0) or 0)
        
        return Financials(
            symbol=symbol,
            report_date=report_date,
            revenue=revenue,
            net_profit=net_profit,
            roe=roe,
            eps=eps,
            debt_ratio=debt_ratio,
            gross_margin=gross_margin,
            net_margin=net_margin,
            operating_cash_flow=0.0,  # 需要额外接口获取
            source='eastmoney',
            timestamp=datetime.now(),
        )
    
    except requests.RequestException as e:
        raise ProviderError('eastmoney', f'请求失败：{e}')
    except (KeyError, ValueError, TypeError, IndexError) as e:
        raise ProviderError('eastmoney', f'解析数据失败：{e}')
