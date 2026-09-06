# 论文研究笔记：组合构建 / 再平衡 / 分散化（论断 #35-37, 41）

> 抓取日期：2026-08-16 | 渠道：Crossref / OpenAlex / Semantic Scholar 官方 API + Springer 官网 HTML（curl 直取摘要）+ arXiv + RePEc + S2 引用上下文（citation contexts）
> 校验规则：标题/作者/年份/DOI 三重交叉校验（Crossref 主渠道）；摘要只记录 API/网页原文，拿不到标"待补"并写明尝试渠道；每句结论附来源 URL。
> ⚠️ 本轮成果：literature-conclusions.md「摘要未取得（8 篇）」中本组 4 篇已处理——Plyakha、Willenbrock、Li-Refalo-Yi 摘要已补齐（分别从 Crossref/Springer 拿到官方原文）；Evans & Archer 1968 无官方摘要（多渠道确认无公开摘要接口），改用 S2 引用上下文（正文可检索片段）如实标注结论。
> ⚠️ 防幻觉说明：Plyakha 的 SSRN 直连页与 Wiley 直连页均被 403/Cloudflare 拦截（WebFetch / Search King edge / cloak 均试过）；摘要改从 Crossref 上的 SSRN 记录（SSRN 自家元数据）取得，内容与渠道一致，可用。

---

## 0. 本组论断与标尺总览

| 论断 | 内容 | 标尺论文 | 本轮状态 |
|:----|:-----|:--------|:--------|
| #35 | 等权跑赢市值加权 | Plyakha-Uppal-Vilkov（SSRN 2724535） | ✅ 摘要补齐（Crossref） |
| #36 | 行业分散降回撤 >20% | Evans & Archer 1968 | ⚠️ 无官方摘要，引用上下文补齐 |
| #37 | 再平衡年化超额 >1% | Willenbrock 2011 | ✅ 摘要三渠道确认 |
| #41 | 行业集中度 >40% 暴跌 >50% | Li-Refalo-Yi 2025（+ Hou-Robinson 2006） | ✅ 摘要补齐（Springer 官网） |

---

## 1. Plyakha, Uppal & Vilkov（#35 标尺）— 等权跑赢市值加权

- **元数据**：*Why Does an Equal-Weighted Portfolio Outperform Value- and Price-Weighted Portfolios?*；Yuliya Plyakha（现署 Yuliya Plyakha）、Raman Uppal、Grigory Vilkov；SSRN 工作论文（无期刊发表版，Crossref 检索未见非 SSRN 版本）：修订版 SSRN #2724535（2016）、初版 SSRN #1787045（2012）；另为 EDHEC 工作论文（literature-map.md 原记，本次未单独抓 EDHEC 页）。
- **摘要要点**（Crossref 上 SSRN 记录 #2724535 的官方摘要全文，2026-08-16 拉取）：
  - 比较**美国主要股指**成分股构建的**等权 / 价值加权 / 价格加权**组合，样本为**过去四十年**（月度再平衡等权组合）。
  - **等权组合在总平均收益、四因子 alpha、夏普比率、确定等价收益（certainty-equivalent return）四方面全面跑赢**价值加权与价格加权——尽管等权组合**组合风险更高**。
  - 超额总收益来自两部分：①承担系统性风险的收益更高（对市场、规模、价值因子的暴露更高）；②四因子模型下 alpha 更高。
  - 非参数**单调性关系检验**：等权与价值/价格加权的总收益差异与**规模、价格、流动性、特质波动率**单调相关。
  - **alpha 的唯一来源是维持等权的月度再平衡**——这是逆向（contrarian）策略，利用了股票收益的**反转（reversal）与特质波动率**；alpha 只取决于月度再平衡本身，**与初始权重选择无关**。
- **方法要点**：美国主要股指成分股、过去四十年（摘要口径）；组合对比口径 = 总收益/四因子 alpha/Sharpe/CE 收益；显著性 = 四因子模型回归 + 非参数单调性检验。（具体指数清单、样本起止年、t 值在摘要之外，未核原文。）
- **作者结论**：等权（月频再平衡）稳定跑赢价值/价格加权，但超额收益**不是免费午餐**——系统性风险暴露更高 + 月度再平衡的逆向交易（反转/特质波动率）贡献 alpha。
- **对论断判定**：
  - **#35 等权跑赢市值加权 → 支持**：论文直接对比等权 vs 市值加权（含价格加权），四口径全面跑赢，方向与幅度结论明确。
  - ⚠️ 引用警示：a) 等权组合**波动更大**（收益是"风险换来的+逆向 alpha"）；b) alpha 依赖**月度再平衡**——本库若用其他再平衡频率或权重口径，结论不可直接平移；c) 论文是美股四十年样本。
