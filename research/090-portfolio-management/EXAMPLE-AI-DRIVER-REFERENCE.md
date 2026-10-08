# AI 参考对象示意（开源参考示例）

> **定位**：示意性的参考对象（reference anchor），展示本系统里的 AI 驱动层「怎么被用」。
> **不泄露的边界**：不搬本机专属私人 prompt、実际私人配置、私人策略個人判断。本示例只展示结构/角色/入口/示意模板。
> **来源锚**：
> - 状态机顺序与层定义：本系统 AGENTS.md 所列状态机八层及 skill 入口。
> - L2a 四角色框架来源：本系统 `.agents/skills/investment-team/SKILL.md`（及对照表 research/130-external-frameworks/ai-berkshire/ADOPTION.json）。
> - 上游框架归属记录：研究库 `research/130-external-frameworks/ai-berkshire/`（README.md / ADOPTION.json / UPSTREAM.json）。

---

## §1. 这个示意要解决的问题

- 开源版本如果光有工具 + 文档，新看的人会缺一个「AI 到底怎么跑这套东西」的锚。
- 所以本文展示：
  - 七层状态机里，每层「大致上 AI 做什么 / 工具做什么 / 产出大致是什么」。
  - L2a 四角色（investment-team）怎么引用/参考，以及它与上游 ai-berkshire 的关系如何表述。
  - 个位数的示意 prompt 模板结构（参考式，不保证直接运行，且不含私人配置）。

---

## §2. 状态机八层的 AI/工具示意（参考）

> 方向：展示每层**入口/角色分工/产出形态**，不是复制本机私人 prompt。数字「八层」指本系统状态机的层数量与顺序（不是八个角色）。

| 层 | 入口/工具（示意） | AI 大致能做的事（示意） | 产出形态（示意） |
|:---|:---|:---|:---|
| 01-capability（能力圈） | fenginvest / fenginvest.py（快查） | 框住自己懂/不懂的边界，标记不懂就跳过 | 层标记 + 能力圈边界 |
| 02-market（市场） | fengdata.py / fengmarket.py / fengmarketdata.py / fengstockintl.py 等 | 取行情/汇率/市场结构，多源交叉核对 | 市场/行情事实包 |
| 03-discipline（硬纪律） | fengrule.py + fengscreen.py | 跑四灯 + 四 DK 纪律 + 去劣筛选结果，递给下一层 | L1 灯 + 筛选结论 |
| 04-quantitative（量化） | fengquant.py / fengtechnicals.py / fengfactor.py | 因子/分位/相关性类量化，供参考 | 量化因子/分位表 |
| 05-qualitative（定性） | **L2a：skill("investment-team")** + 财务/一手资料工具 | 四角色并行：分析师/估值师/risk-assessor/编辑，基于事实+框架产出定性论文 | 定性论文/评估包 |
| 06-collision（碰撞） | fengcollision.py + 讨论入口 | 规则树/对撞/交锋，检验矛盾 | 碰撞结果 + 待解矛盾 |
| 07-report（报告） | fengverify.py / fengverify_gate.py / report_audit.py + L4 报告结构 | 验证/准出/报告结构与数据抽检 | 报告 + 论断卡/验证结果 |
| 08-portfolio（组合） | fengportfolio.py / fengholding.py / fengwatch.py | 组合放置/集中度/钱仓/卖出复盘/监控闭环 | 盘面/告警/复盘记录 |

要点：
- 定性层（05）是被 AI 驱动最多的一层，入口是 `skill("investment-team")`。
- 其他层也能被 AI 辅助，但产物必须由对应工具产生，AI 不得冒充工具结果。
- 状态文件只能经 fengstate.py 修改，不能手工擅自改状态。

---

## §3. L2a 四角色（investment-team）的示意

> L2a 定性层用的四大师并行框架。canonical 正文在 `.agents/skills/investment-team/SKILL.md`；对账与归属见 `research/130-external-frameworks/ai-berkshire/ADOPTION.json`。

示意角色分工（仅示意）：

| 角色（示意） | 大致职责（示意） | 示例性关注点（示意） |
|:---|:---|:---|
| 分析师（business analyst） | 理解生意/护城河/周期位置 | 竞争结构、利润质量、行业地位 |
| 估值师（capitalization/valuation） | 估值/价格-未来价值关系/折现/情景 | 多方法估值、情景、敏感性 |
| 风险评估者（risk-assessor / 李录视角） | 管理层/诚信/资本配置/风险敞口 | 管理层质量、错位风险、金融杠杆关注 |
| 编辑（editor） | 统合/行动阈值/清理冗余/可读性 | 报告清晰度、论文-证伪是否成对 |

