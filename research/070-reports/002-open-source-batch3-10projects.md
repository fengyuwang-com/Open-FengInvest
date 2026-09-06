# 第三批开源源码级研究：10 个项目的借鉴点与替代性评估

> 日期：2026-08-12 ｜ 方法：仓库外 `_research/` 浅克隆，5 个后台子代理逐文件读源码，所有结论引用 file:line，不采信 README 宣传
> 判定标准：价值投资优先；「噪音」= 对内在价值判断零增量的短期信号（股评/涨停榜/技术指标等），不吸收；「能否直接替代我们的方案」是核心问题之一

## 一、总览

| # | 项目 | 定位 | 对 FengInvest 的价值 | 能否直接替代 | 工作量 | 噪音判定 |
|---|---|---|---|---|---|---|
| 1 | implied-expectations | 逆向 DCF「预期投资」 | fengvaluation.py 预期法 + 敏感性分析现成反解引擎 | 部分替代（移植） | S | 纯价值 |
| 2 | FinanceToolkit | 通用财务分析函数库（200+ 比率） | ratios/models 纯计算层可移植 | 不能（数据层冲突） | M | 混杂，只取 ratios+models |
| 3 | pit-fundamentals | PIT 基本面数据集（40 股样本） | fengpit.py 免费对拍基准 + 方法论 | 不能（覆盖太窄） | S | 价值 |
| 4 | edgartools | SEC EDGAR 全能客户端（2.5k star） | **直接替代 fengsec.py**；EntityFacts 喂养 fengpit.py | **能替代 fengsec.py** | M | 价值 |
| 5 | disclosure-alpha | SEC 披露确定性打分（无 LLM） | L2a 会计检查清单客观输入层 | 增强不替代 | S–M | 价值 |
| 6 | akshare | 中国财经数据接口（22k star） | fengdata.py CN 数据层（新浪三表自带披露日） | 部分替代 CN 源 | M | 混杂，只取价值类接口 |
| 7 | quantstats | 组合绩效分析（7.5k star） | fengbacktest 报告输出层 | 不能替代回测，增强报告 | S | 工具性（事后统计） |
| 8 | skfolio | 组合优化（scikit-learn API） | cmd_hrp 直接候选（**无 σ⁴ bug**） | **能替代 cmd_hrp** | S | 价值中立 |
| 9 | Stocksera | 另类数据仪表盘（60+ 数据） | 官方源直连 + 幂等入库模式 | 不能 | S | 噪音为主 |
| 10 | daily_stock_analysis | LLM 股票分析系统（62k star） | LLM 输出契约化 + 预测-结果追踪机制 | 不能 | M | 几乎全是噪音（抄机制不抄逻辑） |

## 二、跨项目关键发现

1. **fengpit.py 数据层的答案已经出现**：edgartools `EntityFacts`（SEC companyfacts API）逐 fact 保留 `filed→filing_date`（得知日）+ `period_end`（财报期）+ `form`（文件类型）双轴（entity/parser.py:184-220），`FactQuery.as_of` 就是 PIT 查询（entity/query.py:318-331），`pit_mode=True` 保留全部版本不去重（entity/entity_facts.py:253-349）。与 pit-fundamentals 的 `first_filed` 语义逐字一致（同源于 companyfacts `filed` 字段，都是 `<= as_of` 过滤）——两项目可互相验证。fengpit 无需自研提取管线。
2. **cmd_hrp 不用手写**：skfolio 的 HRP 无 Riskfolio-Lib 的 σ⁴ 平方两次 bug；距离 d=√(0.5×(1−ρ))=√((1−ρ)/2) 与 Lopez de Prado 论文逐字一致（_distance.py:587），逆方差 1/σ²（_hrp.py:411-413），还内置权重上下限、交易成本、失败回退链。S 工作量接入，替代自研递归二分。
3. **A 股 PIT 数据源缺口被填补**：akshare 新浪三表（`stock_financial_report_sina`）是唯一免费自带「公告日期 + 是否审计」的 A 股三表源——直接升级 fengpit 的 CN 侧。
4. **fengvaluation.py 预期法有现成反解引擎**：implied-expectations 共 337 行纯标准库（model.py + solver.py），「solver never fabricates a number」四模式回退（solver.py:13-14）与 fengquant 的 abstain 哲学同构。
5. **L2a 可机械化一部分**：disclosure-alpha 全程无 LLM（README:18），15 个带证据链的布尔风险 flag + 章节 diff + 抑制词，可直接映射 6 灯检查清单。
6. **62k star 的 daily_stock_analysis 要拆开看**：工程纪律（260 个测试文件/13.4 万行测试、结构化错误枚举、熔断、异常脱敏）名副其实；但其输出契约（sentiment_score / trend_prediction / 狙击点位 / battle_plan）几乎 100% 是短线投机语义——只抄「LLM 输出契约化 + 预测-结果追踪」两个机制，拒绝全部投资逻辑。
7. **明确拒绝项**：Stocksera 全家桶（停维护 2 年、13F 管道不存在、依赖付费 API key）；FinanceToolkit 整体（无 PIT 概念、yfinance 财年启发式错位、sklearn 硬依赖超配）；akshare 的涨停/龙虎榜/舆情类接口（噪音）；daily_stock_analysis 的全部分析 prompt/schema（投机语义）。

## 三、逐项目源码级报告

---

### 1. implied-expectations → fengvaluation.py（预期法移植，S）

