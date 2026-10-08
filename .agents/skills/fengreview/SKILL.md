---
name: fengreview
description: "[FengInvest] 复盘 — 单只/全部/卖出后复盘，评估 thesis_valid、写回 reviews 数组、推进下次回顾日期。买入前用 fenginvest，持有用 fengholding，卖出用 fengexit。"
when_to_use: "复盘。当用户要求复盘单只或全部持仓、评估投资论文（thesis）是否仍有效、定期回顾（月度/季度/半年）、卖出后复盘时使用。触发词：复盘、回顾、论文是否有效、定期检查、该继续持有吗"
allowed-tools:
  - Agent
  - Bash
  - Read
  - Skill
  - Write
triggers:
  - fengreview
  - 复盘
  - 回顾
  - 论文是否有效
---
# FengInvest — 复盘

> 用法：`/fengreview <TICKER>` 或 "复盘 0700.HK"（不指定标的=全部持仓逐一复盘）
> 时机：`next_review_date` 到期（daily 的 REVIEW 提醒）/ 卖出后 / 每季度例行。

## 1. 复盘范围

| 范围 | 命令 |
|:-----|:-----|
| 单只 | `python tools/fengholding.py get <TICKER>` |
| 全部 | `python tools/fengholding.py list`（逐个 get） |
| 卖出后 | 归档文件 `holdings/hold_<TICKER>_closed_<日期>.json`（get 归档 id） |

## 2. 读论文与研究报告

- 持仓 JSON：`thesis.original / exit_conditions / valuation_gap / expected_return / time_horizon_months`
- 研究目录：`research/060-companies/<TICKER>-*/<最新日期>/` 下的 `07-report.md`（A2 假设表 / A3 红线表）、`thesis.md`
- 上次复盘：`reviews[]` 数组（最近一条的 thesis_valid 与 notes）
- 上次判定：`thesis.hypotheses[].outcome`（expected/horizon/status/evidence —— 尚未判定的条目 = 本轮必判）

## 3. 生成复盘模板

```bash
python tools/fengwatch.py review <TICKER>
```

生成 `reviews/review_<TICKER>_<日期>.md` 模板（当前状态 + 退出条件状态 + 复盘笔记）。

## 4. AI 评估论文有效性

### 4.1 论文漂移检测（thesis-drift，先做）

复盘前先区分变化**性质**，防止把股价波动或报告写法变化误判为论文变化：
- **事实改变**（财报行项目/监管披露/公司公告）→ 允许更新假设状态
- **价格改变**（股价波动）→ 不改变论文，仅重估安全边际（paper 的估值锚点不动）
- **措辞改变**（报告写法变化）→ 不构成漂移，忽略
每个假设状态变化**必须引用具体新证据**（财报行项目/公告），找不到证据 → 保持原状态，不为了填表编造。

**PIT 数据时点核对（防前视偏差）**：先查 `thesis.financials_asof`（登记时依据的财报期）。若当前最新财报期已推进 ≥2 期 → 先更新数据再评估；评估只允许引用「决策时点已公开」的财报，禁止用最新财报为当时的持有辩护。

### 4.2 outcome 判定（先做：证据 → 结论）

> 预测-结果闭环：登记时每条假设已写 `outcome.expected`（可证伪预期），复盘时对照**事后事实**逐条判定，写回 `thesis.hypotheses[].outcome` 并汇总进 `reviews[].outcome_check`。

对每条 hypothesis **先做 outcome 判定**（先于 4.3 四态结论——证据在前，结论在后），四档：

| 档位 | 含义 | 判定依据 |
|:-----|:-----|:-----|
| ✅ `hit` | 命中 | 事实达到 expected 阈值（引用财报行项目/公告/价格等硬数据） |
| ❌ `falsified` | 证伪 | 事实明确未达 expected（硬数据否定，非主观感受） |
| ⚠️ `partial` | 部分兑现 | 有进展但未达阈值，或条件部分成立 |
| ⏳ `pending` | 未到期/不可判 | 未到 horizon，或数据缺失无法对照 |

- **evidence 必填具体事实**：数字+来源（如 "FY2026H1 营收 480 亿，未达 520 亿下限 ← 2026 中报"），**禁止"大概还行/差不多"**；判不了就写 `pending` 并注明缺什么数据。
- 判定结果写回 `thesis.hypotheses[].outcome.status / evaluated_date / evidence`（只改本轮涉及的条目），并把本次判定计数写入 `reviews[].outcome_check`（hypotheses_evaluated / hit / falsified / pending / outcome_score）。
- 全部判定完用 `python tools/fengwatch.py outcome <TICKER> --json` 核对写回结果。

**强制规则**：
- `falsified` 或 `partial` 累计 ≥2 → `thesis_valid` 必须降级（或设红线 `triggers.thesis_invalidation = true`）——证据层已两次未兑现，结论层不许继续"有效"
- `pending` 超过该条 `outcome.horizon` 的 2 倍 → 强制判定：补数据判 hit/falsified/partial；数据实在拿不到 → 判 `falsified` 并注明"不可验证"（不允许无限挂起）

### 4.3 假设四态检查（对照 thesis.hypotheses[] 逐条）

