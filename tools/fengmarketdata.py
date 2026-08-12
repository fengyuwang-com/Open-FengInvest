#!/usr/bin/env python3
"""fengmarketdata — Comprehensive market data for value investing dashboard.

Fetches multiple data types from Futu in one shot, outputs a single JSON.
Designed for the Web UI market page.

Usage:
    python tools/fengmarketdata.py

Output sections (when available):
    - indices:      Major index quotes
    - valuation:    Index PE/PB percentiles (HSI)
    - top_movers:   Gainers/losers (HK + US)
    - breadth:      Rise/fall distribution
    - fedwatch:     Fed rate probabilities
    - sectors_hk:   HK industry performance
    - sectors_us:   US industry performance
"""
import json, os, sys, traceback, logging
from datetime import datetime

# Suppress Futu SDK logging (goes to stdout, corrupts JSON output)
logging.getLogger('futu').setLevel(logging.ERROR)
for h in logging.getLogger().handlers:
    h.setLevel(logging.ERROR)
logging.basicConfig(level=logging.ERROR)

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "tools"))


def _ctx():
    from futu import OpenQuoteContext
    return OpenQuoteContext(host='127.0.0.1', port=11111)


def _sf(v):
    """Safe float."""
    if v is None:
        return None
    try:
        fv = float(v)
        import math
        if math.isnan(fv) or math.isinf(fv):
            return None
        return fv
    except (ValueError, TypeError):
        return None


def _g(row, key, default=None):
    """Get value from row (DataFrame row or dict)."""
    if hasattr(row, 'get'):
        return row.get(key, default)
    return getattr(row, key, default)


def fetch_indices():
    """Major index quotes."""
    from futu import RET_OK
    indices = {
        'HK.800000': '恒生指数',
        'HK.800700': '恒生科技',
        'HK.800100': '国企指数',
        'HK.800122': '沪深300',
        'US.SPY': 'S&P 500 (SPY)',
        'US.QQQ': 'Nasdaq 100',
    }
    result = {}
    try:
        ctx = _ctx()
        try:
            for code, name in indices.items():
                ret, snap = ctx.get_market_snapshot([code])
                if ret == RET_OK and snap is not None and not snap.empty:
                    row = snap.iloc[0]
                    result[code] = {
                        'name': name, 'code': code,
                        'price': _sf(_g(row, 'last_price')),
                        'change_pct': round(((_sf(_g(row, 'last_price')) or 0) / (_sf(_g(row, 'prev_close_price')) or 1) - 1) * 100, 2) if _sf(_g(row, 'prev_close_price')) else None,
                        'high': _sf(_g(row, 'high_price')),
                        'low': _sf(_g(row, 'low_price')),
                        'volume': _sf(_g(row, 'volume')),
                        'turnover': _sf(_g(row, 'turnover')),
                        'pe': _sf(_g(row, 'pe_ttm_ratio')),
                        'pb': _sf(_g(row, 'pb_ratio')),
                        'update_time': str(_g(row, 'update_time', '')),
                    }
        finally:
            ctx.close()
    except Exception as e:
        result['_error'] = str(e)[:100]
    return result


def fetch_valuation():
    """Index PE/PB percentile."""
    from futu import RET_OK
    result = {}
    try:
        ctx = _ctx()
        try:
            for vtype, vname in [(1, 'pe'), (2, 'pb'), (3, 'ps')]:
                try:
                    ret, data = ctx.get_valuation_detail('HK.800000', valuation_type=vtype, interval_type=6)  # 5 years
                    if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                        row = data.iloc[0] if hasattr(data, 'iloc') else data
                        tr = _g(row, 'trend', {})
                        if isinstance(tr, dict):
                            result[f'hsi_{vname}_current'] = _sf(tr.get('current_value'))
                            result[f'hsi_{vname}_avg'] = _sf(tr.get('average_value'))
                            result[f'hsi_{vname}_percentile'] = _sf(tr.get('valuation_percentile'))
                except Exception:
                    pass
        finally:
            ctx.close()
    except Exception:
        pass
    return result


