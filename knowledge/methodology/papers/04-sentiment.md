# 论文研究笔记：情绪/媒体/信息（论断 #13-18）

> 抓取日期：2026-08-16 | 渠道：Crossref API / OpenAlex（含摘要还原）/ Semantic Scholar / arXiv 1010.3003 全文 / NYU 作者主页 PDF / figshare 全文 / NBER w18725 / 微信与 Search King 辅助
> 防幻觉纪律：所有条目均来自实际抓取内容；拿不到的标"待补"，不凭记忆补写。DOI 全部经 Crossref 核实。

---

## 1. Baker & Wurgler 2006（#13/#14 标尺）

- **元数据**：Malcolm Baker（Harvard Business School/NBER）、Jeffrey Wurgler（NYU Stern/NBER）；*Investor Sentiment and the Cross-Section of Stock Returns*；The Journal of Finance, 2006, 61(4), 1645–1680；DOI 10.1111/j.1540-6261.2006.00885.x；OpenAlex 被引 6232 次。
- **摘要要点**（官方摘要）：情绪对证券横截面收益的影响；情绪冲击对"估值主观性强、难套利"的证券影响更大；期初情绪低时，小盘/年轻/高波动/亏损/不分红/极端成长/困境股后续收益相对高；情绪高时这些类别收益相对低。
- **方法要点**（全文 PDF 提取）：
  - 样本期：**1963–2001 月度收益**（CRSP-Compustat 合并，share codes 10/11，公司数据 1962–2001）；情绪代理按**年度**（1962–2001）度量；另以 1935–1961 样本做稳健性检查。
  - 样本规模：NYSE 分位基准 + AMEX/NYSE 全样本月度观测；每个情绪代理/特征排序的月度观测约数百至数千（论文以十分位分箱报告平均月收益）。
  - 情绪指数：6 个代理（封闭式基金折价 CEFD、NYSE 换手率 TURN、IPO 数量 NIPO、IPO 平均首日收益 RIPO、新股权益份额 S、股息溢价 PD-ND）→ 第一阶段取 6 代理及其滞后共 12 项的第一主成分 → 每代理选与一阶段指数相关更高的当期/滞后值 → 第二主成分并单位方差化；另有正交化到宏观条件（利率/通胀等）的版本。
  - 指数系数（原文式 2）：SENTIMENT_t = −0.241·CEFD_t + 0.242·TURN_{t−1} + 0.253·NIPO_t + 0.257·RIPO_{t−1} + 0.112·S_t − 0.283·PD−ND_t。
  - 检验设计：非参数双重排序（月初特征十分位 × 上年末 SENTIMENT 高低两档）比较条件平均月收益差 + 条件特征模型回归。
  - 显著性：条件效应显著；最惊人发现——**无条件无预测力的特征（如波动率、盈利、分红）在条件于情绪后出现符号翻转的预测力**；并检验排除系统性风险解释（收益模式与市场/消费增长 beta 无关）。
  - 适用边界：指数是**相对情绪测量**（相对样本均值高低，非绝对水平）；情绪为年度频率；横截面（个股间相对收益）效应，**非**市场整体时序择时信号；美国市场。
- **作者结论**：投资者情绪显著影响横截面收益，难估值/难套利股对情绪最敏感，情绪高低期收益结构反转。
- **对论断判定**：
  - #13 情绪共识：**支持（条件性）**——情绪指数高企时难估值股相对跑输、低情绪时相对跑赢，可作为"情绪反向/风格切换"的学术标尺；但效应是**横截面相对**的，不是"情绪高低=市场涨跌"的择时信号。
  - #14 市场情绪：**部分支持**——论文验证的是"情绪指数预测横截面收益差异"，不是市场指数时序收益；若 #14 把情绪当反向市场指标，应限定在难估值股维度。
- **来源**：NYU 全文 PDF http://pages.stern.nyu.edu/~jwurgler/papers/sentiment.pdf（抓取日期 2026-08-16）；Crossref https://api.crossref.org/works/10.1111/j.1540-6261.2006.00885.x ；OpenAlex https://api.openalex.org/works/doi:10.1111/j.1540-6261.2006.00885.x

## 2. Tetlock 2007（#15 标尺）

