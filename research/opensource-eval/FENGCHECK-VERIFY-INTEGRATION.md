# FENGCHECK-VERIFY-INTEGRATION — 快败模式集成说明

> 日期：2026-09-03
> 来源：借鉴 QuantMind `verify.sh` 五步快败验证模式
> 变更范围：`tools/fengverify_gate.py`（新建）+ `.agents/skills/fengcheck/SKILL.md`（增强）

---

## 借鉴了什么

### QuantMind verify.sh 的设计

QuantMind 的 `verify.sh` 是一个 42 行的 bash 脚本，核心设计：

1. **`set -euo pipefail`** — 任何命令失败立即退出，不继续执行
2. **五步顺序执行**：ruff format → ruff check → basedpyright → lint-imports → pytest
3. **确定性** — 不依赖网络、不依赖 AI，纯工具检查
4. **CI + git hooks 三层执行** — pre-commit（格式/lint）+ pre-push（verify.sh 全量）+ CI（CI 再跑一遍）

### FengInvest 原有审计流程

原 fengcheck 是"全跑完再汇总"模式：7 步工具检查全部执行，然后 AI 逐层审查，最后综合判定。问题是：
- 状态机不完整时，后续的报告检查毫无意义
- 文档缺失时，来源标注检查是浪费
- 每次都要跑完全部步骤才能发现问题

---

## 变更内容

### 1. 新建 `tools/fengverify_gate.py`

五步快败闸门脚本，借鉴 QuantMind 的 `set -euo pipefail` 理念：

| 门 | 检查内容 | 对应 QuantMind 步骤 | 失败行为 |
|----|---------|-------------------|---------|
| Gate 1: state | `fengstate.py verify` — 状态机完整性 | pytest（基础完整性） | HALT |
| Gate 2: structure | `fengdoclint.py --strict` — 文档结构合规 | ruff format（结构规范） | HALT |
| Gate 3: report | `report_audit.py` check+sources+csvdetect — 报告质量 | ruff check（内容规范） | HALT |
| Gate 4: pipeline | `fengstate.py accept` 逐层验收 — 管线完整性 | basedpyright（类型完整） | HALT |
| Gate 5: consistency | 跨文件一致性 — 声明 vs 实际 | lint-imports（架构边界） | WARN |

**特性**：
- `--json` 输出结构化 JSON（供 AI 消费）
- `--gate N` 只跑第 N 门（调试用）
- `--consistency-only` 只跑跨文件一致性（项目级，不需 TICKER）
- 退出码：0=全过，1=某门失败，2=用法错误
- Gate 5 只警告不阻断（一致性问题是项目级，不是分析质量级）

### 2. 增强 `.agents/skills/fengcheck/SKILL.md`

**结构变化**：

```
原流程：1.定位 → 2.读清单 → 3.跑工具(7项全跑) → 4.AI审查 → 5.判定 → 6.报告 → 7.汇报
新流程：0.快败闸门(5门) → 1.定位 → 2.读清单 → 3.跑工具(降级fallback) → 4.AI审查 → 5.判定 → 6.报告 → 7.汇报
```

**关键改动**：
- **新增 Step 0**：五步快败闸门（确定性，无 AI 参与）
- **Step 3 标注为降级 fallback**：闸门已覆盖的内容不再重复跑
- **新增 3h**：跨文件一致性检查（闸门 Gate 5 补充）
- **Step 5 判定逻辑更新**：闸门结果优先于工具检查结果
- **Step 6 报告格式更新**：新增"快败闸门结果"表格

### 3. 跨文件一致性检查（Gate 5 + 3h）

这是 FengInvest 独有的增强（QuantMind 的 lint-imports 检查 Python import 边界，我们检查项目配置一致性）：

1. AGENTS.md 引用的工具 .py 文件是否都存在于 `tools/`
2. AGENTS.md 声明的 skill 目录是否都存在于 `.agents/skills/`
3. 核心 skill 引用的工具是否存在
4. 配置文件（`research_list.json`、`基准参考.md`）是否存在

---

## 未做的（有意不做的）

1. **Python lint/type check** — FengInvest 没有配置 ruff/basedpyright，且 62 个工具脚本的 lint 基线太高。暂不引入，等项目 lint 基线建立后再加。
2. **pre-commit hooks** — QuantMind 用 pre-commit 跑 verify.sh，FengInvest 的 .zcode hooks 只保护状态文件。pre-commit 是 git 层面的，fengcheck 是 skill 层面的，不冲突但暂不引入。
3. **pytest** — FengInvest 的测试不是 pytest 驱动的（没有统一测试套件），所以没有对应 Gate。

---

## 文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `tools/fengverify_gate.py` | 新建 | 五步快败闸门脚本 |
| `.agents/skills/fengcheck/SKILL.md` | 增强 | 快败模式集成 + 跨文件一致性 |
| `research/opensource-eval/FENGCHECK-VERIFY-INTEGRATION.md` | 新建 | 本变更说明 |