**仓库**：Keenan-ux/implied-expectations（MIT，最后提交 2026-07-01，0 star 单作者但工程化完整：CI/lint/golden tests/自动发布）

**定位**：逆向 DCF「预期投资」（Rappaport/Mauboussin 框架）：给定 ticker 与用户输入的价格，从 SEC EDGAR 拉财报，把前向两阶段 FCFF DCF 反着解——求市场隐含的营收增长率、增长需持续的年限、所需营业利润率。**输出永远不是合理估值或目标价，而是「价格隐含的赌注」**（README.md:7-16）。

**源码级关键机制**：
- 数据接入（edgar.py）：companyfacts API，TTL 缓存（ticker→CIK 7 天、companyfacts 1 天），节流 ≤4 req/s（edgar.py:34,140-162）；流量项取**最新完整财年**（form∈{10-K,20-F,40-F}、fp=FY、期间 340–380 天校验，edgar.py:199-206），平衡表项取最新 instant（edgar.py:231-239）；营收与营业利润必须同财年否则拒绝（edgar.py:261-265）；税率优先申报有效税率并 clamp 0–45%，回退 21%（edgar.py:267-274）；增量 ROIC = NOPAT/投入资本 clamp 10–100%，拿不到回退 20%（edgar.py:304-320）。每个数字带 XBRL 概念溯源（provenance）。
- 前向模型（model.py:88-131）：两阶段 FCFF；再投资率 = max(0, g/roic)（增长-资金恒等式，收缩业务不凭空造现金流，model.py:111）；**终期 RONIC 默认等于贴现率**——终值增长价值中性，不偷渡第二段增长故事（model.py:20-24,121-125）。
- 反解引擎（solver.py:67-98）：二分法求根（_TOL=1e-10）+ **四模式回退**：cap 内无解→转 DURATION_AT_CAP；50 年 cap 不够→BEYOND_HORIZON 如实说「超出模型地平线」；价格低于 -90%/年崩塌→BELOW_FLOOR。「solver never fabricates a number」（solver.py:13-14）。
- 敏感性网格（solver.py:164-183）：5/10/15 年 × 贴现率 ±2% 的隐含增长网格——现成的敏感性分析。

**已知问题/坑**：仅美股申报者（银行/保险直接拒绝）；贴现率全局默认 9.5% 无公司 beta；margin 显式期内持平无 fade；亏损公司拒绝反解；trailing 财年非前瞻估计。

**借鉴点**：① model.py+solver.py 共 337 行、纯标准库、MIT——直接移植进 fengvaluation.py 作「预期法」方法（S）；② edgar.py 的 companyfacts 提取模式（财年对齐校验/provenance/节流缓存）并入 fengsec.py 作对照范本；③ 价格=用户输入、零行情依赖——与 fengdata.py 分工天然契合。

**替代性**：不能整体替代 fengvaluation.py（它只是多方法之一），但预期法+敏感性分析是规划中的核心需求，移植 S。

**噪音判定**：纯内在价值工具。代码中不存在任何行情/技术指标/新闻路径，价格只作为用户输入参与求根（cli.py:19-23 免责声明）。

---

### 2. FinanceToolkit → fengvaluation/fengquant 纯计算层（移植 M）

**仓库**：JerBouma/FinanceToolkit v2.1.4（MIT，最后提交 2026-07-14，维护活跃，52 测试文件 698 用例）

**定位**：通用财务分析库（200+ 比率/指标/绩效度量），发起动机是「各平台同一 PE 算出来从 28.93 到 34.4 各不相同」，主张源码透明。**不是价值投资专用**。

