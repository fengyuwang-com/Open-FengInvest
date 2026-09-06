# 东财涨停池 + 腾讯基金 NAV 集成说明

> 集成日期: 2026-09-03
> 源码仓库: RockyZSU/Stock
> 目标文件: `tools/fengdata.py`

---

## 1. 集成内容

从 `RockyZSU-Stock` 提取了两组 API 并集成到 `fengdata.py`：

### 1.1 东财涨停池 API（5 池）

从 `RockyZSU-Stock/datahub/dfcf_hot_block.py` 提取，覆盖东财涨停板行情的全部 5 个池：

| 池代码 | 池名称 | API URL | 说明 |
|--------|--------|---------|------|
| `zt` | 涨停股池 | `getTopicZTPool` | 当日涨停，含封板时间/资金/连板数 |
| `qs` | 强势股池 | `getTopicQSPool` | 60日新高/近期多次涨停的强势股 |
| `zb` | 炸板股池 | `getTopicZBPool` | 涨停后打开（炸板），含振幅/涨速 |
| `dt` | 跌停股池 | `getTopicDTPool` | 当日跌停，含动态市盈率/连续跌停 |
| `yz` | 昨日涨停股池 | `getYesterdayZTPool` | 昨日涨停今日表现，含昨日封板时间 |

**关键参数：**
- `ut` token：从 `quote.eastmoney.com/ztb/newstatic/build/detail.js` 动态提取，缓存 5 分钟
- `date`：交易日 YYYYMMDD 格式
- `dpt`：固定值 `wz.ztzt`

### 1.2 腾讯基金 NAV 估算 API

从 `RockyZSU-Stock/fund/fund_info_spider.py` 的 `TencentFundSpider.get_netvalue()` 提取，采用双源策略：

- **主源**: `http://qt.gtimg.cn/q=jj{code}`（稳定，返回基金名称/单位净值/累计净值/涨跌幅/日期）
- **备源**: `http://web.ifzq.gtimg.cn/fund/newfund/fundSsgz/getSsgz`（历史净值序列，当前可能离线）
- 主源失败时自动回退备源

---

## 2. 用法

```bash
# 东财涨停池 — 默认获取全部 5 池（当日）
python tools/fengdata.py zt-pools

# 指定日期
python tools/fengdata.py zt-pools --date 20260901

# 只获取指定池（逗号分隔）
python tools/fengdata.py zt-pools --pools zt,qs,dt

# 腾讯基金 NAV 估算 — 单只
python tools/fengdata.py --fund-nav 160137

# 多只基金
python tools/fengdata.py --fund-nav 160137 005827 519736
```

---

## 3. 实现细节

### 3.1 代码位置

所有新代码作为独立函数添加在 `tools/fengdata.py` 中（约 280 行），位于 Sina 财务报表函数之后、Mode dispatch 之前：

- `_zt_get_ut()` — ut token 获取（缓存 5 分钟）
- `_zt_http_get()` — 统一 HTTP GET + 0.5s 限流
- `_zt_format_time()` — 封板时间格式化
- `_zt_parse_ztstats()` — 涨停统计解析
- `_zt_pool_fetch()` — 统一池获取（URL/参数映射）
- `_cmd_zt_pools()` — `zt-pools` CLI 入口
- `_fund_nav_fetch()` — 单只基金 NAV 估算
- `_cmd_fund_nav()` — `--fund-nav` CLI 入口

### 3.2 依赖

仅使用 stdlib（`urllib.request`、`json`、`re`、`time`），无新增第三方依赖。

### 3.3 限流与错误处理

- **东财 API**: 每次请求间隔 0.5 秒（`time.sleep(0.5)`），ut token 缓存 5 分钟
- **腾讯 API**: 每只基金间隔 0.3 秒
- **错误处理**: 单池/单基金失败不影响其他，错误信息返回在 JSON 中
- **User-Agent**: 模拟 Chrome 138 浏览器，带完整 Sec-Fetch 头

### 3.4 与现有代码的关系

- 不修改任何现有函数，完全独立的子命令
- CLI 调度在 `main()` 中位于 `--sina-financials` 之后、ticker 解析之前
- 所有新函数以 `_` 开头（内部 API），命令入口以 `_cmd_` 开头

---

## 4. 输出格式

### zt-pools JSON 结构

```json
{
  "date": "20260903",
  "fetched_at": "2026-09-03T15:30:00",
  "data_source": "eastmoney push2ex API",
  "pools": {
    "zt": {
      "name": "涨停股池",
      "count": 45,
      "stocks": [
        {
          "代码": "000001",
          "名称": "平安银行",
          "最新价": 12.50,
          "涨跌幅": 10.01,
          "连板数": 3,
          "首次封板时间": "09:30:15",
          "封板资金": 1234567890,
          "所属行业": "银行"
        }
      ]
    }
  }
}
```

### fund-nav JSON 结构

```json
{
  "count": 2,
  "fetched_at": "2026-09-03T22:08:56",
  "funds": [
    {
      "fund_code": "160137",
      "name": "南方中证互联网指数(LOF)A",
      "nav_estimate": 1.7912,
      "nav_accumulated": 1.7912,
      "change_pct": -0.4059,
      "nav_date": "2026-09-03",
      "source": "qt.gtimg.cn (腾讯基金)",
      "updated_at": "2026-09-03T22:08:56"
    },
    {
      "fund_code": "005827",
      "name": "易方达蓝筹精选混合",
      "nav_estimate": 1.4919,
      "nav_accumulated": 1.4919,
      "change_pct": -0.5996,
      "nav_date": "2026-09-03",
      "source": "qt.gtimg.cn (腾讯基金)",
      "updated_at": "2026-09-03T22:08:56"
    }
  ]
}
```

---

## 5. 注意事项

1. **东财 ut token** 是动态的，每次启动会自动获取，缓存 5 分钟，频繁调用可能触发风控
2. **涨停池数据仅保留最近 30 个交易日**（炸板池和跌停池有此限制）
3. **腾讯基金 NAV** 主源 `qt.gtimg.cn` 稳定可用；备源 `getSsgz` 当前离线（接口返回 `code:21 interface offline`），但代码保留为回退路径
4. 交易日外调用涨停池会返回空数据（非报错）
5. 所有新代码仅依赖 Python stdlib，无新增第三方依赖
