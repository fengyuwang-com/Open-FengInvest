---
name: investment-team
description: 四大师并行投研分析框架 — 段永平(商业模式) + 巴菲特(财务估值) + 芒格(行业竞争) + 李录(风险管理)
allowed-tools:
  - Agent
  - AskUserQuestion
  - Bash
  - Edit
  - Glob
  - Grep
  - Read
  - Skill
  - Write
---

# 投研团队：四角色并行分析框架

对 `$ARGS`（TICKER）进行团队化投资研究分析。使用 Agent 工具并行启动 4 个后台研究 Agent。

> 上游原文此处为「对 $ARGUMENTS 进行团队化投资研究分析。使用 Team 工具创建真正的多Agent并行研究团队。」——ZCode 无 Team/Task 工具，改写为 Agent 工具等价流程（哪些是原文、哪些是适配，见文末《FengInvest 适配注记》第 5 条）。

## 执行流程

### 第一步：取上下文 + 展示团队框架

**（FengInvest 适配）** 本 skill 由 `fenginvest-05-qualitative` 触发，TICKER 已由 args 传入。开工前先取上下文：

```bash
cd "$(git rev-parse --show-toplevel)"
BASE="$(ls -d research/060-companies/<TICKER>-*/$(date +%F) 2>/dev/null | head -1)"
cat "$BASE/02-market.json"
cat "$BASE/03-discipline.json"
head -60 research/040-people/named/duanyongping.md
head -60 research/040-people/named/buffett.md
head -60 research/040-people/named/munger.md
head -60 research/040-people/named/li-lu.md
```

**（上游原文）** 向用户展示以下团队结构，确认后启动：

| 角色 | 职责 | 分析框架 |
|------|------|----------|
| **team-lead**（你自己） | 统筹协调、汇总研判、输出最终报告 | 四大师综合框架 |
| **business-analyst** | 商业模式 & 护城河分析 | 段永平视角 |
| **financial-analyst** | 财务报表 & 估值分析 | 巴菲特视角 |
| **industry-researcher** | 行业格局 & 竞争态势 | 芒格视角 |
| **risk-assessor** | 风险评估 & 管理层研判 | 李录视角 |

**（ZCode 适配）** 本 skill 由 fenginvest L2a 自动触发，没有交互确认环节：展示团队表后直接进入下一步；若被人工单独调用，可先等用户点头。

### 第一步半：AI研究偏见评估

**（上游原文）** 在创建团队前，先向用户展示该公司的"AI可研究性"评估：

**信息丰富度评级**（决定研究策略）：
| 等级 | 特征 | 研究策略调整 |
|------|------|------------|
| A级（信息充裕） | 上市多年、券商覆盖广 | 团队重点放在**反面检验**和**非共识视角**，避免输出与市场一致的"正确的废话" |
| B级（信息适中） | 上市不久、覆盖有限 | 每个Agent的推算数据必须标注置信度，team-lead汇总时标注"数据充分度" |
| C级（信息稀缺） | 冷门/新上市/新兴市场 | 团队转为"第一性原理模式"：不追求报告完整性，聚焦商业本质的几个核心问题 |

**关键提醒**：资料多≠确定性高，资料少≠确定性低。AI能输出的置信度 ≠ 投资的真实确定性。确定性来自商业模式本身，不来自资料数量。

将评级结果告知每个Agent，影响其研究方式。

### 第一步¾：搜索权限预检（关键 · 避免 Agent 静默退化）

**（上游原文的理由）** 在创建团队、启动任何后台 Agent **之前**，必须先确认联网搜索权限已放行。

**为什么必须预检**：本 skill 用 `run_in_background: true` 启动 4 个后台子 Agent，而**后台 Agent 无法向用户弹出交互式权限确认**。若联网搜索不可用（上游原文是 `WebSearch` 未在 `.claude/settings.local.json` 的 `permissions.allow` 白名单中），子 Agent 的联网搜索会被**静默拦截**，导致其退化为仅凭训练知识（有知识截止日期）作答，却仍按框架输出一份"看起来完整、实则未联网"的伪研究——这是本 skill 最危险的失败模式（见 issue #58）。

