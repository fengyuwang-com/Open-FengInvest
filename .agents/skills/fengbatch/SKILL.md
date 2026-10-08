---
name: fengbatch
description: "[FengInvest] 批量自动选股流水线 — 公开 list → 规则粗筛 → 规则精筛 → 幸存者名单 → AI 逐只七层分析 → 汇总报告。深挖单只走 /fenginvest。"
when_to_use: "批量选股。当用户要求从公开指数/ETF 成分或自定义名单里批量筛股时使用。触发词：批量选股、自动筛股、跑一批、流水线、从中证红利/纳指100/SCHD 里筛"
allowed-tools:
  - Agent
  - Bash
  - Read
  - Skill
  - Write
triggers:
  - fengbatch
  - 批量选股
  - 自动筛股
  - 跑一批
  - 流水线
---
# FengInvest — 批量自动选股流水线（fengbatch）

> 定位：自动选股流水线——**程序做苦力（0 token），AI 做判断**。
> 公开 list → 规则粗筛（fengscreen 四维排名）→ 规则精筛（7 硬指标 + 3 豁免）
> → 幸存者名单 → AI 逐只 /fenginvest 七层分析 → 汇总报告。
> 深挖单只走 `/fenginvest`；本 skill 只管批量。

## 用法

```
/fengbatch <list名>          # 内置 list: cn_dividend(中证红利) / us_quality(纳指100) / us_dividend(SCHD)
/fengbatch --file xxx.txt    # 自定义名单（一行一个代码）
/fengbatch 全市场            # 先问用户市场与数量，再走 --file 或与用户确认候选池
```

程序入口：`python tools/fengbatch.py plan --list-name <L> [--file f.txt] [--top 50]`
（批次名自动为 `<list名>-<YYYYMMDD>`，落盘 `research/070-reports/batch/<批次名>/`）

## 工作流

### Step 0 读需求
确认：候选池（内置 list / 文件 / 全市场）、粗筛取前几名（默认 50）。用户没说就用默认。

### Step 1 跑 plan（0 token）
```bash
python tools/fengbatch.py plan --list-name cn_dividend --top 50
```
- 纯本地零 LLM，可能要几分钟（逐只取数）。
- list 接口拉不到 → 程序会报错并给出手动放文件的说明（以 `data/config/batch_lists.json` 为准，内含每个 list 的 manual_hint），如实告知用户，不要死磕重试超过 2 次。
- plan 幂等：重跑同批次覆盖，结果一致。

### Step 2 给用户看幸存者名单，等确认（必须停）
展示摘要表（代码/名字/排名/硬指标结果），并说明：
- 幸存者 N 只 × 每只七层分析约 M 千 token（经验值，说明是估算）
- ⚠️ 金融股（银行/保险/券商）毛利率口径失真，精筛可能误判，需在七层分析时人工复核
等用户确认后才进 Step 3。**未经确认不批量启动分析。**

### Step 3 逐只七层分析（AI 亲自执行）
- 对每只幸存者执行 `/fenginvest <TICKER>`（读 .agents/skills/fenginvest/SKILL.md 工作流）。
- 每只幸存者跑完 /fenginvest 后必须接 /fengcheck（AUDIT 落盘 PASS/CONDITIONAL 才算完）。
- **派后台子 Agent 并行，最多同时 3 只**，跑完一只收一只再补位。
- 随时可用 `python tools/fengbatch.py status <批次名>` 查进度（断点续跑：状态机保证单只不重头）。

### Step 4 汇总报告
```bash
python tools/fengbatch.py summary <批次名>
```
- 生成 `research/070-reports/batch/<批次名>/SUMMARY.md`（读每只的 06-collision 产物，按置信度排序）。
- 向用户汇报：已分析/待分析、各只决策与置信度、一句话结论。

## 边界（红线）

- **不碰持仓**：登记/管理持仓走 `/fengholding`，本 skill 只产出候选名单。
- **不做投机轨道**：右侧/事件驱动短打走 `/fengspec`。
- **不做单只深挖入口**：用户只想分析一只时直接 `/fenginvest`。
- 幸存者 ≠ 买入建议：通过筛选只是去劣，最终决策在七层碰撞后。

## 数据降级（程序已内置）

| 情况 | 行为 |
|:-----|:-----|
| list 接口拉取失败 | 报错 + 手动放文件说明（`data/config/batch_lists.json` 里每个 list 的 manual_hint） |
| akshare 未安装 | 提示 `pip install akshare -i https://pypi.tuna.tsinghua.edu.cn/simple`（不要自动装） |
| 个股数据拿不到 | 标 SKIP 不算 FAIL（宁可漏网不可误杀） |
| 某条指标数据不足 | 该指标 N/A 不判负 |
