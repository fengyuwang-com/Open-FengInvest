# fengtechnicals.py 集成说明

> 日期: 2026-09-03
> 来源: Qlib Alpha158 因子定义（`qlib/contrib/data/loader.py` + `qlib/data/ops.py`）

## 做了什么

从 Qlib Alpha158 数据集中提取 6 个技术因子，用纯 Pandas 重新实现（不依赖 Qlib），新建 `tools/fengtechnicals.py`。

## 6 个因子及其 Qlib 原始表达式

| 因子 | Qlib 表达式 | Pandas 等价 | 含义 |
|:-----|:-----------|:-----------|:-----|
| ROC | `Ref($close, N)/$close` | `close.shift(N)/close` | N 日前价格与当前价之比（变化率） |
| STD | `Std($close, N)/$close` | `close.rolling(N).std()/close` | 归一化波动率 |
| BETA | `Slope($close, N)/$close` | 滚动 OLS 斜率 / close | 归一化趋势斜率 |
| RSQR | `Rsquare($close, N)` | 滚动 OLS R² | 趋势线性度（拟合质量） |
| CORR | `Corr($close, Log($volume+1), N)` | `close.rolling(N).corr(log(volume+1))` | 量价相关性 |
| CNTP | `Mean($close>Ref($close,1), N)` | 上涨天数比例滚动均值 | 上涨天数占比 |

## 与 Qlib 的关键差异

1. **BETA/RSQR**: Qlib 用 Cython 实现 `rolling_slope`/`rolling_rsquare`，我们用纯 Python 循环 + numpy 做 OLS。性能略低但功能等价。
2. **CORR**: Qlib 在 `std≈0` 时置 NaN（`atol=2e-05`），Pandas `rolling.corr` 的默认行为已覆盖此边界。
3. **ROC 语义**: Qlib 的 `Ref($close, N)/$close` >1 表示 N 日前更贵（期间下跌），<1 表示上涨。与常见 ROC 指标（当前价/N日前价）**互为倒数**。

## 数据源

优先 `data/market_data.db`（本地 SQLite，13M+ 行日线），回退 yfinance。与 FengInvest 数据管理铁律一致（`fengdb.py safe_batch`）。

## 输出格式

与 `fengquant.py` 风格一致：
- JSON（默认）: ticker / name / window / factors[] (current_value + percentile + mean/std/min/max)
- 表格（`--no-json`）: 终端可读表格
- 支持单只、批量、单因子（`--factor`）模式

## 用法

```bash
python tools/fengtechnicals.py 0700.HK                  # 单只六因子
python tools/fengtechnicals.py 0700.HK AAPL MSFT        # 批量
python tools/fengtechnicals.py 0700.HK --window 30      # 30 日窗口
python tools/fengtechnicals.py 0700.HK --factor ROC     # 单因子
python tools/fengtechnicals.py 0700.HK --no-json        # 表格输出
```

## 文件变更

| 文件 | 操作 |
|:-----|:-----|
| `tools/fengtechnicals.py` | 新建 |
| `AGENTS.md` | 关键工具表新增条目（+1 工具，62→63） |
| `research/opensource-eval/TECHNICALS-INTEGRATION.md` | 本文件 |
