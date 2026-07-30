# Awesome-Quant 价值投资适配分析

> 来源：[awesome-quant](research/070-reports/000-awesome-quant.md) — 量化金融工具大全
> 目的：筛出对 FengInvest 7层框架**立即有用**的库，聚焦价值投资工作流

## 一、优先级金字塔

```
★★★★★ 核心价值（立即集成）
★★★★   ｜ 高价值（本周研究）
★★★     ｜ 不错（下季度）
★★       ｜ 看看
★         ｜ 不相关（期权/高频/加密货币）
```

---

## 二、各层适配清单

### M 层 — 市场数据 & 基本面

| 库 | 优先级 | 对 FengInvest 的价值 |
|:---|:------|:-------------------|
| **[FinanceToolkit](https://github.com/JerBouma/FinanceToolkit)** | ★★★★★ | 200+ 财务指标、80+ 财务比率，可做 PE/PB/ROE 的外部交叉验证。比 fengfundamentals 覆盖更广 |
| **[edgartools](https://github.com/dgunning/edgartools)** | ★★★★★ | AI-native SEC EDGAR 库，XBRL 结构化财报。可以替代部分 yfinance 基本面，用于 US 上市公司深挖 |
| **[FinanceDatabase](https://github.com/JerBouma/FinanceDatabase)** | ★★★★ | 30万+ 证券符号数据库，可做市场范围审计（我们有没有漏掉某个 ETF 或 index？） |
| **[finagg](https://github.com/theOGognf/finagg)** | ★★★★ | 免费财务 API 聚合，历史数据 → SQL 数据库。架构和我们 `fengdbrefine.py` 思路一致，可借鉴 |
| **[Tradevo Data](https://github.com/christianpichichero-max/pit-fundamentals)** | ★★★★ | **Point-in-time 基本面** — 标注每条财务数据首次公开日期。消除回测中的 lookahead bias，对我们策略验证 #38-#42 极有价值 |
| **[lse-data](https://github.com/londonstrategicedge/lse-data)** | ★★★★ | 免费实时/历史 tick 数据，118,000+ 数据集（美股 2003 年起，经济数据 1900 年起）。可用于非 US/CN/HK 市场的扩展 |
| **[StockVektor](https://stockvektor.com)** | ★★★★ | 免费 US 股票研究：Piotroski F-Score、Altman Z-Score、Beneish M-Score、ROIC、EV/EBIT、13F 超级投资者持仓。直接用于 L2a 定性参考 |
| **[disclosure-alpha](https://github.com/alwank/disclosure-alpha)** | ★★★ | SEC 10-K/10-Q 自动分析：章节提取、语气指标、年份对比。可做 L0 行业扫描的补充数据源 |
| **[FilingFirehose](https://filingfirehose.com)** | ★★★ | SEC 法务风险评分（0-100），8-K 隐藏事件检测。用于 L3 碰撞的"反方检查"输入 |
| **[AlphaSMO](https://github.com/alphasmo/alphasmo-tools)** | ★★★ | 13F 机构持仓 + Form 4 内部人交易信号。可用于管理层质量判断的补充 |
| **[KeepRule](https://keeprule.com)** | ★★ | 巴菲特/芒格的决策原则库，和 knowledge/principles/ 定位重复，但内容可交叉参考 |

### L2b 层 — 量化因子分析

| 库 | 优先级 | 价值 |
|:---|:------|:-----|
| **[alphalens-reloaded](https://github.com/stefan-jansen/alphalens-reloaded)** | ★★★★★ | 已经在用。这是 alphalens 的活跃 fork，确认用这个版本 |
| **[Factor Weave](https://factorweave.com)** | ★★★★ | 因子评分、相似度搜索、免泄漏+免幸存者偏差的 forward-return 标签。免费层可用，用于验证 fengquant 输出 |
| **[Alpha Skills](https://github.com/VernonOY/alpha-skills)** | ★★★ | AI 辅助因子研究，支持 A 股/HK/US。探索性，看有没有我们遗漏的关键因子 |

### L3 层 — 组合 & 风控

| 库 | 优先级 | 价值 |
|:---|:------|:-----|
| **[PyPortfolioOpt](https://github.com/robertmartin8/PyPortfolioOpt)** | ★★★★★ | 经典组合优化（有效前沿/风险平价/HRP）。可用于 fengscreen 的四维排名验证 |
| **[skfolio](https://github.com/skfolio/skfolio)** | ★★★★★ | sklearn 风格的组合优化库，比 PyPortfolioOpt 更新、API 更现代。有交叉验证功能 |
| **[Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib)** | ★★★★ | 组合优化 + 战略资产配置，支持 CVaR 优化。可用于持仓管理的权重计算 |
| **[pyfolio-reloaded](https://github.com/stefan-jansen/pyfolio-reloaded)** | ★★★★ | fengscreen 回测绩效报告的参考基准。确认用 reloaded 版 |
| **[riskkit](https://github.com/HasibVortex369/riskkit)** | ★★★ | 框架无关的风险管理：仓位计算、回撤控制、止损引擎。可拆出有用部分加入 fengwatch |
| **[purgedcv](https://github.com/eslazarev/purged-cross-validation)** | ★★★ | 防数据泄漏的交叉验证。策略验证 #38-#42 的统计检验可借鉴 |
| **[AutoHypothesis](https://github.com/arteemg/AutoHypothesis)** | ★★ | Agentic alpha 发现：经济假设 → 样本内迭代 → 样本外验证。工作流灵感 |

### 策略验证层 — #38-#42 回测

| 库 | 优先级 | 价值 |
|:---|:------|:-----|
| **[vectorbt](https://github.com/polakowo/vectorbt)** | ★★★★★ | 矢量化回测，比 backtrader 快 100x。适用大规模参数网格扫描（和 leftright.py 的 Phase 1 需求一致） |
| **[backtest-bias](https://github.com/Finance-broski/backtest-bias)** | ★★★★★ | 回测幸存者偏差检测！非常直接相关。我们的数据库有退出股票，但回测代码是否有 bias？这个库能验证 |
| **[backtester-mcp](https://pypi.org/project/backtester-mcp/)** | ★★★★ | MCP 回测引擎，内置反过拟合检查（PBO、deflated Sharpe、bootstrap CI）。可做 L3 碰撞的辅助裁判 |
| **[AlphaAssay](https://alphaassay.com)** | ★★★★ | 回测统计检验服务：deflated Sharpe、PBO 检测、placebo 检验。用于最终报告中的统计可靠性标注 |
| **[rulelint](https://github.com/momoddo/rulelint)** | ★★★ | 交易规则 lint：检测 look-ahead 条件、死分支、过期阈值。在写 fengrule 时可借鉴 |
| **[Implied Expectations](https://github.com/Keenan-ux/implied-expectations)** | ★★★★★ | **重点** — 反向 DCF，从股价反推市场隐含的增长预期。直接对应 M 层的"当前价格反映的预期"分析，也对应息价原则的安全边际衡量 |

### DK 知识库补充

| 资源 | 说明 |
|:-----|:-----|
| **[Value Investing Studies](https://github.com/euclidjda/value-investing-studies)** | 价值投资长期表现的数据研究，可补充到 `research/110-strategy-verification/` |
| **[Tidy Finance](https://www.tidy-finance.org/)** | 规范的实证金融研究框架，Python+R 双语言。代码风格可借鉴 |
| **[Systematic Trading](https://github.com/robcarver17/pysystemtrade)** | Robert Carver 的系统化交易框架，可用于趋势跟踪/L2b 因子验证 |
| **[finite differences](https://github.com/bboutelje/qox-python-samples)** | Rust 实现的有限差分定价库，DCF 计算中可选加速 |

---

## 三、立即行动项（本周）

### 🥇 最高优先级

| # | 行动 | 对哪个层 | 预期效果 |
|:-:|:----|:--------|:--------|
| 1 | **集成 `implied-expectations`** 到 M 层输出 | M / 息价原则 | 自动计算每只股票的市场隐含增长预期，和我们的 DCF 估值对比 |
| 2 | **用 `edgartools` 补充 US 基本面** | M / L2b | 解决现有 36 只 US 缺失基本面问题，且数据更准确 |
| 3 | **评估 `backtest-bias`** 检查已有回测 | 策略验证 | 确认 #1-#37 的回测结论不受幸存者偏差影响 |
| 4 | **将 `skfolio` 或 `PyPortfolioOpt`** 加入 fengscreen 的风控层 | L3 | 替代手动等权组合加权，实现风险平价/有效前沿优化 |

### 🥈 次优先级（2 周内）

| # | 行动 | 原因 |
|:-:|:----|:-----|
| 5 | 研究 `Tradevo Data` 的 point-in-time 基本面方案 | 可能需要对现有回测做 lookahead bias 审计 |
| 6 | 试用 `FinanceToolkit` 做 US/CN 财务指标的交叉验证 | 对比已有 fengfundamentals 的精度 |
| 7 | 看看 `StockVektor` 的评分体系能否作为 L2a 的辅助输入 | F-Score/Z-Score 已经在 CLAUDE.md 里提到了 |
| 8 | 把 `KeepRule` 的内容和 `knowledge/principles/` 做交叉参考 | 看有没有遗漏的决策原则 |

---

## 四、与已有工具的重叠

| 已有工具 | awesome-quant 替代/补充 | 结论 |
|:---------|:-----------------------|:----|
| fengdata.py (yfinance) | yfinance (同) | 保持，另加 edgartools 补充 US |
| fengfundamentals.py | FinanceToolkit / finagg | 可参考 API 设计，不替换 |
| fengquant.py | alphalens-reloaded (已在用) | 保持 |
| fengscreen.py | PyPortfolioOpt / skfolio | **建议集成** — 提升组合优化能力 |
| fengrule.py | rulelint | 可参考规则引擎设计 |
| backtest methods (leftright.py) | vectorbt | **建议评估** — 加速参数扫描 |
| knowledge/principles/ | KeepRule | 交叉验证，不替换 |
| research/110-strategy-verification/ | backtest-bias, AlphaAssay | **建议审计** — 验证已测论断 |

---

## 五、不相关类别（跳过）

以下类别与价值投资工作流基本无关，仅在需要时参考：

| 类别 | 原因 |
|:-----|:-----|
| Technical Indicators | 18 个库。我们策略验证测了均线类论断，但日常不依赖技术指标 |
| Financial Instruments & Pricing | 期权定价/固收定价库，不适用于股票价值投资 |
| Sentiment & Alt Data | 舆情数据偏短期交易，与价值投资框架冲突 |
| Prediction Markets | 预测市场，非核心 |
| Visualization | 已用 finplot/mplfinance，够用 |
| Excel Integration | 不使用 Excel 工作流 |
| Cross-Language | 纯 Python 栈，不需要 |
| Commercial Services | 付费服务，优先用免费方案 |

---

## 六、总结

**最大的三个机会：**

1. **`implied-expectations`** — 反向 DCF 完美契合"当前价格反映什么预期"这个核心问题，应优先集成到 M 层
2. **`edgartools`** — 解决 US 基本面缺失问题，而且是 AI-native 设计，和我们框架理念一致
3. **`skfolio`/`PyPortfolioOpt`** — 填补组合优化这一块的工程空白，替代手动等权

**最大的一个风险：**
- 已有 29 条回测论断没有经过 **幸存者偏差** 和 **lookahead bias** 审查。`backtest-bias` 和 `Tradevo Data` 应该优先用来审计。如果发现某些论断结论反转，需要立即修正在 000-README.md 中的标记。
