# 论文研究笔记：宏观/政策/周期（论断 #48-52）

> 抓取日期：2026-08-16 | 渠道：Crossref / OpenAlex / Semantic Scholar / IDEAS-RePEc / EconBiz / AEA 官网 / NBER / Econometric Society 官网 / IMF eLibrary / Bank of Canada / ScienceDirect（反爬失败）/ Search King（搜狗）
> 防幻觉纪律：以下每段内容均来自实际抓取；官方摘要不可得的论文如实标注"待补"并附尝试渠道，不凭记忆补写。

---

## 1. Fama & French 1989（#48 宏观状态 标尺）

- **元数据**：*Business Conditions and Expected Returns on Stocks and Bonds*；Eugene F. Fama, Kenneth R. French；Journal of Financial Economics, 1989, 25(1), 23–49（1989-11）；DOI 10.1016/0304-405x(89)90095-0（Crossref 与 OpenAlex 元数据一致，标题/作者/卷期页全匹配）
- **摘要要点**：**待补 — 官方摘要经多公开渠道确认不可得**。已尝试：Crossref（无 abstract 字段）、OpenAlex（无 abstract_inverted_index）、Semantic Scholar（DOI 记录存在但摘要被出版商"elided"；搜索接口整轮 429 限流）、IDEAS/RePEc（"No abstract is available"）、EconPapers（无）、EconBiz（记录 10005362564 存在、无摘要）、ScienceDirect（403 + 验证码，直连与 jina.ai 代理均拦）、colab.ws（DDoS-Guard 拦截）、BASE（anti-bot 挑战页）、Baidu Xueshu（验证码）、X-MOL（URL 失效）、Sogou 链接页（验证码/无法提取正文）、Unpaywall（is_oa=false）、OpenAlex locations（closed，无任何仓库全文副本）、Google Books API（无结果）、Bing/DDG（反爬/无内容）、CiteSeerX（301）。
- **二手转述（非官方，仅方向参考，不作标尺依据）**：搜狗检索结果 [1]（微信公众号文章）转述其核心思想为"预期收益率具有商业周期属性。经济状态不仅影响企业现金流，也影响投资者要求的风险补偿。因此，当衰退风险上升时，当期股价可能下跌"（抓取于 2026-08-16，原链接为 mp.weixin.qq.com 临时签名 URL）。
- **方法要点**：待补（需原文；预测回归框架——股息率/利差变量对股票与债券预期收益的预测回归，属文献共识性描述，未在本次抓取中核实）。
- **作者结论**：待补。
- **对论断判定**：**方向性支持（弱证据）**——论文主题与二手转述均指向"宏观商业条件驱动预期收益变化"（#48 方向）；但因官方摘要/全文未取得，**正式判定保持待补**，待原文核实后再写入结论表。
- **来源**：Crossref https://api.crossref.org/works/10.1016/0304-405x(89)90095-0 | OpenAlex https://api.openalex.org/works/doi:10.1016/0304-405x(89)90095-0 | Unpaywall https://api.unpaywall.org/v2/10.1016/0304-405X(89)90095-0?email=x

---

## 2. Gilchrist & Zakrajšek 2012（#49 信用利差 标尺）

- **元数据**：*Credit Spreads and Business Cycle Fluctuations*；Simon Gilchrist, Egon Zakrajšek；American Economic Review, 2012, 102(4), 1692–1720（2012-06）；DOI 10.1257/aer.102.4.1692；JEL 分类 E32, E44, G12, G32；**官方复现包**：ICPSR DOI 10.3886/E112536V1（AEA 官网确认）
- **摘要要点**（Crossref 全文 + AEA 官网一致）：用微观层面数据构造信用利差指数，对未来经济活动具有相当预测力（"considerable predictive power"）；将信用利差分解为"预期违约"成分与残差成分——超额债券溢价（excess bond premium, EBP）；与当前经济状态正交的 EBP 冲击导致经济活动与资产价格下行；EBP 上升反映金融部门风险承担能力下降，诱发信贷供给收缩与宏观状况恶化。
- **方法要点**：摘要级信息——微观数据（债券层面）构造聚合利差指数；利差分解（预期违约 vs EBP）；冲击识别要求与当前经济状态正交（正交化/结构识别）；预测对象为未来经济活动。样本期与具体检验细节需原文（AER 免费 PDF 被反爬拦截，待补）。
- **显著性**：摘要原文 "considerable predictive power for future economic activity"。
- **对论断判定**：**支持 #49**——信用利差（尤其剔除预期违约后的 EBP 残差）是经济活动的领先指标，且传导渠道（金融部门风险承担→信贷供给）给出了机制解释；#49 的"信用利差领先"命题有直接权威标尺。
- **来源**：Crossref https://api.crossref.org/works/10.1257/aer.102.4.1692 | AEA https://www.aeaweb.org/articles?id=10.1257/aer.102.4.1692