- **元数据**：Paul C. Tetlock；*Giving Content to Investor Sentiment: The Role of Media in the Stock Market*；The Journal of Finance, 2007, 62(3), 1139–1168；DOI 10.1111/j.1540-6261.2007.01232.x；OpenAlex 被引 4610 次。
- **摘要要点**（官方摘要）：高媒体悲观预测价格**下行压力后回归基本面**；异常高/低悲观预测**高交易量**；结果与噪音/流动性交易者理论一致，**排除**"媒体=基本面新信息代理 / 波动率代理 / 与市场无关的杂音"三种解释。
- **方法要点**：
  - 数据：每日 **Wall Street Journal "Abreast of the Market" 专栏**文本，构建媒体悲观主义测量。
  - 词典：**General Inquirer 程序 + Harvard IV-4 词典**，计算专栏负面词比例（经 Boudoukh, Feldman, Kogan & Richardson 2013, NBER w18725 全文确认："Tetlock (2007) who employs the General Inquirer ... alongside the Harvard-IV-4 dictionary (denote IV-4) to calculate the fraction of negative words in the Abreast of the Market Wall Street Journal column"）。
  - 检验设计：向量自回归（VAR）考察悲观→价格压力→回归的动态；悲观与交易量关系。
  - 显著性：官方摘要报告显著（"high media pessimism predicts ..."，结果为一致显著模式）。
  - 样本期确切年份区间：**待补**（发表版全文无法免费获取；Crossref/OpenAlex/IDEAS 仅有官方摘要，未含样本期数字）。
  - 适用边界：指数级（DJIA/市场）媒体情绪、短期（日内至数日）动态；媒体悲观是**噪音交易情绪代理**而非基本面信息。
- **作者结论**：媒体情绪作用于短期价格压力并随后回归，与噪音交易者模型一致。
- **对论断判定**：#15 新闻影响：**支持（短期反向）**——"媒体极度悲观→短期下行压力→随后回归基本面"为"悲观至极时是买入窗口"提供直接学术依据；但注意：效应在指数级/短期，且"回归"含义是价格回到基本面而非必然上涨。
- **来源**：Crossref https://api.crossref.org/works/10.1111/j.1540-6261.2007.01232.x ；OpenAlex https://api.openalex.org/works/doi:10.1111/j.1540-6261.2007.01232.x ；词典确认：Boudoukh et al. 2013 NBER w18725 PDF http://www.nber.org/papers/w18725.pdf

## 3. Bollen, Mao & Zeng 2011（#16 标尺）

- **元数据**：Johan Bollen, Huina Mao, Xiaojun Zeng；*Twitter mood predicts the stock market*；Journal of Computational Science, 2011, 2(1), 1–8；DOI 10.1016/j.jocs.2010.12.007；Semantic Scholar 被引 5454 次（Crossref 无摘要，Semantic Scholar 有完整摘要）。
- **摘要要点**：大型 Twitter 情绪测量与 DJIA 相关；Granger 因果 + 自组织模糊神经网络（SOFNN）检验；加入特定情绪维度后 DJIA 日涨跌预测**准确率 87.6%**、MAPE 降 >6%；"特定情绪维度而非其他"有效。
- **方法要点**（arXiv 1010.3003 全文提取）：
  - 样本期：**2008-02-28 至 2008-12-19**（约 10 个月）；**9,853,498 条 tweets**，约 **270 万用户**。
  - 情绪工具：OpinionFinder（正/负二分）+ GPOMS（6 维度：Calm 平静 / Alert 警觉 / Sure 确信 / Vital 活力 / Kind 友善 / Happy 快乐）。
  - 检验设计：Granger 因果（样本期 2008-02-28 至 11-03，排除大选/感恩节异常）；SOFNN 输入排列 I0={DJIA t−1,t−2,t−3} 为基准，共 7 种组合（I0、I1=+Calm、I1,2、I1,3…I1,6、IOF=+OpinionFinder）；**测试期 2008-12-01 至 12-19**（19 个交易日）；指标=方向准确率 + MAPE。
  - 显著性：含 Calm 的方向准确率 87.6%；单 20 天窗口偶然概率 0.32%（二项分布），全样本约 10.9 个窗口的整体偶然概率 **3.4%**；嵌套 F 检验 Calm+Happy 线性组合 p=0.66（不显著）→ 情绪维度间为**非线性**关系；OpinionFinder 正负情绪无预测增益（与 Granger 结果一致）。
  - 适用边界：样本极短（约 10 个月、测试期 19 天）、**单一指数（DJIA）**、事后研究、非交易策略测试；情绪为日度聚合。
