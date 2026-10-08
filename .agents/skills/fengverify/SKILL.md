---
name: fengverify
description: "[FengInvest] 论断验证 — 用户喊一句人话（验证论断/复测/回测某个论断/第N号论断能不能信），技能自动跑复测引擎（python tools/fengverify.py <claim_id>）并产出一张 0 代码的【白话论断卡】+ 12 项协议红绿灯。程序负责算数、技能负责说人话。"
when_to_use: "验证回测论断。当用户要求验证/复测某个投资论断、回测某个论断、问'第N号论断能不能信''这个说法靠不靠谱'、或需要对已有白话卡/复测产物做诚实复核时使用。触发词：验证论断、复测、回测某个论断、第N号论断能不能信、论断能信吗、白话论断卡、复测一下。注意：买入分析走 /fenginvest、持仓走 /fengholding、复盘走 /fengreview——本技能只管'论断的回测验证'。"
allowed-tools:
  - Agent
  - Bash
  - Read
  - Skill
  - Write
triggers:
  - fengverify
  - 验证论断
  - 复测
  - 回测论断
  - 论断能不能信
  - 白话论断卡
---

# FengInvest — 论断验证（fengverify）

> 用法：`/fengverify <论断编号或一句话>`。目的：**用户不懂回测代码，只需喊一句人话**（如"#1 能不能信""复测一下年线论断""回测 000-52-claims 里第 7 条"）——**程序负责算数（引擎跑回测、出机器数字），本技能负责说人话（把 results.json 翻译成一张 0 代码的白话论断卡）**。绝不让用户去读 bootstrap / backtest_core / 均线窗口。
> 论断原文清单：`research/110-strategy-verification/000-52-claims.md`；本技能是 52 条论断的复测/复核统一入口。

## 一、触发判定（何时该用本技能）

| 用户说… | 该不该用 | 干什么 |
|:--------|:--------:|:------|
| "验证论断 X / 复测一下 / 回测某个论断 / 第N号论断能不能信" | ✅ 用 | 跑引擎 → 出白话论断卡 |
| "这个说法（统计/回测类）靠不靠谱" | ✅ 用 | 先照 000-claims-def.md 确认对应哪个论断编号，再走全流程 |
| "已有白话卡/复测产物，帮我核一下结论诚不诚实" | ✅ 用 | 走"已有结果复核"分支（见执行步骤 1），不重跑引擎 |
| 买入某只股票、七层分析、持仓检查、复盘论文 | ❌ 别用 | 分别走 /fenginvest、/fengholding、/fengreview |

一句话判定：**凡是"论断/回测结论能不能信"都归本技能；凡是个股买卖 / 持仓生命周期都不归。**

## 二、执行步骤（给 AI 角色看，不是给用户）

### 1. 先分清任务类型：已有结果复核 vs 重新复测

先看该论断目录（如 `001-above-annual-line/`）里有没有现成产物：
- **已有结果复核**（有 `README-白话卡.md` / `RETEST-*/README.md` / `results.json`）：任务是**核对**——白话卡数字是否与 results.json 逐位一致？协议红绿灯是否按 000-PROTOCOL 12 项诚实？结论是否与 results.json 的 `verdict` 一致？（#4 教训：README 标 ✅ 而 results.json 是 `claim_supported=false` 类冲突必须抓出来，以 results.json 与协议清单为准。）**不重跑引擎**，除非数字陈旧/无法溯源。
- **重新复测**（无产物 / 用户明确要重跑 / 旧结论受质疑需按新口径重判 / 论断刚在 000-claims-def.md 登记完）：进入第 3 步跑引擎。

### 2. 查论断是否登记

