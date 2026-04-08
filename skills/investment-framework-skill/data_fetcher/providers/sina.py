"""
新浪财经 API

无需 API Key，实时数据
接口：http://hq.sinajs.cn/
"""

import re
import requests
from typing import List
from datetime import datetime
from ..core import Quote
from ..exceptions import ProviderError


def convert_to_sina_code(symbol: str) -> str:
    """
    转换股票代码为新浪格式
    
    Args:
        symbol: 股票代码
    
    Returns:
        新浪格式代码
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
        return f'sh{symbol}' if symbol.startswith('6') else f'sz{symbol}'


def parse_sina_quote_text(text: str, symbol: str) -> dict:
    """
    解析新浪行情数据
    
    格式：var hq_str_sh600519="贵州茅台，1392.00,1288.00,..."
    
    字段说明：
    0: 名称
    1: 开盘
    2: 昨收
    3: 当前价
    4: 最高
    5: 最低
    6: 买一价
    7: 卖一价
    8: 成交量
    9: 成交额
    """
    pattern = r'var hq_str_(.*?)="(.*?)"'
    matches = re.findall(pattern, text)
    
    if not matches:
        raise ProviderError('sina', '无法解析行情数据')
    
    for code, data in matches:
        fields = data.split(',')
        
        if len(fields) < 10:
            continue
        
        try:
            open_price = float(fields[1]) if fields[1] else 0.0
            prev_close = float(fields[2]) if fields[2] else 0.0
            price = float(fields[3]) if fields[3] else 0.0
            high = float(fields[4]) if fields[4] else 0.0
            low = float(fields[5]) if fields[5] else 0.0
            volume = int(float(fields[8])) if fields[8] else 0
            turnover = float(fields[9]) if fields[9] else 0.0
            
            change = price - prev_close
            change_percent = (change / prev_close * 100) if prev_close > 0 else 0.0
            
            return {
                'symbol': symbol,
                'price': price,
                'change': change,
                'change_percent': change_percent,
                'volume': volume,
                'turnover': turnover,
                'market_cap': 0.0,
                'pe': 0.0,
                'pb': 0.0,
                'high': high,
                'low': low,
                'open': open_price,
                'prev_close': prev_close,
                'source': 'sina',
                'timestamp': datetime.now().isoformat(),
            }
        except (ValueError, IndexError) as e:
            raise ProviderError('sina', f'解析数据失败：{e}')
    
    raise ProviderError('sina', '未找到匹配的数据')


def fetch_sina_quote(symbol: str, timeout: int = 5) -> Quote:
    """
    获取新浪财经行情
    
    Args:
        symbol: 股票代码
        timeout: 超时时间（秒）
    
    Returns:
        Quote 对象
    """
    sina_code = convert_to_sina_code(symbol)
    url = f"http://hq.sinajs.cn/list={sina_code}"
    
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        
        if not response.text.strip():
            raise ProviderError('sina', '返回空数据')
        
        data = parse_sina_quote_text(response.text, symbol)
        return Quote.from_dict(data)
    
    except requests.RequestException as e:
        raise ProviderError('sina', f'请求失败：{e}')


def fetch_sina_indices(symbols: List[str], timeout: int = 5) -> List[Quote]:
    """
    获取新浪财经大盘指数
    
    Args:
        symbols: 指数代码列表
        timeout: 超时时间（秒）
    
    Returns:
        Quote 对象列表
    """
    sina_codes = [convert_to_sina_code(s) for s in symbols]
    url = f"http://hq.sinajs.cn/list={','.join(sina_codes)}"
    
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        
        quotes = []
        
        pattern = r'var hq_str_(.*?)="(.*?)"'
        matches = re.findall(pattern, response.text)
        
        symbol_map = {
            's_sh000001': '000001.SH',
            's_sz399001': '399001.SZ',
            's_sz399006': '399006.SZ',
        }
        
        for code, data in matches:
            fields = data.split(',')
            
            if len(fields) < 4:
                continue
            
            symbol = symbol_map.get(code, code)
            
            try:
                open_price = float(fields[1]) if fields[1] else 0.0
                prev_close = float(fields[2]) if fields[2] else 0.0
                price = float(fields[3]) if fields[3] else 0.0
                
                change = price - prev_close
                change_percent = (change / prev_close * 100) if prev_close > 0 else 0.0
                
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
                    open=open_price,
                    prev_close=prev_close,
                    source='sina',
                    timestamp=datetime.now(),
                )
                quotes.append(quote)
            except (ValueError, IndexError):
                continue
        
        return quotes
    
    except requests.RequestException as e:
        raise ProviderError('sina', f'请求失败：{e}')
