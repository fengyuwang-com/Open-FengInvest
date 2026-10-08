---
name: fengholding
description: "[FengInvest] 持仓持有期管理 — 持仓总览/登记分析/单只检查/后管理（钱仓滚存检测）。买入前用 fenginvest，卖出用 fengexit，复盘用 fengreview。"
when_to_use: "持有期管理。当用户要求查看持仓总览、登记新买入的持仓、检查某只持仓、跑每日监控、钱仓滚存检测时使用。触发词：持仓、持有期、登记持仓、仓位、检查持仓、今日提醒"
allowed-tools:
  - Agent
  - Bash
  - Read
  - Skill
  - Write
triggers:
  - fengholding
  - 持仓
  - 持有期
  - 登记持仓
  - 仓位
---
# FengInvest — 持仓持有期管理

> 用法：`/fengholding` 或 "看看持仓" / "登记新持仓 XXX"
> 前置：买入前分析用 `/fenginvest`；卖出交 `/fengexit`；复盘交 `/fengreview`。

## 变量约定

- `<TICKER>` → 标的代码/唯一标识（如 0700.HK、cash_cny）
- `ROOT` → `cd "$(git rev-parse --show-toplevel)"`

## 1. 持仓总览（三轴盘面）

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengholding.py list
python tools/fengholding.py list --all      # 全量口径（含现金）——必跑，汇报持仓数用
python tools/fengportfolio.py check
```

- `fengholding.py list` = 风险口径 11（排除真现金）；`list --all` = 全量 14（含现金）——**两个口径都必须跑**，完成后汇报"风险/全量"两个数
- `check` 输出：market/segment/combo/单标集中度 + 资金池 + 买入预算（资金墙=预算非风险）
- 实时汇率先跑：`python tools/fengdata.py fx`（失败自动回退快照）
- 汇报时逐只核对滚存阈值（用 `list --all` 的 return_pct）：浮盈 ≥15% = `SOON` 已触发（可择机回收本金）；≥30% = `OPPORTUNITY`（交 `/fengexit` 卖出回收本金）——规则见第 4 节

## 2. 登记新持仓（四段分析）

1. 在 `holdings/hold_<TICKER>.json` 写好持仓 JSON（字段见 `holdings/SCHEMA.md`）
2. 运行登记分析：

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengholding.py add <TICKER>
```

3. 按报告四段处理：
   - **① SCHEMA 校验**：`hard_errors` 非空 → 先修再 add（此时退出码 2，不写文件）
   - **② 价格核对**：登记价 vs 实时价偏差 >10% → 检查是否手误/过时价；非 CNY 缺汇率快照 → 补 `meta.fx_rates`
   - **③ thesis 联动**：检测到 `research/060-companies/<TICKER>-*` 研究目录 → 回填 `thesis.original/exit_conditions/valuation_gap`（报告路径会给出）；缺 exit_conditions 必须补；同时记录 `thesis.financials_asof`（分析所依据的最新财报期，PIT 点及时，见 docs/00-workflow.md 数据纪律）
   - **④ 组合影响**：登记后集中度 delta + 资金池 + 预算扣减；🔴/🟡 超限警告出现 → 向用户确认是否仍要登记（**超限 = 警示 + 重审，非硬否决**；单标破 20% 黄线需论文+证伪条件齐备并记录理由；**40% 绝对上限不可突破**）
4. 回填 thesis 后重跑 add 确认 `validation.warnings` 收敛，再看盘面：

```bash
python tools/fengportfolio.py check
```

