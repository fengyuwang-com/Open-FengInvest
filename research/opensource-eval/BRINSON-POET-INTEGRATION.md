# POET 协方差估计 + Brinson 绩效归因 -- 集成说明

> 日期: 2026-09-03
> 源码: Qlib (`research/opensource-eval/qlib/`)
> 目标: `tools/fengportfolio.py`

## 变更摘要

在 `fengportfolio.py` 中新增两个子命令 + 三个独立类/函数，从 Qlib 提取核心算法，零 qlib 依赖。

### 新增子命令

| 子命令 | 功能 | 用法示例 |
|--------|------|----------|
| `cov-advanced` | 高级协方差矩阵估计（POET / Structured / Shrinkage） | `fengportfolio.py cov-advanced --tickers A,B,C --method poet --num-factors 5` |
| `brinson` | Brinson 绩效归因（配置/选择/交互三因子分解） | `fengportfolio.py brinson --port-weights w.json --bench-weights b.json --port-returns r.json --bench-returns r.json` |

### 新增类/函数

| 名称 | 来源 | 说明 |
|------|------|------|
| `_POETCovEstimator` | `qlib/model/riskmodel/poet.py` | POET 主正交补阈值协方差估计（Fan, Liao & Mincheva 2013） |
| `_StructuredCovEstimator` | `qlib/model/riskmodel/structured.py` | PCA/FA 结构化协方差估计（Fan, Liao & Liu 2016） |
| `_brinson_attribution()` | `qlib/backtest/profit_attribution.py` | Brinson-Fachler 绩效归因核心计算 |

## cov-advanced 参数

```
--tickers A,B,C          标的列表（本地 DB 日收盘）
--returns-file f.csv     或从 CSV 读取（date,ticker,close/return）
--method poet            poet|structured|shrinkage（默认 poet）
--num-factors N          POET/Structured 因子数（默认 0=纯 POET, structured 默认 10）
--thresh T               POET 阈值常数（默认 1.0）
--thresh-method soft     soft|hard|scad（默认 soft）
--factor-model pca       pca|fa（仅 structured，默认 pca）
--json                   JSON 输出
```

### 三种方法对比

| 方法 | 原理 | 依赖 | 适用场景 |
|------|------|------|----------|
| POET | PCA 降维 + 残差相关矩阵阈值收缩 | numpy only | 高维资产协方差（N > T 时尤其有效） |
| Structured | PCA/FA 因子模型，cov = F cov(B) F^T + diag(var(U)) | numpy + sklearn | 有明确因子结构的资产池 |
| Shrinkage | Ledoit-Wolf 常数目标收缩 | numpy only | 通用，稳健 |

## brinson 参数

```
--port-weights w.json    组合行业权重 JSON: {"行业": 小数权重, ...}
--bench-weights b.json   基准行业权重 JSON
--port-returns r.json    组合行业收益率 JSON: {"行业": 小数收益率, ...}
--bench-returns r.json   基准行业收益率 JSON
--json                   JSON 输出
```

### Brinson 三因子分解公式

```
RAA（配置效应）= sum((wp_i - wb_i) * (rb_i - Rb))
RSS（选择效应）= sum(wb_i * (rp_i - rb_i))
RIN（交互效应）= sum((wp_i - wb_i) * (rp_i - rb_i))
RTotal = RAA + RSS + RIN
```

其中 Rb = sum(wb_i * rb_i) 为基准总收益。

## 与 Qlib 源码的差异

1. **零 qlib 依赖** -- 所有 import 改为 numpy/sklearn 按需导入
2. **中文注释** -- 全部注释改为中文，符合 FengInvest 编码规范
3. **类型注解** -- 添加 Python type hints
4. **`eig` -> `eigh`** -- POET 中 `np.linalg.eig` 改为 `eigh`（对称矩阵保证实数特征值，更稳定）
5. **懒加载 numpy** -- 通过 `_try_np()` 按需导入，与文件现有模式一致
6. **Brinson 简化** -- 去掉 Qlib 对 `Position`/`D.features`/`C.dpm` 等 Qlib 内部依赖，改为纯函数输入（dict 进 dict 出）
7. **保持 Qlib 原始算法逻辑不变** -- POET 阈值公式、Structured 分解公式、Brinson Q1-Q4 分解均原样保留

## 未修改的现有功能

`check` / `status` / `sector` / `correlate` / `stress` / `optimize` / `risk` / `hrp` 全部未改动，回归测试通过。