def fetch_top_movers():
    """Gainers and losers for HK and US."""
    from futu import RET_OK
    result = {'hk': {}, 'us': {}}
    try:
        ctx = _ctx()
        try:
            for market, key in [('HK', 'hk'), ('US', 'us')]:
                try:
                    ret_top, top_data = ctx.get_top_movers_rank(market=market, sort_dir='DESC', count=5)
                    if ret_top == RET_OK and top_data is not None and not (hasattr(top_data, 'empty') and top_data.empty):
                        result[key]['gainers'] = []
                        for _, r in top_data.iterrows():
                            nm = str(_g(r, 'code', ''))
                            if len(result[key]['gainers']) < 5 and nm not in {x['code'] for x in result[key]['gainers']}:
                                result[key]['gainers'].append({
                                    'code': nm,
                                    'name': str(_g(r, 'name', ''))[:20],
                                    'price': _sf(_g(r, 'last_price', _g(r, 'price', 0))),
                                    'change_pct': _sf(_g(r, 'change_rate', _g(r, 'change_pct', 0))),
                                    'volume': _sf(_g(r, 'volume', 0)),
                                })
                except Exception as e:
                    pass
                try:
                    ret_bot, bot_data = ctx.get_top_movers_rank(market=market, sort_dir='ASC', count=5)
                    if ret_bot == RET_OK and bot_data is not None and not (hasattr(bot_data, 'empty') and bot_data.empty):
                        result[key]['losers'] = []
                        for _, r in bot_data.iterrows():
                            nm = str(_g(r, 'code', ''))
                            if len(result[key]['losers']) < 5 and nm not in {x['code'] for x in result[key]['losers']}:
                                result[key]['losers'].append({
                                    'code': nm,
                                    'name': str(_g(r, 'name', ''))[:20],
                                    'price': _sf(_g(r, 'last_price', _g(r, 'price', 0))),
                                    'change_pct': _sf(_g(r, 'change_rate', _g(r, 'change_pct', 0))),
                                    'volume': _sf(_g(r, 'volume', 0)),
                                })
                except Exception as e:
                    pass
        finally:
            ctx.close()
    except Exception:
        pass
    return result


def fetch_breadth():
    """Market rise/fall distribution."""
    from futu import RET_OK
    result = {}
    try:
        ctx = _ctx()
        try:
            for market in ['HK', 'US']:
                try:
                    ret, data = ctx.get_rise_fall_distribution(market=market)
                    if ret == RET_OK and data is not None:
                        if hasattr(data, 'empty') and not data.empty:
                            row = data.iloc[0]
                            result[market.lower()] = {
                                'rise': _sf(_g(row, 'rise_count')) or _sf(_g(row, 'raise_count')),
                                'fall': _sf(_g(row, 'fall_count')),
                                'equal': _sf(_g(row, 'equal_count')),
                            }
                except Exception:
                    pass
        finally:
            ctx.close()
    except Exception:
        pass
    return result


def fetch_fedwatch():
    """Fed rate probabilities."""
    from futu import RET_OK
    result = {}
    try:
        ctx = _ctx()
        try:
            ret, data = ctx.get_fed_watch_target_rate()
            if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                # data is a DataFrame with columns for each meeting
                for c in data.columns:
                    result[c] = _sf(data[c].iloc[0]) if hasattr(data, 'iloc') else _sf(data[c])
                result['_meetings'] = [str(c) for c in data.columns]
        except Exception:
            pass
        ctx.close()
    except Exception:
        pass
    return result