5. **论文建立（镜子测试 + 可证伪假设 + 红线）**——买入后立即做，冷静时写清楚：
   - **镜子测试**：写 `thesis.mirror_test`，5 句话说不完整 = 买入决策本身有问题："我以 __ 元买入 __，因为：1 生意本质… 2 护城河… 3 管理层… 4 价格相当于内在价值 _ 折… 5 即使错了下行风险可控"
   - **可证伪假设** `thesis.hypotheses[]`：3-7 条，每条含验证方式+频率（"公司很好"不是假设，"收入增速≥15% ← 季报 ← 每季度"才是），且**每条必带 `outcome.expected`（可证伪预期，含 `horizon` 验证期限）**——**没有可证伪预期的假设不是假设**：
     - ✅ 好：`"expected": "FY2026 营收 ≥ 520 亿（horizon 12 个月，来自管理层指引下限）"` —— 数字阈值 + 期限 + 来源，事后可对照判定
     - ❌ 坏：`"expected": "公司会很好"` —— 不可证伪，登记时打回重写
     - 预期要量化/可观察（数字阈值、时间点、可核验事件），并优先附来源（管理层指引/分析师共识/历史增速），供复盘时对照 expected vs actual 判定（见 fengreview 4.2）
     - 完整字段见 `holdings/SCHEMA.md`（thesis.hypotheses[].outcome）
   - **红线清单** `thesis.redlines[]`：按严重度分级，触发动作**预写**（恐慌时不现场决策）：`fatal`=核心论点证伪→立即清仓 / `severe`=关键假设受损→减50%重评 / `warning`=需要调查
   - 参考：`knowledge/discipline/` 相关纪律 + L4 报告的"建仓策略与退出条件"
   - 字段定义见 `holdings/SCHEMA.md`（thesis.mirror_test/hypotheses/redlines + health_score）

> add 自动回写：`capital_zone`（按币种推断：CNY→CN_IN，HKD/USD→OVERSEAS）、`triggers` 默认（止盈15%/止损10%/下次回顾+90天）、`meta.updated_at`。港股通境内资金投港股：手动标 `capital_zone=CN_IN` + `market_access="hksi"`。

## 3. 单只检查（退出规则）

```bash
python tools/fengholding.py get <TICKER>
python tools/fengwatch.py check <TICKER>
```

- `get` 输出：SCHEMA 校验 + 全量持仓 JSON（id 优先）
- `check` 输出 10 条规则：价格止损/趋势/论文失效/审核到期/价格触发/滚存/基本面/估值泡沫/时间止损/估值回归

## 4. 后管理

### 每日例行

```bash
python tools/fengwatch.py daily
```

- 非 GREEN 持仓产生提醒（`alerts/today.json`），Web 首页"今日提醒"同步显示
- 触发 RED 退出条件 → 交 `/fengexit`

### 异动归因四选一（news-pulse，单日 ±5% / 一周 ±10% 必做）

> 移植自 ai-berkshire news-pulse。异动不是"看新闻解释一下"，而是强制归因分类：

1. 一句话归因（30-60 字）：主因 + 次因 + 性质
2. 按四类侦察：公司公告/财报/管理层动作 → 监管政策 → 行业对手 → 情绪面（卖方评级/资金面）
3. **性质判断四选一（核心结论）**：
   - **价值事件**：基本面真实变化（业绩/护城河/管理层/终局）→ 交 `/fengreview` 重审论文
   - **情绪技术波动**：无基本面对应 → 论文不动，仅记录
   - **真因不明**：找不到匹配异动幅度的事件——**这是最危险的结论**，要么市场提前知道什么（内幕/抢跑），要么漏了信息源 → 标注警示，扩大搜索面，持续观察
   - **混合**：部分价值事件 + 部分情绪放大
4. 诚实面对"不明"——找不到主因就写"真因不明"，**比硬凑因果链更有价值**（市场可能在抢跑利空）

> 噪音边界：异动归因只服务于持仓论文管理（判断"这动的是不是我的论文"），不构成短线买卖信号。

### 钱仓滚存检测（持有的一部分，执行在 fengexit）

- 浮盈 **≥15%** → `SOON` 关注，可择机回收本金
- 浮盈 **≥30%** → `OPPORTUNITY` 建议卖出回收本金留零成本筹码 → 交 `/fengexit` 执行
- 回收后 `phase=capital_recovered`，零成本持有

### 复盘提醒

- `next_review_date` 到期（RED `REVIEW` 提醒）→ 交 `/fengreview`

## 完成后

向用户汇报：持仓数（风险/全量）、三轴盘面结论、登记/检查发现的警告与建议动作（滚存/卖出/复盘）。