---

## 3. Mandelker & Tandon 1985（#50 CPI/通胀 标尺）

- **元数据**：*Common Stock Returns, Real Activity, Money, and Inflation: Some International Evidence*；Gershon Mandelker, Kishore Tandon；Journal of International Money and Finance, 1985, **4(2), 267–286**（1985-06）；DOI 10.1016/0261-5606(85)90048-8
- **⚠️ 元数据修正**：现 literature-map.md 记该文为 4(3), 337–353，**与 Crossref、OpenAlex、IDEAS/RePEc、EconBiz（两条记录 10002431778 / 10005402700）四渠道一致的 4(2), 267–286 不符**，建议将文献表更正为 4(2), 267–286。
- **摘要要点**：**待补 — 老文献公开 API 无官方摘要**。已尝试：Crossref/OpenAlex（无 abstract）、Semantic Scholar（摘要被出版商遮蔽 elided）、IDEAS/RePEc、EconPapers、EconBiz（两条记录均无摘要）、ScienceDirect（403/验证码，直连与 jina 代理）、Sogou（无相关结果）、Unpaywall（closed）、OpenAlex locations（closed，无仓库副本）。
- **方法要点**：待补。
- **作者结论**：待补。
- **对论断判定**：**待补**（判定须待原文核实；本组 #50 的实证依据改由补充论文 Zhang 2021 IMF WP 提供，见下）。
- **来源**：Crossref https://api.crossref.org/works/10.1016/0261-5606(85)90048-8 | IDEAS https://ideas.repec.org/a/eee/jimfin/v4y1985i2p267-286.html | EconBiz https://www.econbiz.de/10002431778

---

## 4. Hamilton 1989（#51 NBER 衰退 标尺）

- **元数据**：*A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle*；James D. Hamilton；Econometrica, 1989, 57(2), 357–384（1989-03）；DOI 10.2307/1912559
- **摘要要点**（OpenAlex 摘要，与 Econometric Society 官网页内容一致）：为非平稳序列中"偶尔发生的离散增长率切换"建模；给出推断未观测状态的算法，副产品是可用最大似然估计参数；实证表明"正增长→负增长"的周期性切换是美国商业周期的反复特征，**可作为定义与度量经济衰退的客观标准**；参数估计显示典型衰退伴随 GNP 水平约 **3% 的永久性下降**。
- **方法要点**：马尔可夫切换模型（自回归参数由离散状态马尔可夫过程驱动）；最大似然估计；对未观测状态做概率性推断（滤波/平滑）；实证样本为战后美国实际 GNP。注：该文是状态识别/度量工具，本身不做前瞻预测。
- **作者结论**：见摘要（3% 永久性 GNP 损失；衰退可客观定义）。
- **对论断判定**：**支持 #51 的方法基础**——NBER 式衰退可用马尔可夫切换等统计模型客观识别与度量（这是 #51"衰退状态识别"的标准工具；注意其定位是识别/度量而非预测）。
- **来源**：OpenAlex https://api.openalex.org/works/doi:10.2307/1912559 | Econometric Society https://www.econometricsociety.org/publications/econometrica/1989/03/01/new-approach-economic-analysis-nonstationary-time-series-and

---

## 5. Santa-Clara & Valkanov 2003（#52 政策周期 标尺）

