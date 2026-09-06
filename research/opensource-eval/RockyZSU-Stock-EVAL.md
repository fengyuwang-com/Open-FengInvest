# RockyZSU/Stock -- Code-Level Evaluation

> Repo: https://github.com/RockyZSU/Stock
> Evaluated: 2026-09-03
> Cloned to: `research/opensource-eval/RockyZSU-Stock/`
> Last updated: 2022-12 (refactoring in progress, 21 open issues)

---

## 1. Overall Impression

This is a personal A-share quant trading project (tutorial-style) by Rocky (30daydo.com). It is a collection of scripts, not a framework -- no unified API, no state machine, no tests, no CLI. The code quality is mixed: some modules are well-structured (fund share monitoring, eastmoney zt pool), while others are quick scripts with hardcoded credentials and deprecated dependencies.

**Core dependency stack:** tushare (pro_api + old API), akshare, sqlalchemy (MySQL), pymongo (MongoDB), requests + parsel, talib.

---

## 2. Module-by-Module Analysis

### 2.1 datahub/ -- Data Collection

#### 2.1.1 `dfcf_hot_block.py` -- Eastmoney ZT Pool (5 functions)

**What it does:** Crawls Eastmoney push2ex API for 5 pools: 涨停股池, 强势股池, 炸板股池, 跌停股池, 昨日涨停股池. Returns clean DataFrames with columns like 代码/名称/涨跌幅/成交额/封板资金/连板数/所属行业.

**Data source:** `https://push2ex.eastmoney.com/getTopicZTPool` (and variants). Dynamic `ut` token extracted from `build/detail.js`.

