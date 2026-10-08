---
name: fengspec
description: "[FengInvest] 投机/交易钱包轨道 — 独立于 /fenginvest 的第二条路径:右侧突破/事件驱动的投机性买入、机械止损、两个钱包规则两套。买入登记用 /fengholding(account_type=TRADING),卖出用 /fengexit,复盘用本 skill 交易级复盘。"
when_to_use: "投机/交易。当用户要求分析右侧突破/事件驱动的投机机会、评估一笔交易性买入、试盘建仓、设定止损条件单、做投机级波段时使用。触发词:投机、交易、右侧、突破、事件驱动、试盘、波段、短打、交易钱包、两个钱包。价值投资输入请走 /fenginvest——两路径混用会被拦:投机标的绕开 fengscreen 七硬指标,价值分析不跑本六步。"
allowed-tools:
  - Agent
  - Bash
  - Read
  - Skill
  - Write
triggers:
  - fengspec
  - 投机
  - 右侧突破
  - 事件驱动
  - 试盘
  - 波段
  - 交易钱包
---

# FengInvest — 投机/交易钱包轨道（fengspec）

> 用法：`/fengspec <TICKER 或事件>`。**本 Skill 与 `/fenginvest` 是完全独立的两条路径（奇衡·双账户制：两个钱包、规则两套、互不干扰）**——本路径做"投机性买入"（右侧突破/事件驱动，回报来自对手盘错误）；投资路径做价值。两路径结论互不覆盖；**同一标的允许分别进投资钱包、交易钱包（隔离记账）**。
>
> 交接链：买入登记 → `/fengholding`（`account_type=TRADING`）；卖出 → `/fengexit`；交易级复盘 → 本 Skill T5。概念定稿见 `docs/11-speculation-track.md`。

## 铁律（先读，违反任一 → 本轮不做）

1. **无来源=不存在**：每个技术/结构判断必须落到来源——人物档（`research/040-people/named/` 投机系）、奇衡库、行情数据；引不出来源的判断不写进决策卡。
2. **本轨道不跑 `/fenginvest` 的七层框架、不跑 `fengstate` 状态机、不走 `fengscreen` 7 硬指标**——投机标的绕开 fengscreen；两层"不接入"边界清晰。
3. **硬约束（初版）**：杠杆=0；总资金 30% 硬顶永不爆仓；单票 ≤10%；首笔试盘 ≤3%；单标最大浮亏 -20% 机械止损（`fengwatch` 对 TRADING 强制）。
4. **只做右侧**：不做投井（无方向区间死买）、不做 A/B 点（逃顶/抄底=赌博），只做 C/D 点。

## 变量约定

- `TICKER`：交易标的代码；`EVENT`：触发事件描述。
- 知识底座（每个人物档读对应 §）：`knowledge/methodology/speculative-masters-map.md`（矩阵）+ `research/040-people/named/` 的 `sperandeo.md` / `larry-williams.md` / `elder.md` / `livermore.md`(§13) / `edward-thorpe.md` / `nassim-taleb.md` + 奇衡总纲（本机外部参考：奇衡项目 `docs/research/奇衡论投机性买入-研究文档.md`，路径按本机环境自行解析）。
- 行情数据：`python tools/fengdata.py`（价格/汇率）；结构数据视标的市场选择本地可用源，多源交叉验证。
- 本轮产出（交易决策卡）写入 `research/speculative/<YYYY-MM-DD>-<TICKER>-decide.md`（gitignored 本地路径，勿入 060-companies）。

## 六步流程（每步：做什么 / 查什么 / 跑什么 / 输出）

### T0 — 触发：先有"事件/结构"，再研究标的

- 确认触发源：右侧突破（阻力最小路线）/ 事件驱动（重组、并购、业绩超预期、题材暖风）/ 动量确认。
- 查 `sperandeo.md` §7（2B 结构=反转扳机）、`livermore.md` §13（关键点=跟庄）、`larry-williams.md`（趋势起爆点）、`elder.md`（三重滤网多级确认）。
- **禁止**：投井、A/B 点、无事件纯情绪追买。
- 输出：触发源一句话 + 候选标的列表（≤3）。
- 可选跑 tickflow 薄桥：`python tools/fengtick.py t0`（读 tickflow data/ 下扫描结果，聚合触发源 + ≤3 候选）→ 产物 `research/speculative/<YYYY-MM-DD>-candidates.json`。