**预检步骤（ZCode 适配版：把上游的 WebSearch 白名单检查换成搜索工具探针）**：

1. 用 Bash 探一次搜索链路：
   ```bash
   python "${SEARCH_KING_DIR}"/scraper.py --search "ping" --limit 1 | head -5
   ```
2. 若报错 / 空结果（即搜索不可用）→ **停下来，不要启动 Agent**，提示用户：
   > ⚠️ 检测到搜索链路不可用。后台研究 Agent 无法联网，会退化成仅凭训练知识作答。请先修好 Search-King（或改用其它可用搜索工具），再重跑本命令。
3. 探测成功 → 正常继续。

### 第二步：创建团队

**（ZCode 适配）** 上游原文用 TeamCreate 创建团队：`team_name: {公司名}-research`（英文小写，如 `meituan-research`）、`agent_type: team-lead`。

ZCode 无 TeamCreate：**不创建团队资源**，等价物是「4 个 `run_in_background: true` 的 Agent + 每份 prompt 顶部写死 `你是{公司名}投研团队中的"{角色}"`」，角色名沿用上游（business-analyst / financial-analyst / industry-researcher / risk-assessor）。

### 第三步：创建4个任务

**（ZCode 适配）** 上游原文用 TaskCreate 建 4 个任务（每个带 subject、description、activeForm）。ZCode 无 TaskCreate：**把这 4 个任务的 subject 与 description 原样写成 4 份 Agent prompt 的正文**（即下面各任务的标题与要点，一条不许省）。

#### 任务1：商业模式分析
- subject: `分析{公司名}商业模式、护城河与用户价值`
- description 包含：
  1. 商业模式本质：核心生意定义、收入结构拆解
  2. 平台/产品飞轮效应如何运转
  3. 护城河分析：品牌/转换成本/网络效应/规模效应/技术壁垒，逐一验证
  4. 用户/客户价值：为各方创造了什么独特价值
  5. 业务矩阵与协同效应
  6. 段永平"好生意"标准评估：差异化、定价权、可持续竞争优势
  7. 要求搜索最新财报、行业报告等公开信息

#### 任务2：财务与估值分析
- subject: `分析{公司名}财务数据、盈利能力与估值`
- description 包含：
  1. 近3-5年营收、净利润、经营利润趋势
  2. 盈利能力指标：ROE、ROA、毛利率、经营利润率
  3. 现金流分析：经营性现金流、自由现金流、资本开支
  4. 资产负债表健康度：现金储备、负债率、流动性
  5. 估值分析：PE/PS/PB/EV等，与历史及同业对比
  6. 安全边际评估：内在价值 vs 当前股价
  7. **金融严谨性验证（必须使用Bash调用工具，禁止心算）**：
     - 市值验算：`python tools/financial_rigor.py verify-market-cap --price {价格} --shares {股本} --reported {报告市值} --currency {币种}`
     - 估值验算：`python tools/financial_rigor.py verify-valuation --price {价格} --eps {EPS} --bvps {每股净资产}`
     - 关键数据交叉验证：`python tools/financial_rigor.py cross-validate --field {字段} --values '{JSON}' --unit {单位}`
     - 三情景估值：`python tools/financial_rigor.py three-scenario --price {价格} --eps {EPS} --shares {股本亿} --growth {乐观} {中性} {悲观} --pe {乐观PE} {中性PE} {悲观PE}`
     - 将工具输出结果直接嵌入报告中作为验证记录

#### 任务3：行业与竞争分析
- subject: `分析{行业}行业格局与{公司名}竞争态势`
- description 包含：
  1. 行业规模与增长：市场规模、增速、渗透率
  2. 竞争格局：主要对手市场份额、竞争策略对比
  3. 核心竞争者威胁评估：逐个分析主要竞争对手
  4. 各细分赛道格局
  5. 行业趋势：技术变革、政策影响、新进入者
  6. 产业链分析：上中下游价值分配
  7. 要求搜索最新行业数据和竞争动态

