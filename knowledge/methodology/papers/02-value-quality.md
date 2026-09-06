# 论文研究笔记：价值/质量/估值（论断 #29-34, 39, 42, 31）

> 抓取日期：2026-08-16 | 渠道：Crossref / OpenAlex / Semantic Scholar（元数据四渠道交叉校验）；IDEAS-RePEc、NBER 官网（Crawl4AI 渲染）、Wayback Machine 存档（ScienceDirect/JSTOR/SSRN 历史页面）、OpenAlex 摘要索引、作者工作论文 PDF（摘要正文）。
> 防幻觉纪律：以下摘要均为逐字抓取的实际文本（附来源 URL）；仅标注"摘要内证据"与"摘要外未核验"的内容。

---

## 0. 本轮完成与勘误

- **FF 1993 与 FF 1988 摘要"待补"已解决**：此前 Crossref/OpenAlex 误匹配 REITs/方法学论文；本轮经 Crossref+OpenAlex+Semantic Scholar+Unpaywall 四渠道标题/作者双重校验（Eugene F. Fama & Kenneth R. French），摘要取自 Wayback Machine 存档的 ScienceDirect 官方页面（见各节来源）。
- **发现文献表误配（第 5 处相似标题陷阱）**：`literature-map.md` 中 Piotroski 2000 链接的 `SSRN abstract_id=249510`，经 SSRN 存档页标题核实，实为 **Wayne R. Guay《Discussion of Value Investing: …》（JAR 同卷讨论稿）**，不是 Piotroski 论文本身。正确来源为 JAR 发布版 DOI **10.2307/2672906**（JSTOR）。已在本轮修正 literature-map.md。
- **数值口径差异待复核**：literature-conclusions.md 记"巴菲特夏普 0.79"；NBER w19681 官方摘要原文为 **0.76**。本轮以官方摘要为准，0.79 疑为论文正文/其他口径，建议复核。
- 其他 6 篇论文的摘要均与 literature-conclusions.md 既有记录一致（Novy-Marx / Buffett's Alpha / Gandhi-Lustig / Campbell-Shiller 已补原文）。

---

## 1. Novy-Marx 2013（#33 标尺）

- **元数据**：Robert Novy-Marx, "The Other Side of Value: The Gross Profitability Premium", Journal of Financial Economics, 2013, 108(1), 1–28（Crossref 核验）；DOI 10.1016/j.jfineco.2013.01.003
- **摘要要点（逐字，IDEAS/Elsevier 官方摘要）**：
  > Profitability, measured by gross profits-to-assets, has roughly the same power as book-to-market predicting the cross section of average returns. Profitable firms generate significantly higher returns than unprofitable firms, despite having significantly higher valuation ratios. Controlling for profitability also dramatically increases the performance of value strategies, especially among the largest, most liquid stocks. These results are difficult to reconcile with popular explanations of the value premium, as profitable firms are less prone to distress, have longer cash flow durations, and have lower levels of operating leverage. Controlling for gross profitability explains most earnings related anomalies and a wide range of seemingly unrelated profitable trading strategies.
- **方法要点（摘要内证据）**：盈利度量=毛利率/总资产（gross profits-to-assets）；横截面平均收益预测力与 BM 相当；对盈利做控制后价值策略表现大增（尤其大市值、高流动性股票）。
- **作者结论**：盈利（毛利率）是独立于价值的定价维度；可解释多数盈利类异象；与"困境/现金流久期/经营杠杆"等价值溢价流行解释难相容。
- **对论断判定**：**支持 #33**（"低PE+高ROE 跑赢市场"的质量半边——盈利公司显著更高收益）。注意：论文用"毛利率/资产"而非 ROE，度量口径有差异。
- **来源**：https://ideas.repec.org/a/eee/jfinec/v108y2013i1p1-28.html ；Crossref https://api.crossref.org/works/10.1016/j.jfineco.2013.01.003

## 2. Fama & French 1993（#33/#34 标尺；摘要"待补"→已补）