### T1 — 环境闸：大盘/年线/现金流闸门

- 查 `sperandeo.md`（指数相互验证：沪深同向创新高/破位才算全面牛熊；年线上方当牛做、下方当熊做）、`larry-williams.md`（波幅坍缩倒计时）、`edward-thorpe.md` §11（错位闸）、`nassim-taleb.md` §11（黑天鹅前置信号闸）。
- 复用系统纪律：2638 法则（上证≤2638 仓位≤30%）、年线法则（标的须年线上方）。
- **环境不对 → 本轮不做**（这是"不做"最常见的一层，不是硬扛）。
- 输出：环境三灯（大盘/年线/现金流）＋ 结论"放行/驳回"。

### T2 — 结构确认：右侧确认 + 阻力位

- 右侧确认：`python tools/fengrule.py` 后发制人 4 信号（≥3/4 🟢 才算确认）；阻力位突破是否放量有效。
- 查 `sperandeo.md`（设底线前高/前低，不看破不动；2B 与旗形/扩散形区分）、`elder.md`（支撑压力三维评估）、`livermore.md` §13（主升浪特征、领头羊符号）。
- **假突破识别**：突破后迅速回落/量价背离 → 放弃（可参考奇衡（本机外部参考：奇衡项目 `output_bilibili/BV14E411c7rJ_识别假突破_corrected.md`））。
- 输出：结构判定（确认/否决）+ 关键防线位（止损锚）。
- 可选跑 tickflow 薄桥（防线位摘要，纯本地未联网）：`python tools/fengtick.py t2 <TICKER> --file <OHLCV.csv|json>`（复刻 tickflow `levels.py` 纯函数：前高前低/pivot/ATR 波动通道 + 一句话止损锚）→ 输出直接填决策卡"关键防线位"行。

### T3 — 纪律捆：一切预写，入场前完成（不可省）

入场前把以下全写进决策卡与持仓 JSON，缺任何一项不进场：

1. **身份标签（三选一）**：🎁投机（买机会）/ ⚔️交易（赚对手盘错误）/ 🏦投资（靠分红回购）——标签为"投资"者**转交 `/fenginvest`**，本轨道只处理 🎁/⚔️（奇衡三分法，见 `larry-williams.md`）。
2. **首笔试盘 ≤3%**；确认后按 5-10% 分笔加仓（金字塔递减，只对赢家加码，不向下摊平）。
3. **止盈价 / 跌多少认错 / 期望损益比**入场前三问（`knowledge/discipline/奇衡卖出艺术.md`）。
4. **无条件止损 + 条件单**：禁止"心理止损"；预写触发价与动作（`sperandeo.md` §11；`livermore.md` §13 只做 C/D 点）。
5. **滚存线**：浮盈≥30% 回收本金（系统钱仓滚存）。
6. **时间窗上限**：事件交易 1-3 个月、波段 3-12 个月，到窗未兑现重评。
7. **凯利/爆仓约束**（仅组合层面）：分数凯利 κ≤1/2、单笔与连亏熔断、融资来源上限（`edward-thorpe.md` §11；`nassim-taleb.md` §11）。
- 输出：纪律捆表（每一项含数值/触发/动作）。

### T4 — 监控：只看预设信号，不看盘面噪音

- `python tools/fengwatch.py daily`（TRADING 账户 -20% 机械止损已强制；论文类检查对 TRADING 跳过）。
- 紧盯 T3 预写的：止损线 / 结构证伪（2B、破位）/ 事件兑现 / 滚存线 / 时间窗。
- 查 `edward-thorpe.md` §11（错位回归 vs 更异常）、`nassim-taleb.md` §11（封底结构失效即预警）。
- 输出：监控点列表 + 每次触发记录。
- 可选（tickflow 外部信号参考，不改 fengwatch.py）：`python tools/fengtick.py t4` 查看"tickflow 监控信号 → fengwatch"接入文档；`python tools/fengtick.py t0` 把当日 tickflow 触发并入 `research/speculative/<YYYY-MM-DD>-candidates.json` 供人工对照监控点。

### T5 — 卖出/复盘：触发—归类—执行—复盘

