---
name: fengexit
description: "[FengInvest] 卖出决策与执行 — 触发源识别/理由分类/卖出前检查/滚存执行/清仓归档。持有期用 fengholding，复盘用 fengreview。"
when_to_use: "卖出决策。当用户要求卖出/清仓/减仓某只持仓、评估是否该卖、执行钱仓滚存回收本金、或出现止损/止盈信号时使用。触发词：卖出、清仓、减仓、滚存、止盈、止损、割肉、该不该卖"
allowed-tools:
  - Agent
  - Bash
  - Read
  - Skill
  - Write
triggers:
  - fengexit
  - 卖出
  - 清仓
  - 减仓
  - 滚存
  - 止盈
  - 止损
---
# FengInvest — 卖出决策与执行

> 用法：`/fengexit <TICKER>` 或 "卖出 0700.HK" / "滚存回收本金"
> 前置：持有期状态用 `/fengholding` 查；卖出后复盘交 `/fengreview`。

## 1. 触发源识别（为什么现在卖？）

| 触发源 | 证据 |
|:-------|:-----|
| daily 警报 | `python tools/fengwatch.py daily` 出现 RED/YELLOW |
| 价格异动 | 单日 >5% 异动（08-exit.md 定期重审） |
| 论文失效 | `triggers.thesis_invalidation=true` 或复盘判定假设动摇 |
| 纪律检查 | 组合集中度超限（check 🔴/🟡）→ **只约束买入、不加仓，不是卖出理由**（见拦截原则） |
| 换仓机会 | 机会成本比较：新标的风险调整后收益显著更优 |

先跑 `python tools/fengholding.py get <TICKER>` + `python tools/fengwatch.py check <TICKER>` 拿当前状态。

## 2. 理由分类（docs/08-exit.md 六类）

| 类型 | 触发 | 动作 |
|:-----|:-----|:-----|
| 价格止损(硬) | 买入后跌 >20% | 强制退出 |
| 基本面止损 | FCF 由正转负/营收连续降/ROE<10% | 退出或降50% |
| 时间止损 | 持有≥6个月论文未兑现（check 的 time_stop 提醒） | 重新评估，不通过则退出 |
| 估值回归 | thesis 价差未在期限内兑现（valuation_regression 提醒） | 审视减仓 |
| 估值泡沫 | 市值/FCF>50x | 清仓80%+ |
| 论文失效 | 🔴核心论点推翻 / 🟡关键假设动摇 / 🟢时间框架超出 | 清仓 / 降50%观察1季 / 重评估 |

理由必须落到 `--reason`，写清是哪一类 + 证据。

**卖出拦截原则（强制，2026-08-16 起）：**
- 六类理由**均未触发** → **默认不执行卖出**，只给评估结论。用户仍要求卖 → 先明确告知"无纪律依据"，并要求用户**二次确认**（确认后方可执行，`--reason` 标注"无纪律依据-用户二次确认"）。
- 组合超限（🔴/🟡）**不是**卖出理由：默认动作是约束买入（预算自动卡死），等市场变化自然缓解；只有论文失效类依据才能触发降仓。
- 例外：滚存回收本金（第 4 节，浮盈 ≥30%）是第四类合法卖出，不需六类理由。
- 提供选项时默认推荐"不卖/重新评估"，不把清仓列为可选项；确需列出时标注"无纪律依据"。

## 3. 卖出前检查（先查自己，再查市场）

> **卖出艺术挂链（2026-09-30）**：优雅卖出三类型（基本面变了/价格太贵/更好的机会）、2B 法则卖出触发器、移动止盈保护、买分歧卖抱团语气校正 → `knowledge/discipline/奇衡卖出艺术.md` + `knowledge/奇衡思想总纲.md` §5。TRADING 账户另有移动止盈保护规则（fengwatch `check_trailing_profit_guard`：浮盈>15% 保护线成本+5%，每+10% 上移 5%）。INVESTMENT 账户仍以论文止损为最高优先级。

- **偏误自查**：处置效应（"回本就卖"）？锚定（"等回到成本价"）？沉没成本（"都亏这么多了"）？—— 任一命中 → 停手重审
- **取舍原则**：这笔钱放着 vs 换成现金/其他标的，3 年内哪个更优？（机会成本）
- **确认执行价**：用实时价核对（`fengdata.py <T> --mode price`），不要拍脑袋挂价

## 4. 滚存卖出执行（部分卖出，持仓保留）

适用：浮盈 ≥30%（daily 的 OPPORTUNITY 建议），回收本金留零成本筹码。

```bash
# 先算卖出股数：回收额 = 本金，ceil 取整（与 Web 计算器一致）
python tools/fengwatch.py sell <TICKER> --price <实时价> --shares <股数> --reason "滚存回收本金: 浮盈X%"
```

- 部分卖出（股数 < 持仓股数）自动：更新余仓 shares、`capital.realized_pl`、`capital_rollover.recovered/zero_cost_shares/phase`（足额回收→`capital_recovered`）
- **回笼资金自动入池**（sell 内建）：CN_IN 持仓 → `cash_cny`（按实时汇率折 CNY）；OVERSEAS → `cash_<币种>`（原币）；找不到对应现金持仓则提示人工登记（`fengholding add`）
- 卖出后验证：`python tools/fengholding.py get <TICKER>` 看 `capital_rollover.phase` 与余仓

## 5. 普通卖出执行（清仓归档）

```bash
python tools/fengwatch.py sell <TICKER> --price <实时价> --shares <全部股数> --reason "<六类理由: 证据>"
```

- 清仓自动：追加 sell 交易、`capital.realized_pl` 累计、`lifecycle_phase=closed`、归档为 `hold_<TICKER>_closed_<日期>.json`；回笼资金同样自动入池（规则同第 4 节滚存）
- 验证归档：`python tools/fengwatch.py history` 看胜率/盈亏更新

## 6. 交 fengreview 复盘

卖出完成 → `/fengreview <TICKER>`（无论盈亏都复盘，沉淀"学到了什么"）。

## 完成后

向用户汇报：卖出理由分类、执行结果（股数/价格/已实现盈亏/余仓或归档）、滚存阶段变化。