- **元数据**：Eugene F. Fama & Kenneth R. French, "Common Risk Factors in the Returns on Stocks and Bonds", Journal of Financial Economics, 1993, 33(1), 3–56（February 1993）；DOI 10.1016/0304-405X(93)90023-5（OpenAlex/S2/Unpaywall 三渠道标题+作者双重校验：E. Fama, K. French）
- **摘要要点（逐字，Wayback 存档的 ScienceDirect 官方页面 2011-07-09 快照）**：
  > This paper identifies five common risk factors in the returns on stocks and bonds. There are three stock-market factors: an overall market factor and factors related to firm size and book-to-market equity. There are two bond-market factors, related to maturity and default risks. Stock returns have shared variation due to the stock-market factors, and they are linked to bond returns through shared variation in the bond-market factors. Except for low-grade corporates, the bond-market factors capture the common variation in bond returns. Most important, the five factors seem to explain average returns on stocks and bonds.
- **方法要点（摘要内证据）**：识别 5 个共同风险因子——股票市场三因子（市场、规模 SMB、账面市值比 HML）+ 债券市场两因子（期限、违约）；检验五因子对股票/债券平均收益的解释力。
- **作者结论**：五因子"似乎能解释股票与债券的平均收益"（"seem to explain average returns"）——HML（价值因子）由此成为定价标尺。
- **对论断判定**：**支持 #33/#34 的价值因子半边**——BM（账面市值比）是系统定价因子，为"低估值跑赢"提供因子定价框架。注意：论文因子是 BM（PB 的反面），不是 PE；且不涉及银行股特异性。
- **来源**：https://web.archive.org/web/20110709224238/http://www.sciencedirect.com/science/article/pii/0304405X93900235 ；（注：Semantic Scholar 提供的 nes.ru 开放 PDF 镜像已 404，不可用）

## 3. Frazzini, Kabiller & Pedersen "Buffett's Alpha"（#33）

- **元数据**：Andrea Frazzini, David Kabiller, Lasse H. Pedersen, "Buffett's Alpha", NBER Working Paper 19681, 2013 年 11 月（2013 年 12 月修订）；DOI 10.3386/w19681
- **摘要要点（逐字，NBER 官网页面）**：
  > Berkshire Hathaway has realized a Sharpe ratio of 0.76, higher than any other stock or mutual fund with a history of more than 30 years, and Berkshire has a significant alpha to traditional risk factors. However, we find that the alpha becomes insignificant when controlling for exposures to Betting-Against-Beta and Quality-Minus-Junk factors. Further, we estimate that Buffett's leverage is about 1.6-to-1 on average. Buffett's returns appear to be neither luck nor magic, but, rather, reward for the use of leverage combined with a focus on cheap, safe, quality stocks. Decomposing Berkshires' portfolio into ownership in publicly traded stocks versus wholly-owned private companies, we find that the former performs the best, suggesting that Buffett's returns are more due to stock selection than to his effect on management. These results have broad implications for market efficiency and the implementability of academic factors.
- **方法要点（摘要内证据）**：巴菲特长期业绩归因于传统因子 + BAB（低波）+ QMJ（质量）因子暴露；杠杆约 1.6:1。
- **作者结论**：巴菲特超额收益=杠杆 × 便宜 + 安全 + 高质量股票的选择；非运气、非魔法；公开持股部分表现优于全资私有公司。
- **对论断判定**：**支持 #33**（价值+质量+低波组合逻辑——"低PE+高ROE"的学术翻版）；同时提示质量/低波因子是可实现的学术因子。
- **来源**：https://www.nber.org/papers/w19681

## 4. Piotroski 2000（#31/#39 标尺）

- **元数据**：Joseph D. Piotroski, "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers", Journal of Accounting Research, 2000, 38(Supplement), 1–41；DOI 10.2307/2672906（Crossref 核验：JAR, vol 38, page 1, 2000）
- **摘要要点（逐字，Wayback 存档的 JSTOR 官方页面 2020-06-16 快照）**：
  > This paper examines whether a simple accounting-based fundamental analysis strategy, when applied to a broad portfolio of high book-to-market firms, can shift the distribution of returns earned by an investor. I show that the mean return earned by a high book-to-market investor can be increased by at least 7.5% annually through the selection of financially strong high BM firms, while the entire distribution of realized returns is shifted to the right. In addition, an investment strategy that buys expected winners and shorts expected losers generates a 23% annual return between 1976 and 1996, and the strategy appears to be robust across time and to controls for alternative investment strategies. Within the portfolio of high BM firms, the benefits to financial statement analysis are concentrated in small and medium-sized firms, companies with low share turnover, and firms with no analyst following, yet this superior performance is not dependent on purchasing firms with low share prices. A positive relationship between the sign of the initial historical information and both future firm performance and subsequent quarterly earnings announcement reactions suggests that the market initially underreacts to the historical information. In particular, one-sixth of the annual return difference between ex ante strong and weak firms is earned over the four three-day periods surrounding these quarterly earnings announcements. Overall, the evidence suggests that the market does not fully incorporate historical financial information into prices in a timely manner.
