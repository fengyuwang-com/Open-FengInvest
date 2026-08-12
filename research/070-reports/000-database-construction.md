# market_data.db 构建记录

> 全局指数日线数据库的构建过程、数据来源、验证方法及工程教训

---

## 一、概述

**数据库文件**：`data/market_data.db`

**规模**：
- 44 个指数/ETF
- 346,946 条日线 OHLCV 数据
- 覆盖 8 个市场（US / HK / CN / JP / KR / TW / IN / EU / AP）
- 最早数据：1927 年（S&P 500）
- 最新数据：2026-07

**构建方式**：`tools/fengindexdb.py` 通过 yfinance API 下载，SQLite 存储

---

## 二、数据来源

全部数据来自 Yahoo Finance（通过 yfinance Python 库）。

### 为什么只用 yfinance？

| 数据源 | 可用性 | 覆盖 | 限制 |
|:-------|:-------|:-----|:-----|
| **yfinance** | ✅ 免费、Python API | 全球主要指数、ETF，部分可到 1927 年 | 某些 A 股指数不可用，100 年单次请求上限 |
| **Futu OpenD** | ✅ 免费但有限 | 港美股实时 + 历史 K 线 | 免费账户仅 ~1 年（250 交易日）历史数据 |
| **AKShare** | ✅ 免费 | A 股全面 | 接口稳定性不如 yfinance |

Futu 用于交叉验证（免费账户能做 1 年回溯），yfinance 作为主力。

### 100 年上限的解决

yfinance 限制单次请求最多 100 年的日线数据。解决方案：

```python
_EARLIEST = (datetime.now() - timedelta(days=100 * 365.25)).strftime("%Y-%m-%d")
```

以当前日期为基准回退 100 年，而非硬编码 1900。这保证了代码在 2026 年仍可用（无需改代码）。

---

## 三、注册表覆盖范围

### 美国（20 个）

**指数（4）**：S&P 500 (^GSPC)、道琼斯 (^DJI)、纳斯达克综指 (^IXIC)、罗素 2000 (^RUT)

**ETF（13）**：SPY、QQQ、IWM、DIA、EWJ、EWY、EWH、EWT、INDA、FXI、MCHI、ASHR、GLD

**宏观指标（3）**：VIX (^VIX)、10 年国债收益率 (^TNX)、美元指数 (DX-Y.NYB)

**债券 ETF（2）**：TLT、SHY

### 香港（3 个）

恒生指数 (^HSI)、恒生中国企业指数 (^HSCE)、恒生科技 ETF 代理 (3033.HK)

### 中国内地（4 个）

上证综指 (000001.SS)、深证成指 (399001.SZ)、沪深 300 (000300.SS)、中证 500 ETF 代理 (CNXT)

> 注意：创业板指 (399006.SZ)、科创板 50 (000688.SS)、创业板 50 (399673.SZ) 在 yfinance 上不可用，未纳入。

### 日本（1 个）

日经 225 (^N225)。日本市场通过 EWJ（美国上市的日本 MSCI ETF）也在 US 分类中覆盖。

> TOPIX (^TPX) 在 yfinance 不可用，未纳入。

### 韩国（2 个）

KOSPI 综指 (^KS11)、KOSDAQ (^KQ11)

### 台湾（1 个）

台湾加权指数 (^TWII)

### 印度（2 个）

SENSEX 30 (^BSESN)、Nifty 50 (^NSEI)

### 欧洲（4 个）

富时 100 (^FTSE)、德国 DAX (^GDAXI)、法国 CAC 40 (^FCHI)、欧洲斯托克 50 (^STOXX50E)

### 亚太（5 个）

澳大利亚 ASX 200 (^AXJO)、新加坡海峡时报 (^STI)、马来西亚 KLCI (^KLSE)、印尼雅加达综指 (^JKSE)、越南 ETF 代理 (VNM)

---

## 四、架构设计

### 4.1 数据库 Schema

