# PROMPT 草案 v2 — 创始人过目文档（零 key Prompt 计划）

> 2026-09-07。9 条正式 Prompt 模板已按 [PROMPT-PLAN.md](PROMPT-PLAN.md) 四条硬约束重写完毕（文件头统一 `<!-- DRAFT v2：待创始人过目后启用 -->`），**未上线**，待创始人点头。
> 对应文件：`fengweb/src/prompt-templates/` 下 9 个（m.md / 03-discipline.md / 04-quantitative.md 三个纯工具层模板未动）。

## 怎么审（两步，10 分钟）

1. **审文字**：通读下面 9 节，重点看"注入了哪些原则"是否符合你的原话口径；任何一条不对，指出来我改。
2. **实测（可选但建议）**：把模板全文贴给 DeepSeek 网页版试三条最关键的——
   - `05-qualitative`（最重的一条）：在 `{{EVIDENCE}}` 处随便粘一段公司简介，看它是否老实写"资料未提供"、护城河是否穿透到机制而非"品牌好"；
   - `06-collision`：粘一份假的 L1/L2b/L2a 结果，看它是否按规则树给 BUY/WAIT/PASS 且 conflicts 带严重度；
   - `07-report`：粘一份各层 JSON，看白话报告是否零术语、反方意见是否没被写软。
   贴回验证等 GUI 七卡做完后再验（/prompt/submit 真门 = fengstate complete，本次没动）。

## 状态层 5 条（贴回过 fengstate complete 真门）

### 1. 01-capability — L0 能力圈（2668 字）

- 用途：三问判定 懂/半懂/不懂，不懂 → 全层 PASS（宁可漏网不可误杀）。
- 注入原则：坐标原则（DK，说不出对标坐标 = 圈外强信号）；信条 3 不信噪音（名气/热度不等于看得懂）；信条 6 不模棱两可（三选一，判定口径写死）；信条 7 执行>判断（半懂必须带不懂点清单去补）。
- schema 要点：`three_questions`(恰 3 项)+`dk_coordinate`+`judgement` **已对齐 fengstate key_fields**；另加 `understand_verdict`(understand/partial/not_understand)、`unclear_points`(不懂点清单，懂也要写"最可能看错的地方")、`noise_warning`。

### 2. 05-qualitative — L2a 定性（3998 字，最重的一条）

- 用途：护城河五问逐答 + 结构性壁垒论证 + 息价三层次 + 六灯汇总。
- 注入原则：五问 = 定价权（巴菲特通胀测试）/可复制性（对手砸钱能否砸出来）/成本与结构/生命周期（**任何 form 都有生命周期**：品牌会老化、渠道可复制、技术被绕开、牌照会到期）/真实需求（信条 5）；**反敷衍核心：禁止"品牌好/历史悠久/行业龙头"式空话，必须写机制+对手复制代价+证据三件事**；息价原则（安全边际三层次，verdict 不许粉饰）；信条 3 不信噪音；信条 6 明确评级；六灯口径（≥3🟢且无🔴=整体🟢）。
- schema 要点：`moat_rating`(wide/narrow/eroding/none) 对齐 GUI 贴回门；含 `moat_five_questions`(5 项)、`moat.structural`、`margin_of_safety`、`lights`(六灯)、`qualitative_light`。

### 3. 06-collision — L3 碰撞（3294 字，红队角色）

- 用途：先当反方（红队四问 + 至少 5 条质疑），再按规则树裁决。
- 注入原则：碰撞铁律（不产生新信息/🔴可往上推翻不可往下忽略/多规则取更严）；不接飞刀、不蹭热点（月涨>30% 禁 BUY 无豁免）；后发制人；买分歧卖共识（一致看多=危险信号）；取舍原则（机会成本必答）；息价（安全边际<30%→WAIT）；家国🔴→PASS；2638/年线仓位提醒；信条 6（WAIT 必须写清在等什么）。
- schema 要点：`decision`+`confidence`+`position_pct`+`conflicts` **已对齐 fengstate key_fields**（按你的要求用 conflicts 不用 challenges）；每条 conflict 带 `severity`(high/medium/low)+`handling`；另加 `wait_condition`、`final_check`（亏钱5种方式/跌30%加仓还是割肉/涨30%卖吗/近因/机会成本）。

### 4. review — 复盘（2678 字）

- 用途：thesis_valid 总判定 + 四态假设逐条复核 + 红线对照 + 健康度评分。
- 注入原则：论文止损不是价格止损（亏损本身不是卖出理由，价格与论文背离必须点名）；处置效应自查（"如果是别人拿着我会怎么判"）；价值陷阱警告（便宜+下跌+论文"看似"成立 = 最危险组合）；falsified 不许被"长期来看"洗白；unknown 不许用来回避判断；信条 6 + 下次回顾给具体日期（信条 7）。
- schema 要点：`thesis_valid`(valid/uncertain/falsified) 对齐 GUI 贴回门；含 `hypotheses`[](四态)、`redlines`[](intact/approaching/breached)、`health_score`、`price_vs_thesis`、`action`(四选一)、`next_review`。

### 5. 07-report — L4 白话报告（2020 字，特殊：输出 markdown 非 JSON）

