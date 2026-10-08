# pwb-toolbox Evaluation

> Repo: https://github.com/paperswithbacktest/pwb-toolbox  
> Cloned: 2026-09-03  
> Language: Python 3.10+, depends on backtrader, deap, ccxt, huggingface_hub, scipy, pyarrow  
> License: See LICENSE.txt

## What It Is

PapersWithBacktest Toolbox -- a framework for systematic trading strategy development. It provides:
- A parquet-based dataset pipeline (7 asset classes, sourced from PWB API or HuggingFace)
- A Backtrader-based backtesting engine with 11 pre-built portfolio strategy templates
- A performance analytics library (25+ metrics, 17+ plot types)
- A genetic algorithm optimization engine for indicator weight tuning
- Live execution connectors (Interactive Brokers, CCXT/crypto)
- Legacy SSRN paper crawling and strategy classification modules

## Code Quality

Generally clean, well-documented Python. Pure implementations for metrics (numpy/pandas only, no quantlib dependency). Backtrader integration is straightforward. The GA optimization engine uses DEAP. Some modules (execution, legacy SSRN) have heavier dependencies (ccxt, kili, transformers, huggingface).

---

## Module-by-Module Verdict

### 1. Datasets (`pwb_toolbox/datasets/`)

**Data Sources:** PapersWithBacktest API (parquet shards) + HuggingFace Hub. Covers Bonds, Commodities, Crypto, ETFs, Forex, Indices, Stocks.

**Key Techniques:**
- Sharded parquet with predicate pushdown (filters symbols at shard level, never loads full dataset into memory)
- ETF proxy extension: extends ETF history backward using related indices/commodities (e.g., SPY extended via SPX, GLD via gold futures)
- Bond yield-to-price conversion from symbol-encoded maturity (US10Y -> price)
- Global index FX conversion (CAC (EUR) -> USD via EUR/USD rate)

**Verdict: "可参考"**  
The parquet sharding pattern is smart but FengInvest already has its own data pipeline (fengdata.py, fengstockintl.py, fengastock.py, fengfuyao.py) that pulls from multiple live sources. We don't need to adopt PWB's data layer. However, two techniques are worth borrowing:
- **ETF proxy extension** for backtesting -- extending ETF history back before its IPO using a related index or commodity is a genuinely useful pattern that FengInvest lacks
- **Bond yield-to-price conversion** -- a clean implementation we could reference if we ever need fixed income backtesting

### 2. Backtest Engine (`pwb_toolbox/backtesting/backtest_engine.py`)

`run_strategy()`: Loads data via PWB datasets, configures Backtrader Cerebro, applies commission model, runs strategy, returns result. Clean ~90-line wrapper.

`sensitivity_results()`: Perturbs one parameter at a time across a range of scale factors, computes a metric for each. Useful for robustness checking.

**Verdict: "不适用"**  
FengInvest already has its own backtesting engine (`fengbacktest.py` + `backtest_core.py`) built on a custom framework (not Backtrader). The architectures are fundamentally different. Direct adoption would mean replacing FengInvest's entire backtest stack. Not worth it.

### 3. Portfolio Strategy Templates (`pwb_toolbox/backtesting/strategies.py`)

11 pre-built templates: Daily Equal Weight, Daily Leverage, Equal Weight Entry/Exit, Dynamic Equal Weight, Monthly Long/Short, Monthly Long/Short Quantile, Monthly Ranked Equal Weight, Quarterly Top Momentum, Rolling Semester Long/Short, Weekly Long/Short Decile, Weighted Allocation.

**Verdict: "可参考"**  
The strategy patterns are clean and well-documented. Specific value:
- **MonthlyLongShortQuantilePortfolio** -- uses `bt.add_timer()` for month-start rebalancing, a pattern we could reference
- **DynamicEqualWeightPortfolio** -- supports rebalance-only-on-set-change vs. rebalance-on-any-signal-change, two modes FengInvest's portfolio optimizer doesn't offer
- **WeeklyLongShortDecilePortfolio** -- decile-based long/short sorting with configurable fraction is a useful quantitative pattern

However, all of these are Backtrader-specific classes. FengInvest uses its own framework. We'd need to port the logic, not the code.

### 4. Commission Estimation (`pwb_toolbox/backtesting/commission.py`)

**Novel approach:** Uses a Gibbs sampler (Bayesian MCMC) to estimate bid-ask spread from price data, with a Roll(1984) estimator as fallback for short series. Estimates per-symbol commissions from log-price changes.

**Verdict: "可参考"**  
This is genuinely interesting. FengInvest's `fengbacktest.py` uses a flat 25bps cost model. The Gibbs sampler approach estimates actual effective spread from price data, which is more realistic. However:
- Requires sufficient price history (>= 5 observations minimum)
- Assumes specific microstructure model (Roll model)
- The code is self-contained (~100 lines) and could be extracted as a standalone utility