- **作者结论**：公共情绪的特定维度（Calm 起关键作用）可预测 DJIA 次日方向。
- **对论断判定**：#16 社交媒体：**支持（弱/有条件）**——确证"社交媒体情绪存在统计预测力"；但样本规模小、测试期短、单指数，**不能**支撑"可交易 alpha"级结论，作为"情绪信号有信息含量"证据使用。
- **来源**：arXiv 全文 https://arxiv.org/abs/1010.3003 （PDF https://arxiv.org/pdf/1010.3003）；Semantic Scholar https://api.semanticscholar.org/graph/v1/paper/DOI:10.1016/j.jocs.2010.12.007 ；Crossref https://api.crossref.org/works/10.1016/j.jocs.2010.12.007

## 4. Jegadeesh, Kim, Krische & Lee 2004（#17 标尺）

- **元数据**：Narasimhan Jegadeesh, Joonghyuk Kim, Susan D. Krische, Charles M. C. Lee；*Analyzing the Analysts: When Do Recommendations Add Value?*；The Journal of Finance, 2004, 59(3), 1083–1124；DOI 10.1111/j.1540-6261.2004.00657.x；OpenAlex 被引 1041 次。
- **摘要要点**（官方摘要）：卖方分析师普遍推荐 "glamour"（正动量/高增长/高成交量/相对昂贵）股；**盲从共识代价高**——共识**水平**仅在有利量化特征（价值股+正动量股）上增加价值；不利特征股中共识水平越高后续收益**越差**；相反，共识的季度**变化**是稳健收益预测器，且与大量其他预测变量正交。
- **方法要点**（figshare 全文 PDF 提取）：
  - 样本期：**1985–1998**（56 个季度）；Zacks 数据库"当前个人推荐"（未满 1 年）+ CRSP/Compustat/IBES 数据；每季度样本公司约 400–1000+ 家（1985 年约 405 家 → 1990s 末约 1000 家）。
  - 检验设计：季度共识**水平**（12 个月累积）vs 季度**变化**（CHGCONS）；**calendar-time 可实施组合策略**（区分于 Womack 事件研究）；按量化特征（QScore：价值/动量，含 12 个其他预测变量）分类交互检验；Spearman 秩相关 + 自相关稳健 t 统计量（逐季度估计取时序均值）。
  - 显著性：共识水平在低 QScore（不利特征）组超额收益"reliably negative"（可靠为负，随持有期延长更强）；共识变化稳健且正交；**6 个月后无显著 drift**。
  - 边界：美国、1985–1998 时代数据；共识水平预测力被"growth bias"污染，变化受污染小。
- **作者结论**：共识水平价值有限（仅限价值+正动量股），共识变化才是稳健信号。
- **对论断判定**：#17 分析师共识：**反对（盲从共识水平）**——论文直接反驳"跟分析师共识买"：平均水平上共识越高对不利特征股反而越差；但**细分口径**：共识的"变化"（升级/降级）有信息价值——若 #17 论断用"共识上调/下调"则应转向支持。
- **来源**：figshare 全文 PDF https://figshare.com/articles/online_resource/Analyzing_the_analysts_when_do_recommendations_add_value_/23891319 （下载 https://ndownloader.figshare.com/files/41889408）；Crossref https://api.crossref.org/works/10.1111/j.1540-6261.2004.00657.x ；OpenAlex https://api.openalex.org/works/doi:10.1111/j.1540-6261.2004.00657.x

## 5. Sias 2004（#18/#47 标尺）

- **元数据**：Richard W. Sias；*Institutional Herding*；Review of Financial Studies, 2004, 17(1), 165–206；DOI 10.1093/rfs/hhg035；OpenAlex 被引 906 次（Crossref 无摘要，OpenAlex 有完整摘要）。
- **摘要要点**（OpenAlex 官方摘要）：机构投资者本季度对某证券的需求与上季度需求**正相关**；归因于机构彼此跟随进出同一证券（"herding"羊群）+ 机构跟随自己的滞后交易（"following their own lag trades"自跟）；机构是"动量"交易者，但**羊群中只有一小部分来自动量交易**；机构需求与**滞后机构需求**的关系强于与**滞后收益**的关系；结果与"机构从彼此交易中**推断信息**"假说最一致。
- **方法要点**：
  - 检验设计核心（来自官方摘要）：季度层面机构需求的自相关分解（羊群 vs 自跟 vs 动量）；横截面回归比较机构需求与滞后机构需求、滞后收益的关系强度。
  - 样本期/数据源（如 13F 季度持仓、1983–1997 等具体区间）：**待补**（RFS 全文无免费渠道，Wiley/OUP 均拦截；仅官方摘要可验证）。