**Code quality:** High. Each function is self-contained, returns a well-structured DataFrame. Uses akshare as a dependency but re-implements the actual crawling (akshare's `stock_zt_pool_em` is imported but called separately as a sanity check).

**Verdict: 可直接复用** -- The 5 `stock_zt_pool_*_em()` functions are clean, well-documented, and return DataFrames directly usable by fengwatch.py or fengportfolio.py. The `ut` token extraction pattern is useful. Note: FengInvest already uses akshare's `stock_zt_pool_em`, but this code has additional pools (强势/炸板/跌停/昨日涨停) that akshare may not expose in the same way.

#### 2.1.2 `jucao_announcement.py` -- CNINFO Fund Announcements

**What it does:** Crawls `cninfo.com.cn` for fund announcements (季报/年报/申购赎回/分红/基金经理变更 etc.), saves to MongoDB.

**Data source:** `http://www.cninfo.com.cn/new/hisAnnouncement/query` (POST API).

**Code quality:** Medium. Hardcoded cookie/session values. Uses `BaseService` which is their shared HTTP wrapper.

**New data source?** CNINFO announcement API -- not currently in FengInvest's toolkit. Could be useful for monitoring fund manager changes and major fund events.

**Verdict: 可参考** -- The CNINFO API endpoint and category mapping (`params_dict`) are useful reference. The actual code needs cleanup (hardcoded cookies, MongoDB dependency). If FengInvest ever needs fund announcement monitoring, this is the right API to use.

#### 2.1.3 `ninwen.py` -- Ninwen Convertible Bond Data

**What it does:** Crawls ninwin.cn for comprehensive convertible bond data (42 columns including 转股溢价率/纯债价值/双低/信用/折现率 etc.). Requires login + captcha recognition.

**Data source:** `www.ninwin.cn` (web scraping with session/CSRF/captcha).

**Code quality:** Medium-high. Clean parsing with parsel/XPath. The column mapping is thorough.

**New data source?** Ninwen (宁稳) is a specialized convertible bond data site. FengInvest uses jisilu (集思录) for bond data but ninwen offers more fields (老式双低/新式双低/弹性/折现率).

**Verdict: 可参考** -- The column mapping and parsing logic is valuable if we want ninwen bond data. The captcha login flow makes direct integration fragile. The 42-column schema is a good reference for what fields exist in the bond data universe.

#### 2.1.4 `foreignexchange.py` -- USD/CNY Rate

**What it does:** Scrapes hexun.com for USD buy/sell price, stores to MySQL, sends WeChat notification.

**Data source:** `data.bank.hexun.com` -- the code itself marks this as "失效" (defunct).

**Verdict: 不适用** -- Data source is dead. FengInvest already has `fengdata.py fx` which covers USDCNY/HKDCNY/USDHKD with fallback.

#### 2.1.5 `repurchase.py` -- Stock Buyback Data

**What it does:** Uses `xcsc_tushare` (申万宏源 tushare fork) to get repurchase data, merges with jisilu bond data.

**Data source:** `xcsc_tushare` -- a tushare variant from 申万宏源.

**New data source?** `xcsc_tushare` is a tushare fork with `repurchase()` endpoint. However, the code says "这个接口失效了" (this API is defunct).

**Verdict: 不适用** -- API is dead, and FengInvest's `fengastock.py` already has broader data coverage.

#### 2.1.6 `black_list_sql.py` -- Stock Blacklist

**What it does:** Reads a CSV of blacklisted stocks (code;name;reason) and inserts into MySQL.

**Verdict: 不适用** -- Simple file-to-DB loader. FengInvest's screening logic in `fengscreen.py` is more sophisticated.

#### 2.1.7 `yanbao_crawl.py` -- Research Report PDF Download

**What it does:** Crawls `aigc.idigital.com.cn/djyanbao/` for research report PDFs and downloads them.

**Data source:** 同花顺 iDigital research report index page.

**Verdict: 可参考** -- Simple but useful data source. If FengInvest needs automated research report collection, this URL endpoint is worth testing.

---

### 2.2 fund/ -- Fund Monitoring (The Strongest Module)

#### 2.2.1 `fund_share_crawl.py` + `fund_share_update.py` + `LOF_Model.py` -- Exchange Direct Fund Share Crawling

**What it does:** Crawls fund share data directly from:
- **深交所 (SZSE):** `fund.szse.cn/api/report/ShowReport/data` -- JSON API for LOF/ETF scale data
- **上交所 (SSE):** `query.sse.com.cn/commonQuery.do` -- JSONP API for LOF/ETF scale data

Uses SQLAlchemy ORM with two tables: `LOF_BaseInfo` (fund metadata) and `LOF_Share` (daily share records).

**Code quality:** High. Clean separation: SZFundShare and SHFundShare handle their respective exchange APIs. The ORM model is well-designed. The `SHFundShare.crawl_etf()` handles pagination correctly.

**Data sources:** Direct exchange APIs -- these are official, stable data sources. Not currently in FengInvest's toolkit.

**Verdict: 可直接复用** -- This is the most valuable finding in the entire repo. The SSE and SZSE fund share API endpoints are clean, no authentication required, and provide authoritative fund share data. FengInvest could directly import or adapt:
- The SSE ETF URL pattern: `http://query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE=...`
- The SSE LOF URL pattern: `http://query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_FUND_LOF_SCALE_CX_S&FILEDATE=...`
- The SZSE URL pattern: `http://fund.szse.cn/api/report/ShowReport/data?CATALOGID=1000_lf&TABKEY=tab1&...`
- The JSONP-to-JSON parsing pattern (`jsonp2json`)
- The ORM schema for fund share tracking

**Specific reuse plan:** Create a new `tools/fengfund.py` or add fund share endpoints to `fengastock.py`. The SSE/SZSE URLs are the same endpoints that akshare's `fund_etf_fund_daily_em` and similar functions use internally, but having the direct URLs is more transparent.

#### 2.2.2 `ShareDetection.py` -- LOF/ETF Share Change Alert

**What it does:** Compares yesterday's share vs day-before-yesterday's share. Triggers email alert if:
- Share change exceeds `PERCENT` threshold (10% default)
- Absolute share difference exceeds `DIFF_MAX` (LOF: 200, ETF: 100000 万份)

**Code quality:** Medium. The logic is sound but the date calculation is a bit fragile (hardcoded offsets).

**Verdict: 可参考** -- The detection logic (percentage + absolute threshold dual-filter) is a useful pattern. FengInvest could implement a similar mechanism in `fengwatch.py` to monitor ETF/LOF share flows as a signal for institutional activity.

#### 2.2.3 `LOF_arbitrage.py` -- LOF Premium/Discount Monitor

**What it does:** Gets LOF real-time prices from Sina, calculates premium/discount rate vs NAV, alerts if premium >= 4% and volume >= 10万. Uses `akshare` for `fund_purchase_em()` (申购赎回状态) and `stock_individual_spot_xq()` (雪球成交额).

**Data sources:** Sina finance API + akshare.

**Code quality:** Medium-high. Clean structure, good error handling.

**Verdict: 可参考** -- The premium/discount calculation pattern is useful. However, FengInvest's investment framework is equity-focused (not fund arbitrage), so this is more of a reference pattern than a direct integration target.

#### 2.2.4 `fund_info_spider.py` + `fund_tencent.py` -- Tencent Fund Data

**What it does:** Crawls fund data from `gu.qq.com` (Tencent Finance), stores to MySQL. Gets real-time NAV estimation, calculates premium/discount, sends email alerts.

**Data source:** `gu.qq.com/{code}` HTML page + `web.ifzq.gtimg.cn/fund/newfund/fundSsgz/getSsgz` JSON API.

**Code quality:** Medium. Uses demjson (fragile JSON parser), hardcoded MySQL table names, session management is basic.

**Verdict: 可参考** -- The Tencent fund NAV estimation API (`web.ifzq.gtimg.cn/fund/newfund/fundSsgz/getSsgz?symbol=jj{code}`) is a useful real-time data source. Not critical for FengInvest's current scope.

#### 2.2.5 `ark_funds.py` -- ARK ETF Holdings

**What it does:** Crawls ARK Innovation/Next Gen/FinTech/Genomics/Autonomous ETF top-10 holdings from `ark-funds.com`, stores to MongoDB.

**Data source:** `ark-funds.com/auto/gettopten.php` (POST API).

**Code quality:** Medium. Clean HTML parsing with parsel.

**New data source?** ARK fund holdings -- not in FengInvest.

**Verdict: 不适用** -- ARK funds are US-listed and not relevant to FengInvest's A-share/HK focus. The pattern of scraping ETF holdings is interesting but the data source is too narrow.

#### 2.2.6 `danjuan_fund.py` -- Danjuan Fund Portfolios

**What it does:** Crawls 蛋卷基金 (Danjuan) API for fund portfolio plans, their holdings, and details. Stores to MongoDB.

**Data source:** `danjuanfunds.com/djapi/fundx/portfolio/v3/plan/united/page` JSON API.

**Code quality:** High. Clean API-based crawling, good separation of concerns.

**Verdict: 可参考** -- The Danjuan API endpoints for fund portfolio data are useful if FengInvest ever needs to track smart-beta or target-date fund holdings. Low priority.

#### 2.2.7 `etf_info.py` -- CSI Index ETF Constituents

**What it does:** Crawls `csindex.com.cn` for:
1. Full market index list (1797 indices with metadata)
2. ETF constituent stocks with weights (download XLS + parse weight page)

**Data source:** `csindex.com.cn` -- China Securities Index official site.

**Code quality:** Medium. The XLS download + page parsing for weights is a bit brittle.

**New data source?** CSI Index constituent data -- FengInvest doesn't have direct CSI index constituent crawling.

**Verdict: 可参考** -- The CSI Index URL patterns are useful:
- Index list: `http://www.csindex.com.cn/zh-CN/indices/index?page={}&page_size=50`
- Constituent XLS: `http://www.csindex.com.cn/uploads/file/autofile/cons/{}cons.xls`
- Weight page: `http://www.csindex.com.cn/zh-CN/indices/index-detail/{code}`

If FengInvest needs to track which stocks are in which index, these endpoints are the authoritative source.

#### 2.2.8 `jsl_fund.py` -- Jisilu LOF Data

**What it does:** Crawls jisilu.cn for stock LOF and index LOF lists, stores to MongoDB.

**Data source:** `jisilu.cn/data/lof/stock_lof_list/` and `index_lof_list/`.

**Code quality:** Low. The URLs may be stale (hardcoded timestamps). Uses demjson.

**Verdict: 不适用** -- Simple data fetch, jisilu has anti-scraping measures. FengInvest doesn't need LOF lists.

#### 2.2.9 `etf_range_increment.py` -- ETF History Data

**What it does:** Uses `akshare.fund_etf_category_sina` and `akshare.fund_etf_hist_sina` to get ETF lists and historical OHLCV data, stores to MySQL.

**Data source:** akshare (Sina backend).

**Verdict: 不适用** -- FengInvest already uses akshare directly. No added value.

---

### 2.3 k-line/ -- Technical Pattern Recognition

#### `recognize_form.py` -- talib Candlestick Pattern Detection

**What it does:** Uses `talib.CDL2CROWS` to detect "two crows" pattern, then visualizes with matplotlib candlestick chart + annotations.

**Code quality:** Low. Only one pattern implemented (two crows). Hardcoded file path. No return value (only plt.show). Uses deprecated `mpl_finance`.

**talib usage pattern:** `talib.CDL2CROWS(open, high, low, close)` returns +100 (bullish), -100 (bearish), or 0 (no pattern).

**Verdict: 可参考** -- The talib usage pattern is correct and simple. FengInvest could use talib for pattern detection as an additional signal layer. The available talib candlestick patterns include: CDL2CROWS, CDL3BLACKCROWS, CDL3INSIDE, CDL3LINESTRIKE, CDL3STARSINSOUTH, CDLBELTHOLD, CDLCLOSINGMARUBOZU, CDLDOJI, CDLDOJISTAR, CDLDRAGONFLYDOJI, CDLENGULFING, CDLEVENINGSTAR, CDLHAMMER, CDLHANGINGMAN, CDLHARAMI, CDLINVERTEDHAMMER, CDLLOCUSTO, CDLMARUBOZU, CDLMORNINGSTAR, CDLONNECK, CDLPIERCING, CDLSHOOTINGSTAR, CDLSPINNINGTOP, CDLTRISTAR, CDLXSIDEGAP3METHODS, etc.

However, FengInvest's philosophy emphasizes fundamental analysis (7-layer framework) over technical patterns, so talib integration is low priority.

---

### 2.4 machine_learning/ -- ML Prediction

#### `贝叶斯预测涨跌.py` -- Naive Bayes Direction Prediction

**What it does:** Uses BernoulliNB to predict next-day stock direction (up/down) based on:
- **Features:** Industry (one-hot), log market cap quintile, 5-day momentum quintile
- **Labels:** Next day return > 0 = 1, else 0
- **Backtest:** Rolling window (train on day i, predict day i+1, evaluate on day i+2)

**Data source:** `DataAPI.*` -- This is **Uqer (优矿)** platform API, which has been shut down. The code literally cannot run outside Uqer.

**Code quality:** Medium. The rolling-window backtest logic is clean. But the feature engineering is very basic (only 3 features, all categorical via qcut). No hyperparameter tuning, no cross-validation, no feature importance analysis.

**Verdict: 不适用** -- The Uqer platform is dead, so this code cannot run. The approach (BernoulliNB on categorical features for daily direction prediction) is too simplistic to be useful. FengInvest's `fengquant.py` (6-factor z-score) is more sophisticated. If ML prediction is ever needed, this is not the right starting point.

---

### 2.5 monitor/ -- Real-time Monitoring

#### 2.5.1 `realtime_monitor_ts.py` -- Tushare Real-time Bond Monitoring

**What it does:** Uses `tushare.get_apis()` and `tushare.quotes()` (old tushare pro API) to monitor convertible bond and stock price changes in real-time. Triggers WeChat alerts on:
- Price change exceeding threshold (default 8%)
- Bid-ask spread exceeding 40 (千)

**Code quality:** Medium. The monitoring loop with cooldown timers is well-designed. But uses deprecated tushare API (`get_apis`, `quotes`), and the stock list is read from a hardcoded OneDrive path.

**Verdict: 不适用** -- Uses deprecated tushare API, hardcoded paths. FengInvest has `fengwatch.py` with 10 exit rules which is more comprehensive. The monitoring pattern (cooldown timer to avoid duplicate alerts) is a useful design pattern worth noting.

#### 2.5.2 `ceiling_break.py` -- Limit-up Board Break Monitor

**What it does:** Monitors limit-up stocks for board break (开板). Uses `tushare.get_realtime_quotes()` to check if bid volume drops below 10,000 lots.

**Code quality:** Low. Uses threading for multi-stock monitoring. Simple threshold logic.

**Verdict: 不适用** -- Niche use case (limit-up board break), uses deprecated API. Not aligned with FengInvest's investment philosophy.

---

### 2.6 Other Notable Files

#### `select_stock.py` -- Legacy Stock Screener

Uses old tushare API (`get_stock_basics`, `get_k_data`, `get_hist_data`). Implements MA crossovers, volume analysis, area counting, IPO age analysis.

**Verdict: 不适用** -- Entirely based on deprecated tushare v0.7.5 API. FengInvest's `fengscreen.py` and `fengquant.py` are far more sophisticated.

#### `stockInfo.py` -- News Crawler to ElasticSearch

Crawls stock news and stores to ElasticSearch. Not examined in detail.

**Verdict: 不适用** -- FengInvest doesn't use ElasticSearch. News analysis is out of scope for current tools.

---

## 3. Data Sources -- Overlap vs. Novel

| Data Source | In This Repo | In FengInvest | Notes |
|:---|:---:|:---:|:---|
| tushare (old API) | Heavy | Partial (pro) | Old API deprecated; FengInvest uses pro_api |
| akshare | Yes | Yes | Overlap -- both use it |
| baostock | No | Yes | FengInvest has it, this repo doesn't |
| yfinance | No | Yes | FengInvest has it, this repo doesn't |
| fuyao (同花顺) | No | Yes | FengInvest has it, this repo doesn't |
| a-stock-data | No | Yes | FengInvest has it, this repo doesn't |
| **SSE direct (query.sse.com.cn)** | **Yes** | **No** | **NEW -- ETF/LOF fund share data** |
| **SZSE direct (fund.szse.cn)** | **Yes** | **No** | **NEW -- ETF/LOF fund share data** |
| **Eastmoney push2ex** | **Yes** | **Partial** | **Extended -- 5 ZT pools (strong/break/dt/yesterday)** |
| **CNINFO (cninfo.com.cn)** | **Yes** | **No** | **NEW -- Fund announcements** |
| **Ninwen (ninwin.cn)** | **Yes** | **No** | **NEW -- Extended convertible bond data** |
| **CSI Index (csindex.com.cn)** | **Yes** | **No** | **NEW -- Index constituents** |
| **Tencent fund (gu.qq.com)** | **Yes** | **No** | **NEW -- Real-time fund NAV estimation** |
| **Danjuan API** | **Yes** | **No** | **NEW -- Smart beta fund portfolios** |
| **ARK Fund** | **Yes** | **No** | **Not relevant (US ETF)** |
| **Jisilu** | **Yes** | **Partial** | FengInvest uses jisilu for bonds |
| **Sina finance** | Yes | Partial | Both use Sina APIs |
| **Uqer (优矿)** | Yes | No | Platform shut down |
| **xcsc_tushare** | Yes | No | API defunct |

---

## 4. Summary Verdicts

### "可直接复用" -- Can Import Directly

1. **`dfcf_hot_block.py`** -- 5 Eastmoney ZT pool functions (涨停/强势/炸板/跌停/昨日涨停). Clean, self-contained, returns DataFrames. Can be added to fengastock.py or a new fengzdt.py.

2. **`fund_share_crawl.py` + `LOF_Model.py`** -- SSE/SZSE direct fund share crawling. The API URLs, JSONP parsing, and ORM schema are directly usable. This is the most architecturally valuable finding.

### "可参考" -- Good Ideas, Needs Rework

3. **`ShareDetection.py`** -- LOF/ETF share change alert logic (percentage + absolute threshold). Pattern is useful for fengwatch.py fund flow monitoring.

4. **`LOF_arbitrage.py`** -- Premium/discount calculation pattern. Sina API for real-time LOF prices.

5. **`fund_info_spider.py`** -- Tencent fund NAV estimation API (`web.ifzq.gtimg.cn`).

6. **`jucao_announcement.py`** -- CNINFO fund announcement API endpoint and category mapping.

7. **`ninwen.py`** -- Ninwen bond data schema (42 columns). Useful reference for what fields exist.

8. **`etf_info.py`** -- CSI Index constituent data URLs and parsing.

9. **`yanbao_crawl.py`** -- Research report download source.

10. **`k-line/recognize_form.py`** -- talib candlestick pattern detection pattern.

### "不适用" -- Does Not Fit

11. **`machine_learning/贝叶斯预测涨跌.py`** -- Uqer platform is dead. Approach too simplistic.
12. **`datahub/foreignexchange.py`** -- Data source defunct. FengInvest has fx coverage.
13. **`datahub/repurchase.py`** -- xcsc_tushare API defunct.
14. **`datahub/black_list_sql.py`** -- Simple CSV-to-DB loader.
15. **`monitor/realtime_monitor_ts.py`** -- Deprecated tushare API.
16. **`monitor/ceiling_break.py`** -- Deprecated API, niche use case.
17. **`select_stock.py`** -- Entirely deprecated tushare v0.7.5.
18. **`fund/ark_funds.py`** -- US ETF data, not relevant.
19. **`fund/jsl_fund.py`** -- Simple jisilu fetch, fragile.

---

## 5. Recommendations

1. **Priority 1: Add SSE/SZSE fund share endpoints to FengInvest.** This is genuinely new capability -- tracking ETF/LOF fund share changes as an institutional flow signal. Create a new tool (e.g., `tools/fengfund.py`) with `share-history`, `share-alert`, and `share-diff` subcommands. The API endpoints are stable, no auth required, and provide daily authoritative data.

2. **Priority 2: Consider adding the extended Eastmoney ZT pools.** FengInvest already has basic ZT data, but the 强势股池/炸板股池/跌停股池/昨日涨停股池 are useful market sentiment indicators. Could be added as a `--pools` flag to fengwatch.py or a separate fengzdt.py tool.

3. **Priority 3: Register new data sources in the opensource_list.json.** The SSE/SZSE endpoints, CNINFO announcement API, and CSI Index URLs are worth documenting even if not immediately integrated.

4. **Low priority:** The convertible bond ninwen data and research report download sources are worth noting but not urgent given FengInvest's current scope.

---

## 6. Registration

Project already registered in `data/config/opensource_list.json` with status "noted". Update status to "evaluating" -> "evaluated" with note referencing this evaluation file.