- **来源**：Crossref https://api.crossref.org/works/10.2139/ssrn.2724535 （摘要全文）；SSRN 页面 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2724535 （直连 403，需代理）；初版 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1787045

## 2. Evans & Archer 1968（#36 标尺）— 分散化降低收益离差

- **元数据**：*Diversification and the Reduction of Dispersion: An Empirical Analysis*；John L. Evans、Stephen H. Archer；The Journal of Finance, 1968, 23(5), 761–767（1968-12）；DOI 10.1111/j.1540-6261.1968.tb00315.x（Crossref 与 OpenAlex 双渠道确认；OpenAlex W1973241508，被引 531；RePEc 记录 153 引）。
- **摘要要点**：**无官方摘要**——老文献，以下渠道全部尝试过均无摘要：Crossref（无 abstract 字段）、OpenAlex（NONE）、Semantic Scholar（NONE，含 tldr）、RePEc/IDEAS 页面（有标题无摘要）、Wiley 官网（Cloudflare "Just a moment…" 拦截，WebFetch/cloak/curl 三路均失败）、JSTOR（无公开页面入口，Crossref 无 JSTOR alternative-id）、MDPI/PMC 相关综述（403 或不在库）。→ 按任务预案，用**引用方正文片段**（S2 citation contexts，2026-08-16 拉取 100 条引用中命中 40+ 条含 Evans-Archer 描述）如实转述：
  - **方法共识**（多条引用一致）：随机选取股票构建**等权组合**，组合规模递增（1 至 40 只），度量**平均收益率标准差（dispersion）随组合规模的下降速率**；开创了"组合规模→风险"的实证研究范式（"Evans and Archer conducted the first realworld study…random equal-weight portfolios of increasing cardinality…plotting the average portfolio volatility as a function of cardinality" — *Defining and measuring portfolio diversification*, 2021）。
  - **结论共识**：平均标准差随规模**快速下降**，规模到达一定数量后边际下降**可忽略**（"the average standard deviation decreases quickly when the portfolio size increases" — *Z-score vs minimum variance preselection methods*, 2020）；**8–10 只**成为业界流传的分散化"经验法则"（"The traditional 'rule of thumb'…complete reduction of diversifiable risk with only 8–10 stocks in the portfolio has been presented in many studies after the pioneering work of Evans and Archer (1968)" — *How Many Stocks Are Sufficient for Equity Portfolio Diversification? A Review of the Literature*, JRFM 2021）；早期基于（半）年度/季度数据的文献总结的最优持股数为 **8–16 只**（同综述 + *Portfolio Diversification Revisited*, 2022）；亦有引用称"10 只足够"（*Investing in Reputation*, 2025）或"最少 8 只"（*Does financial integration impact performance of equity anomalies?*, 2022）。
  - ⚠️ 口径备注：Evans & Archer 测的是**股票数量分散**（等权、随机），不是**行业分散**；度量是**收益标准差（离差）**，不是回撤。另有 2023 年引文称样本为"1 至 40 只股票、19 只后无显著差异"（*Applying Random Forest…*, 2023）——与主流"8-10 只"表述略有出入，注明以防误引。论文原始样本细节（股票池/时期）未从公开渠道核实到，不写。
