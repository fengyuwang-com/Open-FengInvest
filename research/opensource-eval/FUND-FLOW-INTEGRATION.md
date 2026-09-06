# Fund Flow Integration — ETF/LOF 份额变动监控

## 变更概述

将 RockyZSU/Stock 开源项目的沪深交易所直连 ETF/LOF 份额 API 集成到 `tools/fengwatch.py`，新增 `fund-share` 子命令。

## 数据来源

| 交易所 | API 地址 | 返回格式 | 关键字段 |
|:-------|:---------|:---------|:---------|
| SSE 上交所 ETF | `query.sse.com.cn/commonQuery.do` (sqlId: `COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L`) | JSONP | SEC_CODE, SEC_NAME, TOT_VOL(份), STAT_DATE |
| SSE 上交所 LOF | `query.sse.com.cn/commonQuery.do` (sqlId: `COMMON_SSE_FUND_LOF_SCALE_CX_S`) | JSONP | FUND_CODE, FUND_ABBR, INTERNAL_VOL(万份), TRADE_DATE |
| SZSE 深交所 | `fund.szse.cn/api/report/ShowReport/data` (CATALOGID: 1000_lf) | JSON | sys_key(代码), jjjcurl(名称), dqgm(规模/万份) |

## 新增文件

- `research/opensource-eval/FUND-FLOW-INTEGRATION.md` — 本文件

## 修改文件

- `tools/fengwatch.py` — 新增以下内容:

### 新增函数 (位于 Data Loading 之前)

| 函数 | 功能 |
|:-----|:-----|
| `_fund_http_get(url, headers, timeout)` | 通用 HTTP GET，带超时和错误处理 |
| `_parse_jsonp(text)` | JSONP 响应解析（SSE 接口返回 JSONP 格式） |
| `fetch_sse_etf_shares(date_str)` | 查询上交所 ETF 份额，自动翻页 |
| `fetch_sse_lof_shares(date_str)` | 查询上交所 LOF 份额（一次性全量） |
| `fetch_szse_fund_shares(page)` | 查询深交所 LOF/ETF 份额，自动翻页 |
| `fetch_all_fund_shares(codes, exchanges)` | 统一入口，合并沪深数据，支持按代码/交易所过滤 |
| `compute_share_changes(current_data, warn_pct)` | 计算份额日环比变动，标记超阈值异动 |
| `cmd_fund_share(args)` | `fund-share` 子命令实现 |

### 新增子命令

```
fengwatch.py fund-share                  查询全量 ETF/LOF 份额
fengwatch.py fund-share --codes 510300   指定代码查询
fengwatch.py fund-share --exchange SSE   只查上交所
fengwatch.py fund-share --exchange SZSE  只查深交所
fengwatch.py fund-share --threshold 3    设置告警阈值（百分比）
fengwatch.py fund-share --top 20         只显示变动最大的前 N 条
fengwatch.py fund-share --json           纯净 JSON 输出
```

### 默认参数

- 告警阈值: `FUND_SHARE_WARN_PCT = 5.0`（份额日环比变动超过 ±5% 告警）
- HTTP 超时: `FUND_SHARE_TIMEOUT = 15` 秒（交易所 API 不稳定，合理超时）

### 设计决策

1. **使用 urllib 而非 requests**: 避免引入额外依赖，fengwatch.py 原有代码不依赖 requests
2. **JSONP 解析**: SSE 接口返回 JSONP 格式（`callback({...})`），需剥离回调函数包装
3. **份额单位差异**: SSE ETF 为"份"，SSE LOF 和 SZSE 为"万份"——输出时统一标注单位
4. **历史对比**: SSE 接口支持指定日期查询，可获取前一日数据做环比；SZSE 接口无日期参数，需后续对接本地 DB 缓存
5. **不破坏现有功能**: 新功能作为独立子命令添加，不修改任何现有函数逻辑
6. **中文注释**: 所有新代码均有中文注释，风格与 fengwatch.py 一致

## 已知限制

- SZSE 深交所 API 不支持历史日期查询，份额变动对比仅覆盖 SSE 数据
- 交易所 API 可能不稳定或返回空数据，需合理超时和错误处理（已实现）
- 非交易日可能无新数据更新

## 源码参考

- RockyZSU/Stock: `research/opensource-eval/RockyZSU-Stock/fund/fund_share_crawl.py` (SZFundShare / SHFundShare 类)
- RockyZSU/Stock: `research/opensource-eval/RockyZSU-Stock/fund/LOF_Model.py` (ShareModel ORM)