def fetch_sectors():
    """HK industry sector performance top 10."""
    from futu import RET_OK
    result = {}
    try:
        ctx = _ctx()
        try:
            ret, data = ctx.get_heat_map_data(market='HK', sort_field='CHANGE_RATE', count=10, plate_type='INDUSTRY')
            if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                sectors = []
                for _, r in data.iterrows():
                    sectors.append({
                        'name': str(r.get('plate_name', r.get('name', '?')))[:20],
                        'change_pct': _sf(r.get('change_rate', r.get('change_pct', 0))),
                        'market_val': _sf(r.get('market_val', 0)),
                    })
                result['hk_top'] = sectors
        except Exception:
            pass

        ret, data = ctx.get_heat_map_data(market='US', sort_field='CHANGE_RATE', count=10, plate_type='INDUSTRY')
        if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
            sectors = []
            for _, r in data.iterrows():
                sectors.append({
                    'name': str(r.get('plate_name', r.get('name', '?')))[:20],
                    'change_pct': _sf(r.get('change_rate', r.get('change_pct', 0))),
                    'market_val': _sf(r.get('market_val', 0)),
                })
            result['us_top'] = sectors
        ctx.close()
    except Exception:
        pass
    return result


def fetch_dividend_leaders():
    """High dividend yield leaders."""
    from futu import RET_OK
    result = []
    try:
        ctx = _ctx()
        try:
            for market in ['HK', 'US']:
                ret, data = ctx.get_dividend_rank(market=market, rank_type='HIGH_YIELD', count=10)
                if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                    for _, r in data.iterrows():
                        result.append({
                            'market': market,
                            'code': str(r.get('code', '?'))[:12],
                            'name': str(r.get('name', ''))[:16],
                            'yield': _sf(r.get('dividend_yield_ttm', r.get('dividend_yield', 0))),
                            'price': _sf(r.get('price', 0)),
                        })
        except Exception:
            pass
        ctx.close()
    except Exception:
        pass
    return result[:15]


def fetch_ipos():
    """Recent IPO list."""
    from futu import RET_OK
    result = []
    try:
        ctx = _ctx()
        try:
            ret, data = ctx.get_ipo_list()
            if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                for _, r in data.iterrows():
                    result.append({
                        'code': str(r.get('code', '?'))[:12],
                        'name': str(r.get('name', '?'))[:20],
                        'price': _sf(r.get('price', 0)),
                        'market': str(r.get('market', r.get('sec_type', '')))[:6],
                    })
        except Exception:
            pass
        ctx.close()
    except Exception:
        pass
    return result[:10]


def fetch_rating_changes():
    """Recent analyst rating changes (US only)."""
    from futu import RET_OK
    result = {'upgrades': [], 'downgrades': []}
    try:
        ctx = _ctx()
        try:
            ret, data = ctx.get_rating_change(market='US', change_type='UPGRADE', count=8)
            if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                for _, r in data.iterrows():
                    result['upgrades'].append({
                        'code': str(r.get('code', '?'))[:12],
                        'name': str(r.get('name', '?'))[:16],
                        'target': _sf(r.get('target_price', r.get('price', 0))),
                    })
        except Exception:
            pass
        try:
            ret, data = ctx.get_rating_change(market='US', change_type='DOWNGRADE', count=8)
            if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                for _, r in data.iterrows():
                    result['downgrades'].append({
                        'code': str(r.get('code', '?'))[:12],
                        'name': str(r.get('name', '?'))[:16],
                        'target': _sf(r.get('target_price', r.get('price', 0))),
                    })
        except Exception:
            pass
        ctx.close()
    except Exception:
        pass
    return result


def fetch_value_picks():
    """Value picks: low PE + high ROE via stock filter."""
    from futu import RET_OK
    result = {'hk': [], 'us': []}
    try:
        ctx = _ctx()
        try:
            ret, data = ctx.get_stock_filter(market='HK', filter_list=[], sort='pe', ascend=True, num=10)
            if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                for _, r in data.iterrows():
                    pe = _sf(r.get('pe', r.get('pe_ratio', 0)))
                    if pe and pe > 0:
                        result['hk'].append({
                            'code': str(r.get('code', '?'))[:12],
                            'name': str(r.get('name', ''))[:16],
                            'pe': pe,
                            'price': _sf(r.get('price', 0)),
                        })
        except Exception:
            pass
        try:
            ret, data = ctx.get_stock_filter(market='US', filter_list=[], sort='pe', ascend=True, num=10)
            if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                for _, r in data.iterrows():
                    pe = _sf(r.get('pe', r.get('pe_ratio', 0)))
                    if pe and pe > 0:
                        result['us'].append({
                            'code': str(r.get('code', '?'))[:12],
                            'name': str(r.get('name', ''))[:16],
                            'pe': pe,
                            'price': _sf(r.get('price', 0)),
                        })
        except Exception:
            pass
        ctx.close()
    except Exception:
        pass
    return result