| 状态 | 含义 | 处理 |
|:-----|:-----|:-----|
| 🟢 `valid` | 假设成立 | 继续持有 |
| 🟡 `weakened` | 边际弱化 | 记录证据，观察 |
| 🔴 `damaged` | 受损 | 关键假设 → 降50%观察1季（交 fengexit） |
| ⚫ `broken` | 破裂 | 核心论点证伪 → 立即清仓（交 fengexit） |

### 4.4 红线检查（对照 thesis.redlines[] 逐条）

- 触发 `fatal` → `thesis_valid: false`，🔴 立即清仓（动作已预写，不现场决策）
- 触发 `severe` → 减50%重新评估，交 fengexit
- 触发 `warning` → 调查并记录
- 红线触发优先级高于"估值便宜"

### 4.5 健康度评分（10 分制，量化论文）

```
health_score = 10 − 破裂数×3 − 受损数×2 − 弱化数×1 − 红线触发数×5 − outcome.falsified数×1
```

| 分数 | 动作 |
|:----:|:-----|
| 9-10 | 加仓候选 |
| 7-8 | 持有 |
| 5-6 | 警惕，缩短复盘周期 |
| 3-4 | 减仓（交 fengexit） |
| 1-2 | 卖出（交 fengexit） |

**outcome 惩罚项说明**：`− outcome.falsified×1` 只针对「outcome 已判 falsified 但四态 status 未同步降级」的假设（证据与结论脱节）；该假设若已按 damaged/broken 扣分（4.3），不重复扣。保持 10 分制不变。

**outcome_score（证据层分数，与 health_score 并行写入 `reviews[].outcome_check`）**：

```
outcome_score = 10 − falsified×2 − partial×1   （下限 0，只度量预测兑现率）
```

- 它与 health_score 的关系：outcome_score 是**证据层**（预期兑现没有），health_score 是**结论层**（论文整体健康含四态+红线）；两者都写，同一事实不重复惩罚。
- `outcome_score ≤ 6` → 下轮复盘周期减半（如 90d → 45d）。

同时求值 `exit_conditions[]`：逐条对照当前状态（价差收敛/政策/护城河），命中 → 交 fengexit。

**数据验算**：复盘中涉及的价格/市值/估值判断必须 `python tools/financial_rigor.py verify-market-cap / verify-valuation` 验算（禁止心算）。

### 4.6 机会成本排序（portfolio-review，季度复盘必做）

> "每一块钱都应该放在回报最高的地方"（巴菲特）。每季度对**全部持仓**做一次机会成本排序：

| 排名 | 标的 | 当前占比 | 预期年化回报 | 确定性 | 预期回报×确定性 |
|:----:|:-----|:-------:|:----------:|:------:|:--------------:|

- 预期年化估算（`python tools/financial_rigor.py three-scenario`）：简化公式 ≈ FCF Yield + 预期增速；价值型用安全边际回归+增速+股息率验证
- **关键问题**：排名最后的持仓，预期回报是否高于现金（无风险利率 ~4%）？不是 → 建议卖出换现金（交 fengexit）
- **换仓门槛（卖出条件.md）**：新标的隐含年化回报须高出现有持仓 **5 个百分点以上**才换仓（"一眼胖瘦"）；**不同确定性的标的不能直接比回报点数**——低确定性的隐含回报要按胜率打折后再比
- 垫底仓位即使论文完好，机会成本分析也可触发换仓建议（理由③：更好的机会也是卖出理由）

## 5. 写回 holdings JSON（reviews 闭环）

编辑 `holdings/hold_<TICKER>.json`：

```json
"reviews": [
  { "date": "<YYYY-MM-DD>", "type": "monthly", "thesis_valid": true,
    "triggers_ok": true, "notes": "<结论>", "action": "hold",
    "health_score": 8, "hypotheses": [ {"id":"H1","status":"valid"} ],
    "outcome_check": { "hypotheses_evaluated": 2, "hit": 1, "falsified": 0,
                       "partial": 0, "pending": 1, "outcome_score": 8 } }
]
```

- `type`: buy|monthly|quarterly|exit|ad_hoc；`action`: hold|add|reduce|exit
- 同步更新 `thesis.hypotheses[].outcome`（4.2 判定的 status/evaluated_date/evidence）、`thesis.hypotheses[].status`（四态）、`thesis.redlines[]`（触发记录）、`health_score`（4.5 公式）、`reviews[].outcome_check`（4.2 汇总）
- `thesis_valid: false` → 同步设 `triggers.thesis_invalidation = true`

## 6. 推进下次回顾日期

```json
"triggers": { "next_review_date": "<当前日期+90天>" }
```

- 保持 `price_up_alert/price_down_alert/stop_loss_pct` 不动（除非复盘发现需要调整）
- 更新 `meta.updated_at`

## 7. 记录决策日志

```bash
# 追加一条 journal 记录（或由 fengwatch 复盘动作生成）
python tools/fengwatch.py log --limit 5   # 查看最近日志
```

## 完成后

向用户汇报：outcome 判定结果（逐假设 hit/falsified/partial/pending 与证据）、论文是否有效（逐假设）、exit_conditions 求值结果、action 结论（hold/add/reduce/exit）、下次回顾日期。
