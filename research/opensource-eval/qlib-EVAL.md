# Qlib (Microsoft) - Code-Level Evaluation

> 仓库: https://github.com/microsoft/qlib
> 克隆日期: 2026-09-03
> 评估目标: 与 FengInvest 七层框架的模块级复用/参考价值

---

## 1. 架构总览

Qlib 是微软出品的 AI 量化投资平台，完整覆盖数据采集 -> 因子计算 -> 模型训练 -> 回测 -> 分析的全链路。代码结构清晰，模块松耦合，MIT 协议。

```
qlib/
  data/          # 数据层: 自研二进制存储 + 表达式引擎 (Cython)
  contrib/       # 贡献模块: Alpha158/360 因子、30+ ML/DL 模型、策略、评估、报告
  model/         # 模型基类 + 风险模型 (POET/Structured/Shrinkage)
  backtest/      # 回测引擎: 事件驱动 + 嵌套执行 + Brinson 归因
  strategy/      # 策略基类
  rl/            # 强化学习 (订单执行)
```

---

## 2. 数据层 (Data Layer)

### 2.1 数据存储

Qlib 使用自研的二进制列存储格式 (非 SQLite/CSV)，存放在 `~/.qlib/qlib_data/` 下。核心类:
- `CalendarProvider` - 交易日历
- `InstrumentProvider` - 标的信息
- `FeatureProvider` - 特征数据
- `ExpressionEngine` - 表达式计算引擎 (Cython 加速)

**关键文件**: `qlib/data/data.py`, `qlib/data/storage/file_storage.py`

### 2.2 数据采集器 (scripts/data_collector/)

| 采集器 | 数据源 | 支持市场 | 频率 |
|--------|--------|----------|------|
| yahoo/ | Yahoo Finance | 美股/A股/港股 | 日线 |
| baostock_5min/ | BaoStock | A股 | 5分钟 |
| cn_index/ | 东方财富 | A股指数 | 日线 |
| us_index/ | Yahoo Finance | 美股指数 | 日线 |
| br_index/ | Yahoo Finance | 巴西指数 | 日线 |
| crypto/ | Yahoo Finance | 加密货币 | 日线 |
| fund/ | Yahoo Finance | 基金 | 日线 |
| pit/ | Yahoo Finance | PIT 财报 | 季度 |

**FengInvest 对比**: FengInvest 用 yfinance + AKShare + baostock，数据源更丰富但分散在多个工具里。Qlib 的采集器统一且可扩展，但仅覆盖 OHLCV + 基本财报，没有 AKShare 的实时数据、龙虎榜、融资融券等 A 股特有数据。

### 2.3 表达式引擎 (qlib/data/ops.py)

这是 Qlib 最精华的模块之一。提供 **40+ 个 Cython 加速的算子**，支持复合表达式:

- **Element-Wise**: Abs, Sign, Log, Not, ChangeInstrument
- **Pair-Wise**: Add, Sub, Mul, Div, Power, Greater, Less, And, Or
- **Rolling**: Mean, Std, Var, Skew, Kurt, Max, Min, Rank, Quantile, Med, Mad, Slope, Rsquare, Resi, Corr, Cov, Delta, Count, EMA, WMA, IdxMax, IdxMin
- **Pair-Rolling**: Corr, Cov (双变量滚动)
- **Conditional**: If
- **Time**: TResample

表达式语法示例: `Ref($close, 5)/$close`, `Mean($close, 20)`, `Corr($close, Log($volume+1), 20)`

**FengInvest 对比**: FengInvest 的 `fengquant.py` 只有 6 个因子 (PE/FwdPE/ROE/利润率/收入增长/D/E + 动量)，用 yfinance info 字典取值。Qlib 的表达式引擎在技术因子计算上强几个数量级。

### 2.4 PIT (Point-in-Time) 数据库

`qlib/data/pit.py` 实现了 PIT 查询算子 `P()`，支持用财报发布日期对齐数据，避免未来函数。

**FengInvest 对比**: FengInvest 的 `fengpit.py` 也有 PIT 双轴可见性 (us/cn)，功能类似但实现独立。

---

## 3. 因子/Alpha 库

### 3.1 Alpha158 (qlib/contrib/data/loader.py)

158 个因子，基于 5/10/20/30/60 日滚动窗口，涵盖:

| 类别 | 因子 | 数量 |
|------|------|------|
| K线形态 | KMID, KLEN, KMID2, KUP, KUP2, KLOW, KLOW2, KSFT, KSFT2 | 9 |
| 价格水平 | OPEN/HIGH/LOW/VWAP x 5窗口 | 25 |
| 成交量 | VOLUME x 5窗口 | 5 |
| 趋势 | ROC, MA, STD, BETA, RSQR, RESI | 30 |
| 极值 | MAX, MIN, QTLU, QTLD | 20 |
| 位置 | RANK, RSV, IMAX, IMIN, IMXD | 25 |
| 量价相关 | CORR, CORD | 10 |
| 趋势统计 | CNTP, CNTN, CNTD | 15 |
| RSI 系 | SUMP, SUMN, SUMD | 15 |
| 量能 | VMA, VSTD, WVMA, VSUMP, VSUMN, VSUMD | 30 |

### 3.2 Alpha360

360 个因子，60 天的原始 OHLCV 价格 (归一化)，适合深度学习模型。

### 3.3 因子计算方式

Qlib 的因子是**声明式表达式**，在数据加载时由表达式引擎实时计算:
```python
fields = ["Ref($close, 5)/$close", "Mean($close, 20)/$close", "Std($close, 20)/$close"]
```

**FengInvest 对比**: FengInvest 用命令式 Python 计算因子。Qlib 的声明式方式更易维护和组合，但需要二进制存储支持。

---

## 4. 回测引擎 (Backtest Engine)

### 4.1 架构

事件驱动 + 嵌套执行器设计:

```
Strategy -> TradeDecision -> Executor -> Exchange -> Position
    |                                            |
    +--- collect_data_loop (generator) ---------+
```

核心文件:
- `qlib/backtest/backtest.py` - 主循环 (Generator 模式)
- `qlib/backtest/exchange.py` - 交易所模拟 (滑点/冲击成本/涨跌停)
- `qlib/backtest/executor.py` - 嵌套执行器 (日线套分钟线)
- `qlib/backtest/position.py` - 持仓管理
- `qlib/backtest/account.py` - 账户管理

### 4.2 Brinson 归因

`qlib/backtest/profit_attribution.py` 实现了 Brinson 绩效归因:
- RAA (资产配置超额收益)
- RSS (个股选择超额收益)
- RIN (交互效应)
- 支持按行业/市值分组

### 4.3 策略

- `TopkDropoutStrategy` - TopK 轮换策略 (定期替换表现最差的 N 只)
- `WeightStrategyBase` - 权重策略基类
- `EnhancedIndexingStrategy` - 增强指数策略 (风险模型优化 + 跟踪误差控制)
- `SignalStrategy` - 基于信号的策略

### 4.4 评估

`qlib/contrib/evaluate.py` 提供:
- `risk_analysis()` - 风险分析 (年化收益/IR/最大回撤)
- `indicator_analysis()` - 交易指标分析 (价格优势/正向率/成交率)
- `backtest_daily()` - 日线回测入口

**FengInvest 对比**: FengInvest 用 vnpy 范式 + 量化回测 (`fengbacktest.py`)，支持 T+1 对齐/涨跌停过滤/冲击成本。Qlib 的嵌套执行器设计更灵活 (支持多时间尺度)，但 Brinson 归因是 FengInvest 没有的。两者可互补: Qlib 的归因分析可直接复用到 FengInvest 的组合层。

---

## 5. 风险模型 (Risk Model)

### 5.1 StructuredCovEstimator (qlib/model/riskmodel/structured.py)

基于 PCA/FA 的结构化协方差估计:
```python
X = B @ F.T + U
cov(X.T) = F @ cov(B.T) @ F.T + diag(var(U))
```
支持 PCA 和 Factor Analysis 两种因子模型。

### 5.2 POETCovEstimator (qlib/model/riskmodel/poet.py)

主正交补阈值估计 (POET)，支持 soft/hard/scad 三种阈值方法。适用于大维协方差矩阵估计。

### 5.3 ShrinkageCovEstimator (qlib/model/riskmodel/shrink.py)

协方差收缩估计。

**FengInvest 对比**: FengInvest 的 `fengportfolio.py` 有 HRP (层次风险平价) 和 CVaR 风险归因，但没有因子模型协方差估计。Qlib 的 POET/Structured 模型可直接用于 FengInvest 的组合优化。

---