- **方法要点（摘要内证据）**：F-Score 式基本面信号（历史财务报表信息）筛选高 BM 组合；样本期 1976–1996；多空（买预期赢家/卖预期输家）年化 23%。
- **作者结论**：在价值股（高 BM）内部，财务强弱信号可将平均收益提高 ≥7.5%/年、整体收益分布右移；市场对历史财务信息反应不及时（公告日前后集中兑现约 1/6 的强弱差）。
- **对论断判定**：**方向支持 #31/#39**——"安全边际（高 BM）+ 财务强"确实提高胜率/收益（分布右移≈胜率提升）；但摘要无"安全边际>30%"、"胜率>80%"、"2 倍低估"任何具体数值表述——**数值阈值无文献标尺，须用本库回测自证**。口径警示：论文收益集中于小/中盘、低换手、无分析师覆盖股，与 A 股大盘价值策略不完全可比。
- **来源**：https://web.archive.org/web/20200616104354/https://www.jstor.org/stable/2672906 ；Crossref https://api.crossref.org/works/10.2307/2672906
- **⚠️ 勘误**：literature-map.md 原链接 `SSRN 249510` 实为 Wayne R. Guay 的《Discussion of Value Investing: …》（JAR 讨论稿，SSRN 存档页标题已核实），已修正。

## 5. Fama & French 1988（#32 标尺；摘要"待补"→已补）

- **元数据**：Eugene F. Fama & Kenneth R. French, "Dividend Yields and Expected Stock Returns", Journal of Financial Economics, 1988, 22(1), 3–25；DOI 10.1016/0304-405X(88)90020-7（OpenAlex/S2/Unpaywall 标题+作者双重校验）
- **摘要要点（逐字，Wayback 存档的 ScienceDirect 官方页面 2019-01-22 快照）**：
  > The power of dividend yields to forecast stock returns, measured by regression R2, increases with the return horizon. We offer a two-part explanation. (1) High autocorrelation causes the variance of expected returns to grow faster than the return horizon. (2) The growth of the variance of unexpected returns with the return horizon is attenuated by a discount-rate effect - shocks to expected returns generate opposite shocks to current prices. We estimate that, on average, the future price increases implied by higher expected returns are just offset by the decline in the current price. Thus, time-varying expected returns generate 'temporary' components of prices.
- **方法要点（摘要内证据）**：股息率对股票收益的预测回归，R² 随收益期限增加而上升；两段式解释（预期收益自相关 + 贴现率效应）；隐含"价格临时成分"（均值回复）。
- **作者结论**：股息率是长期预期收益的有效预测变量；时变预期收益产生价格的临时（可逆）成分。
- **对论断判定**：**部分支持 #32**（"股息率>无风险利率跑赢"）——论文支持"股息率=长期预期收益指标"（这正是 #32 的学术依据）；但摘要无"股息率 vs 无风险利率"比较口径，论文框架是回归 R² 而非阈值比较，**具体比较规则需本库自证**。
- **来源**：https://web.archive.org/web/20190122014349/https://www.sciencedirect.com/science/article/pii/0304405X88900207 ；IDEAS 记录 https://ideas.repec.org/a/eee/jfinec/v22y1988i1p3-25.html（该页无摘要）

## 6. Campbell & Shiller（#29/#30 标尺）