Worth implementing as an optional commission model in FengInvest's backtest engine.

### 5. Universe Selection (`pwb_toolbox/backtesting/universe.py`)

`get_most_liquid_symbols(n)`: Ranks all stocks by volume * price, returns top N.  
`get_least_volatile_symbols(symbols)`: Filters out stocks with > 300% max single-day price change.

**Verdict: "可直接复用"**  
Very simple but clean implementations. The liquidity ranking (volume * close) is a standard screen. FengInvest's `fengscreen.py` does more sophisticated screening (7 hard indicators + 3 exemptions), but a quick liquidity filter like this is a useful pre-filter. Could be copied as-is.

### 6. Sigmoid Composite Indicator (`pwb_toolbox/backtesting/indicators.py`)

Combines N Backtrader indicators via weighted linear combination, applies sigmoid to produce a [0, 1] probability score. Supports bias term and value clipping for numerical stability.

**Verdict: "可参考"**  
Clean pattern for signal combination. FengInvest doesn't have an equivalent composite signal mechanism -- signals are typically binary (pass/fail). A weighted composite indicator that combines multiple factors into a single probabilistic score could be useful for the collision layer (L3). Would need adaptation to FengInvest's non-Backtrader architecture.

### 7. Performance Metrics (`pwb_toolbox/performance/metrics.py`)

25+ metrics, all pure numpy/pandas implementations:
- **Standard:** total_return, CAGR, returns_table (monthly/yearly matrix), rolling_cumulative_return, annualized_volatility
- **Risk:** max_drawdown (with duration), ulcer_index, ulcer_performance_index, parametric VaR, parametric Expected Shortfall, tail_ratio
- **Ratios:** Sharpe, Sortino, Calmar, Omega, Information ratio
- **Factor:** CAPM alpha/beta, Fama-French 3-factor, Fama-French 5-factor regression
- **Statistical:** skewness, kurtosis, variance ratio test (Lo-MacKinlay), ACF, PACF

**Verdict: "可直接复用"**  
This is the highest-value module. Every metric is self-contained (no quantlib dependency). Key gaps in FengInvest that this fills:
- **Fama-French 3/5 factor regression** -- FengInvest's `fengfactor.py` does factor analysis but doesn't have the standard Fama-French regression. This implementation is ~40 lines and could be adopted directly
- **Ulcer Index** and **Ulcer Performance Index** -- not in FengInvest's toolset
- **Variance ratio test** (Lo-MacKinlay) -- test for market efficiency, not present in FengInvest
- **Parametric Expected Shortfall** -- CVaR is in FengInvest's risk attribution but not as a standalone metric function
- **ACF/PACF** -- not present in FengInvest

### 8. Performance Plots (`pwb_toolbox/performance/plots.py`)

17 plot functions, all matplotlib:
- Equity curve (log scale), return heatmap (calendar), underwater chart
- Rolling volatility, VaR, Sharpe, Sortino, skewness, kurtosis
- QQ plot, factor exposures bar chart, trade return histogram
- Holding period box plot, exposure time series, cumulative shortfall, alpha vs return scatter

**Verdict: "可直接复用"**  
Clean matplotlib code. FengInvest's `fengweb/` frontend generates some of these but not all. Missing from FengInvest:
- **Rolling Sharpe/Sortino/VaR/skewness/kurtosis plots** -- FengInvest has rolling metrics in code but no dedicated plot functions
- **QQ plot** -- not present
- **Calendar return heatmap** -- not present
- **Trade return histogram** -- not present
- **Implementation shortfall cumulative plot** -- not present

### 9. Trade Statistics (`pwb_toolbox/performance/trade_stats.py`)

Functions for trade-level analysis: hit_rate, average_win_loss, expectancy, profit_factor, trade_duration_distribution, turnover, implementation_shortfall, slippage_stats, latency_stats.

**Verdict: "可直接复用"**  
Clean and useful. FengInvest has some of these in `fengbacktest.py` but not as standalone reusable functions. The implementation shortfall and slippage analysis modules are particularly useful for evaluating execution quality. Could be extracted as a standalone module.

### 10. GA Optimization Engine (`pwb_toolbox/backtesting/optimization_engine.py`)

Genetic algorithm using DEAP for optimizing indicator weights and bias. Parallel evaluation (multiprocessing Pool), tournament selection, blend crossover, Gaussian mutation. Objective: maximize Calmar ratio.

**Verdict: "可参考"**  
FengInvest doesn't have a strategy parameter optimizer. This could be useful for tuning weights in the factor model or collision layer. However:
- It's tightly coupled to Backtrader (runs full backtest for each candidate)
- FengInvest's architecture is different, so the evaluation function would need rewriting
- The GA framework itself (DEAP) is generic and could be reused, but the integration code is not