打开 `research/110-strategy-verification/000-claims-def.md`，按 id 或按 statement 关键词查找：
- **已登记**：记下 `folder` / `data_scope` / `signal_def` / `holding_days` / `verdict_metric`（主判据！）/ `cost_bps` / `oos`。继续第 3 步。
- **未登记**：告诉用户"该论断还没在 000-claims-def.md 登记"，把登记格式贴给他（见下方【四、论断登记格式】），用户确认登记完成后再跑引擎。定义即契约：改定义 = 改版本，须留档。

### 3. 跑引擎（主入口）

```bash
# 主入口（稳定、推荐）：读 000-claims-def.md 的论断定义 → 跑回测 → 出 results.json
python tools/fengverify.py <claim_id> [--out <claim_dir>/RETEST-<YYYY-MM-DD>]
```

- 可选入口（若已接线）：`python tools/fengbacktest.py verify --claim <N>`——由另一条线接线中，未就绪就以 fengverify.py 为准，不强行依赖。
- 输出：`<out>/results.json`（机器可读全量结果：per-market + 汇总 + 样本外 + protocol_lights + verdict）。
- 引擎失败 → **修依赖，不手工填数**：查 pyyaml/numpy 是否安装、`data/market_data.db` 是否存在、claims-def 的 YAML 是否解析、id 是否存在。任何"依赖坏了/数据缺席"都不准拿记忆或人工猜数顶替。

### 4. 读 results.json 填模板

严格照抄 `000-FORMAT-SAMPLE-白话卡.md` 的结构（7 节：红绿灯结论 / 论断原文 / 我们怎么测的 / 关键数字 / 是否可采信 / 证据链 / 下一步）。数字来源字段对照：
- 汇总关键数字 ← `aggregate.*` 与 `aggregate_oos.*`（above/below 均值、胜率、中位、样本量）
- 判据裁决 ← `verdict.*`（diff_net_pooled_pp / p / CI95 / supported_at_95 / oos_same_direction）
- 分市场细节 ← `per_market.*`
- 协议红绿灯 ← `protocol_lights`
白话卡里每个数字都要能在 results.json 对应字段定位；定位不到就如实标"未提供/未做"，**不许编**。

### 5. 按 000-PROTOCOL 12 项逐条打勾

按 `000-PROTOCOL.md` 第 2 节 12 项逐条打 ✅/⚠️/❌ 或"未做"：判据对齐 / 复权 / 前视时序 / 交易成本 / 退市股+成分股生效日 / 基准口径 / 效果量超噪音地板 / 显著性检验 / 样本外 / 幸存者审计 / 方法对标文献 / A股制度（仅涉 A 股时）。引擎已输出 `protocol_lights` 的先取机器值，缺项按协议口径人工补勾并在落款**签名 + 日期**。**任一非 ✅ → 结论只能标 ❓ 待复测 / 🟡 有条件，不许标 ✅**（000-PROTOCOL 使用规则 2）。

### 6. 产物落盘

- 全新复测 → `<claim_dir>/RETEST-<YYYY-MM-DD>/README.md`（白话卡，参照 #1 复测版：`001-above-annual-line/RETEST-2026-08-20/README.md`）或 `<claim_dir>/README-白话卡.md`。
- 复核已有产物 → 就地更新对应 README/白话卡，并把本次修正写成 `<claim_dir>/.../audit-notes.md`（对照旧实现：改了什么、为什么、数据工程对账）。
- 落盘全部在 `research/110-strategy-verification/` 下（入库区，随 git 同步；本地例外仅 060-companies/state/speculative/opensource-eval），不写本地路径。

### 7. 更新结论总览

把结果写回 `000-CONCLUSIONS.md` 对应论断行（初标 / 复核 / 一句话依据）。**若该行已由其它流程更新过（如 2026-08-20 六条复核已更新 #1/#4/#7/#33/#40/#42），则跳过、不强改。**

## 三、铁律（先读，违反任一 → 本轮不算完成）