def _quick_ctx():
    """Create a short-lived context with per-call timeout."""
    from futu import OpenQuoteContext
    return OpenQuoteContext(host='127.0.0.1', port=11111)

def _try(fn, timeout=8):
    """Run fn with a simple try/except, return None on failure."""
    try:
        return fn()
    except Exception:
        return None


def fetch_sectors():
    """Sector performance via heat map (HK industry plates)."""
    from futu import RET_OK
    result = {}
    try:
        ctx = _quick_ctx()
        try:
            ret, data = ctx.get_heat_map_data(market='HK', sort_field='CHANGE_RATE', count=8, plate_type='INDUSTRY')
            if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                result['hk'] = [{'name': str(r.get('plate_name','?'))[:16], 'change': _sf(r.get('change_rate',0))} for _, r in data.iterrows()]
        except: pass
        try:
            ret, data = ctx.get_heat_map_data(market='US', sort_field='CHANGE_RATE', count=8, plate_type='INDUSTRY')
            if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                result['us'] = [{'name': str(r.get('plate_name','?'))[:16], 'change': _sf(r.get('change_rate',0))} for _, r in data.iterrows()]
        except: pass
        ctx.close()
    except: pass
    return result


def fetch_ipos():
    """Recent IPO list (HK)."""
    from futu import RET_OK
    result = []
    try:
        ctx = _quick_ctx()
        try:
            ret, data = ctx.get_ipo_list()
            if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                for _, r in data.iterrows():
                    result.append({'code': str(r.get('code',''))[:12], 'name': str(r.get('name',''))[:16], 'price': _sf(r.get('price',0))})
        except: pass
        ctx.close()
    except: pass
    return result[:10]


def fetch_economic_calendar():
    """Upcoming economic events."""
    from futu import RET_OK
    result = []
    try:
        ctx = _ctx()
        from datetime import date, timedelta
        today = date.today().isoformat()
        next_week = (date.today() + timedelta(days=14)).isoformat()
        try:
            ret, data = ctx.get_economic_calendar(begin_date=today, end_date=next_week, importance='HIGH', count=15)
            if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                for _, r in data.iterrows() if hasattr(data, 'iterrows') else []:
                    result.append({
                        'date': str(_g(r, ('date', 'begin_date', 'time'), ''))[:10],
                        'event': str(_g(r, ('event', 'title', 'name'), '?'))[:40],
                        'country': str(_g(r, ('country', 'market', 'region'), '')),
                        'importance': str(_g(r, 'importance', '')),
                    })
        except Exception:
            pass
        ctx.close()
    except Exception:
        pass
    return result[:15]


def main():
    result = {
        'fetched_at': datetime.now().isoformat(),
        '_warnings': ['⚠️ S&P 500 使用 SPY ETF 作为代理（Futu 无直接指数代码）'],
    }

    print("[*] Fetching indices...", file=sys.stderr)
    result['indices'] = fetch_indices()

    print("[*] Fetching valuation...", file=sys.stderr)
    result['valuation'] = fetch_valuation()

    print("[*] Fetching top movers...", file=sys.stderr)
    result['top_movers'] = fetch_top_movers()

    print("[*] Fetching breadth...", file=sys.stderr)
    result['breadth'] = fetch_breadth()

    print("[*] Fetching FedWatch...", file=sys.stderr)
    result['fedwatch'] = fetch_fedwatch()

    print("[*] Fetching sectors...", file=sys.stderr)
    result['sectors'] = _try(fetch_sectors)

    print("[*] Fetching IPOs...", file=sys.stderr)
    result['ipos'] = _try(fetch_ipos)

    print("[*] Fetching economic calendar...", file=sys.stderr)
    result['economic_calendar'] = fetch_economic_calendar()

    # Clean None values
    result = {k: v for k, v in result.items() if v}

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