- **方法要点**：随机等权组合 × 规模递增（1–40）；度量收益率标准差下降曲线；结论 = 分散化的边际风险降低收益在较小规模即耗尽。
- **作者结论**（转述）：分散化能实质降低组合收益离差，且**少量股票（约 8–10 只）即获得绝大部分效果**。
- **对论断判定**：
  - **#36 行业分散降回撤 >20% → 部分支持（方向支持、口径不同）**：论文证明"分散化显著降低组合风险"，方向支持；但 a) 论文是**股票数**分散而非**行业**分散；b) 度量是**收益标准差**而非**回撤**；c) ">20%"幅度未报告。故 #36 可用本文作"分散化降低波动"的学术依据，但"行业/回撤/20%"三要素均需本库自己的回测实证，不能直接引用论文数字。
  - 补充佐证：Wikipedia《Diversification (finance)》以本文为引证来源之一（"More stocks give lower price volatility"），页内 Elton-Gruber 数据表显示 1 只→20 只，年化标准差 49.24%→21.68%（比率 0.44），30 只→20.87%，1000 只→19.21%——与"大部分分散收益在小规模即获得"一致（来源：https://en.wikipedia.org/wiki/Diversification_(finance) ）。
- **来源**：https://doi.org/10.1111/j.1540-6261.1968.tb00315.x ；OpenAlex https://api.openalex.org/works/W1973241508 ；S2 引用上下文 https://api.semanticscholar.org/graph/v1/paper/8bd8e76cd5326d787162ea0982c0bc2541171fb7/citations ；RePEc https://ideas.repec.org/a/bla/jfinan/v23y1968i5p761-767.html ；Wikipedia https://en.wikipedia.org/wiki/Diversification_(finance)

## 3. Willenbrock 2011（#37 标尺）— 再平衡产生分散化收益

- **元数据**：*Diversification Return, Portfolio Rebalancing, and the Commodity Return Puzzle*；Scott Willenbrock；Financial Analysts Journal, 2011, 67(4), 42–49；DOI 10.2469/faj.v67.n4.1（Crossref/OpenAlex/S2 三渠道确认）；SSRN 预印本 #1898864（2010）；arXiv:1109.1256（2011-09，作者署名 University of Illinois at Urbana-Champaign）。
- **摘要要点**（OpenAlex 与 S2 逐字一致，arXiv 页复核一致）：
  - **分散化收益（diversification return）是再平衡组合赚取的增量收益**；作者论证其**根本来源是再平衡本身**——再平衡"迫使投资者卖出相对升值资产、买入相对贬值资产"（arXiv 原文 paraphrase）。
  - 对比：**买入持有**组合的增量收益来自"表现最好的资产在组合中占比越来越大"。
  - 借此**解决了 Gorton & Rouwenhorst 商品期货指数谜题的两个方面**。
  - arXiv 摘要补充要点：分散化收益**常被错误归因于方差降低**；"对于任何由波动资产构成并再平衡的组合，分散化收益都可能是显著的收益来源"（arXiv 页 paraphrase，原文 "Diversification return can be a significant source of return for any rebalanced portfolio of volatile assets"）。
- **方法要点**：理论推导（分解组合几何收益 vs 加权几何收益）+ 商品期货指数实证（Gorton-Rouwenhorst 指数谜题）。（论文正文的具体推导步骤未核，仅摘要口径。）
- **作者结论**：再平衡本身是分散化收益的来源，不是方差降低；再平衡=高抛低吸（卖出涨的、买入跌的）。
- **对论断判定**：
  - **#37 再平衡年化超额 >1% → 支持（方向）/ 幅度待核**：论文确立"再平衡有独立、可观的收益贡献"，方向支持；但"年化 >1%"这一具体幅度是**本库论断口径**，论文摘要未报告具体百分比——幅度需对照本库回测或 Booth-Fama 1992 框架计算。
  - ⚠️ 引用警示（结合 Chambers-Zdanowicz 2014，见 5.5）：再平衡收益**不是期望值的免费增加**，而是**均值回归策略**的体现；在无均值回归的随机游走世界里无此收益。引用时不要写成"再平衡无风险增加收益"。
- **来源**：https://doi.org/10.2469/faj.v67.n4.1 ；arXiv https://arxiv.org/abs/1109.1256 ；SSRN https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1898864

## 4. Li, Refalo & Yi 2025（#41 标尺）— 行业集中度与股票收益

