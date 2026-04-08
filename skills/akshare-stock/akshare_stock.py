"""
A 股数据获取模块 (akshare_stock.py)
====================================
主力: Baostock (个股K线) + AkShare (指数)
Fallback: AkShare 新浪
"""

import warnings
warnings.filterwarnings('ignore')

import json
import sys
import io
import time
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd


def _bs_code(symbol):
    symbol = symbol.strip()
    return f"sh.{symbol}" if symbol.startswith(('6', '9')) else f"sz.{symbol}"


def _ak_code(symbol):
    symbol = symbol.strip()
    if '.' in symbol:
        return symbol
    return f"sh.{symbol}" if symbol.startswith(('6', '9')) else f"sz.{symbol}"


def _norm(d):
    return d.replace('-', '') if d and '-' in d else (d or '')


def _mute():
    old = sys.stdout
    sys.stdout = io.StringIO()
    return old


def _unmute(old):
    sys.stdout = old


# ===========================================================================
# Baostock — PRIMARY for stock daily K-line
# ===========================================================================

def baostock_kline(symbol, start_date="", end_date="", adjust="qfq"):
    try:
        import baostock as bs
    except ImportError:
        return None

    code = _bs_code(symbol)
    sd = _norm(start_date) or "20200101"
    ed = _norm(end_date) or datetime.now().strftime("%Y%m%d")
    if len(sd) < 8 or len(ed) < 8:
        return None

    sd_f = f"{sd[:4]}-{sd[4:6]}-{sd[6:]}"
    ed_f = f"{ed[:4]}-{ed[4:6]}-{ed[6:]}"
    adj_map = {'': '3', 'qfq': '2', 'hfq': '1'}

    old = _mute()
    try:
        lg = bs.login()
        if lg.error_code != '0':
            _unmute(old)
            return None
        rs = bs.query_history_k_data_plus(
            code, 'date,code,open,high,low,close,volume',
            start_date=sd_f, end_date=ed_f,
            adjustflag=adj_map.get(adjust, '3'),
        )
        bs.logout()
    finally:
        _unmute(old)

    if rs.error_code != '0':
        return None

    data = []
    while (rs.error_code == '0') and rs.next():
        data.append(rs.get_row_data())
    if not data:
        return None

    df = pd.DataFrame(data, columns=rs.fields)
    df = df.rename(columns={
        'date': '日期', 'open': '开盘', 'high': '最高',
        'low': '最低', 'close': '收盘', 'volume': '成交量'
    })
    for c in ['开盘', '最高', '最低', '收盘', '成交量']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    keep = ['日期', '开盘', '最高', '最低', '收盘', '成交量']
    avail = [c for c in keep if c in df.columns]
    return df[avail].sort_values('日期').reset_index(drop=True) if avail else None


# ===========================================================================
# AkShare — for index
# ===========================================================================

def akshare_index(symbol="sh000001", start_date="", end_date=""):
    try:
        import akshare as ak
    except ImportError:
        return None

    ak_sym = symbol
    if '.' not in symbol and len(symbol) == 6:
        ak_sym = "sh" + symbol

    sd = _norm(start_date) or "20200101"
    ed = _norm(end_date) or datetime.now().strftime("%Y%m%d")

    old = _mute()
    try:
        df = ak.stock_zh_index_daily(symbol=ak_sym)
    finally:
        _unmute(old)

    if df is None or df.empty:
        return None

    df = df.rename(columns={
        'date': '日期', 'open': '开盘', 'high': '最高',
        'low': '最低', 'close': '收盘', 'volume': '成交量'
    })
    keep = ['日期', '开盘', '最高', '最低', '收盘', '成交量']
    avail = [c for c in keep if c in df.columns]
    if avail:
        df = df[avail]
    if sd:
        df = df[df['日期'].astype(str).str.replace('-', '') >= sd]
    if ed:
        df = df[df['日期'].astype(str).str.replace('-', '') <= ed]
    return df.sort_values('日期').reset_index(drop=True)


def akshare_stock_daily(symbol, start_date="", end_date="", adjust="qfq"):
    """AkShare新浪源 (fallback)"""
    try:
        import akshare as ak
    except ImportError:
        return None

    ak_sym = _ak_code(symbol)
    sd = _norm(start_date) or "20200101"
    ed = _norm(end_date) or datetime.now().strftime("%Y%m%d")

    old = _mute()
    try:
        df = ak.stock_zh_a_daily(
            symbol=ak_sym, start_date=sd, end_date=ed, adjust=adjust
        )
    finally:
        _unmute(old)

    if df is None or df.empty:
        return None
    if 'date' not in df.columns:
        return None

    df = df.rename(columns={
        'date': '日期', 'open': '开盘', 'high': '最高',
        'low': '最低', 'close': '收盘', 'volume': '成交量'
    })
    keep = ['日期', '开盘', '最高', '最低', '收盘', '成交量']
    avail = [c for c in keep if c in df.columns]
    if avail:
        df = df[avail]
    return df.sort_values('日期').reset_index(drop=True)