#### 任务4：风险与管理层评估
- subject: `评估{公司名}投资风险与管理层质量`
- description 包含：
  1. 管理层评估：CEO能力圈、诚信度、战略眼光、资本配置能力、历史决策质量
  2. 监管风险：当前及潜在监管影响
  3. 竞争风险：各竞争对手威胁程度评估
  4. 业务风险：新业务亏损、扩张不确定性
  5. 宏观风险：经济周期、行业周期影响
  6. 治理结构：股权结构、关联交易、股东回报政策
  7. 长期确定性：10年后公司会怎样？什么可能颠覆其商业模式？
  8. 要求搜索最新监管动态、管理层言论等

### 第四步：启动4个并行Agent

**（ZCode 适配）** 上游原文用 Task 工具同时启动4个Agent（**必须在同一条消息中并行调用**），每个Agent带 `subagent_type: general-purpose`、`run_in_background: true`、`team_name`、`name`。ZCode 无 `Task`/`team_name`——等价写法：用 **Agent 工具**，`subagent_type: general-purpose`、`run_in_background: true`，角色名写进 prompt 顶部（ZCode 子 Agent 是独立回合，通过自身结果回报，无 SendMessage 通道）。

每个Agent的prompt模板：

```
你是{公司名}投研团队中的"{角色中文名}"，负责从{大师名}投资视角分析{公司名}。

请完成任务 #{任务编号}：{任务subject}

具体要求：
{任务description的内容}

**研究方法**：
- 使用搜索工具搜索最新公开信息（财报、行业报告、新闻）
- **财务数据必须来自两个独立来源**，按 `research/130-external-frameworks/ai-berkshire/skills/financial-data.md` 的规范执行（美股：macrotrends+stockanalysis；港股：aastocks+macrotrends；A股：东方财富+巨潮资讯；台股：FinMind `tools/twstock_data.py`+Goodinfo），两源误差>1%须标记
- 确保数据准确，关键数据标注来源
- 分析要深入，不流于表面
- **搜索：** `python "${SEARCH_KING_DIR}"/scraper.py --search "关键词" --limit 5`（取正文加 `--read <URL>`）
- **联网失败禁止伪装**：若搜索被拦截/不可用，禁止用训练知识冒充联网结果。必须在报告顶部醒目标注「⚠️ 本报告未能联网，基于训练知识（截止日期 X），置信度降级」，并如实告知 team-lead，由其决定是否中止研究

**输出要求**：
- 报告要详尽，使用Markdown表格呈现关键数据
- 每个分析维度要有明确结论和评分
- 报告末尾要有该维度的总体结论

**完成后**：
1. 上游原文在此处用 TaskUpdate 把任务标记为 completed（ZCode 无 TaskUpdate → 跳过，改为在报告末尾声明「本任务完成」）
2. 上游原文用 SendMessage 把完整分析报告发给 team-lead（ZCode 无 SendMessage → 改为把完整报告作为子 Agent 的最终返回结果原样交出）
```

### 第五步：接收报告并跟踪进度

- 向用户实时展示进度表（哪些Agent已完成、哪些仍在研究中）
- 每收到一份报告，更新进度并展示该报告的核心要点（3-5条）
- 等待全部4份报告到齐

### 第六步：关闭团队成员

**（ZCode 适配）** 上游原文：全部报告收到后，向 4 个Agent发送 shutdown_request（使用 SendMessage，type: "shutdown_request"）。ZCode 无 SendMessage/shutdown_request 通道，且后台 Agent 返回结果即自然结束——本步等价物 = **确认 4 份报告全部到手、无 Agent 仍在运行**（必要时用 TaskOutput 收尾），再进入汇总。若运行环境确实提供团队消息通道，则按上游原文发 shutdown_request。

### 第七步：汇总最终报告

综合4份分析报告，输出以下结构的最终报告：

---

#### 1. 一句话结论
> 用一段话（50-100字）概括是否值得投资及核心逻辑

#### 2. 四维评分总表
| 维度 | 框架 | 评分(1-5星) | 核心判断 |
|------|------|------------|----------|

综合评分：X / 5

#### 3. 核心数据速览
关键财务和经营指标表格（近2年对比）

#### 4. 各维度分析摘要
每个维度摘取3-5条最重要的发现

#### 5. 投资论点（Bull vs Bear）
- 🟢 看多逻辑（5-7条）
- 🔴 看空逻辑（5-7条）