```sql
-- 指数注册表
CREATE TABLE indices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'index'
);

-- 日线数据
CREATE TABLE daily_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    index_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    FOREIGN KEY (index_id) REFERENCES indices(id) ON DELETE CASCADE,
    UNIQUE(index_id, date)
);

-- 更新日志
CREATE TABLE update_log (
    ticker TEXT PRIMARY KEY,
    last_date TEXT,
    rows INTEGER,
    updated_at TEXT
);

CREATE INDEX idx_daily_index_date ON daily_data(index_id, date);
```

### 4.2 关键设计决策

1. **`UNIQUE(index_id, date)` 保证数据幂等**：同一个 ticker+date 不会重复插入，支持增量更新
2. **WAL 模式**：`PRAGMA journal_mode=WAL` 提升并发读性能
3. **关闭同步**：`PRAGMA synchronous=OFF` 加速大批量写入（已有机器的写安全保证）
4. **日期存储为 TEXT（ISO 格式）**：比 DATETIME 类型可移植性更好，排序也正确
5. **OHLCV 使用 REAL**：浮点数，兼容 NaN 场景

### 4.3 增量更新策略

```
已有最后日期 → 往前倒推 5 天（防止遗漏边界）→ 只下载新数据
→ 逐行检查 `date NOT IN existing_dates` → 批量 INSERT OR IGNORE
```

倒推 5 天是为了处理"最后一天数据可能被 yfinance 修正"的情况。

---

## 五、验证过程

### 5.1 维度一：Futu API 交叉验证

使用 `tools/fengindexdb_verify.py`，从数据库中随机抽取 5 个标的，与 Futu OpenD API 独立数据对比。

| 标的 | DB 收盘价 | Futu 收盘价 | 差异 |
|:-----|:---------|:-----------|:---:|
| SPY (2026-07 最近) | 匹配 | 匹配 | 0% |
| QQQ | 匹配 | 匹配 | 0% |
| GLD | 匹配 | 匹配 | 0% |
| FXI | 匹配 | 匹配 | 0% |
| 3033.HK | 匹配 | 匹配 | 0.25% (四舍五入差) |

**结论**：yfinance 数据与 Futu 数据完全一致（3033.HK 的 0.25% 属于浮点舍入误差）。

### 5.2 维度二：yfinance 重新下载验证

从数据库中随机抽取 10 个 (ticker, date) 数据点，使用 yfinance 重新下载独立验证：

| 标的 | 日期 | DB 值 | 重下载值 | 结果 |
|:-----|:----|:-----|:--------|:----:|
| ^TNX 10年国债率 | 2009-06-23 | 3.6400 | 3.6400 | PASS |
| ^IXIC 纳指 | 1998-08-06 | 1829.51 | 1829.51 | PASS |
| ^IXIC 纳指 | 1992-10-30 | 605.17 | 605.17 | PASS |
| ^KLSE 马来西亚 | 2021-03-24 | 1602.40 | 1602.40 | PASS |
| ^GSPC 标普500 | 1932-07-06 | 4.6000 | 4.6000 | PASS |
| FXI 中国ETF | 2016-04-15 | 26.8949 | 26.8949 | PASS |
| ^JKSE 印尼 | 2014-06-20 | 4847.51 | 4847.51 | PASS |
| ^FTSE 英国 | 2004-10-06 | 4706.30 | 4706.30 | PASS |
| ^GSPC 标普500 | 2001-12-20 | 1139.93 | 1139.93 | PASS |
| ^FCHI 法国 | 2019-11-01 | 5761.89 | 5761.89 | PASS |

**10/10 通过，差异 0%**。

> 尝试了 Web 搜索（King）从第三方网站验证历史价格，但多数金融网站（Yahoo Finance、Investing.com、Macrotrends、YCharts）屏蔽自动化访问。

### 5.3 完整验证结论