# ===========================================================================
# 实时行情 (Sina)
# ===========================================================================

_SINA_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'


def get_spot_quotes(top_n=50, max_retries=3):
    url = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
    params = {
        'page': '1', 'num': str(min(top_n, 80)), 'sort': 'changepercent',
        'asc': '0', 'node': 'hs_a', '_s_r_a': 'auto',
    }
    full_url = f"{url}?{urllib.parse.urlencode(params)}"

    items = None
    for i in range(max_retries):
        try:
            time.sleep(0.3 * i)
            req = urllib.request.Request(full_url, headers={
                'User-Agent': _SINA_UA,
                'Referer': 'https://finance.sina.com.cn/stock/',
                'Accept': 'application/json, text/javascript, */*',
            })
            resp = urllib.request.urlopen(req, timeout=15)
            items = json.loads(resp.read().decode('gbk'))
            break
        except Exception:
            if i >= max_retries - 1:
                raise
            time.sleep(1 + i)

    if not items:
        return pd.DataFrame()

    rows = []
    for item in items:
        rows.append({
            '代码': item.get('code', ''),
            '名称': item.get('name', ''),
            '最新价': item.get('trade', ''),
            '涨跌额': item.get('pricechange', ''),
            '涨跌幅': item.get('changepercent', ''),
            '开盘价': item.get('open', ''),
            '最高价': item.get('high', ''),
            '最低价': item.get('low', ''),
            '昨收': item.get('settlement', ''),
            '成交量': item.get('volume', ''),
            '成交额': item.get('turnover', ''),
            '市盈率': item.get('pe', ''),
        })
    df = pd.DataFrame(rows)
    for col in ['最新价', '涨跌额', '涨跌幅', '开盘价', '最高价', '最低价', '昨收', '市盈率']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df.head(top_n)


def get_index_hist(symbol="sh000001", start_date="", end_date=""):
    df = akshare_index(symbol, start_date, end_date)
    if df is not None and not df.empty:
        return df
    return pd.DataFrame()


# ===========================================================================
# 高层接口
# ===========================================================================

def get_stock_hist(symbol, start_date="", end_date="", adjust="qfq"):
    sd = start_date or "20200101"
    ed = end_date or datetime.now().strftime("%Y%m%d")

    # Layer 1: Baostock
    df = baostock_kline(symbol, sd, ed, adjust)
    if df is not None and not df.empty:
        return df, 'baostock'

    # Layer 2: AkShare sina
    time.sleep(0.5)
    df = akshare_stock_daily(symbol, sd, ed, adjust)
    if df is not None and not df.empty:
        return df, 'akshare_sina'

    return None, 'none'


# ===========================================================================
# 自检
# ===========================================================================

def _self_test():
    print("=" * 50)
    print("akshare_stock 数据源自检")
    print("=" * 50)
    results = {}

    print("\n[1/4] Baostock (000001)...")
    try:
        df = baostock_kline("000001", "20260101", "20260404")
        ok = df is not None and not df.empty
        results['baostock'] = '✅' if ok else '⚠️'
        print(f"  {results['baostock']} {len(df) if df is not None else 0} records")
        if ok:
            print(df.tail(2).to_string(index=False))
    except Exception as e:
        results['baostock'] = f'❌ {e}'
        print(f"  {results['baostock']}")

    print("\n[2/4] A股实时行情 (前5)...")
    try:
        df = get_spot_quotes(top_n=5)
        ok = not df.empty
        results['spot'] = '✅' if ok else '⚠️'
        print(f"  {results['spot']} {len(df)} stocks")
        if ok:
            cols = [c for c in ['代码', '名称', '最新价', '涨跌幅'] if c in df.columns]
            print(df[cols].to_string(index=False))
    except Exception as e:
        results['spot'] = f'❌ {e}'
        print(f"  {results['spot']}")

    print("\n[3/4] AkShare指数 (sh000001)...")
    try:
        df = akshare_index("sh000001", "20260101", "20260404")
        ok = df is not None and not df.empty
        results['akshare'] = '✅' if ok else '⚠️'
        print(f"  {results['akshare']} {len(df) if df is not None else 0} records")
        if ok:
            print(df.tail(2).to_string(index=False))
    except Exception as e:
        results['akshare'] = f'❌ {e}'
        print(f"  {results['akshare']}")

    print("\n[4/4] 高层接口 get_stock_hist (600519)...")
    try:
        df, src = get_stock_hist("600519", "20260301", "20260404")
        ok = df is not None and not df.empty
        results['hist_api'] = '✅' if ok else '⚠️'
        print(f"  {results['hist_api']} source={src}, {len(df) if df is not None else 0} records")
        if ok:
            print(df.tail(2).to_string(index=False))
    except Exception as e:
        results['hist_api'] = f'❌ {e}'
        print(f"  {results['hist_api']}")

    print("\n" + "=" * 50)
    for k, v in results.items():
        print(f"  {k}: {v}")
    print("=" * 50)


if __name__ == "__main__":
    _self_test()
