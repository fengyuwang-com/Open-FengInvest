#!/usr/bin/env python3
"""
verify-039-cheaper-switch.py

Investment Claim #39: "A new stock must be at least 2x more undervalued
than current holdings to be worth switching to"

Methodology:
1. Price/52-week-high ratio as cheapness proxy (lower = more undervalued)
2. Monthly simulation: for each month-end, rank US stocks by cheapness
3. "Holdings" = stocks in valuation deciles 5-10 (fair to expensive)
4. For each threshold T (1.0x, 1.5x, 2.0x, 3.0x), find candidates T times cheaper
5. Compare forward 6-month returns of switching (buy cheapest qualifying candidate)
   vs. holding the original stock
6. Determine which threshold(s) produce better switching outcomes

Two variants: (a) no filter, (b) trailing_pe < 50 filter (excludes extreme valuations)

Database: market_data.db
  indices(id, ticker, name, market, category)  -- PK is id
  daily_data(id, index_id, date, open, high, low, close, ...)
  fundamentals(index_id, trailing_pe, ...)
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict, deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'market_data.db')
RESULTS_FILE = os.path.join(SCRIPT_DIR, 'results.json')

THRESHOLDS = [1.0, 1.5, 2.0, 3.0]
WINDOW_52W = 252          # trading days in ~1 year
FORWARD_DAYS = 126        # trading days in ~6 months
MIN_STOCKS_PER_MONTH = 30  # minimum for a valid monthly snapshot
PE_FILTER_MAX = 50         # exclude stocks with trailing_pe > 50

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_us_stock_ids(db):
    """Return list of (id, ticker) for US stocks."""
    cur = db.execute(
        "SELECT id, ticker FROM indices "
        "WHERE market='US' AND category='stock' ORDER BY ticker"
    )
    return [(row[0], row[1]) for row in cur.fetchall()]


def get_global_month_ends(db):
    """
    Return sorted list of month-end dates (last trading day of each
    calendar month) present in daily_data.
    """
    cur = db.execute("SELECT DISTINCT date FROM daily_data ORDER BY date")
    month_map = {}
    for (d,) in cur.fetchall():
        month_map[d[:7]] = d
    return sorted(month_map.values())


def get_trailing_pes(db, stock_ids):
    """
    Return dict {index_id: trailing_pe} for stocks with positive PE.
    """
    pes = {}
    ids = [sid for sid, _ in stock_ids]
    placeholders = ",".join("?" * len(ids))
    cur = db.execute(
        f"SELECT index_id, trailing_pe FROM fundamentals "
        f"WHERE index_id IN ({placeholders})",
        ids,
    )
    for idx_id, pe in cur.fetchall():
        if pe is not None and pe > 0:
            pes[idx_id] = pe
    return pes


# ---------------------------------------------------------------------------
# Rolling window computation
# ---------------------------------------------------------------------------

def rolling_max(values, window):
    """
    O(n) rolling maximum via monotonic deque.
    For each position i, maximum of values[max(0, i-window+1) : i+1].
    First window-1 positions will reflect a partial window.
    """
    dq = deque()
    result = [0.0] * len(values)
    for i, v in enumerate(values):
        while dq and dq[0] <= i - window:
            dq.popleft()
        while dq and values[dq[-1]] <= v:
            dq.pop()
        dq.append(i)
        result[i] = values[dq[0]]
    return result


def compute_cheapness_and_forward(prices, window=WINDOW_52W, forward=FORWARD_DAYS):
    """
    Given sorted [(date, close), ...], for each position i with a full
    52-week lookback AND a valid 6-month forward price, yield:
        (date, cheapness, fwd_return)

    cheapness = close_i / 52w_high_i   (lower = more undervalued, 0..1)
    fwd_return = close_{i+forward} / close_i - 1
    """
    n = len(prices)
    closes = [p[1] for p in prices]
    highs = rolling_max(closes, window)

    for i in range(window, n - forward):
        cheapness = closes[i] / highs[i] if highs[i] > 0 else 1.0
        fwd_return = closes[i + forward] / closes[i] - 1.0
        yield prices[i][0], cheapness, fwd_return


# ---------------------------------------------------------------------------
# Metrics collection
# ---------------------------------------------------------------------------

def collect_monthly_metrics(db, stock_ids, month_ends, pe_data):
    """
    For every US stock with sufficient history, compute cheapness and
    forward return at each month-end date.

    Returns list of dicts:
        {date, index_id, ticker, cheapness, fwd_return, trailing_pe}
    """
    metrics = []
    month_set = set(month_ends)

    for idx_id, ticker in stock_ids:
        cur = db.execute(
            "SELECT date, close FROM daily_data "
            "WHERE index_id=? AND close IS NOT NULL ORDER BY date",
            (idx_id,),
        )
        prices = [(row[0], row[1]) for row in cur.fetchall()]
        if len(prices) < WINDOW_52W + FORWARD_DAYS:
            continue  # not enough history for 52w lookback + 6m forward

        trailing_pe = pe_data.get(idx_id)

        for date, cheapness, fwd_return in compute_cheapness_and_forward(prices):
            if date in month_set and 0.0 < cheapness <= 1.0:
                metrics.append({
                    'date': date,
                    'index_id': idx_id,
                    'ticker': ticker,
                    'cheapness': cheapness,
                    'fwd_return': fwd_return,
                    'trailing_pe': trailing_pe,
                })

    return metrics


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def run_simulation(metrics, pe_filter=False):
    """
    Run the switching simulation for all thresholds.

    For each month-end:
      1. Rank stocks by cheapness (ascending)
      2. Holdings = deciles 5-10 (upper half of cheapness range)
      3. For each threshold T:
         - Find candidates with cheapness <= holding_cheapness / T
         - Switch return = 6m forward return of cheapest candidate
         - Excess = switch_return - hold_return

    Returns (per_threshold_results, months_processed).
    """
    # Group metrics by date
    by_date = defaultdict(list)
    for m in metrics:
        by_date[m['date']].append(m)

    # Accumulators per threshold
    res = {t: {
        'hold_returns': [],
        'switch_returns': [],
        'excess_returns': [],
        'count': 0,
    } for t in THRESHOLDS}

    months_processed = 0

    for date in sorted(by_date.keys()):
        stocks = by_date[date]
        if len(stocks) < MIN_STOCKS_PER_MONTH:
            continue

        # Optional PE filter: restrict to stocks with reasonable PE
        if pe_filter:
            stocks = [
                s for s in stocks
                if s['trailing_pe'] is not None and s['trailing_pe'] < PE_FILTER_MAX
            ]
            if len(stocks) < MIN_STOCKS_PER_MONTH:
                continue

        # Sort by cheapness ascending
        stocks.sort(key=lambda s: s['cheapness'])
        n = len(stocks)

        # Identify holdings (deciles 5-10)
        holdings = []
        for i, s in enumerate(stocks):
            decile = min(i * 10 // n, 9)  # 0-based deciles 0..9
            if decile >= 4:               # deciles 4..9 = top 60%
                holdings.append(s)

        if not holdings:
            continue

        months_processed += 1

        for threshold in THRESHOLDS:
            for holding in holdings:
                c_h = holding['cheapness']
                max_candidate_cheapness = c_h / threshold

                candidates = [
                    s for s in stocks
                    if s['cheapness'] <= max_candidate_cheapness
                    and s['index_id'] != holding['index_id']
                ]
                if not candidates:
                    continue

                # Best candidate = cheapest (lowest cheapness ratio)
                best = min(candidates, key=lambda s: s['cheapness'])

                hold_ret = holding['fwd_return']
                switch_ret = best['fwd_return']
                excess = switch_ret - hold_ret

                res[threshold]['hold_returns'].append(hold_ret)
                res[threshold]['switch_returns'].append(switch_ret)
                res[threshold]['excess_returns'].append(excess)
                res[threshold]['count'] += 1

    return res, months_processed


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_results(results, months_processed, filter_label):
    """
    Convert per-threshold raw lists into summary statistics.

    Returns dict with fields matching the required output schema.
    """
    out = {
        'filter': filter_label,
        'months_processed': months_processed,
        'threshold_levels': [],
        'win_rate_by_threshold': {},
        'avg_return_by_threshold': {},
        'avg_excess_return_by_threshold': {},
        'median_excess_return_by_threshold': {},
        'std_excess_return_by_threshold': {},
        't_stat_excess_by_threshold': {},
        'pair_count_by_threshold': {},
        'optimal_threshold': None,
    }

    best_win_rate = -1.0
    best_threshold = None

    for t in THRESHOLDS:
        r = results[t]
        cnt = r['count']
        if cnt == 0:
            continue

        # Win rate: fraction of switches with positive excess return
        wins = sum(1 for e in r['excess_returns'] if e > 0)
        win_rate = wins / cnt

        # Means
        avg_hold = sum(r['hold_returns']) / cnt
        avg_switch = sum(r['switch_returns']) / cnt
        avg_excess = sum(r['excess_returns']) / cnt

        # Median excess
        sorted_excess = sorted(r['excess_returns'])
        mid = cnt // 2
        median_excess = sorted_excess[mid]

        # Standard deviation
        if cnt > 1:
            var = sum((e - avg_excess) ** 2 for e in r['excess_returns']) / (cnt - 1)
            std_excess = var ** 0.5
            t_stat = avg_excess / (std_excess / (cnt ** 0.5)) if std_excess > 0 else 0.0
        else:
            std_excess = 0.0
            t_stat = 0.0

        out['threshold_levels'].append(t)
        out['win_rate_by_threshold'][str(t)] = round(win_rate, 4)
        out['avg_return_by_threshold'][str(t)] = {
            'hold': round(avg_hold, 6),
            'switch': round(avg_switch, 6),
        }
        out['avg_excess_return_by_threshold'][str(t)] = round(avg_excess, 6)
        out['median_excess_return_by_threshold'][str(t)] = round(median_excess, 6)
        out['std_excess_return_by_threshold'][str(t)] = round(std_excess, 6)
        out['t_stat_excess_by_threshold'][str(t)] = round(t_stat, 4)
        out['pair_count_by_threshold'][str(t)] = cnt

        if win_rate > best_win_rate:
            best_win_rate = win_rate
            best_threshold = t

    out['optimal_threshold'] = best_threshold
    out['threshold_levels'].sort()
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(SCRIPT_DIR, exist_ok=True)
    print(f"Database: {DB_PATH}")
    print(f"Script:   {os.path.abspath(__file__)}")
    print()

    db = sqlite3.connect(DB_PATH)

    # 1. Stock list
    stock_ids = get_us_stock_ids(db)
    print(f"US stocks found in indices table:       {len(stock_ids)}")

    # 2. Month-end dates from daily_data
    month_ends = get_global_month_ends(db)
    print(f"Month-end dates in daily_data:           {len(month_ends)}")
    print(f"  Range: {month_ends[0]}  to  {month_ends[-1]}")

    # 3. Fundamentals / trailing PE
    pe_data = get_trailing_pes(db, stock_ids)
    print(f"Stocks with positive trailing_pe:        {len(pe_data)}")

    # 4. Collect cheapness + forward return metrics
    print(f"\nComputing price/52w-high cheapness and 6-month forward returns...")
    all_metrics = collect_monthly_metrics(db, stock_ids, month_ends, pe_data)
    print(f"  Monthly observations generated:        {len(all_metrics)}")

    # 5. Simulation: no PE filter
    print(f"\n--- Simulation: NO PE FILTER ---")
    raw_no_filter, months_no_filter = run_simulation(all_metrics, pe_filter=False)
    res_no_filter = aggregate_results(raw_no_filter, months_no_filter, 'none')
    _print_summary(res_no_filter)

    # 6. Simulation: PE filter (trailing_pe < 50)
    print(f"\n--- Simulation: PE FILTER (trailing_pe < {PE_FILTER_MAX}) ---")
    raw_filtered, months_filtered = run_simulation(all_metrics, pe_filter=True)
    res_filtered = aggregate_results(raw_filtered, months_filtered,
                                     f'trailing_pe < {PE_FILTER_MAX}')
    _print_summary(res_filtered)

    # 7. Build final output
    output = {
        'claim': (
            '#39: A new stock must be at least 2x more undervalued '
            'than current holdings to be worth switching to'
        ),
        'methodology': (
            'Monthly simulation using price/52-week-high ratio as cheapness proxy. '
            'Holdings = stocks in deciles 5-10 (upper 60% of cheapness range). '
            'For each threshold T, candidate stocks must have '
            'cheapness <= holding_cheapness / T. '
            'Switch return = forward 6-month return of the cheapest qualifying '
            'candidate. Hold return = forward 6-month return of current holding. '
            'Two filter modes: (1) no PE filter, (2) trailing_pe < 50 filter '
            '(excludes extremely high-valuation stocks).'
        ),
        'forward_period': '6 months (~126 trading days)',
        'cheapness_metric': 'close / 52-week-high (lower = more undervalued)',
        'date_range': {'start': month_ends[0], 'end': month_ends[-1]},
        'results': {
            'no_pe_filter': res_no_filter,
            f'pe_filtered_lt_{PE_FILTER_MAX}': res_filtered,
        },
    }

    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"Results written to: {RESULTS_FILE}")
    print(f"{'=' * 60}")

    db.close()
    return 0


def _print_summary(res):
    """Print human-readable per-threshold results."""
    print(f"  Months processed:  {res['months_processed']}")
    print(f"  Optimal threshold: {res['optimal_threshold']}x")
    print(f"  {'T':>5s}  {'Pairs':>8s}  {'WinRate':>8s}  {'AvgExcess':>10s}  "
          f"{'MedExcess':>10s}  {'t-stat':>8s}")
    print(f"  {'-'*5}  {'-'*8}  {'-'*8}  {'-'*10}  {'-'*10}  {'-'*8}")
    for t in sorted(res['threshold_levels']):
        ts = str(t)
        wr = str(res['win_rate_by_threshold'].get(ts, '--'))
        ae = str(res['avg_excess_return_by_threshold'].get(ts, '--'))
        me = str(res['median_excess_return_by_threshold'].get(ts, '--'))
        ts_val = str(res['t_stat_excess_by_threshold'].get(ts, '--'))
        pc = res['pair_count_by_threshold'].get(ts, 0)
        print(f"  {t:>5.1f}x  {pc:>8d}  {wr:>8s}  {ae:>10s}  {me:>10s}  {ts_val:>8s}")


if __name__ == '__main__':
    sys.exit(main())