- **元数据**：John Y. Campbell & Robert J. Shiller, "Valuation Ratios and the Long-Run Stock Market Outlook: An Update", NBER Working Paper 8221, 2001 年 4 月；DOI 10.3386/w8221（其 1998 年 JPM 版为文献表原有引用）
- **摘要要点（逐字，NBER 官网页面）**：
  > The use of price earnings ratios and dividend-price ratios as forecasting variables for the stock market is examined using aggregate annual US data 1871 to 2000 and aggregate quarterly data for twelve countries since 1970. Various simple efficient-markets models of financial markets imply that these ratios should be useful in forecasting future dividend growth, future earnings growth, or future productivity growth. We conclude that, overall, the ratios do poorly in forecasting any of these. Rather, the ratios appear to be useful primarily in forecasting future stock price changes, contrary to the simple efficient-markets models. This paper is an update of our earlier paper (1998), to take account of the remarkable behavior of the stock market in the closing years of the twentieth century.
- **方法要点（摘要内证据）**：美国年度数据 1871–2000 + 12 国季度数据（1970 起）；检验 PE 与股息率对股息增长/盈利增长/生产率增长 vs 未来价格变化的预测力。
- **作者结论**：估值比率预测基本面增长差，但**主要预测未来股票价格变化**（高估值→低长期回报的学术表述），与简单有效市场模型相反。
- **对论断判定**：**方向支持 #29/#30**（PE 高分位→长期回报走低，即高位减仓/清仓逻辑的标尺）；论文是长期、指数层面的预测关系，无"80%/95% 分位"、"FCF>50x"阈值表述——**阈值无文献标尺**。
- **来源**：https://www.nber.org/papers/w8221

## 7. Gandhi & Lustig 2015（#34 银行股）

- **元数据**：Priyank Gandhi & Hanno Lustig, "Size Anomalies in U.S. Bank Stock Returns", The Journal of Finance, 2015, 70(2), 733–768（April 2015）；DOI 10.1111/jofi.12235；NBER 工作论文版 w16553（2010-11，修订 2014-11）标题为"Size Anomalies in U.S. Bank Stock Returns: A Fiscal Explanation"
- **摘要要点（逐字，IDEAS/JF 官方摘要；与 NBER 摘要一致）**：
  > The largest commercial bank stocks, ranked by total size of the balance sheet, have significantly lower risk-adjusted returns than small- and medium-sized bank stocks, even though large banks are significantly more levered. We uncover a size factor in the component of bank returns that is orthogonal to the standard risk factors, including small minus big, which has the right covariance with bank returns to explain the average risk-adjusted returns. This factor measures size-dependent exposure to bank-specific tail risk. These findings are consistent with government guarantees that protect shareholders of large banks, but not small banks, in disaster states.
- **方法要点（摘要内证据）**：按资产负债表总规模排序的银行股票组合；风险调整收益对比 + 正交规模因子；与银行特异尾部风险暴露挂钩。
- **作者结论**：最大银行股风险调整收益显著更低（尽管杠杆更高）；存在银行特异性规模因子；与"大行股东获政府隐性担保"一致。
- **对论断判定**：**部分支持 #34 + 口径警示**——论文确立"银行股内部存在系统性异象"，为 #34 的学术支撑；但**异象方向是"规模"而非"PB<1"**：低风险调整收益的是"最大银行"，小/中型银行反而更高。若 #34 买的是低 PB 大行，论文反而提示其风险调整收益低（需注意是高收益绝对口径 vs 风险调整口径）。FF 1993 HML 提供 BM 维度框架，同样不针对银行股。
- **来源**：https://ideas.repec.org/a/bla/jfinan/v70y2015i2p733-768.html ；https://www.nber.org/papers/w16553

## 8. Carhart 1997（#42 标尺）

- **元数据**：Mark M. Carhart, "On Persistence in Mutual Fund Performance", The Journal of Finance, 1997, 52(1), 57–82；DOI 10.1111/j.1540-6261.1997.tb03808.x
- **摘要要点（逐字，IDEAS/Blackwell 官方摘要）**：
  > Using a sample free of survivor bias, the author demonstrates that common factors in stock returns and investment expenses almost completely explain persistence in equity mutual funds' mean and risk-adjusted returns. Darryll Hendricks, Jayendu Patel, and Richard Zeckhauser's (1993) 'hot hands' result is mostly driven by the one-year momentum effect of Narasimham Jegadeesh and Sheridan Titman (1993), but individual funds do not earn higher returns from following the momentum strategy in stocks. The only significant persistence not explained is concentrated in strong underperformance by the worst-return mutual funds. The results do not support the existence of skilled or informed mutual fund portfolio managers.