- **卖出分类**（`奇衡卖出艺术.md`）：①止盈卖出（达成目标即走，不贪后段）②保护性止损（破位无条件执行，"你错了也要做"）③买入理由消失（入场理由每天检查，不成立即减仓；买分歧卖共识在卖出侧落地）。
- **移动保护**：有浮盈上移止损至最近底分型极点（止损从"剁手"变"剪指甲"）。
- **离场后**：不马上买回去（钱仓滚存）。
- **交易级复盘（本轨道自己的，不走 `/fengreview` 论文四态）**：区分"手气 vs 结构可重复"（少壮靠手气警钟）；outcome 四态判定（hit/falsified/partial/pending）写回持仓 `reviews`；总结买卖点纪律执行打分。
- 输出：卖出执行单 + 复盘（含手气/结构归因）。

## 纪律集速查（链接到数据库，引用不展开）

见 `knowledge/methodology/speculative-masters-map.md` §2 六步矩阵（每格含来源文件路径）——T0 触发 7 家、T1 环境闸 5 家、T2 结构 4 家、T3 纪律捆 6 家、T4 监控 3 家、T5 卖出 4 家，全部逐条带源。

## 两钱包隔离（不回退）

| 维度 | 投资钱包（/fenginvest） | 交易钱包（本轨道） |
|:--|:--|:--|
| 入场依据 | 价值/论文 | 右侧结构/事件 |
| 周期 | 1-5 年+ | 3-12 个月 |
| 止损 | 论文止损（价格跌不卖） | 机械止损 -20%（条件单化） |
| 仓位 | 按置信 30-50% DCA | 试盘 3% → 5-10%，总 30% 硬顶 |
| 归因 | 进价值组合/HRP | 独立归因，不并入价值组合主体口径 |
| 同票双钱包 | 可并存，隔离记账（登记时给"同标双钱包"警示） | 同左 |

## 输出模板（交易决策卡）

```markdown
# fengspec 决策卡 — {TICKER} — {YYYY-MM-DD}
- 钱包：TRADING ｜ 身份标签：🎁投机/⚔️交易
- 触发（T0）：{触发源一句话 + 来源}
- 环境（T1）：大盘{🟢🟡🔴} 年线{上方/下方} 现金流闸{放行/驳回} → {执行/不做}
- 结构（T2）：右侧信号 {n/4} ｜ 关键防线位 {止损锚} ｜ 假突破 {是/否}
- 纪律捆（T3）：试盘 {≤3%} ｜ 止盈 {目标} ｜ 认错 {跌多少} ｜ 期望损益比 {x:1}
  ├ 止损条件单 {触发价/动作} ｜ 滚存线 {≥30%回收} ｜ 时间窗 {N 月}
  ├ 单票仓位 {≤10%} ｜ 总资金占用 {≤30%} ｜ 杠杆 0
  └ 证伪条件（redlines）：{什么结构/事件发生则清仓}
- 监控（T4）：{监控点；-20%机械止损已按 TRADING 生效}
- 卖出计划（T5）：{止盈/保护性止损/理由消失 各自触发与动作}
- 复盘：{手气 vs 结构归因；outcome 四态}
- 来源：{每条判断的人物档/奇衡库/行情来源路径}
```

## 登记 / 卖出 / 复盘命令

```bash
# 买入登记（先按 holdings/SCHEMA.md 写好 TRADING 持仓 JSON，再 add 四段校验）
#   thesis.redlines 必填（预写结构证伪=红线，违者 fengspec 拒登）
#   triggers.stop_loss_pct=-0.20（TRADING 机械止损）
python tools/fengholding.py add <TICKER>

# 每日监控（TRADING 机械止损强制；论文类检查跳过）
python tools/fengwatch.py daily

# 卖出闭环（价格/股数/理由按工具交互填写；TRADING 破位无条件执行）
python tools/fengwatch.py sell <TICKER>
```

## 完成后

- 汇报：决策卡 5 档结论（进场/观望/放弃/减仓/清仓）+ 纪律捆 + 关键来源；买入且用户确认 → 提示 `/fengholding` 登记（`account_type=TRADING`）。
- 隐私红线：交易记录/决策卡均在本地 gitignored 路径，不进公开文档。
- 边界声明：本 Skill 是交易纪律与判据抽取工具，不是预测器；"消息/内幕/他人推荐"一律降权，只认结构+纪律。
- 开源登记：提到开源项目即登记 data/config/opensource_list.json（提到=入表）。