#### 6. 巴菲特买入前Checklist
| # | 检查项 | 通过? | 说明 |
10个核心检查项，逐一评估

#### 7. 最终投资建议
- 定性判断表（生意质量/管理层/估值/时机）
- 分层操作建议表（激进型/稳健型/保守型 → 建议+价格区间）
- 关键催化剂（加仓信号/减仓信号各3-5条）

#### 8. 总结段落
100-200字的最终总结

---

### 第八步：保存报告

**（上游原文）** 将完整最终报告写入 `~/{公司名}投资研究报告_{日期}.md`（日期格式 YYYYMMDD）。

**（FengInvest 适配）** 报告落点是本仓分析目录，且必须过状态机（不能只写文件）：

```bash
cd "$(git rev-parse --show-toplevel)"
BASE="$(ls -d research/060-companies/<TICKER>-*/$(date +%F) 2>/dev/null | head -1)"
# 1) 写入 L2a 产出（本系统规定的落点，替代上游的 ~/{公司名}投资研究报告_{日期}.md）
#    → $BASE/05-qualitative.md
# 2) 产出 L3 碰撞引擎的输入契约（键名固定，见文末注记第 2 条）
#    → $BASE/05-qualitative_lights.json
python tools/fengstate.py complete <TICKER> 05-qualitative "$BASE/05-qualitative.md"
```

完成后通知用户可以进入 L3（06 - 碰撞引擎）。

### 第九步：数据抽检（准出流程）

```bash
# Step 1 — 提取抽检清单（15%随机抽样）
python tools/report_audit.py extract \
  --report "$BASE/05-qualitative.md"

# Step 2 — 对清单每项从可靠信源取数（参见 research/130-external-frameworks/ai-berkshire/skills/financial-data.md）

# Step 3 — 输出准出/打回判决
python tools/report_audit.py verdict \
  --results '<填好的JSON>' \
  --report 05-qualitative.md
```

**【准出】** 全部通过 → 报告可发布；**【打回】** 有不通过 → 修正后重审。

### 第十步：清理团队

**（ZCode 适配）** 上游原文：使用 TeamDelete 清理团队资源。ZCode 没有 TeamCreate/TeamDelete，也就没有团队资源要清理——本步等价物 = **清掉本次产生的临时文件 + 向用户汇报「L2a 完成，可进入 L3」**。

## 重要注意事项

1. **4个Agent必须并行启动**——在同一条消息中调用4次 Agent 工具（上游原文为 Task 工具）
2. **Agent 回报走自身结果**——ZCode 子 Agent 是独立回合，把完整报告作为最终返回结果交出（上游原文为 SendMessage 消息通信）
3. **数据准确性**——要求Agent使用搜索工具取最新数据，关键数据交叉验证
4. **结论要明确**——不回避给出买入/观望/回避建议和具体价格区间
5. **所有分析必须有数据支撑**——附数据来源
6. **耐心等待**——4个Agent研究需要几分钟，实时向用户更新进度
7. **反偏见意识**——team-lead在汇总时必须评估：各Agent的分析是否受限于资料充裕度？是否与市场共识过度趋同？最终报告需包含"信息丰富度评级"和"AI研究局限性声明"
8. **信息稀缺时的诚实原则**——宁可在报告中留白标注"数据不足"，也不要用推测填满框架伪装确定性

---

## FengInvest 适配注记（2026-09-16 首次安装；2026-09-17 随并入升级刷新）

### canonical 在哪

**本仓 `.agents/skills/investment-team/SKILL.md` 为 canonical。** 来源 = ai-berkshire（https://github.com/xbtlin/ai-berkshire，commit `6354c68`，MIT (c) 2026 xbtlin），正文已并入本仓 `research/130-external-frameworks/ai-berkshire/skills/investment-team.md`（逐字原文，供对账与 diff）。

（旧注记曾把 canonical 指向本机用户全局目录 `~/.claude/skills/investment-team/SKILL.md`：那是"脖子拴在别人家"——项目外的一次改动能让本仓 L2a 静默失效，已作废。ZCode 的技能发现路径也不含 `~/.claude/skills/`，此前 ZCode 会话里 `Skill("investment-team")` 必然落空、只能走四大师降级路径。）