- **方法要点（摘要内证据）**：无幸存者偏差样本；共同因子 + 费用归因基金业绩持续性；"热手"效应大部分=一年动量。
- **作者结论**：业绩持续性几乎完全被共同因子与费用解释；**唯一未被解释的显著持续性是"最差基金持续跑输"**；不支持存在有技能的基金经理。
- **对论断判定**：**方向支持 #42**（"组合 DNA 3 年跑输>20% 应质疑"）——论文证明业绩难持续、追热手无效、且"差者恒差"是唯一显著持续模式，与"长期跑输即警示"方向一致。口径警示：对象是共同基金（净值/费用口径）而非个股组合；"3 年""20%"无直接文献表述。
- **来源**：https://ideas.repec.org/a/bla/jfinan/v52y1997i1p57-82.html

---

## 补充论据论文（4 篇，Crossref/OpenAlex 检索+校验）

### S1. Asness, Moskowitz & Pedersen 2013 — Value and Momentum Everywhere（#33/#34 价值溢价跨市场）
- **元数据**：Clifford S. Asness, Tobias J. Moskowitz, Lasse Heje Pedersen, "Value and Momentum Everywhere", The Journal of Finance, 2013, 68(3), 929–985；DOI 10.1111/jofi.12021（Crossref 核验）
- **摘要要点（逐字，OpenAlex）**：8 个市场/资产类别中价值与动量溢价一致存在，收益呈强共同因子结构；价值与动量负相关；可用三因子模型刻画共同全球风险；全球资金流动性风险是部分来源。
- **对论断判定**：**支持 #33/#34 的价值因子普适性**——价值溢价非美国特例（跨 8 市场一致）。
- **来源**：https://doi.org/10.1111/jofi.12021 ；摘要 https://api.openalex.org/works/doi:10.1111/jofi.12021

### S2. Liu, Stambaugh & Yuan 2019 — Size and Value in China（A 股直接相关）
- **元数据**：Jianan Liu, Robert F. Stambaugh, Yu Yuan, "Size and value in China", Journal of Financial Economics, 2019, 134(1), 48–69；DOI 10.1016/j.jfineco.2019.03.008（Crossref 核验）
- **摘要要点（逐字，IDEAS/Elsevier）**：中国规模因子剔除最小 30% 公司（壳价值）；价值因子用盈利-价格比（EP）取代 BM 后能捕捉全部中国价值效应；CH-3 模型显著优于照搬 FF 1993 的模型（后者在 EP 因子上留下 17% 年化 alpha）；CH-3 解释多数中国异象（含盈利与波动异象）。
- **对论断判定**：**支持 #33 的 A 股落地口径**——A 股价值因子首选 EP（低 PE）而非 BM，且盈利异象可被 CH-3 解释——与"低PE+高ROE"论断直接对口；同时警示 A 股壳价值/最小市值股污染。
- **来源**：https://ideas.repec.org/a/eee/jfinec/v134y2019i1p48-69.html

### S3. Asness, Frazzini & Pedersen 2019 — Quality Minus Junk（#33 质量因子 24 国证据）
- **元数据**：Clifford S. Asness, Andrea Frazzini, Lasse H. Pedersen, "Quality minus junk", Review of Accounting Studies, 2018 在线首发；DOI 10.1007/s11142-018-9470-2（Crossref 核验；工作论文版 SSRN 10.2139/ssrn.2312432）
- **摘要要点（逐字，OpenAlex）**：质量=盈利性、增长、安全；高质量股价格更高但不显著多；QMJ 因子（多高质量/空低质量）在美国及 24 国获得显著风险调整收益；质量价格在互联网泡沫期触底，且低质量价格预示 QMJ 未来高收益；分析师预测存在系统性质量相关错误。
- **对论断判定**：**强支持 #33**——"高 ROE（盈利性）跑赢"的质量半边获 24 国证据，且与"便宜+安全+质量"（Buffett's Alpha）闭环。
- **来源**：https://doi.org/10.1007/s11142-018-9470-2 ；摘要 https://api.openalex.org/works/doi:10.1007/s11142-018-9470-2