- **元数据**：*Industry Classification, Industry Concentration, and Stock Returns*；Scott Li、James Refalo、Jong-Hwan Yi；Financial Markets and Portfolio Management, 2025, 39(3), 337–363（online 2025-03-17，Springer 官网 meta 确认）；DOI 10.1007/s11408-025-00470-z（Crossref/OpenAlex/S2 三渠道确认）；文章类型 OriginalPaper（Springer dc.type 确认）。
- **摘要要点**（Springer 官网 HTML `Abs1-content` 原文，2026-08-16 curl 直取）：
  - 研究**美国市场**中**不同行业分类层级**下行业集中度水平与股票收益的关系。
  - 结论一：**效应在不同分类层级间差异显著**；该差异**不能被规模、账面市值比、动量等常见风险因子完全解释**。
  - 结论二：关系**随样本期变化**（1963–2019，对应市场微观结构演化）。
  - 结论三：**两位 SICCD 与 Fama-French 48 行业分类**在**行业整合期（1998–2019）**构造的"行业集中度高−低"多空组合收益**显著更高**。
  - 结论四：结果**支持 Schumpeter 的理论**（创新/创造性破坏视角下的风险与收益解释）。
- **方法要点**：美国市场 1963–2019；多分类层级（SICCD 层级 + FF48）对比；集中度多空组合（high-minus-low）收益；风险因子（规模/BM/动量）解释力检验。（具体集中度指标构造、显著性水平在摘要之外，未核原文。）
- **作者结论**：行业集中度对股票收益的影响**真实存在但高度依赖分类口径与时期**；整合期高集中度组合有显著溢价。
- **对论断判定**：
  - **#41 行业集中度 >40% 暴跌 >50% → 部分支持（前提成立、结论不等价）**：论文与 Hou-Robinson 2006 共同确认**"行业集中度是横截面收益的显著决定因素"**，即 #41 的前提（行业集中度影响组合表现）有学术支撑；但论文测的是**横截面收益溢价**，不测"集中度 >40% 的暴跌概率/幅度 >50%"，该具体阈值断言仍需本库回测验证。
  - ⚠️ 方向警示：Hou & Robinson 2006 发现**高集中度行业收益更低**（低竞争度→低创新→低风险补偿）；Li et al. 2025 发现整合期高集中度组合收益**更高**——两文在集中度溢价**方向上有张力**，引用时须按样本期/分类口径区分，不能混用。
- **来源**：Springer https://link.springer.com/article/10.1007/s11408-025-00470-z （摘要原文页）；https://doi.org/10.1007/s11408-025-00470-z

---

## 5. 补充论据论文

### 5.1 Swade, Nolte, Shackleton & Lohre 2023（#35 等权最新实证）
- **元数据**：*Why Do Equally Weighted Portfolios Beat Value-Weighted Ones?*；Alexander Swade、Sandra Nolte、Mark Shackleton、Harald Lohre；The Journal of Portfolio Management, 2023, 49(5), 167–187；DOI 10.3905/jpm.2023.1.482（OpenAlex/S2 双渠道确认）。
- **摘要要点**（OpenAlex 与 S2 逐字一致）：等权（EW）组合在**多个投资宇宙、多个十年**中跑赢市值加权（VW）；EW–VW 价差归因：**显著正规模因子暴露** + 再平衡带来的**短期反转收益** + **负动量暴露** + **1 月季节性**；并在 S&P 500 成分股（更可投资宇宙）复核。
- **作者结论**：等权跑赢是长期事实，但本质是**因子暴露的组合**（规模+反转−动量+季节），非单一"等权魔法"。
- **对论断判定**：#35 → **支持**（最新实证 + 机制分解，与 Plyakha 的"再平衡→反转→alpha"结论互相印证）。
- **来源**：https://doi.org/10.3905/jpm.2023.1.482

### 5.2 DeMiguel, Garlappi & Uppal 2009（#35/#36 朴素 1/N 策略）
- **元数据**：*Optimal Versus Naive Diversification: How Inefficient Is the 1/N Portfolio Strategy?*；Victor DeMiguel、Lorenzo Garlappi、Raman Uppal；Review of Financial Studies, 2009, 22(5), 1915–1953；DOI 10.1093/rfs/hhm075（Crossref/OpenAlex 双渠道确认，被引 3268）。
- **摘要要点**（OpenAlex）：用 7 组实证数据评估 14 个基于样本的均值-方差模型及其降估误差扩展，**没有一个在夏普比率/确定等价收益/换手率上稳定优于朴素 1/N 等权**——样本外最优化的收益被**估计误差**抵消；按美股参数校准，均值-方差策略要超越 1/N 需约 **3000 个月（25 只资产）/ 6000 个月（50 只资产）**的估计窗口。
- **作者结论**：样本外等权 1/N 极难被击败，"最优分散化的路还很长"。
- **对论断判定**：#35/#36 → **支持**（等权作为基准的稳健性；分散化收益来自简单规则而非复杂优化）。
- **来源**：https://doi.org/10.1093/rfs/hhm075