- **元数据**：*The Presidential Puzzle: Political Cycles and the Stock Market*；Pedro Santa-Clara, Rossen Valkanov；The Journal of Finance, 2003, 58(5), 1841–1872（2003-09）；DOI 10.1111/1540-6261.00590
- **摘要要点**（Crossref 全文，IDEAS 页一致）：民主党任期内股市超额收益显著更高——市值加权 **9%**、等权 **16%**；差异来自更高的实际股票收益与更低的实际利率；统计显著且在子样本中稳健；不能被与预期收益相关的商业周期变量解释；不集中于选举日附近；两党任期市场风险无差异，无法用风险溢价辩护 → 政治周期的收益差异因此是一个"谜"。
- **方法要点**：摘要级信息——总统党派虚拟变量对月度超额收益的回归；等权/市值加权两种组合口径；子样本稳健性；控制商业周期变量；选举窗口检验。样本期细节摘要未给出（待补：全文/SSRN 版被验证码拦截）。
- **对论断判定**：**支持 #52**（美国政治周期效应显著存在、量级可观），但注意：(a) 是事后统计规律、机制未明（论文自认 puzzle）；(b) 为美国样本，外推到他国需谨慎。
- **来源**：Crossref https://api.crossref.org/works/10.1111/1540-6261.00590 | IDEAS https://ideas.repec.org/a/bla/jfinan/v58y2003i5p1841-1872.html

---

## 6. 补充论据论文（2020 后为主，7 篇）

### #48 宏观状态补充
| 论文 | 出处 | 摘要要点（抓取原文） | 对论断判定 |
|:-----|:-----|:---------------------|:----------|
| Moench & Stein, *Equity Premium Predictability over the Business Cycle*（2021 SSRN 3920153 → **2025-09 正式发表于 JFQA**）DOI 10.1017/s0022109025102093 | Crossref 摘要 | 权益收益在衰退 onset 呈**V 型**：商业周期顶点前急跌入负、衰退展开后强恢复；衰退前期限利差走平，基于期限利差的 Probit 衰退概率显著提升权益溢价的样本内与样本外预测、优于多个基准；修正 1982 年期限利差均值结构断点后预测力更强 | **支持 #48**（宏观状态/衰退概率→预期收益，现代实证），兼补 #51（期限利差→衰退概率） |
| Lin, Tao, Wang, Wu, *Credit Spreads, Business Conditions, and Expected Corporate Bond Returns*（2020）JRFM 13(2):20，DOI 10.3390/jrfm13020020 | Crossref 摘要 | 聚合信用利差指数对公司债收益短/长周期均有显著预测力，经济与统计显著、对多种控制稳健；比传统 default/term spread 预测力更强；投机级成分预测力更强；预测力来源=对未来经济状况的预测能力 | **支持 #48/#49**（利差经"商业条件"渠道作用于预期收益，与 FF 1989/GZ 2012 一脉相承） |

### #49 信用利差补充
| 论文 | 出处 | 摘要要点（抓取原文） | 对论断判定 |
|:-----|:-----|:---------------------|:----------|
| Leboeuf & Hyun, *Is the Excess Bond Premium a Leading Indicator of Canadian Economic Activity?*（Bank of Canada Staff Analytical Note 2018-4，2021 收录）DOI 10.34989/san-2018-4 | OpenAlex 摘要 | 加拿大公司债利差领先未来一年实际 GDP 变化；**EBP 贡献了该预测力的大部分**；EBP 意外上升 10bp → 三年内 GDP 累计 -0.4%、CPI -0.1% | **支持 #49**（GZ 的 EBP 框架在加拿大复现，且给出量化幅度） |