- **作者结论**：机构羊群现象确证；主要驱动是机构间信息推断，而非动量或盲目跟风。
- **对论断判定**：
  - #18 机构资金流（跟随机构资金流）：**有条件支持**——机构需求存在强季度持续性（羊群+自跟），说明"机构资金流有可观测的持续性/聚集性"；但论文结论是"相关性/行为模式"，**非**"机构买入=后续正收益"的可交易信号，且羊群含信息推断（非纯噪音）。
  - #47 羊群（行为基础）：支持"机构羊群存在且可测"。
- **来源**：OpenAlex https://api.openalex.org/works/doi:10.1093/rfs/hhg035 ；Crossref https://api.crossref.org/works/10.1093/rfs/hhg035 ；作者 CV 确认元数据：https://eller.arizona.edu/sites/default/files/Sias_CV_July_2025.pdf

---

## 补充论据论文（6 篇，2020+ 优先，全部经 OpenAlex/Crossref 校验）

### S1. Huang, Jiang, Tu & Zhou 2015 — 情绪指数最新构建（#13/#14）
- **元数据**：Dashan Huang, Fuwei Jiang, Jun Tu, Guofu Zhou；*Investor Sentiment Aligned: A Powerful Predictor of Stock Returns*；Review of Financial Studies, 2015, 28(3)；DOI 10.1093/rfs/hhu080；OpenAlex 被引 1155。
- **摘要要点**：提出"对齐"（aligned）情绪指数——通过消除情绪代理中的共同噪音成分，样本内/样本外预测力大幅超越既有指数（含 BW 指数）；统计与经济显著性兼备；优于公认宏观变量；还能预测按行业/规模/价值/动量分组的横截面收益；预测力来源与有限套利相关。
- **对论断判定**：#13/#14 补充支持——BW 指数存在可改进空间，对齐法提升市场收益预测力；建议复核 #13/#14 时以 BW 2006 为基准方法、以本篇为增强版参照。
- **来源**：https://api.openalex.org/works/doi:10.1093/rfs/hhu080

### S2. Obaid & Pukthuanthong 2021 — 新闻照片情绪指数（#13/#14）
- **元数据**：Khaled Obaid, Kuntara Pukthuanthong；*A picture is worth a thousand words: Measuring investor sentiment by combining machine learning and photos from news*；Journal of Financial Economics, 2021；DOI 10.1016/j.jfineco.2021.06.002；OpenAlex 被引 207。
- **摘要要点**：机器学习分类新闻照片情绪，构建日度市场情绪指数 "Photo Pessimism"；1926–2018 样本上预测市场收益反转与交易量增加；预测力集中在**高套利限制股**与**高不确定期**；业务新闻照片的预测力比一般新闻照片**强 6 倍以上**；照片悲观度在创伤性事件日/有影响力照片日可超越文本情绪。
- **对论断判定**：#13/#14 补充支持——非文本情绪渠道（照片）同样有横截面/时序预测力，强化"情绪可测、难估值股敏感"结论的现代证据。
- **来源**：https://api.openalex.org/works/doi:10.1016/j.jfineco.2021.06.002 ；Semantic Scholar https://api.semanticscholar.org/graph/v1/paper/DOI:10.1016/j.jfineco.2021.06.002

### S3. Huynh, Foglia, Nasir & Angelini 2021 — 媒体情绪最新实证（#15）
- **元数据**：Toan Luu Duc Huynh, Matteo Foglia, Muhammad Ali Nasir, Eliana Angelini；*Feverish sentiment and global equity markets during the COVID-19 pandemic*；Journal of Economic Behavior & Organization, 2021；DOI 10.1016/j.jebo.2021.06.016；OpenAlex 被引 170。
- **摘要要点**：以 17 大经济体六类行为指标（媒体覆盖、假新闻、恐慌、情绪、媒体炒作、信息流行病 infodemic），样本 2020-01-01 至 2021-02-03，TVP-VAR（时变参数向量自回归）构建 "feverish sentiment" 指数并测度全球市场情绪冲击的**总/净连通性**（谁发送/接收情绪冲击）。
- **对论断判定**：#15 补充支持——媒体/信息生态（含假新闻）在极端事件期对全球市场有可测的传染性影响；佐证"媒体情绪影响市场"，且提示危机期情绪信号更强。
- **来源**：https://api.openalex.org/works/doi:10.1016/j.jebo.2021.06.016 ；Semantic Scholar（含 OA PDF：https://pure.hud.ac.uk/ws/files/37393095/Manuscript_without_authors_details.pdf）