### 5.3 Statman 1987（#36 需要多少只股票）
- **元数据**：*How Many Stocks Make a Diversified Portfolio?*；Meir Statman；Journal of Financial and Quantitative Analysis, 1987, 22(3), 353–363；DOI 10.2307/2330969（Crossref/OpenAlex 双渠道确认，被引 613）。
- **摘要要点**（OpenAlex）：一个充分分散的随机股票组合**至少需要 30 只（借贷投资者）或 40 只（贷出投资者）**，**反驳**了"约 10 只即基本分散"的流行观念；并与个人投资者实际持股分散度对比。
- **作者结论**：10 只不够——分散化需要 30–40 只（含**资产出售/借贷约束**后的口径）。
- **对论断判定**：#36 → **部分支持/修正**：与 Evans-Archer"8-10 只"张力明显——**方向都是"分散降风险"**，但 Statman 以更严格的均值-方差口径（组合标准差须达市场水平的约 1.1 倍以内）给出更高门槛；引用 #36 时应并陈两文，避免只引 Evans-Archer 支持"少量股票即可"。
- **来源**：https://doi.org/10.2307/2330969

### 5.4 Hou & Robinson 2006（#41 行业集中度与收益）
- **元数据**：*Industry Concentration and Average Stock Returns*；Kewei Hou、David T. Robinson；The Journal of Finance, 2006, 61(4), 1927–1956；DOI 10.1111/j.1540-6261.2006.00893.x（Crossref/OpenAlex 双渠道确认，被引 919；SSRN 初版 10.2139/ssrn.479726）。
- **摘要要点**（OpenAlex）：**集中度更高行业的公司平均收益更低**（控制规模/BM/动量等后仍显著）；随机性、测量误差、资本结构、持续性现金流冲击均不能解释；用产业组织理论解释：高集中度行业**进入壁垒**使公司免受不可分散困境风险，或**创新更少**因而风险更低→要求更低预期收益；时间序列检验支持风险解释。
- **作者结论**：行业集中度与平均收益**显著负相关**（风险视角）。
- **对论断判定**：#41 → **部分支持（前提）**：确认"行业集中度是横截面收益的系统性决定因素"；方向与 Li et al. 2025 整合期结果相反（见第 4 节警示）；不测暴跌概率/幅度。
- **来源**：https://doi.org/10.1111/j.1540-6261.2006.00893.x

### 5.5 Chambers & Zdanowicz 2014（#37 再平衡收益的"限制"视角，重要对冲引用）
- **元数据**：*The Limitations of Diversification Return*；Donald R. Chambers、John S. Zdanowicz；The Journal of Portfolio Management, 2014, 40(4), 65–76；DOI 10.3905/jpm.2014.40.4.065（OpenAlex 确认，被引 28）。
- **摘要要点**（OpenAlex）：分散化收益是组合几何平均收益超出成分几何加权平均的部分，曾被宣扬为**信息有效市场中的额外收益来源**；本文证明**分散化收益并非期望价值的增加**；但**再平衡可以是有效的均值回归策略**——再平衡带来的任何期望价值增强**来自均值回归，而非分散化或方差降低**。
- **作者结论**：再平衡收益≠免费午餐；其价值依赖**均值回归**。
- **对论断判定**：#37 → **修正性引用**：与 Willenbrock 搭配使用——"再平衡有收益"须限定"均值回归环境下"；#37 的"年化超额>1%"应在本库回测中检验均值回归假设是否成立。
- **来源**：https://doi.org/10.3905/jpm.2014.40.4.065

### 5.6 Booth & Fama 1992（#37 "分散化收益"概念源头，摘要待补）
- **元数据**：*Diversification Returns and Asset Contributions*；David G. Booth、Eugene F. Fama；Financial Analysts Journal, 1992, 48(3), 26–32；DOI 10.2469/faj.v48.n3.26（Crossref/OpenAlex 确认；"分散化收益"术语出处，Willenbrock 摘要亦提及该术语起源于再平衡组合语境）。
- **摘要要点**：**待补**（OpenAlex/S2 均无摘要；tandfonline 直连未取到内容）。
- **对论断判定**：#37 → 概念源头文献（术语出处），判定依赖正文，标"待补"。
- **来源**：https://doi.org/10.2469/faj.v48.n3.26