示意性的研讨方式（仅示意）：
- 四角色并行：同一家公司/同一论文，各角色基于同一事实包出发，不串行依赖偏好顺序。
- 编辑统合后，形成定性论文 + 证伪条件（redlines），再交 L3 碰撞与状态机后续层。

---

## §4. L2a 与上游 ai-berkshire 的关系（示意）

> 这是示意，不是把私人用法搬出来。

- 上游 ai-berkshire（[xbtlin/ai-berkshire](https://github.com/xbtlin/ai-berkshire)）是**定性分析框架/技能源**的上游。
- 本系统对它的归属/并入关系，由 `research/130-external-frameworks/ai-berkshire/` 里的：
  - `README.md`（说人话：为什么并入、目录结构、四档口径、更新办法）。
  - `UPSTREAM.json`（repo/commit/license/synced_at/file_count/files 的 sha256）。
  - `ADOPTION.json`（逐文件归属：absorbed / kept / referenced / superseded、owner/landing/note）。
- 本系统里唯一的 absorbed 条目是 `investment-team`（canonical 正文在本仓 `.agents/skills/investment-team/SKILL.md`，上游只作来源）。
- 其余 20 个 skill 正文物理并入本仓 `research/130-external-frameworks/ai-berkshire/skills/`，作为参考资料；故意不放进 `.agents/skills/`，避免绕过七层状态机的平行入口。
- 四档判据：
  - absorbed（并入）：正文物理在本仓 + 落可读路径 + 有自有承接者。
  - kept（留档）：正文物理在本仓但没自有承接者/没入口消费。
  - referenced（引用）：本仓无正文，只写上游仓库+路径。
  - superseded（自有承接）：上游有该能力，但本系统已用自有 skill/工具承接。

示意性 table（仅示意，正式的是 ADOPTION.json/UPSTREAM.json）：

| 事例（示意） | 示例性 status（示意） | 示例性 owner（示意） | 说明（示意） |
|:---|:---|:---|:---|
| investment-team 正文 | absorbed（示意） | investment-team（示意） | 唯一进发现路径的 L2a 入口 |
| bottleneck-hunter 正文 | superseded（示意） | fengsource（示意） | 发现路径 2 产业链瓶颈，其余仅作参考留档 |
| 某些正文无承接者（示意） | kept（示意） | null（示意） | 正文留档作方法参考 |

---

## §5. 七层怎么被 AI 驱动：示意走法

> 以下是一个参考示意，不是私人 prompt 的复制。

- 要对一个新标的做研究，先由 `/fengsource` 入口做选股（thesis-first，自主选股，入口禁止跑筛子）。
- 选股之后通过 `/fengscreen` 去劣筛选（七硬指标 + 三豁免），通过者进 `/fenginvest <TICKER>`。
- `/fenginvest` 开始完整七层分析，状态机强制顺序。
- 定性层（L2a）走 `skill("investment-team")` 四角色并行，产出论文+证伪条件。
- L3 碰撞再检验矛盾。
- L4 报告层走验证/准出/报告结构。
- 买入后交 `/fengholding` 登记分析四段+论文（登录持仓 JSON），进入持有期。
- 持有期用 `/fengwatch` 类工具 daily/check/review/sell/history/outcome 维持监控与卖出闭环。
- 验证论断走 `/fengverify` 跑引擎 + 按协议项目打红绿灯。

---

## §6. 示意 prompt 模板结构（仅参考式，不保证直接运行）

> 注意：这是示意的「模版结构」，不含本机私人 prompt/配置。

示意 1 — 选股开始（示例）：
```
[示意] 以 thesis-first 自主选股开头，列出考虑的几条发现路径，经过三道闸门（证据/周期/护城河），给出候选卡，再排队七层。
```

示意 2 — 定性层（示例）：
```
[示意] 调用 investment-team 四角色并行：分析师、估值师、风险评估者、编辑。事实包来自 fengdata/fengsec/fengastock 等取数结果；不编造数字；多源交叉不过关的标记出来。
```

示意 3 — 碰撞/验证（示例）：
```
[示意] 碰撞层把前面定性结论放进规则树/对撞，列出矛盾；验证层按协议项目打红绿灯，结论卡附带来源。
```

示意 4 — 组合放置（示例）：
```
[示意] 论文+证伪齐备后，把结论交给组合层：标 market/segment/qualifier，算集中度与钱仓，按置信度档次安排仓位，理由落日志。
```

---

## §7. 这个示意里没有的东西（边界重申）

- 不含本机私人 prompt、不含私人评估过程、不含私人配置。
- 不含个人持仓/组合当前盘面/中间研究过程。
- 若上游新增了 skill/报告索引能力，可在开源侧带公开可引用部分 + 归属说明，不带本机专属对账肌肉。

---

*（本文是开源参考示意，不含本机私人 prompt/配置。）*