### S4. Hirshleifer, Hou, Teoh & Zhang 2004 — Do Investors Overvalue Firms with Bloated Balance Sheets?（资产负债表质量/安全边际）
- **元数据**：David Hirshleifer, Kewei Hou, Siew Hong Teoh, Yinglei Zhang, "Do investors overvalue firms with bloated balance sheets?", Journal of Accounting and Economics, 2004, 38, 297–331；DOI 10.1016/j.jacceco.2004.10.002（Crossref 核验）
- **摘要要点（逐字，作者工作论文版 2004-09；发布版同源）**：累计经营利润超过累计自由现金流时后续盈利增长弱；1964–2002 样本期内，净营运资产/总资产是长期股票收益的强负向预测变量；对大量控制变量与检验方法稳健。
- **对论断判定**：**支持 #31 的"质量防御"半边**——"资产负债表干净（净营运资产低）"是安全边际之外的质量筛查维度，可作 Piotroski F-Score 的互补信号。
- **来源**：DOI https://doi.org/10.1016/j.jacceco.2004.10.002 ；工作论文 PDF https://econwpa.ub.uni-muenchen.de/econ-wp/fin/papers/0412/0412001.pdf

---

## 逐条论断判定汇总

| 论断 | 判定 | 一句话依据 | 待补/口径警示 |
|:-----|:-----|:-----------|:--------------|
| #29 PE>80% 分位减仓 | 方向支持 | Campbell-Shiller：估值比率主要预测未来价格变化（高 PE→低长期收益） | "80% 分位"阈值无文献表述 |
| #30 PE>95% 或 FCF>50x 清仓 | 方向支持 | 同上 | "95%/50x"阈值无文献表述 |
| #31 安全边际>30% 胜率>80% | 方向支持 | Piotroski：高 BM+财务强→平均收益 +≥7.5%/年、分布右移；FF 1993 价值溢价 | "30%""80%"数值无直接标尺；样本偏中小盘 |
| #32 股息率>无风险利率跑赢 | 部分支持 | FF 1988：股息率预测力随期限增强（R²↑），长期预期收益指标 | 无"股息率 vs 无风险利率"比较口径 |
| #33 低PE+高ROE 跑赢市场 | **强支持** | FF 1993（HML）+ Novy-Marx（盈利预测力≈BM）+ Buffett's Alpha（价值+质量+低波+杠杆）+ QMJ（24 国）+ VME（8 市场） | Novy-Marx 用毛利率/资产而非 ROE；A 股用 EP 而非 BM（LSY 2019） |
| #34 PB<1+股息>3% 银行股 | 部分支持+口径警示 | Gandhi-Lustig：银行股异象存在但方向是"规模"（大行风险调整收益更低）；FF 1993 HML 为 BM 框架 | 论文不支持"低 PB 大行跑赢"；注意绝对收益 vs 风险调整口径 |
| #39 换股必须 2 倍低估 | 方向支持 | Piotroski 多空 23%/年（1976–1996）+ FF 1993 价值溢价 | "2 倍低估"阈值无文献标尺 |
| #42 组合 DNA 3 年跑输>20% | 方向支持 | Carhart：业绩持续性≈共同因子+费用；唯一显著持续=最差基金持续差 | 对象是共同基金非个股组合；"3 年/20%"无直接标尺 |

## 附：本轮渠道记录
- 摘要成功渠道：IDEAS-RePEc（Novy-Marx/Carhart/Gandhi-Lustig/LSY2019）、NBER 官网（Buffett's Alpha/Campbell-Shiller/Gandhi-Lustig）、Wayback Machine（ScienceDirect 官方摘要页：FF 1993/FF 1988；JSTOR：Piotroski）、OpenAlex 摘要索引（VME/QMJ）、作者工作论文 PDF（Hirshleifer 2004）。
- 失败渠道记录：ScienceDirect 实时页（验证码 403）、SSRN 实时页与 API（Cloudflare 403）、JSTOR 实时页（JS 不可用）、Semantic Scholar 摘要字段（全部 null，仅元数据可用）、Unpaywall（三篇均 closed access）。