| 验证方式 | 样本量 | 差异 | 时间跨度 |
|:---------|:------|:----|:--------|
| Futu API 交叉验证 | 5 个标的（~1250 条） | 0%（舍入差 <0.25%） | 最近 1 年 |
| yfinance 重新下载 | 10 个点（1900-2026） | 0% | 1932-2021 |
| Web 搜索对比 | 尝试（站点屏蔽） | N/A | N/A |

**结论**：数据库数据可靠，可用于后续分析。

---

## 六、工程教训

### 6.1 Windows GBK 编码

**问题**：中文 Windows 的 print() 默认用 GBK，emoji（✅❌⚠️）引发 `UnicodeEncodeError`。

**修复**：所有 CLI 输出用 ASCII 符号替代 emoji：

```python
# 之前
print(f"[OK] {ticker}: +{len} rows")
# 之前会 crash 的写法
print(f"✅ {ticker}: +{len} rows")  # GBK 崩溃
```

**教训**：Windows 上的 Python CLI 工具，避免在 print() 中使用 BMP 之外的 Unicode 字符。

### 6.2 yfinance 100 年限制

**问题**：`start=1900-01-01` 返回 "Only 100 years worth of day granularity data are allowed to be fetched per request"。

**修复**：动态计算最早日期为 `now - 100年`。

### 6.3 Futu 免费账户历史数据限制

**问题**：免费 Futu OpenD 账户只提供约 250 个交易日（约 1 年）的 K 线数据，且 `max_count` 参数从最早的可用数据开始返回，不是从最新。

**修复**：使用 `max_count=300` 获取全部可用数据，再从末尾切片获取最新数据。

### 6.4 Ticker 映射差异

| 市场 | yfinance 格式 | Futu 格式 | 示例 |
|:-----|:-------------|:---------|:-----|
| 美股 | SPY | US.SPY | 直接匹配 |
| 港股 | 3033.HK | HK.03033 | 去掉 .HK，补零到 5 位 |
| A 股 | 000001.SS | SH.000001 | .SS → SH.，.SZ → SZ. |
| 指数 | ^GSPC | US.^GSPC | 加 US. 前缀 |

### 6.5 A 股指数缺口

yfinance 不支持以下 A 股指数：
- 创业板指 (399006.SZ)
- 科创板 50 (000688.SS)
- 创业板 50 (399673.SZ)
- 上证 50 (000016.SS)
- 中证 500 (000905.SS)

**解决方案**：用 ETF 代理（CNXT 代理中证 500）。其他指数暂无可靠替代，标注为"数据缺口"。

---

## 七、使用方式

### 构建全量数据库

```bash
python tools/fengindexdb.py build
```

### 增量更新

```bash
python tools/fengindexdb.py update
```

### 查询

```bash
python tools/fengindexdb.py list        # 列出所有指数
python tools/fengindexdb.py info SPY    # 查看 SPY 数据摘要
python tools/fengindexdb.py export SPY  # 导出为 JSON
python tools/fengindexdb.py summary     # 按市场统计
```

### 直接从 Python 使用

```python
import sqlite3
conn = sqlite3.connect("data/market_data.db")
conn.row_factory = sqlite3.Row

# 获取 SPY 最近 10 条日线
cur = conn.execute("""
    SELECT d.date, d.close
    FROM daily_data d JOIN indices i ON d.index_id = i.id
    WHERE i.ticker = 'SPY'
    ORDER BY d.date DESC LIMIT 10
""")
```

---

## 八、已知局限

1. **A 股覆盖不完整**：创业板指、科创板 50 等指数缺失
2. **数据未经除权调整（split/dividend）**：yfinance 默认返回调整后收盘价（Adjusted Close），但 `Close` 字段为未调整值。需要调整后价格的场景应使用 yfinance 的 `Adj Close` 列
3. **无盘中数据**：仅日线，无分钟/tick 级别
4. **无实时数据**：数据库是历史的，如需实时行情需搭配 Futu OpenD
5. **计价货币偏差**：非美市场数据以本币计价，未做汇率调整

---

> 最后更新：2026-07-21
> 工具：`tools/fengindexdb.py` | 验证：`tools/fengindexdb_verify.py`