### 11. Multi-Strategy Portfolio (`pwb_toolbox/backtesting/portfolio.py`)

`run_portfolio()`: Aggregates multiple strategies' NAVs with target weights, annual rebalancing.  
`generate_reports()`: Prints metrics summary, saves equity curve, return heatmap, underwater chart, rolling Sharpe plot + JSON metrics.

**Verdict: "可参考"**  
FengInvest's `fengportfolio.py` is more sophisticated (three-axis orthogonal layout, constraint rebalancing, risk attribution, HRP). This module is simpler. The annual rebalancing logic is a useful pattern for combining strategy-level allocations. But FengInvest doesn't need this at the portfolio level.

### 12. Execution Connectors (`pwb_toolbox/execution/`)

- **CCXTConnector**: Crypto exchange connectivity (Binance, etc.) via ccxt
- **IBConnector**: Interactive Brokers connectivity
- **Optimal limit order**: Almgren-Chriss style optimal execution using ODE solver

**Verdict: "不适用"**  
FengInvest is an analysis/decision framework, not an execution platform. The IB/CCXT connectors are out of scope. The optimal limit order formula is theoretically interesting but not actionable for FengInvest's use case (long-term equity investing, not HFT).

### 13. Legacy SSRN Modules (`pwb_toolbox_legacy/`)

SSRN abstract crawling, classification (DistilBERT fine-tuned), strategy extraction, summarization via Kili labeling platform.

**Verdict: "不适用"**  
Niche research automation tooling. Not relevant to FengInvest.

---

## Gap Analysis: What pwb-toolbox Fills That FengInvest Lacks

| Capability | FengInvest Status | pwb-toolbox Has | Recommendation |
|:-----------|:-----------------|:----------------|:---------------|
| Fama-French 3/5 factor regression | No | Yes (40 lines) | **Adopt** -- extract as standalone function |
| Ulcer Index / UPI | No | Yes | **Adopt** -- useful risk metric |
| Variance ratio test (Lo-MacKinlay) | No | Yes | **Adopt** -- market efficiency test |
| ACF / PACF | No | Yes | **Adopt** -- time series analysis |
| Parametric VaR (standalone) | In risk attribution only | Yes (standalone) | **Reference** -- FengInvest already has CVaR |
| Calendar return heatmap | No | Yes (matplotlib) | **Adopt** -- nice for reports |
| QQ plot | No | Yes | **Adopt** -- distribution diagnostics |
| Rolling Sharpe/Sortino/VaR plots | Metrics exist, no plot functions | Yes (17 plot types) | **Adopt** plot patterns |
| Implementation shortfall analysis | No | Yes | **Adopt** -- execution quality metric |
| Gibbs sampler bid-ask estimation | No | Yes | **Reference** -- novel but niche |
| ETF proxy historical extension | No | Yes | **Reference** -- useful for backtesting |
| Composite sigmoid signal | No (binary only) | Yes | **Reference** -- could inform L3 collision |
| GA strategy optimization | No | Yes (DEAP-based) | **Reference** -- architecture mismatch |

---

## Overall Recommendation

**Do not adopt pwb-toolbox as a dependency.** The architectures are incompatible (Backtrader vs. FengInvest's custom engine). Instead, cherry-pick specific implementations:

1. **High-value extractions** (clean, self-contained, no Backtrader dependency):
   - `fama_french_3factor()` / `fama_french_5factor()` from metrics.py (~40 lines)
   - `ulcer_index()` / `ulcer_performance_index()` from metrics.py (~20 lines)
   - `variance_ratio()` from metrics.py (~15 lines)
   - `acf()` / `pacf()` from metrics.py (~30 lines)
   - `plot_qq_returns()` / `plot_return_heatmap()` from plots.py (~40 lines each)
   - `trade_implementation_shortfall()` / `slippage_stats()` from trade_stats.py (~30 lines)
   - `get_most_liquid_symbols()` from universe.py (~10 lines)

2. **Reference patterns** (logic worth borrowing, not code directly):
   - ETF proxy extension logic from datasets.py
   - Gibbs sampler commission estimation from commission.py
   - Dynamic rebalance trigger modes from strategies.py
   - Sigmoid composite indicator pattern from indicators.py

3. **Skip entirely:**
   - Backtest engine (incompatible architecture)
   - Execution connectors (out of scope)
   - Legacy SSRN modules (irrelevant)
   - GA optimization (too tightly coupled to Backtrader)

**Total adoptable code: ~200 lines** of pure metric/plot functions that fill genuine gaps in FengInvest's 62-tool suite.
