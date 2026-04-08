"""
腾讯财经 API

无需 API Key，实时数据
接口：http://qt.gtimg.cn/
"""

import re
import requests
from typing import List
from datetime import datetime
from ..core import Quote
from ..exceptions import ProviderError


def convert_to_tencent_code(symbol: str) -> str:
    """
    转换股票代码为腾讯格式
    
    Args:
        symbol: 股票代码（如：600519.SH, 000001.SZ）
    
    Returns:
        腾讯格式代码（如：sh600519, sz000001）
    """
    symbol = symbol.upper().strip()
    
    # 处理指数
    if symbol == '000001.SH':
        return 's_sh000001'
    elif symbol == '399001.SZ':
        return 's_sz399001'
    elif symbol == '399006.SZ':
        return 's_sz399006'
    
    # 处理个股
    if '.SH' in symbol:
        code = symbol.replace('.SH', '')
        return f'sh{code}'
    elif '.SZ' in symbol:
        code = symbol.replace('.SZ', '')
        return f'sz{code}'
    else:
        # 假设是 A 股
        return f'sh{symbol}' if symbol.startswith('6') else f'sz{symbol}'


def parse_tencent_quote_text(text: str, symbol: str) -> dict:
    """
    解析腾讯行情数据（非 JSON 格式）
    
    格式：v_sh600519="51~贵州茅台~600519~1392.00~104.00~8.10~..."
    
    字段说明：
    0: 状态
    1: 名称
    2: 代码
    3: 当前价
    4: 涨跌额
    5: 涨跌幅
    6: 成交量
    7: 成交额
    8: 最高
    9: 最低
    10: 开盘
    11: 昨收
    """
    pattern = r'v_(.*?)="(.*?)"'
    matches = re.findall(pattern, text)
    
    if not matches:
        raise ProviderError('tencent', '无法解析行情数据')
    
    for code, data in matches:
        fields = data.split('~')
        
        if len(fields) < 12:
            continue
        
        # 提取数据
        try:
            price = float(fields[3]) if fields[3] else 0.0
            change = float(fields[4]) if fields[4] else 0.0
            change_percent = float(fields[5]) if fields[5] else 0.0
            volume = int(float(fields[6])) if fields[6] else 0
            turnover = float(fields[7]) if fields[7] else 0.0
            high = float(fields[8]) if fields[8] else 0.0
            low = float(fields[9]) if fields[9] else 0.0
            open_price = float(fields[10]) if fields[10] else 0.0
            prev_close = float(fields[11]) if fields[11] else 0.0
            
            return {
                'symbol': symbol,
                'price': price,
                'change': change,
                'change_percent': change_percent,
                'volume': volume,
                'turnover': turnover,
                'market_cap': 0.0,  # 腾讯不提供市值
                'pe': 0.0,  # 腾讯不提供 PE
                'pb': 0.0,  # 腾讯不提供 PB
                'high': high,
                'low': low,
                'open': open_price,
                'prev_close': prev_close,
                'source': 'tencent',
                'timestamp': datetime.now().isoformat(),
            }
        except (ValueError, IndexError) as e:
            raise ProviderError('tencent', f'解析数据失败：{e}')
    
    raise ProviderError('tencent', '未找到匹配的数据')


def fetch_tencent_quote(symbol: str, timeout: int = 5) -> Quote:
    """
    获取腾讯财经行情
    
    Args:
        symbol: 股票代码
        timeout: 超时时间（秒）
    
    Returns:
        Quote 对象
    """
    tencent_code = convert_to_tencent_code(symbol)
    url = f"http://qt.gtimg.cn/q={tencent_code}"
    
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        
        # 检查返回内容
        if not response.text.strip():
            raise ProviderError('tencent', '返回空数据')
        
        data = parse_tencent_quote_text(response.text, symbol)
        return Quote.from_dict(data)
    
    except requests.RequestException as e:
        raise ProviderError('tencent', f'请求失败：{e}')


def fetch_tencent_indices(symbols: List[str], timeout: int = 5) -> List[Quote]:
    """
    获取腾讯财经大盘指数
    
    Args:
        symbols: 指数代码列表
        timeout: 超时时间（秒）
    
    Returns:
        Quote 对象列表
    """
    # 转换为腾讯代码
    tencent_codes = [convert_to_tencent_code(s) for s in symbols]
    url = f"http://qt.gtimg.cn/q={','.join(tencent_codes)}"
    
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        
        quotes = []
        
        # 解析每个指数
        pattern = r'v_(.*?)="(.*?)"'
        matches = re.findall(pattern, response.text)
        
        symbol_map = {
            's_sh000001': '000001.SH',
            's_sz399001': '399001.SZ',
            's_sz399006': '399006.SZ',
        }
        
        for code, data in matches:
            fields = data.split('~')
            
            if len(fields) < 12:
                continue
            
            symbol = symbol_map.get(code, code)
            
            try:
                price = float(fields[3]) if fields[3] else 0.0
                change = float(fields[4]) if fields[4] else 0.0
                change_percent = float(fields[5]) if fields[5] else 0.0
                
                quote = Quote(
                    symbol=symbol,
                    price=price,
                    change=change,
                    change_percent=change_percent,
                    volume=0,
                    turnover=0.0,
                    market_cap=0.0,
                    pe=0.0,
                    pb=0.0,
                    high=0.0,
                    low=0.0,
                    open=0.0,
                    prev_close=0.0,
                    source='tencent',
                    timestamp=datetime.now(),
                )
                quotes.append(quote)
            except (ValueError, IndexError):
                continue
        
        return quotes
    
    except requests.RequestException as e:
        raise ProviderError('tencent', f'请求失败：{e}')