## 6. 模型库 (Model Zoo)

### 6.1 监督学习模型 (30+)

| 类别 | 模型 | 文件 |
|------|------|------|
| GBDT | XGBoost, LightGBM, CatBoost | xgboost.py, gbdt.py, catboost_model.py |
| GBDT 增强 | DoubleEnsemble | double_ensemble.py |
| RNN | LSTM, GRU, ALSTM | pytorch_lstm.py, pytorch_gru.py, pytorch_alstm.py |
| CNN | TCN, ADD | pytorch_tcn.py, pytorch_add.py |
| Attention | GATs, HIST | pytorch_gats.py, pytorch_hist.py |
| Transformer | Transformer, Localformer, TRA | pytorch_transformer.py, pytorch_localformer.py, pytorch_tra.py |
| MLP | MLP, TabNet, SFM, Sandwich | pytorch_nn.py, pytorch_tabnet.py, pytorch_sfm.py, pytorch_sandwich.py |
| Meta | DDG-DA | contrib/rolling/ddgda.py |
| 时间序列 | ALSTM_TS, GATs_TS, LSTM_TS 等 | *_ts.py 系列 |

### 6.2 强化学习

RL 用于订单执行优化:
- PPO, OPDS, TWAP
- 支持多层嵌套环境

### 6.3 模型训练框架

- `qlib/model/base.py` - 模型基类
- `qlib/model/trainer.py` - 训练器
- `qlib/model/ens/` - 集成学习
- `qlib/model/interpret/` - 模型解释

**FengInvest 对比**: FengInvest 不依赖 ML 模型做选股 (七层框架是规则驱动 + 人类判断)。Qlib 的模型库是为纯量化 Alpha 挖掘设计的，与 FengInvest 的哲学不同。但如果未来 FengInvest 想在 L2b 层引入 ML 信号，Qlib 的 GBDT 模型可直接用。

---

## 7. 独特工具 (FengInvest 没有的)

| 工具 | 功能 | FengInvest 可用性 |
|------|------|-------------------|
| POET 协方差估计 | 大维协方差估计 | **可直接复用** - 增强 fengportfolio.py 的优化器 |
| Brinson 绩效归因 | 配置/选择/交互效应分解 | **可直接复用** - 组合层归因分析 |
| DDG-DA | 概念漂移自适应 | **可参考** - 市场状态切换的思路 |
| 嵌套执行器 | 多时间尺度回测 | **可参考** - 日线+分钟线的嵌套策略 |
| TopK 轮换策略 | 定期替换最差持仓 | **可参考** - 组合再平衡的思路 |
| Enhanced Indexing | 风险模型约束优化 | **可参考** - 指数增强思路 |
| 增强表达式引擎 | 40+ Cython 算子 | **可参考** - 技术因子计算模式 |
| Alpha158/360 | 标准化因子集 | **可参考** - 因子设计参考 |

---

## 8. 模块级复用判定

### 可直接复用 (Copy/Import)

1. **POET/Structured 协方差估计器** (`qlib/model/riskmodel/`)
   - 代码: `poet.py`, `structured.py`, `shrink.py`
   - 理由: 纯数学实现，无外部依赖 (仅 numpy/scipy)，接口清晰
   - 用途: 增强 `fengportfolio.py` 的风险模型，替代简单的经验协方差

2. **Brinson 绩效归因** (`qlib/backtest/profit_attribution.py`)
   - 代码: `brinson_pa()` 及辅助函数
   - 理由: 独立模块，输入输出明确 (positions -> 归因 DataFrame)
   - 用途: 组合层 P 的绩效分析

3. **Alpha158 因子定义** (`qlib/contrib/data/loader.py`)
   - 代码: `Alpha158DL.get_feature_config()` 的因子列表
   - 理由: 因子表达式是纯字符串，可提取用于 FengInvest 的技术因子
   - 用途: 扩展 fengquant.py 的因子库

### 可参考 (需重写适配)

4. **表达式引擎** (`qlib/data/ops.py`)
   - 原因: 依赖 Qlib 自研二进制存储，无法直接跑在 FengInvest 的 SQLite/yfinance 上
   - 参考价值: 算子设计模式 (Rolling 基类 + 子类)、Cython 加速思路
   - 适配方向: 可提取 Pandas 版算子 (非 Cython 版) 用于 FengInvest