### 5.7 Kühn & Luenberger 2009（#37 再平衡频率研究）
- **元数据**：*Analysis of the rebalancing frequency in log-optimal portfolio selection*；Daniel Kühn、David G. Luenberger；Quantitative Finance, 2009, 10(2), 221–234；DOI 10.1080/14697680802629400（OpenAlex 确认，被引 40）。
- **摘要要点**（OpenAlex）：对数最优（log-optimal）框架下研究再平衡频率：**无交易成本且再平衡间隔短于约一年时，连续再平衡仅略优于离散再平衡**；高频率在交易成本下反而损害绩效，低频率则接近静态策略；分散化对组合增长率的均值与方差及其对再平衡频率的敏感性有双重效应。
- **作者结论**：再平衡频率存在最优区间（约一年内连续 vs 离散差异小；成本权衡）。
- **对论断判定**：#37 → **频率维度补充**：支持"再平衡频率选择有实质影响"；与本库 #37 的"年化超额"结合时可作频率设定依据。
- **来源**：https://doi.org/10.1080/14697680802629400

---

## 6. 汇总：对论断的判定一览

| 论断 | 标尺论文 | 判定 | 一句话依据 |
|:----|:--------|:----|:----------|
| #35 等权跑赢市值加权 | Plyakha-Uppal-Vilkov | **支持** | 月频再平衡等权组合在总收益/四因子 alpha/Sharpe/CE 收益四口径全面跑赢，alpha 来自再平衡的逆向交易（反转+特质波动率），代价是更高风险 |
| #36 行业分散降回撤>20% | Evans & Archer 1968 | **部分支持（口径不同）** | 分散化显著降低收益离差且 8-10 只即获大部分效果；但论文测"股票数分散+标准差"，非"行业分散+回撤"，>20% 幅度无论文依据；Statman 1987 更严格（30-40 只） |
| #37 再平衡年化超额>1% | Willenbrock 2011 | **支持（方向），幅度待本库核实** | 再平衡本身产生分散化收益（高抛低吸），是 Gorton-Rouwenhorst 谜题的关键；但 Chambers-Zdanowicz 警示该收益来自均值回归而非无风险增值，">1%"需回测确认 |
| #41 行业集中度>40%暴跌>50% | Li-Refalo-Yi 2025 | **部分支持（前提），阈值断言无直接论文证据** | 行业集中度确为横截面收益的显著决定因素（分类层级/样本期依赖）；"暴跌>50%"的阈值与集中度多空收益测的是不同东西，需本库回测；方向注意 Hou-Robinson 2006 与 Li et al. 相反 |

## 7. 待补事项清单

1. **Evans & Archer 1968 官方摘要/原文**：Wiley 官网（Cloudflare）、JSTOR（无入口）、Semantic Scholar tldr 均拿不到；如需原文级细节（精确样本 470 只 NYSE 等），需有 Wiley 订阅权限的渠道补正文。
2. **Plyakha 论文正文细节**（具体指数清单、样本起止年、t 值）：SSRN 直连被 403，需代理后下载 PDF 核正文。
3. **Li et al. 2025 方法细节**（集中度指标构造、显著性水平）：摘要之外未核原文；Springer 页有付费墙，正文需订阅。
4. **Booth & Fama 1992 摘要**：OpenAlex/S2 无，tandfonline 未取到；属概念源头文献，正文细节待补。
5. **#36/#41 的"幅度/阈值"对照**：本组 4 篇标尺均不直接报告"回撤降 20%"或"暴跌 50%"类数字——这些阈值必须由本库回测验证，论文仅提供机制与方向。

---
*维护规则：本文件由"论文研究员"子代理按组维护（03 = 组合构建/再平衡）；新增论文结论必须附来源 URL；摘要未取得的写"待补"并列出尝试渠道；联动：literature-map.md（元数据表）、literature-conclusions.md（结论对照表，其中本组 Plyakha/Willenbrock/Li et al. 三条"摘要未取得"已可更新为"已取得"）。*