### 调用前必须知道的 4 处与 FengInvest 现状的差异

1. **第八步的状态机步名**：不是 `complete <TICKER> l2a`，而是
   `python tools/fengstate.py complete <TICKER> 05-qualitative "$BASE/05-qualitative.md"`。
   合法步名 8 个：01-capability / 02-market / 03-discipline / 04-quantitative / 05-qualitative / 06-collision / 07-report / 08-portfolio。
2. **必须额外产出 `05-qualitative_lights.json`**：键名固定为
   `好生意 / 护城河 / 安全边际 / 管理层 / 需求稳定 / 会计质量`，值为 `{"light":"GREEN|YELLOW|RED","detail":"..."}`。
   这是 L3 碰撞引擎的输入契约；省略会让 `fengcollision.py` 退到 proxy 推断并误判（AAPL 案例实测）。
3. **搜索工具路径**：`python "${SEARCH_KING_DIR}"/scraper.py --search "关键词" --limit 5`；
   取正文加 `--read <URL>`。搜索失败禁止用训练知识冒充，须在报告顶部醒目标注「未能联网，置信度降级」。
4. **大师知识库路径**：`research/040-people/named/{duanyongping,buffett,munger,li-lu}.md`（注意是 `li-lu.md` 不是 `li-iu.md`）。

### 哪些是上游原文、哪些是 ZCode 适配（不删减，只改写）

**上游原文逐字保留**（本轮补回的 45 行即在其中）：第一步团队表；第一步半 AI 研究偏见评估的三级表 + 「关键提醒」（资料多≠确定性高）+ 将评级告知每个 Agent；第一步¾ 的「为什么必须预检」全段（后台 Agent 无法交互确认 → 静默退化为伪研究，见 issue #58）；第三步四个任务的 subject/description 全文（含**任务2 的金融严谨性验证：必须用 Bash 调 `financial_rigor.py`，禁止心算**、任务4 的 8 项）；第四步的搜索方法条目（含**财务数据两源交叉的信源规范**：美股 macrotrends+stockanalysis / 港股 aastocks+macrotrends / A股 东方财富+巨潮 / 台股 FinMind+Goodinfo，两源误差>1% 须标记）；第六步/第七步的汇总报告 8 节（含**第 6 节巴菲特买入前 Checklist 10 项**、第 7 节关键催化剂）；**第九步 `report_audit.py extract` / `verdict` 数据抽检准出流程**（【准出】/【打回】）；**第十步清理团队**；重要注意事项第 7 条（反偏见意识）与第 8 条（信息稀缺时的诚实原则）。

**ZCode 适配改写（工具名/落点，非删减）**：
- `Team 工具` → Agent 工具并行（第二步：不创建团队资源；第六步 shutdown_request → 确认报告到齐；第十步 TeamDelete → 无资源可清，改为清临时文件 + 汇报）。
- `Task`/`TaskCreate`/`TaskUpdate` → 第三节四个任务的 subject/description 直接写进 Agent prompt；子 Agent 用自身返回结果代替 `SendMessage` 汇报（第三步、第四步模板、重要注意事项第 1/2 条）。
- `WebSearch` 权限白名单预检 → 第一步¾ 的 Search-King 探针（同样的失败模式、同样"停下来不要启动 Agent"的处置）。
- `~/{公司名}投资研究报告_{日期}.md` → 本仓 `$BASE/05-qualitative.md`（第八步），并补 `fengstate.py complete` 与 `05-qualitative_lights.json`。
- `python3` → `python`（Windows）；上游 `skills/financial-data.md` 的引用路径改为本仓并入副本 `research/130-external-frameworks/ai-berkshire/skills/financial-data.md`。
- frontmatter 的 `allowed-tools` 删掉了 ZCode 不存在的 `SendMessage` / `TaskCreate` / `TaskUpdate` / `TaskList` / `TaskGet`（保留 Agent / AskUserQuestion / Bash / Edit / Glob / Grep / Read / Skill / Write）；这些工具的流程已在正文里改成 Agent 等价物，不影响本体。