- 用途：把 L0/M/L1/L2b/L2a/L3 各层结论翻译成人话报告书，走 /api/prompt/submit-md 通道（不进状态机）。**旧文件是 05-qualitative 的错误复制（旧 bug），已彻底重写。**
- 注入原则：信条 6（结论卡必须 BUY/HOLD/ADD/REDUCE/WAIT/PASS 之一，没有"也有道理"）；零术语翻译表（年线/PE/FCF/夏普/z-score/分位数/安全边际等）；反方意见不许写软（红队三条原汁原味）；息价"还不够便宜"直说；取舍原则补一句；红线清单+下次回顾。
- schema 要点：无 JSON——9 节固定结构（结论卡→干嘛的→生意好不好→数字→反方→便宜不便宜→钱怎么摆→什么情况证明我错了→下次再看），每个数字后跟"这意味着什么"，报告 800–1500 字。

## 场景层 4 条（不进状态机，自由 schema）

### 6. exit — 卖出自查（3216 字）

- 用途：卖出前三步自查：归账户 → 六类理由归类 → 六项偏误自查。
- 注入原则：双账户制打头（INVESTMENT 论文止损 vs TRADING 机械止损-20%；因亏损而卖=散户思维）；六类理由判定表（红线被突破只能 thesis_broken/risk_control，不许洗成"估值"；集中度超标不是卖出理由）；钱仓滚存（浮盈≥30% 或市值≥投入×1.3 建议滚存）；段永平"买错了现价立即卖"；取舍原则。
- schema 要点：`reason_class`(六类)+`bias_checks`[](六项全列：sunk_cost/loss_aversion/confirmation/anchoring/disposition/recency) 对齐 GUI 贴回门；另加 `account_type`、`redline_status`、`proceed`、`advice`(四选一)。

### 7. discuss — 有锚讨论对手（2313 字，守锚不投降版）

- 用途：基于框架锚点的观点交锋，不讨好、不和稀泥。
- 注入原则：锚 = 框架结论（六信条+DK 四原则+六纪律+标的既有结论，附"家法速查"表）；**同一层面反驳**（谈生意用生意回、谈估值用估值回，不许偷换层面、不许"长期来看"回避）；信条 3 噪音判定（专门字段点名对方论据里的噪音）；revise 必须写清改了哪条；信条 6 收尾不许骑墙。
- schema 要点：`stance`(hold_anchor/revise/concede)+`rebuttal` 对齐 GUI 贴回门；另加 `anchor`、`steelmanned`、`noise_callout`、`evidence_needed`、`closing`。

### 8. translate — 白话翻译器（2073 字）

- 用途：任意工具输出（回测白话卡/筛选结果/审计报告）→ 零术语大白话。
- 注入原则：术语词表 20+ 条（年线/PE/FCF/夏普/回撤/IC/z-score/分位数/胜率赔率/CVaR/BETA/bootstrap/解禁/质押/安全边际等）；三段结构（one_liner→展开→caveats）；数字保留但每个跟"这意味着什么"；原文矛盾/缺数据/截断逐条进 caveats——**替工具圆谎是本岗位最大失职**。
- schema 要点：`plain_explanation` 对齐 GUI 贴回门；另加 `one_liner`、`terms_explained`[]、`caveats`[]。

### 9. spec — 投机侧车解读（2212 字）

- 用途：tickflow T0(触发候选)/T2(结构防线位)/T4(监控) 输出 → 交易级风险大白话 + 机械止损位复述。
- 注入原则：双账户制铁律（只用交易钱包；把短线亏损硬扛成长期投资=第一大错误）；后发制人（右侧信号 n/4 判定：≥3/4 可试盘、1-2/4 等回踩、空头/假突破放弃）；机械止损（错了就走，不加仓不摊平不转长期）；幽灵原则（侧车只供数据，纪律/卖出留主框架）；钱仓滚存不适用交易账户。
- schema 要点：`risk_verdict`(可试盘/等回踩/放弃)+`stop_loss` 对齐 GUI 贴回门（输入没给止损位填 null 并注明）；另加 `right_side_signal`、`stop_loss_source`(逐字对应输入)、`max_loss_plain`(最坏亏多少)、双提醒字段。

## 通用约束（9 条全部内置）

- 自包含：每条开头声明"没有联网、没有文件系统，一切判断只基于本 Prompt 资料"；{{EVIDENCE}} 标注"系统自动预填，可能不完整"。
- 反敷衍：数据不足写"不知道/资料未提供"，禁止编造数字；无来源判断标"（推测）"。
- 占位符只用 {{TICKER}}/{{NAME}}/{{EVIDENCE}} 三个（GUI 现有替换逻辑零改动）；状态层 4 条末尾 = 输出 schema（fenced json，字段说明中文）+ 完整示例 + "只输出 JSON"；07-report 末尾 = "直接输出 markdown 报告全文"。
- 每条带"自反方（必做）"段，示例全部用虚构 DEMO 公司防止模型照抄。

## 验证结果（2026-09-07）

- 8 个含 JSON 的模板：所有 fenced json 块 + GUI extractOutputSchema 抽取逻辑实测 JSON.parse 全部通过。
- 字数全部落在 2000–4000（见各节标注；07-report 2020 为下限附近，因其无 schema 块）。
- 注意：GUI `PROMPT_LAYER_MIN_KEYS` 对 06-collision 写的是 challenges(alt: conflicts)——本草案统一用 conflicts，已在 alt 兼容范围内，无需改 api.ts；workspace.ejs 七卡 + submit-md 前端接线属 GUI 改造步骤，另起任务。