### #51 衰退识别/预测补充
| 论文 | 出处 | 摘要要点（抓取原文） | 对论断判定 |
|:-----|:-----|:---------------------|:----------|
| Ahmed & Chinn, *Do Foreign Yield Curves Predict U.S. Recessions and GDP Growth?*（NBER WP 30737，2022-12 初版 / 2023-08 修订） | NBER 页面 | 非美 G7 国家的期限利差**对"未来一年内美国衰退"的预测力强于美国自身期限利差**；美/外利差在不同时域与不同经济活动成分上起作用；外国利差收窄与美出口、FDI 流入持续下滑相关 | **支持 #51 方向**（利差可预测衰退），但提示只看美国利差不够（多国信息更佳） |
| Blanchflower & Bryson, *The Sahm Rule and Predicting the Great Recession Across OECD Countries*（NBER WP 29300，2021；后发表于 National Institute Economic Review 2022, DOI 10.1017/nie.2021.47） | NBER 页面 | 以连续两季负增长为起点比较 OECD 各国大衰退起点；Sahm 规则对多数国家信号**晚于** GDP 法；GDP 与劳动市场数据大幅修订使转折点不即时可见；作者提出基于"失业恐惧"调查的规则（较 12 个月低点上升 10 点）更及时且不受修订影响；英美的定性调查数据在 2006-2007/2007 末-2008 初即预警 | **支持 #51 主题**（衰退起点识别存在多规则竞争、官方定调滞后——识别口径需谨慎） |
| Carstensen, Heinrich, Reif, Wolters, *Predicting ordinary and severe recessions with a three-state Markov-switching dynamic factor model*（2020）IJF 36(3), 829–850，DOI 10.1016/j.ijforecast.2019.09.005 | IDEAS 摘要 | 用 6 个领先指标对德国商业周期建**三状态**马尔可夫切换动态因子模型；三态=扩张/普通衰退/严重衰退；第三态能区分大衰退等严重下行，改进实时衰退检测与 GDP nowcasting | **支持 #51**（Hamilton 1989 框架的现代扩展：加"严重衰退"状态提升识别能力） |
| Vrontos, Galakis, Vrontos, *Modeling and predicting U.S. recessions using machine learning techniques*（2021）IJF 37(2), 647–671，DOI 10.1016/j.ijforecast.2020.08.005 | IDEAS 摘要 | 惩罚 Logit、k-近邻、贝叶斯广义线性模型预测美国衰退**优于标准 Logit/Probit**；"results strongly support the application of machine learning over more standard econometric techniques" | **支持 #51 方向**（衰退可预测性），方法上 ML 优于传统分类模型 |

### #52 政策周期补充
| 论文 | 出处 | 摘要要点（抓取原文） | 对论断判定 |
|:-----|:-----|:---------------------|:----------|
| Cieslak, Morse, Vissing-Jørgensen, *Stock Returns over the FOMC Cycle*（2019）JF 74(5), 2201–2248，DOI 10.1111/jofi.12818 | OpenAlex 摘要 | 1994 年以来权益溢价**全部**产生于 FOMC 周期的第 0、2、4、6 周（偶数周）；通过会间目标利率变动、联邦基金期货与理事会内部会议将之与美联储建立因果联系；美联储靠意外宽松压低权益溢价；证据指向联储官员与媒体/金融界的系统性非正式沟通为传导渠道 | **支持 #52 广义版**（"政策周期影响股市"不限于党派周期——央行政策节奏周期同样显著），是对 SCV 党派效应的补充视角 |
| Han, Lu, Xu, Zhou, *From Red to Blue: The Long-Run Inversion of Political Cycles and Stock Market Returns Over 153 Years*（SSRN 5749464，2025） | OpenAlex 元数据（Yufeng Han, Yueliang Lu, Weike Xu, Guofu Zhou, 2025）；**摘要待补**（SSRN 页面验证码拦截、OpenAlex 无摘要） | 标题表明：在 153 年长样本中检验政治周期与股市收益关系，发现方向发生长期反转（由"红"转"蓝"） | **直接检验 SCV 命题的现代长样本更新**（若其结论成立，则 #52 需限定时期）；判定待摘要取得后核实 |

### #50 CPI/通胀补充
| 论文 | 出处 | 摘要要点（抓取原文） | 对论断判定 |
|:-----|:-----|:---------------------|:----------|
| Zhang, *Stock Returns and Inflation Redux: An Explanation from Monetary Policy in Advanced and Emerging Markets*（IMF WP/21/219，2021-08）DOI 10.5089/9781513586755.001 | OpenAlex 摘要 | 货币理论预测：货币政策逆周期时实际股票收益与通胀**负相关**；用 **71 个经济体**扩展数据检验：货币当局越逆周期，股票-通胀关系越负；汇率锚国家市场不响应；通胀目标制国家响应更强；央行能把通胀控制在目标带内时市场才对通胀敏感；**零利率下限（ZLB）下出现结构断点、实际股票收益不再响应通胀** | **支持 #50 的方向细化**（通胀与股市存在显著关系、以负相关为主），但关系**强烈依赖货币政策体制**——#50 不能写成简单线性规律 |
| Chiang & Chen, *Inflation risk and stock returns: Evidence from US aggregate and sectoral markets*（2023）NAJEF 68, 101986，DOI 10.1016/j.najef.2023.101986 | Crossref/OpenAlex 元数据（Thomas C. Chiang, Pei-Ying Chen, 2023-09）；**摘要待补**（Elsevier 反爬、S2 限流、IDEAS 未收录） | 待补 | 待补（美国总量+分行业通胀风险定价，方向候选） |