5. **嵌套回测执行器** (`qlib/backtest/executor.py`)
   - 原因: 与 Qlib 的 Exchange/Position 紧密耦合
   - 参考价值: 多时间尺度 (日线套分钟线) 的架构设计
   - 适配方向: FengInvest 已有 vnpy 范式回测，可借鉴嵌套思路

6. **DDG-DA 概念漂移** (`qlib/contrib/rolling/ddgda.py`)
   - 原因: 依赖 Qlib 的数据管线和训练器
   - 参考价值: 市场动态自适应的思路
   - 适配方向: 可简化为 FengInvest 的市场状态检测模块

7. **TopK 轮换策略** (`qlib/contrib/strategy/signal_strategy.py`)
   - 原因: 依赖 Qlib 的 Signal/Exchange/Position 体系
   - 参考价值: 定期再平衡 + 轮换的逻辑
   - 适配方向: 可参考其 hold_thresh/forbid_all_trade_at_limit 逻辑

8. **Enhanced Indexing 策略** (`qlib/strategy/optimizer/enhanced_indexing.py`)
   - 原因: 依赖风险模型数据 + Qlib 基础设施
   - 参考价值: 风险约束优化 + 跟踪误差控制
   - 适配方向: FengInvest 的组合优化可借鉴约束优化思路

### 不适用

9. **模型库 (30+ ML/DL 模型)**
   - 原因: FengInvest 是规则驱动 + 人类判断框架，不依赖 ML 选股
   - 不适用: 模型训练/推理流程与 FengInvest 架构冲突
   - 例外: 如果未来在 L2b 层引入 ML 信号，LightGBM 可直接用

10. **Qlib 自研存储格式**
    - 原因: FengInvest 用 SQLite + 本地文件，迁移成本高
    - 不适用: 存储层完全不兼容

11. **强化学习模块** (`qlib/rl/`)
    - 原因: FengInvest 不做高频/订单执行优化
    - 不适用: 架构目标不同

12. **在线服务模块** (`qlib/contrib/online/`)
    - 原因: FengInvest 有 fengweb 自己的 Web 服务
    - 不适用: 重复功能

---

## 9. 能否增强 fengquant.py 的 6 因子系统?

### 结论: 有价值但需选择性引入

fengquant.py 当前的 6 个因子:
1. value_pe (PE)
2. value_fwd_pe (Fwd PE)
3. quality_roe (ROE)
4. profit_margin (利润率)
5. growth_revenue (收入增长)
6. leverage_de (D/E)
7. momentum_6m (6 月动量)

**Qlib 可补充的技术因子** (从 Alpha158 提取):

| 因子 | 来源 | FengInvest 适用性 |
|------|------|-------------------|
| ROC (Rate of Change) | Alpha158 | 可替代 momentum_6m 的简化版 |
| STD (波动率) | Alpha158 | 风险维度，fengquant 目前没有 |
| BETA (趋势斜率) | Alpha158 | 趋势强度，可增强 L2b |
| RSQR (线性拟合 R^2) | Alpha158 | 趋势质量，可增强 L2b |
| RSV (相对强弱) | Alpha158 | 价格位置，可增强 L2b |
| CORR (量价相关) | Alpha158 | 量价背离检测 |
| CNTP/CNTN (涨跌天数比) | Alpha158 | 趋势统计 |

**建议**: 不要直接搬 Qlib 的表达式引擎 (太重)，而是提取 5-8 个关键技术因子用 Pandas 实现，集成到 fengquant.py 或新建 `fengtechnicals.py`。具体步骤:

1. 从 Alpha158 提取: ROC_20, STD_20, BETA_20, RSQR_20, CORR_20, CNTP_20
2. 用 Pandas 实现 (非 Cython)，复用 FengInvest 的 yfinance 数据
3. 与现有 6 个基本面因子并列输出，不改变七层框架结构

---

## 10. 总结评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 代码质量 | 9/10 | 微软工程标准，注释完善，测试齐全 |
| 架构设计 | 9/10 | 松耦合模块化，表达式引擎优雅 |
| 与 FengInvest 兼容性 | 4/10 | 存储/数据管线不兼容，哲学不同 (纯量化 vs 七层框架) |
| 复用价值 | 7/10 | 风险模型/归因/因子定义可直接复用 |
| 最大收获 | - | POET 协方差估计 + Brinson 归因 + Alpha158 因子设计 |