### S4. Gu & Kurov 2020 — Twitter 情绪预测力后续（#16）
- **元数据**：Chen Gu, Alexander Kurov；*Informational role of social media: Evidence from Twitter sentiment*；Journal of Banking & Finance, 2020；DOI 10.1016/j.jbankfin.2020.105969；OpenAlex 被引 164。
- **摘要要点**：**待补**（Elsevier 摘要接口无公开记录，ScienceDirect 需验证码；元数据/标题/年份/期刊/引用数已核验）。
- **对论断判定**：#16 补充（预期方向：考察 Twitter 情绪的信息角色/预测力，被引 164 为社交情绪领域高被引后续）；摘要待补后补判定。
- **来源**：https://api.openalex.org/works/doi:10.1016/j.jbankfin.2020.105969

### S5. Kong, Lin, Liu & Tan 2021 — 分析师推荐最新检验（#17）
- **元数据**：Dongmin Kong, Chen Lin, Shasha Liu, Weiqiang Tan；*Whose money is smart? Individual and institutional investors' trades based on analyst recommendations*；Journal of Empirical Finance, 2021；DOI 10.1016/j.jempfin.2021.04.001；OpenAlex 被引 43。
- **摘要要点**：上交所**账户级交易数据**：活跃机构投资者在"强力买入/买入"（"持有/卖出"）评级上显著净买入（净卖出）；机构根据分析师"买方压力"调整交易；机构因结合买方压力交易**获得超额收益**；相比之下个人投资者表现出异常交易反应（截断处：反应过度等）。
- **对论断判定**：#17 补充支持——分析师推荐信息含量对**机构**成立（机构能用好它），对**个人**有害；与 JKKL 2004 互补：共识本身无普适价值，价值取决于使用者与交易条件。
- **来源**：https://api.openalex.org/works/doi:10.1016/j.jempfin.2021.04.001 ；Semantic Scholar https://api.semanticscholar.org/graph/v1/paper/DOI:10.1016/j.jempfin.2021.04.001

### S6. Choi & Sias 2009 — 机构羊群后续（#18）
- **元数据**：Nicole Y. Choi, Richard W. Sias；*Institutional industry herding*；Journal of Financial Economics, 2009, 94(3), 469–491；DOI 10.1016/j.jfineco.2008.12.009；OpenAlex 被引 383。
- **摘要要点**：**待补**（Elsevier 无公开摘要接口；元数据经 Crossref/OpenAlex/作者 CV 三重核验）。
- **对论断判定**：#18 补充——Sias 自己的行业级羊群延伸研究（行业层面机构羊群），作为 #18 复核时的后续参照；摘要待补后补判定。
- **来源**：https://api.openalex.org/works/doi:10.1016/j.jfineco.2008.12.009 ；作者 CV https://eller.arizona.edu/sites/default/files/Sias_CV_July_2025.pdf

---

## 各组判定一览（供 #13-18 复核时对照）

| # | 论断主题 | 标尺论文 | 判定 | 关键限定 |
|:-:|:--------|:---------|:-----|:---------|
| 13 | 情绪共识 | Baker-Wurgler 2006 | 支持（条件性） | 横截面相对效应；难估值股维度最明显；情绪为相对测量 |
| 14 | 市场情绪 | Baker-Wurgler 2006 | 部分支持 | 论文测横截面差异，非市场时序择时；对齐版（S1）增强时序预测 |
| 15 | 新闻影响 | Tetlock 2007 | 支持（短期反向） | 悲观→短期下行→回归；指数级/短期；样本期待补 |
| 16 | 社交媒体 | Bollen-Mao-Zeng 2011 | 支持（弱/有条件） | 87.6% 方向准确率但样本 10 个月/单指数/非交易策略 |
| 17 | 分析师共识 | Jegadeesh et al. 2004 | 反对（盲从共识水平） | 水平仅价值+正动量股有用；共识"变化"有信息 |
| 18 | 机构资金流 | Sias 2004 | 有条件支持 | 羊群+自跟持续性强；非"买入=正收益"信号；信息推断为主 |

## 待补清单（后续可补）
- Tetlock 2007：样本期确切年份区间（发表版全文不可得）
- Sias 2004：样本期/数据源（13F?）等细节（RFS 全文不可得）
- Gu & Kurov 2020、Choi & Sias 2009：官方摘要（Elsevier 摘要接口限制）

## 维护规则
- 本笔记所有 DOI 均经 Crossref 验证；摘要/方法细节标注了实际抓取来源与日期。
- 补充论文入选标准：2020+ 优先、主题对应 #13-18、OpenAlex 被引排序靠前；被引数截至 2026-08-16。
- 联动：literature-map.md（元数据表）、literature-conclusions.md（论文结论对照）。