---

## 7. 汇总：每篇对论断的一行式判定

| 论文 | 判定 |
|:-----|:-----|
| Fama & French 1989（#48） | 方向性支持（二手转述+主题）；官方摘要待补，正式判定待原文核实 |
| Gilchrist & Zakrajšek 2012（#49） | 支持：信用利差（尤其 EBP 残差）是经济活动领先指标，机制=金融部门风险承担→信贷供给 |
| Mandelker & Tandon 1985（#50） | 待补（老文献无公开摘要）；元数据修正为 JIMF 4(2):267-286 |
| Hamilton 1989（#51） | 支持（方法基础）：马尔可夫切换可客观识别/度量衰退（识别而非预测） |
| Santa-Clara & Valkanov 2003（#52） | 支持（美国样本、事后规律、机制未明——论文自认"谜"） |
| Moench & Stein 2025 JFQA（#48 补） | 支持：衰退概率（期限利差 Probit）显著提升权益溢价样本内/外预测 |
| Lin et al. 2020 JRFM（#48/#49 补） | 支持：利差指数预测债券收益的源头=预测未来经济状况 |
| Leboeuf & Hyun 2021 BoC（#49 补） | 支持：EBP 领先加拿大 GDP，10bp 冲击→三年 GDP -0.4% |
| Ahmed & Chinn 2022 NBER（#51 补） | 支持：外国期限利差预测美衰退强于美国利差（多国信息） |
| Blanchflower & Bryson 2021 NBER（#51 补） | 支持主题：衰退起点识别口径竞争（Sahm vs GDP 法），官方定调滞后 |
| Carstensen et al. 2020 IJF（#51 补） | 支持：Hamilton 三状态扩展区分严重衰退、改进实时识别 |
| Vrontos et al. 2021 IJF（#51 补） | 支持方向：ML 预测美国衰退优于标准 Logit/Probit |
| Cieslak et al. 2019 JF（#52 补） | 支持广义版：FOMC 周期（政策节奏周期）吞噬全部权益溢价 |
| Han et al. 2025 SSRN（#52 补） | 候选：153 年长样本政治周期反转检验；摘要待补 |
| Zhang 2021 IMF（#50 补） | 支持方向细化：股票-通胀负相关为主、强度取决于货币政策体制与 ZLB |
| Chiang & Chen 2023 NAJEF（#50 补） | 候选：美国总量+行业通胀风险定价；摘要待补 |

---

## 8. 待补清单与维护提示

1. **FF 1989 官方摘要**：多渠道穷尽不可得（渠道见第 1 节）。建议后续途径：机构订阅库（EBSCO/ProQuest 全文）、Sci-Hub 以外的合法图书馆通道、或引用该论文的综述中转录的摘要。在取得前，文献结论表（literature-conclusions.md）的 #48 条目应保持"待补"。
2. **Mandelker & Tandon 1985 摘要**：同上方，且文献表卷期页需修正（4(3), 337–353 → **4(2), 267–286**，四渠道交叉确认）。
3. **Semantic Scholar API**：本日整轮 429 限流，待限流恢复后可补试（DOI 记录均存在，但两篇 Elsevier 老文的摘要显示为"被出版商 elided"，成功率低）。
4. **补充论文摘要待补 2 篇**：Han et al. 2025（SSRN 验证码）、Chiang & Chen 2023（Elsevier 反爬）——均已有经过校验的元数据，可先登记。
5. **SCV 2003 样本期**、**GZ 2012 样本/检验细节**：摘要级信息完整；全文细节（PDF 被反爬拦截）待补。