1. **判据必须与论断承诺的量一致**（#1 判据错位教训）：论断说"收益"就只按"平均收益"裁决，中位收益辅助，胜率仅参考；用错判据得出的结论一律作废，不得写进白话卡。
2. **数字只来自 results.json，不编造**：无来源 = 不存在。每个数字都能在 results.json 定位到对应字段；定位不到就如实标"未做/未提供"。
3. **红绿灯诚实**：协议 12 项有一项 ❌ 或 ⚠️ 就不能标 ✅；#1 复测把旧"✅ 7/7 市场支持"推翻为"❌ 不成立"并如实宣告——**复测推翻旧结论是正面案例，不是事故**，照实写进白话卡与 000-CONCLUSIONS.md。
4. **产物只在 `research/110-strategy-verification/`（入库区，随 git 同步）**：不写本地路径、不把该路径引用进公开文档。
5. **Windows 编码**：读写含中文文件一律显式 `encoding="utf-8"`（默认 GBK 会乱码）。
6. **绝不经手状态机**：fengverify 与 `fengstate` 八层框架无关，不 init / complete / renew 任何 `temp_state_*.json`；论断验证结论只写回 000-CONCLUSIONS.md 与白话卡。

## 四、论断登记格式（未登记时提示用户）

```yaml
claims:
  - id: <N>
    folder: <NNN-xxx-xxx>
    title: <一句话标题>
    statement: <论断原文，可证伪>
    h0: <零假设>
    data_scope:
      markets: [...]
      category: stock
      survivorship: <股票池是否含退市股说明>
    signal_def:
      key: <信号定义，如 close > MA200>
      lookahead: <防前视说明>
    holding_days: [20, 60, 120]
    verdict_metric:
      primary: 平均收益（扣成本后）
      secondary: 中位收益
      reference_only: 胜率
    price_basis: 前复权 close
    cost_bps: 25
    oos: 每标的自有交易日后 20% 单独跑同口径
    protocol_refs: [...]
```

## 五、输出示例（#1 复测版白话卡头部，粘自真实产物）

```markdown
# 白话论断卡 · 复测版 — 论断 #1「年线之上」(RETEST 2026-08-20)
...
## 1) 红绿灯结论
> **❌ 不成立（按论断承诺的"收益"判据）**
一句话理由：**用真正的"收益"当裁判，年线上方买入不仅没有更赚，平均收益反而更低——20 日显著更低（19 市场汇总差 −0.98 个百分点，95% 置信区间整个在 0 以下），60/120 日也是负差。胜率确实在年线上方略高（+0.3~+3.4 个百分点），但那不是收益优势，是下方段偶尔冒出的大反弹把"平均值"拉上去了。**——所以当年"✅ 7/7 市场支持"不可信，重测后是 ❌。
```

**技能产物长这样**：全卡 0 代码，5 秒扫结论、30 秒看懂方法、要抠细节再点证据链；完整版见 `001-above-annual-line/RETEST-2026-08-20/README.md`。

## 六、关联技能（在哪用）

| 技能 | 角色（一行） |
|:-----|:------------|
| `/fengverify`（本技能） | 验证/复测"论断能不能信"，出白话论断卡 |
| `/fenginvest` | 买入前七层分析——论断框架是它各层判据的证据源，验证结论供其引用 |
| `/fengholding` | 持有期管理——已验证可采信的论断可作持有/监控/滚存依据；持仓登记归它 |
| `/fengreview` | 复盘——论文是否仍有效可引用已验证论断作底牌，本技能提供"可采信"判定 |

## 完成后

- 汇报（给用户 0 代码结论）：论断编号 + 红绿灯结论（✅ 可采信 / 🟡 有条件 / ❌ 不成立 / ❓ 待复测）+ 主判据一句话理由 + 协议 12 项里任何非 ✅ 项 + ≤3 条下一步。
- 开源登记：提到开源项目即登记 data/config/opensource_list.json（提到=入表）。
- 隐私红线：白话卡/审计/结论总览改动都在入库区，随 git 同步；不写 060/state/speculative 等本地路径。