**源码级关键机制**：
- 数据接入：FMP（主，需 key）+ yfinance（自动回退），逐 ticker 并发 + sleep 0.1s 防限流（fundamentals_model.py:27-140,154-156）；归一化用 CSV 映射表（normalization/*.csv + *_yf.csv 两套供应商字段→统一 Generic 名，normalization_model.py:51-69）——**扩展数据源=新增映射 CSV**，架构如此设计。
- **无时点/披露日概念**：全库检索 filed_date/disclosure 仅命中 FMP ESG 接口；三表列是期间（财年末 PeriodIndex），不携带「何时披露」。
- 模型模块（models_controller.py 2530 行）：DuPont 五因子分解（dupont_model.py:10-140）、前向单段 DCF（intrinsic_model.py:11-111，5 期投影+Gordon 终值）、WACC（债务市值=账面值简化，wacc_model.py:113-115）、Altman Z / Piotroski / Beneish M / Graham 数 / PVGO / EVA。**无任何逆向估值**（implied growth/reverse dcf 零命中）。
- 比率模块：纯函数式 Series→Series 签名（profitability_model.py:23），输出 MultiIndex DataFrame。

**已知问题/坑**：① **yfinance 财年→日历年启发式错位**（1–5 月财年末的公司整体前移一年，yfinance_model.py:103-121）；② FMP/yfinance 双源混用时同一公司各期可能来自不同供应商；③ 依赖偏重（sklearn 为算比率硬依赖）；④ 模块级 `warnings.filterwarnings("ignore")`（toolkit_controller.py:51-54），除零/NaN 直接透传——「透明简单」而非「严谨精确」。

**借鉴点**：归一化 CSV 映射模式 → fengdata.py 多源归一化；86 个纯函数比率 → fengquant.py 因子池候选（但需自行处理缺失 abstain——它缺数据就 NaN 透传）；DuPont/Altman/Piotroski/Beneish → 质量拆解组件。

**替代性**：**不能替代 fengvaluation.py 的数据+计算层（L）**：无 SEC 直连、无逆向 DCF、无披露日概念、依赖重。**可中等量（M）移植纯计算层**：抽 20-30 个比率和 DuPont/Altman/Piotroski/Beneish 进 fengquant/fengvaluation，但需逐函数复核口径。

**噪音判定**：价值与噪音混杂——ratios/models 全基于三张表历史数字（价值侧）；但仓库含完整 technicals/options/risk/discovery（新闻搜索）模块，正是定义的短期噪音。**只取 ratios/ + models/ 两个子目录，其余一概不引入**。

---

### 3. pit-fundamentals → fengpit.py 免费对拍基准（S）

**仓库**：christianpichichero-max/pit-fundamentals（CC0，2026-08-07 单 commit）

**定位**：免费 PIT（时点）美股基本面数据集（40 只大盘股 × 7 个概念 × FY2011–2026，3280 行）+ 查询/校验工具。数据源 SEC EDGAR companyfacts。**注意：构建管线不在本仓库**（全量数据是付费 API $49/月）——仓库只有成品 CSV + stdlib 查询脚本。

**源码级关键机制**：
- Schema 13 列：ticker, cik, concept, xbrl_tag, fiscal_year, period_end, **first_filed**, lag_days, filed_reliable, original_value, latest_value, restated, qa_status。每个数字带 XBRL 概念完整溯源（如 AAPL 早年 `SalesRevenueNet` → 近年 `RevenueFromContractWithCustomerExcludingAssessedTax`）。
- **可见性定义**：`first_filed` = 该期间数值首次可被公众知晓的日期；lag_days = first_filed − period_end（METHODOLOGY.md:54-55）；`query_asof.py:39` 的 `first_filed <= as_of` 过滤——与 edgartools `FactQuery.as_of`（`filing_date <= as_of`）语义逐字一致。
- **披露日可靠性分层**：40 行原始 10-K 早于 XBRL 时代 → `filed_reliable=False`，「日期不可靠宁可标记也不伪造」；qa_status 四档（clean 3227 / lag_out_of_range 40 / tag_switch_discontinuity 10 / implausible_value 3——MCD DilutedShares 单位歧义按原样保留不猜单位）。
- **重述检测**：后续文件修改某期间值 >0.5% 则 restated=True，同时保留 original_value（当时可知）与 latest_value（现在厂商会给的）；309 行 original≠latest，其中 20 行是 DilutedShares 的追溯拆股调整（AMZN 20:1）——文档明确警告这是回测最危险的坑（METHODOLOGY.md:63-70）。
- 流项只留 345–385 天 duration（防季度/stub 混入）；1 月 1–7 日 period_end 归上一年（处理 JNJ 52/53 周财年）；`verify_public_sample.py` + GitHub Actions 防文档与数据漂移。

**已知问题/坑**：无构建管线（不可复现）；年度 only（10-Q 季度 PIT 是 roadmap）；无负债/债务/现金概念（资产负债表只有 Assets 和 StockholdersEquity）；银行/保险 revenue 是近似概念（JPM 自认，METHODOLOGY.md:144）。

**借鉴点**：① first_filed/lag_days 双轴 + filed_reliable 分层 → fengpit.py 可见性模型的 ground truth 对照；② original_value vs latest_value + restated → fengpit 的 vintage 维度设计（重述含拆股追溯是「当期数字 vs 当时数字」的量化模板）；③ qa_status 四档 → 数据质量标记规范；④ check_your_data.py（timing/vintage 双分离检查）→ 可移植成自有数据源体检工具（纯 stdlib）。

**替代性**：**不能替代 fengpit 数据层**（7 概念 × 40 股太窄、无季度），**但可作免费对拍基准**（S）：与 fengpit 同源于 companyfacts，用 query_asof.py 对 AAPL/AMZN/TSLA 的 revenue/first_filed 做抽查验证。其 first_filed 取自 companyfacts `filed` 字段——正是 edgartools 也保留的字段，意味着**自建同样数据集可行而不必依赖付费 API**。

**噪音判定**：价值明确——对抗性审计公开了两个真 bug（财年错位、拆股/单位歧义），限制显式标记不隐藏。噪音部分仅 README 推销付费 API 的文案。

---

### 4. edgartools → 直接替代 fengsec.py（M）

**仓库**：dgunning/edgartools v5.48.0（MIT，2.5k star，2026-08-12 当天还在提交；565 测试文件、169KB CHANGELOG，五年持续演进）

**定位**：SEC EDGAR 全能结构化客户端：把任意 filing（10-K/10-Q/8-K/13F/Form 3/4/5/基金/ABS…20+ 种）解析成类型化对象 + pandas DataFrame。依赖中量（httpx + httpxthrottlecache + pyrate-limiter + stamina + pyarrow + pandas），无重型框架。

**源码级关键机制**：
- **XBRL 双轴——两条路径，一条有双轴、一条没有**：
  - 路径 A：单份 filing（`Financials`，financials.py:118-131）解析 inline XBRL 出标准三表 + 14 个标准化指标（get_revenue/get_net_income/get_total_liabilities...，financials.py:442-915）。fact 只有 period 列（facts.py:69-92），披露日在该 filing 的 Filing.filing_date 上——单文件内「财报期轴完整、披露日轴是常量」，对 PIT 足够。
  - 路径 B：companyfacts（`EntityFacts`，entity/filings.py:612）——**真正的 PIT 金矿**：逐 fact 保留 `filed→filing_date`（entity/parser.py:184）、`form`（parser.py:219）、`accn`、`fy/fp`（parser.py:193-194）。`FactQuery.as_of` 即 PIT 查询（entity/query.py:318-331）；`to_dataframe(pit_mode=True)` 保留全部 fact 版本不做期间去重（entity/entity_facts.py:253-349）；`balance_sheet(as_of=...)` 直接出时点资产负债表。
- Filings API：get_filings(year, quarter, form=...)（_filings.py:1249-1347），docstring 明示 year/quarter 是**提交日（日历）不是财年**——正是 PIT 需要的口径；Filing.period_of_report（_filings.py:1539-1560）从 SGML 头取财报期。
- Form 3/4/5（ownership/ 包：交易分类、10b5-1 计划检测）、13F-HR（XML 2013+ / TXT 2012- 双格式）、8-K（CurrentReport：items/has_earnings/press_releases，current_report.py:498-678）全支持。
- 限流/缓存：令牌桶 9 req/s（httpclient.py:160-176）、submissions 30s TTL / index 30min / **Archives 永久缓存**、stamina 重试（attempts=6，尊重 Retry-After）、`EDGAR_IDENTITY` 环境变量 UA——与 FENG_HTTP_UA 同为 SEC 合规方案。

**已知问题/坑**：① **Archives 永久缓存曾把 SEC 瞬时故障的空响应永久缓存**（Issue #672，官方用 clear_empty_cached_responses 打补丁）——自管缓存不要照抄「永久缓存」规则；② XBRL 解析器在 v2 重写中（XBRL2-Rewrite.md），API 可能有变动；③ companyfacts 的 `filed` 是 EDGAR 接受日，不是新闻发布日——事件日轴需另外从 8-K/新闻源补；④ 体量大（1.4GB 测试数据），只想要「下载+抽 XBRL」会带来远超所需的表面积。

**借鉴点**：EntityFacts 逐 fact 双轴 + FactQuery.as_of + pit_mode → fengpit.py 数据层蓝本（得知日轴逐字对应）；get_filings 提交日口径 → fengpit 事件日数据源；Form 3/4/5 + 13F → fengquant/fengportfolio 的 insider/机构持仓因子数据层（避免自写 XML 解析器）；限流/缓存/重试/UA → fengthrottle 功能对照清单（注意其永久缓存坑）；本地存储离线模式 → fengsec 本地归档方案。

**替代性**：**能替代 fengsec.py，且是大幅升级，工作量 M**：方案 A（推荐）= 以 edgartools 为数据获取层替换 fengsec 的 HTTP/XBRL 部分，fengthrottle 保留或退化为薄封装（对齐 9 req/s、处理缓存目录迁移）；若只想升级「下载+抽数」环节，S（get_filings + Financials 两行调用）。

**噪音判定**：价值高。PIT 能力有源码级实现 + 测试 + 文档示例，非宣传。噪音集中在 edgar/ai/（MCP/LLM 工具）与 README 营销腔调——可选 extra 避开。诚实边界：它是「解析器+下载器」不是「PIT 数据集」——「自动按披露日去重、防 vintage」的最终逻辑仍需 fengpit 自己实现。

---

### 5. disclosure-alpha → L2a 会计检查清单客观输入层（S–M）

**仓库**：alwank/disclosure-alpha v1.5.1（Apache-2.0，2026-06-30，PyPI Production/Stable）

**定位**：确定性（deterministic）SEC 披露分析：输入 10-K/10-Q HTML，输出可复现的 JSON 分数、布尔风险指标、章节级 YoY diff。**全程无 LLM**（README:18）——与「研究必须可复现」哲学高度一致。核心依赖仅 5 个（bs4/lxml/numpy/sec-parser/sklearn）；45 个测试文件。自带验证：S&P500 FY2025 Item 1A n=478，specificity ρ≈0.87（vs NER）、boilerplate ρ≈0.92（vs LS 4-gram）。

**源码级关键机制**：
- 打分（deterministic_scoring.py:130-405 + scoring_types.py:4-14）：10 个 0–100 分量加权（risk_factor_intensity 0.20 / disclosure_change 0.15 / mdna_uncertainty 0.15 / legal_regulatory 0.10 / liquidity_stress 0.10 / boilerplate 0.10 / internal_controls 0.05 / event_severity 0.05 / tone_negativity 0.05）；每个分量带 provenance（输入/权重/原始值）完全可审计；缺分量记入 missing 并输出 score_coverage_ratio。
- v2 默认（deterministic_scoring.py:734-871）：证据加权模型 blend_evidence（scoring_types.py:105-121），tone 指标先经百分位校准（calibration.py:48-79，按 10-K/10-Q 基准百分位数组）。
- **15 个布尔风险 flag**（dictionaries/flags.py）：material_weakness / significant_deficiency / ineffective_controls / restatement / non_reliance / auditor_change / investigation（subpoena/wells notice/DOJ）/ settlement / material_legal_proceeding / **going_concern** / covenant_breach / guidance_withdrawal / cybersecurity_incident；全部句子级正则 + **同句抑制词**（"no material weakness"、"has been alleviated"，flags.py:109-135）+ 章节作用域限定（FLAG_SECTION_SCOPE，flags.py:137-196）。
- 章节 diff（diff_engine.py:43-81,138-160）：TF-IDF 余弦 + 可选 embedding 双通道；句子对齐贪心匹配（阈值 0.55）；v2 变化分 = 0.55×alignment（新增句/新增风险语言/数字变更/主题）+ 0.45×v1；数字变更检测（text_matching.py:72-82）；language_deltas 四类词比率 YoY。
- EDGAR 抓取（edgar/client.py）：全局锁 0.11s/请求（~9 req/s）、company_tickers lru_cache、Range 头只拉 HTML 前 128KB 解析 DEI 标签做**财年消歧**（edgar/resolver.py:112-134,306-373）；磁盘缓存 data/cache/sec_filings/。

**已知问题/坑**：8-K 支持残缺（回退 10-Q 解析器，section_extractor.py:135-136，`--ticker`/HTTP 路由不支持 8-K）；v1 聚合 confidence_score=0.3 是占位符（deterministic_scoring.py:400）；校准百分位是硬编码默认值（baselines.py:16-28）非实时语料；boilerplate 基线只有 Item 1A FY2025 一份。

**借鉴点**：① 15 flags + 抑制词 + 证据链 → L2a 6 灯检查清单的自动化（going_concern/covenant_breach→流动性灯；material_weakness/restatement→内控灯；investigation→法律灯；guidance_withdrawal→指引灯）；② edgar/resolver.py 财年消歧 + 磁盘缓存 → fengsec.py 增强（S）；③ boilerplate 度量 → 识别「满篇套话的 10-K」；④ diff 引擎 → 8-K 披露事件初筛。

**替代性**：不能替代 L2a（还有人工定性判断），但可作**客观输入层**：只消费 CLI/HTTP 输出 S；移植 flags/diff 进 fengstate L2a 子步骤 M（需处理 Python 3.11+ 与 sec-parser 依赖）。

**噪音判定**：价值类。无 LLM、可复现、指标全是「披露中真正有效信息量」的度量；对 fengsec 的增强照抄（Apache-2.0）。

---

### 6. akshare → fengdata.py CN 数据层（M）

**仓库**：akfamily/akshare v1.18.84（MIT，21,978 star，2026-08-10 仍活跃；包内 30+ 业务目录，__init__.py 343 条顶层 import）

**定位**：中国财经数据接口库（免 token）。依赖多但轻量（bs4/lxml/pandas/requests/curl_cffi/**mini-racer** 反爬 JS 引擎）。

**源码级关键机制**：
- **新浪三表（PIT 关键）**：`stock_financial_report_sina`（stock_finance_sina.py:24-91）调新浪 getFinanceReport2022 API，一次最多 1000 期；**每个报告期附加「公告日期(publish_date) + 数据源 + 是否审计(is_audit) + 币种 + 类型 + 更新日期」6 行元数据**（:59-77）——A 股唯一免费自带披露日的三表源。注意是宽表转置，公告日期在行里需行转列。
- 同花顺三表（stock_finance_ths.py:58/92/130）**无公告日期**——PIT 不完整只能当补充源；东财 A 股**没有三表接口**只有主要指标（RPT_F10_FINANCE_MAINFINADATA，原始字段透传未映射，:181-225）。
- 港股三表（东财 F10，stock_finance_hk_em.py:13-105）长表结构，**columns 参数未请求 NOTICE_DATE 列**——需实弹验证。
- 分红（PIT 完整）：stock_history_dividend_detail（新浪）返回公告/除权除息/股权登记/红股上市日（:360-480）；巨潮公告查询（stock_disclosure_cninfo.py:129-205）按类别查披露时间。
- 股本：stock_main_stock_holder 含截止+公告日期（:696-766）；估值：stock_zh_valuation_baidu（PE(TTM)/PE(静)/PB 历史序列）。
- 行情：stock_zh_a_hist（东财日线，qfq/hfq，字段比 yfinance 全，stock_hist_em.py:952-1040）。

**已知问题/坑**：① **无内置缓存、无限流**——429 直接抛 RateLimitError 不等待（request.py:56-61），**必须用 fengthrottle 包裹**；② import 重量：无懒加载，import 必执行 343 条顶层 import；③ 页面结构脆弱（硬编码 read_html 表格下标，如 :281 的 [12]）；④ 新浪三表元数据以行附加，不做行转列会把「公告日期」当科目；⑤ 东财涨跌幅口径（可能含 ST 5%）与 fengbacktest 涨跌停过滤需核对。

**借鉴点**：① 新浪三表 → fengpit 的 CN 直接数据源（财报期+披露日+审计状态一次拿齐，比 yfinance 报表是 PIT 升级）；② 巨潮公告 → 披露日校准/交叉验证；③ 分红事件全时间线 → 持有期除权提醒；④ 无缓存/429 直抛 → 套 fengthrottle 后再批量调用；⑤ 东财原始字段透传 → 自建列映射层。

**替代性**：可替代但**不建议裸依赖**（14 个依赖包 + 全量 init 成本 + 无契约接口）。二选一：a) 完整安装 + fengthrottle + 适配层（M）；b) 把新浪三表/东财日线/分红几个接口按需移植进 fengdata（代码单薄、纯 requests+pandas，M 稍小且可控）。定期回归测试必须（上游接口无稳定性承诺）。

**噪音判定**：价值与噪音清晰分界——三表/分红/股东/PE-PB/巨潮披露日期全部是价值增量；同一仓库的涨停/龙虎榜/人气榜/热榜/股吧舆情接口（stock_hot_rank_em.py / stock_lhb_em.py / stock_weibo_nlp.py 等）**明确不引入**。

---

### 7. quantstats → fengbacktest 报告输出层（S）

**仓库**：ranaroussi/quantstats v0.0.81（Apache-2.0，7.5k star，8026 行，125 测试）

**定位**：组合绩效分析：~90 个绩效/风险指标 + HTML/matplotlib tearsheet。

**源码级关键机制**：
- 指标集（stats.py）：sharpe（:841，std ddof=1，smart 参数带自相关惩罚 :901）、sortino、max_drawdown（:2451，**phantom baseline 技巧**：首日前插基准值避免首日亏损漏算，:2472-2487）、drawdown_details（:2992 回撤明细表）、greeks（:2676，beta=cov/var，**简化 Jensen alpha 非 OLS 截距无 rf**）、probabilistic_sharpe/sortino（:1258/1292）、cagr/calmar/omega/ulcer_index/var/cvar（:1861/1921）、kelly_criterion、win_rate、profit_factor。
- 输入接口（utils.py:583-650）：`_prepare_returns` 自动判别——序列 min≥0 且 max>1 视为净值转 pct_change，否则视为收益率；收益率序列与净值曲线都可直接喂，index 需 DatetimeIndex。
- tearsheet：`html()`（reports.py:178-263）单文件 HTML + SVG 内嵌（无 GUI 依赖，适合归档）；`metrics()`（:1135）纯计算返回指标表；benchmark 可为 Series 或字符串代码（字符串→yfinance 下载）。

**已知问题/坑**：① **值域歧义（最危险）**：净值序列全程 <1（亏损组合 0.5~0.95）会被误判为收益率序列，指标全失真——净值必须先归一化（base≥1）或显式转收益率；② alpha/beta 为简化版（算术平均+cov/var，无 rf，与 CAPM 口径不一致）；③ yfinance 硬依赖（仅为字符串 benchmark 服务）；④ 0.0.81 刚修复 circular import 与 dd_get_stats NameError——近期发布质量有波动；⑤ matplotlib 默认字体不含中文。

**借鉴点**：① 输入=收益率序列或净值曲线 → 与 fengbacktest 的 PnL 序列天然对接；② metrics() 纯计算接口 → 绩效表并入 fengquant/fengbacktest 无绘图副作用；③ html() 单文件 HTML → 一次调用产出可归档绩效报告；④ drawdown_details + phantom baseline → 补 fengbacktest 回撤拆分与首日亏损边界；⑤ probabilistic_sharpe（自相关惩罚）→ 因子共识/策略对比时区分「运气 vs 能力」。

**替代性**：**不能替代 fengbacktest**（T+1 对齐/涨跌停过滤/冲击成本/PnL 拆分是它完全没有的），**可直接作为其绩效报告输出层，S**：`qs.reports.html(returns)` 或 `qs.metrics(returns)`（注意净值归一化坑）。若不想引入 seaborn+yfinance 两个重依赖：移植 drawdown_details/max_drawdown/probabilistic_sharpe 等 3-5 个函数进 fengbacktest（纯 pandas/numpy，Apache-2.0 允许保留版权头），M。

**噪音判定**：全部是**事后绩效统计**（sharpe/回撤/胜率/VaR）——对「已实现策略的执行质量」有增量，对「内在价值判断」零增量；工具性价值，不产生任何买卖信号。可吸收进组合风险层与回测报告，其输出不得进入投资决策链。

---

### 8. skfolio → cmd_hrp 直接候选（S）

**仓库**：skfolio/skfolio v0.20.1（BSD-3，2026-07-28 活跃；src 49,500 行、**tests 35,000 行/1,707 个测试函数**）

**定位**：基于 scikit-learn API 的现代组合优化库。依赖：numpy/scipy/pandas/cvxpy-base/clarabel（求解器）/scikit-learn/joblib/plotly（画树状图）。

**源码级关键机制**：
- **HRP（核心核查：无 σ⁴ bug，忠实还原论文）**：主类 HierarchicalRiskParity（_hrp.py:29）；距离 d=√(0.5×(1−ρ))=√((1−ρ)/2)（_distance.py:587，与论文逐字一致）；聚类用 scipy linkage（默认 **Ward**——文档明示是对论文 single-linkage 的有意偏离，_hrp.py:45-51）；seriation 用 optimal_leaf_ordering + leaves_list（:396-400）；递归二分（:405-433）簇内逆风险权重 1/σ²（:411-413）、簇风险 w^T Σ w（_base.py:335-373）。**方差只作为风险度量出现一次，全程无二次平方**（对比 Riskfolio-Lib 的 σ⁴ bug）。额外支持 min/max 权重约束（:439-487）与交易成本/管理费——超出论文的工程扩展。
- 风险度量枚举（measures/_enums.py:107-188）：VARIANCE/SEMI_VARIANCE/CVAR/EVAR/WORST_REALIZATION/CDAR/MAX_DRAWDOWN/AVERAGE_DRAWDOWN/EDAR/ULCER/GMD 等，全部可进 cvxpy 目标/约束（CVaR 辅助变量线性化 _base.py:1874、EDaR ExpCone :2114、GMD OWA :2148）。历史口径：回撤=cum/peak−1 复利口径（_measures.py:861-882）；CDaR=对回撤序列算 CVaR（:944）。
- 优化器：凸优化走 cvxpy + CLARABEL（_base.py:419-425）；四种目标（MINIMIZE_RISK/MAXIMIZE_RETURN/MAXIMIZE_UTILITY/MAXIMIZE_RATIO）；基数/分组约束 MIP（:2232+）；非凸路径 HRP/HERC/NCO/Schur；失败回退链 fallback + raise_on_failure（_hrp.py:213-229）。
- API：完整 sklearn 协议 fit/predict/fit_predict/score（=Sharpe）/partial_fit；Portfolio 对象提供全部度量属性。

**已知问题/坑**：HRP 默认 Ward 而非论文 single-linkage（要逐字复刻需显式改）；`Portfolio.contribution`（MCTR 式）用有限差分（_portfolio.py:873-929，回撤类 h 默认 1e-1 精度需留意）非解析梯度；CHANGELOG 维护滞后（头部只到 v0.13.0 而版本已是 0.20.1）；部分距离度量 O(n²) 双重循环有 TODO: parallelize。

**借鉴点**：① HRP（论文口径 σ²、可换 risk_measure、权重约束、交易成本）→ **cmd_hrp 候选计算层**；② Portfolio.contribution 有限差分风险贡献 / RiskBudgeting 凸优化 → fengportfolio MCTR 对照验证；③ CVaR/CDaR/MaxDrawdown 统一枚举 + cvxpy 线性化配方 → 压力测试与风险度量口径；④ uncertainty_set（mu/cov 不确定集 + DR-CVaR）→ 压力测试「最坏情形」思路；⑤ WalkForward + purged CV（model_selection）→ fengbacktest 样本外评估防泄漏。

**替代性**：**cmd_hrp：能，S**——输入就是 (n×m) 收益率 DataFrame，`HierarchicalRiskParity().fit_predict(X)` 即可，内置权重上下限/交易成本/失败回退，比自己手写递归二分更省。**cmd_risk：部分能，M**——风险度量/压力测试/约束再平衡有现成实现，但 MCTR 是有限差分且 fengportfolio 已有自己的语义，更合适定位「内部算法对照」。前置依赖 cvxpy-base + clarabel（纯 Python/Rust wheel，Windows 无痛）。

**噪音判定**：纯组合数学/风险工程库，不涉及公司内在价值，价值中立——基础设施而非判断层，可放心吸收。

---

### 9. Stocksera → 仅借鉴数据管道模式（S）

**仓库**：guanquann/Stocksera（MIT，777 star，**最后提交 2024-08-19，实际约 2 年未更新**，README 自注「still in the midst of fixing bugs (Govt trades)」）

**定位**：「另类数据仪表盘」网站 + REST API：60+ 数据面板（内部人交易、国会交易、期权 max pain、空头、FTD、借贷费率、Reddit/Twitter 情绪、经济数据等）。Django 3.1.6 + MySQL + DRF + Plotly；settings.py:32 DEBUG=True、SECRET_KEY 明文提交——纯演示级工程；无实质测试。

**源码级关键机制（数据来源清单）**：
- 内部人交易：Finviz 网页抓取（finvizfinance 库），仅 buys、过滤 Value≥$50,000（get_latest_insider_trading.py:23-28）；聚合表按 Ticker 近 30 天 Value 之和 + Proportion=|Amount|/MktCap×100（:53-73）。
- 空头成交：FINRA CDN 每日 txt（get_short_volume.py:33-37）；FTD：SEC data.json → zip（get_failure_to_deliver.py:34-66）；借贷费率：IBKR 匿名 FTP；Reg SHO：NYSE API。
- 国会交易：senate/house-stock-watcher-data S3 聚合 JSON（get_senate_trading.py:16-18）。
- 情绪类：Reddit WSB（praw，VADER 情绪）、Stocktwits、Twitter 提及/粉丝、恐惧贪婪指数、Jim Cramer。
- **13F：代码库中未找到**——全仓 grep 无任何 13F 抓取/解析任务；唯一的季度机构持仓来自 yfinance `institutional_holders`（app/views.py:129）。

**已知问题/坑**：依赖至少 4 个付费 API key（FINNHUB/FMP/POLYGON/TWITTER）；需自建 MySQL；无任务调度框架（外部 cron 手动跑）；多脚本并发写库无锁。

**借鉴点**：① `INSERT IGNORE + UNIQUE 约束` 幂等摄入模式（get_latest_insider_trading.py:43-49）→ fengdata.py 本地存储层；② 官方源直连清单（FINRA 空头 / SEC data.json FTD / IBKR FTP / NYSE threshold）→ 未来补空头/FTD 事实数据直接照 URL 模板抓（可改写为纯 requests+pandas，S）；③ 「30 日净买入/市值占比」派生指标 → L2a「内部人增持灯」的指标模板。**不建议移植 Django/MySQL/Plotly 全家桶**。

**替代性**：不能替代任何 FengInvest 模块（fengdata/fengsec 的职责它都不覆盖，且停维护、依赖陈旧、无测试）。**「内部人增持」信号的正确做法是走 SEC EDGAR Form 4 XML（用 fengsec/edgartools 的限流缓存），参考其聚合+占比指标设计即可**——不依赖此仓库。

**噪音判定**：噪音为主——WSB/Twitter 情绪、期权 max pain、空头/FTD/借贷费率、低流通、恐惧贪婪指数均为市场微观结构与情绪，对内在价值零增量；内部人增持方向上有信息量但 Finviz 二手抓取无 Form 4 审计链，只能当弱线索（需自建才有资格进 L2a）；国会交易时滞 45 天 + 金额区间制，判噪音。

---

### 10. daily_stock_analysis → 借鉴工程机制，拒绝投资逻辑（M）

**仓库**：ZhuLinsen/daily_stock_analysis（MIT，**62k star**，2026-08-10 仍活跃）

**定位**：「基于 AI 大模型的 A股/港股/美股/日股/韩股/台股自选股智能分析系统，每日自动分析并推送『决策仪表盘』到企业微信/飞书/Telegram/Discord/Slack/邮箱」。技术栈：Python 3.10+ 后端约 5 万行、**260 个测试文件约 13.4 万行测试**、React 前端 275 个 TS 文件约 8.2 万行、FastAPI + Electron + Docker。

**源码级关键机制**：
- LLM 接入：litellm 多厂商（GEMINI/ANTHROPIC/OPENAI/DEEPSEEK，analyzer.py:1865-1869,2745）+ 本地 CLI 后端 + 用量审计 + 失败重试与模型切换（_AllModelsFailedError）。
- 数据流（core/pipeline.py:405）：实时行情 → 筹码分布（带熔断）→ 趋势分析 → 多维情报搜索 → 组上下文 → LLM 生成 → **JSON 解析/校验/修复/完整性重试**（_parse_response :4501、_fix_json_string :4606、_check_content_integrity :4272-4366）→ AnalysisResult → 落库 → Markdown 渲染（按平台转义）→ 13 个通知渠道 → **决策信号抽取与事后 outcome 追踪**（decision_signal_outcome_service.py:81-322，对 AI 输出做 accountability）。
- 质量证据：结构化错误枚举（generation_backend.py:14-40）、fail-open 适配器、熔断、盘中/盘前相位护栏、异常文本脱敏（analyzer.py:2688-2743）、AGENTS.md 严格质量底线。
- 反面痕迹：巨型文件（analyzer.py 4,804 行）、补丁驱动演进（注释大量 Issue #N）、legacy 平行路径。

**投资逻辑判定（关键）——几乎完全是短线投机**：输出契约核心字段是 sentiment_score（0-100 打分）、trend_prediction、operation_advice（买/加/持/减/卖/观望）、**short_term_outlook（1-3 日）**、**get_sniper_points()「狙击点位」=买入/止损/止盈价位**（analyzer.py:1670-1697,1797-1801）、battle_plan「作战计划」；15 个策略 13 个纯技术/情绪（缠论/波浪/龙头战法/热点/情绪周期，strategies/*.yaml）；基本面只是 prompt 里的辅助表格行（analyzer.py:3795-3839）；**全库搜不到 DCF/内在价值逻辑**。

**借鉴点（只抄机制）**：① **LLM 输出契约化 + 校验/修复/完整性重试管线** → fengstate/fengvaluation 的 AI 流程（要求 LLM 输出结构化 JSON，缺字段自动补问重试，M）；② 多数据源 failover 管理器 → fengdata.py 容错模式（M）；③ **决策信号落库 + 事后 outcome 命中率追踪** → fengreview 复盘：把 thesis 预测落库、事后判定命中/证伪，形成纪律闭环——**唯一同时「抄机制又合价值哲学」的点，若只做一件事就抄这个**（M）；④ 通知渠道抽象 → fengweb 推送层（S）；⑤ 报告 Markdown 渲染按平台转义 → fengweb 报告输出（S）；⑥ React+FastAPI 仪表盘页面结构可作 fengweb 参考蓝图，但全套照搬属过度工程（L 不划算）。

**替代性**：不能替代任何模块——它没有估值引擎、没有内在价值框架，是「LLM 包装 + 技术面择时 + 推送」系统。价值在组件级借鉴，尤其 #1 LLM 输出契约化和 #3 预测-结果追踪。

**噪音判定**：其输出几乎 100% 是噪音（对内在价值判断零增量），工程机制本身价值相关。**借鉴其工程成熟度，拒绝其投资逻辑。**

---

## 四、落地建议（按优先级排序，待审核后实施）

| 优先级 | 动作 | 来源 | 工作量 | 说明 |
|---|---|---|---|---|
| 1 | cmd_hrp 接入 skfolio | skfolio | S | 无 σ⁴ bug 的论文口径 HRP，内置约束/成本/回退，替代自研递归二分 |
| 2 | fengsec.py 升级为 edgartools 数据层 | edgartools | M | 全套表单解析 + EntityFacts PIT 双轴原料；fengthrottle 保留为薄封装或对照 |
| 3 | fengpit.py 数据层照 EntityFacts 双轴建 | edgartools + pit-fundamentals | M | filing_date=得知日、period_end=财报期；pit-fundamentals CSV 免费对拍 |
| 4 | fengvaluation.py 移植预期法 | implied-expectations | S | 337 行纯标准库反解引擎 + 敏感性网格；「不编造数字」与 abstain 同构 |
| 5 | fengdata.py CN 数据层接 akshare 新浪三表 | akshare | M | 唯一免费自带公告日期+审计的 A 股三表源；fengthrottle 包裹；只取价值类接口 |
| 6 | L2a 会计检查清单接 disclosure-alpha | disclosure-alpha | S–M | 15 flags + 章节 diff 机械化 6 灯检查；或仅消费 CLI 输出 |
| 7 | fengbacktest 报告接 quantstats metrics | quantstats | S | 纯计算接口 + 单文件 HTML；注意净值归一化坑 |
| 8 | fengreview 复盘 outcome 追踪闭环 | daily_stock_analysis | M | thesis 预测落库 + 事后命中/证伪判定（只抄机制不抄逻辑） |
| — | 拒绝 | Stocksera / FinanceToolkit 整体 / akshare 噪音接口 / daily_stock_analysis 投资逻辑 | — | 理由见各节 |
