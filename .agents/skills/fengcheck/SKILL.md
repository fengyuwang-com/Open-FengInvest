---
name: fengcheck
description: "[FengInvest] 审计自检 — 对照基准参考清单验证已完成的七层分析，跑审计工具，出合规报告。每次 fenginvest 完成后必须运行。"
when_to_use: "fenginvest 后必跑（2026-09-09 创始人立规），用户单独要求也可跑。触发词：审计、自检、检查质量、合规检查、过一遍清单、fengcheck"
allowed-tools:
  - Agent
  - Bash
  - Read
  - Write
  - Glob
triggers:
  - fengcheck
  - 审计
  - 自检
  - 合规检查
  - 质量检查
---

# fengcheck — 七层分析审计自检（快败增强版）

> 每次 fenginvest 完成后运行此 skill，对照 `knowledge/基准参考.md` 逐项验证，跑已有审计工具，出合规报告。
> 用法：`/fengcheck <TICKER>`
>
> **快败模式**（借鉴 QuantMind verify.sh）：确定性门按顺序执行，任一门失败立即停止，不跑后续步骤。
> 设计哲学：前一步不过，后一步不跑——省时间、省 token、早暴露问题。

## 变量约定

```
TICKER: 目标代码（如 002032.SZ）
ROOT:   项目根目录（本仓库根）
BASE:   research/060-companies/<TICKER>-<中文名>/<YYYY-MM-DD>/
```

---

## 0. 五步快败闸门（确定性，无 AI 参与）

> 运行 `tools/fengverify_gate.py`，五个门按顺序执行，任一失败立即停止。
> 这是借鉴 QuantMind `verify.sh` 的核心增强——确定性检查先行，AI 审查在后。

### 0a. 运行全部五门（快败模式）

```bash
cd ROOT
python tools/fengverify_gate.py <TICKER> --json
```

**五门顺序**：

| 门 | 检查内容 | 失败行为 |
|----|---------|---------|
| 1. state | `fengstate.py verify` — 状态机完整性 + 跨层一致性 | **HALT** — 状态机不完整，后续检查无意义 |
| 2. structure | `fengdoclint.py --strict` — 文档结构合规（双格式 + 总览） | **HALT** — 文档缺失，报告检查无意义 |
| 3. report | `report_audit.py` check + sources + csvdetect — 报告质量三连 | **HALT** — 报告不合格，逐层审查无意义 |
| 4. pipeline | `fengstate.py accept` 逐层验收 — 管线完整性 | **HALT** — 层未验收，内容审查无意义 |
| 5. consistency | 跨文件一致性 — AGENTS.md/skills/configs vs 实际文件 | **WARN**（不 HALT，但记录问题） |

### 0b. 快败结果处理

- **全部通过** → 继续 step 1（AI 内容审查）
- **任一门失败** → 输出失败详情，**跳过后续所有步骤**，直接进入 step 6（综合判定），判定为 **FAIL**
- **只有 Gate 5 (consistency) 失败** → 记录问题但不阻止后续步骤（一致性问题是项目级警告，不是分析质量问题）

### 0c. 单独运行跨文件一致性（不需 TICKER）

```bash
python tools/fengverify_gate.py --consistency-only
```

检查项：
1. AGENTS.md 中引用的工具 .py 文件是否都实际存在于 `tools/`
2. AGENTS.md 中声明的 skill 目录是否都实际存在于 `.agents/skills/`
3. AGENTS.md 中引用的配置文件（`research_list.json`、`基准参考.md`）是否存在
4. 核心 skill（fenginvest/fengholding/fengexit/fengreview/fengcheck）引用的工具是否都存在

---

## 1. 定位分析目录

```bash
# 找到该 ticker 最新的分析目录
ls -d research/060-companies/<TICKER>-*/*/ | sort -r | head -1
```

- 如果没有找到目录 → 告知用户"未找到该标的的分析目录"并终止
- 如果找到 → 确认 `00-INDEX.md` 存在（不存在则终止，说明分析未完成）

记录 `BASE` 路径供后续步骤使用。

---

## 2. 读取基准参考清单

读取 `knowledge/基准参考.md`，加载所有检查项（L0-1 到 X-5，共 42 项：内容 37 + 跨层 5）。

---

## 3. 跑已有审计工具（自动化）

> **注意**：如果 step 0 的快败闸门已通过，本步骤中的 3a-3f 与闸门检查重叠。
> 此处保留为**降级 fallback**——当直接调用 fengcheck 而非经过闸门时仍可独立运行。
> 推荐做法：始终先跑 step 0，通过后再跑本步骤的 3g（闸门未覆盖的额外检查）。

按顺序执行以下工具，记录每项结果：

### 3a. 文档结构合规

```bash
cd ROOT
python tools/fengdoclint.py $BASE --strict
```

记录：通过/失败 + 具体问题

### 3b. 状态机全量验证

```bash
python tools/fengstate.py verify <TICKER>
```

记录：通过/失败 + 跨层一致性警告

### 3c. 逐层验收

```bash
for layer in 01-capability 02-market 03-discipline 04-quantitative 05-qualitative 06-collision 07-report 08-portfolio; do
  python tools/fengstate.py accept <TICKER> $layer
done
```

记录：逐层通过/失败

### 3d. 报告结构校验

```bash
python tools/report_audit.py check --report $BASE/07-report.md
```

记录：missing_sections / missing_key_fields / min_items_failures

### 3e. 报告来源标注

```bash
python tools/report_audit.py sources --report $BASE/07-report.md
```

记录：unsourced_count / section_unsourced

> 对应基准 M-5：另对 `$BASE/02-market.md` 跑一遍（该文件非标准报告结构，工具结果仅供参考，M-5 最终以人工核验为准）：
>
> ```bash
> python tools/report_audit.py sources --report $BASE/02-market.md
> ```

### 3f. CSV 乱入检测

```bash
python tools/report_audit.py csvdetect --report $BASE/07-report.md
```

记录：issue_count / issues

### 3g. PE 交叉验证（可选，N/A 属环境限制）

```bash
python tools/fengquality.py --cross-check <TICKER> --file $BASE/02-market.json
```

记录：status（PASS/WARNING/FAIL/NOT_AVAILABLE）

> 注：N/A 属环境限制（美股也可能 403/反爬），本地 pe_ttm + 报告 rigor 验算可作为替代证据。

### 3h. 跨文件一致性检查（闸门 Gate 5 补充）

```bash
python tools/fengverify_gate.py --consistency-only
```

记录：AGENTS.md 声明 vs 实际文件的差异（如有）

---

## 4. 逐层内容审查（AI 读文件）

对每层的 JSON/MD 文件，对照基准参考清单逐项打 ✅/❌：

### L0 能力圈
- 读 `01-capability.md`
- [L0-1] 三个灵魂拷问是否逐一充分回答（每问有独立段落，不是一句话跳过）
- [L0-2] DK 坐标原则五维度是否逐条覆盖（对标/价差/坐标类型/稳定性/兑现路径）
- [L0-3] judgement 是否明确（IN/OUT/UNCERTAIN 三选一 + 理由）

### M 市场层
- 读 `02-market.json` + `02-market.md`
- [M-1] 四灯齐全（宏观/估值/趋势/情绪），每灯有来源 URL
- [M-2] pe_ttm 字段存在（工具已验证）
- [M-3] DK 家国原则五维度逐条覆盖（政策方向/级别/时间/对冲/国际关系）
- [M-4] 均线数据 >= 250 交易日
- [M-5] 关键数字有来源标注

### L1 纪律层
- 读 `03-discipline.json` + `03-discipline.md`
- [L1-1] 8 条规则齐全（2638/年线/均线/真价值/后发/情绪/双账户/风控）
- [L1-2] overall_light 明确
- [L1-3] DK 纪律 4 条逐条覆盖
- [L1-4] 快速否决路径已检查
- [L1-5] 深度价值路径已检查

### L2b 量化层
- 读 `04-quantitative.json` + `04-quantitative.md`
- [L2b-1] 因子数量 >= 4
- [L2b-2] 每因子有 signal 字段（BULL/NEUTRAL/BEAR）
- [L2b-3] abstained 字段存在（A 股 FCF/ROIC 可 abstain，小写键名）
- [L2b-4] consensus 段落存在

### L2a 定性层
- 读 `05-qualitative.md` + `05-qualitative_lights.json`
- [L2a-1] 六灯字段齐全
- [L2a-2] 四大师各有独立段落
- [L2a-3] team_verdict 段落存在
- [L2a-4] 会计质量段落存在
- [L2a-5] 六步法段落存在

### L3 碰撞层
- 读 `06-collision.json` + `06-collision.md`
- [L3-1] decision 字段存在
- [L3-2] adversarial 段落存在（对抗性四问）
- [L3-3] bias_check 段落存在
- [L3-4] dk_rules 字段存在
- [L3-5] `sources/fengcollision_raw.json` 存在

### L4 报告层
- 读 `07-report.md` + `07-narrative.md`
- [L4-1] 报告结构 10+ 章节（工具已验证）
- [L4-2] 首行格式匹配 `BUY/HOLD/WAIT/PASS @ xx%`
- [L4-3] extract 抽检清单已人工填数并跑 verdict 通过（extract 只产抽检清单，不承诺全自动——fetched_value 必须人工填数）
- [L4-4] 来源标注覆盖（工具已验证）
- [L4-5] `07-narrative.md` 存在
- [L4-6] CSV 乱入通过（工具已验证）

### P 组合层
- 读 `08-portfolio.json` + `08-portfolio.md`
- [P-1] dashboard 三轴字段齐全
- [P-2] budget 段落存在
- [P-3] stress_test 段落存在
- [P-4] correlation 段落存在

### X 跨层维度
- [X-1] `00-INDEX.md` 存在且含"层间关系"和"核心数据速查"（工具：fengdoclint 自动检查）
- [X-2] 双格式规范（JSON 层必须有同名 .md 配对，工具：fengdoclint 自动检查）
- [X-3] `fengdoclint.py --strict` 通过（工具已验证）
- [X-4] `fengstate.py verify` 全量通过（工具已验证）
- [X-5] `fengstate.py accept` 逐层通过（工具已验证）

---

## 5. 综合判定

| 结果 | 条件 |
|------|------|
| **PASS** | 快败闸门全部通过 + 所有工具通过 + 所有清单项 ✅ |
| **CONDITIONAL PASS** | 快败闸门通过，但有非致命 FAIL 项（列出待修项，可交付） |
| **FAIL** | 快败闸门失败 **或** 有致命缺失（必须修复后重跑对应层） |

### 快败闸门结果优先

- 如果 step 0 的 `fengverify_gate.py` 任一门失败 → 直接判定 **FAIL**，不再跑 step 1-4
- 如果只有 Gate 5 (consistency) 失败 → 判定 **CONDITIONAL PASS**（一致性问题是项目级警告）
- 如果全部通过 → 继续 step 1-4 的详细审查

### 致命缺失定义

- 任意一层 JSON 文件缺失或空壳
- `fengstate.py verify` 有 FAIL（Gate 1）
- `fengdoclint.py --strict` 不合规（Gate 2）
- 报告首行格式不合规（Gate 3）
- `00-INDEX.md` 缺失（Gate 2）
- 管线逐层验收失败（Gate 4）

---

## 6. 产出合规报告

写入 `$BASE/AUDIT_REPORT.md`，格式如下（`## 快败闸门结果` 为强制节——产物必须含五门表，缺失视为 AUDIT 不合格）：

```markdown
# 审计报告 — <TICKER> <中文名> <日期>

> 结论：**PASS / CONDITIONAL PASS / FAIL**

## 快败闸门结果

| 门 | 检查内容 | 结果 | 详情 |
|----|---------|------|------|
| Gate 1: state | 状态机完整性 | ✅/❌ | ... |
| Gate 2: structure | 文档结构合规 | ✅/❌ | ... |
| Gate 3: report | 报告质量三连 | ✅/❌ | ... |
| Gate 4: pipeline | 管线逐层验收 | ✅/❌ | ... |
| Gate 5: consistency | 跨文件一致性 | ✅/⚠️ | ... |

> 注：HALT 时未运行的门填 ⏭️未运行（注明被哪一门 HALT）。

## 工具检查结果（补充）

| 工具 | 结果 | 详情 |
|------|------|------|
| fengdoclint --strict | ✅/❌ | ... |
| fengstate verify | ✅/❌ | ... |
| fengstate accept | ✅/❌ | ... |
| report_audit check | ✅/❌ | ... |
| report_audit sources | ✅/❌ | ... |
| report_audit csvdetect | ✅/❌ | ... |
| fengquality cross-check | ✅/❌/N/A | ... |
| consistency-only（项目级，可选） | ✅/⚠️ | ... |

## 逐层合规

| 层 | 检查项 | 通过 | 未通过 | 未通过项 |
|----|-------|------|-------|---------|
| L0 | 3 | 3 | 0 | — |
| M | 5 | 5 | 0 | — |
| L1 | 5 | 4 | 1 | L1-5 深度价值路径未覆盖 |
| ... | ... | ... | ... | ... |
| 跨层维度 | 5 | 5 | 0 | — |
| **合计** | **42** | — | — | 内容 37 + 跨层 5 |

## 修复建议

（如有未通过项，逐条列出修复方法）
```

---

## 7. 向用户汇报

向用户简要汇报：
1. 综合判定（PASS / CONDITIONAL PASS / FAIL）
2. 通过率（X/Y 项通过）
3. 关键问题（如有）
4. 修复建议（如有）

**若为 FAIL**：明确告知哪些层需要修复，建议用什么工具重跑，并按双线修复纪律执行（见下）。

---

## 8. 双线修复纪律（2026-09-09 创始人立规）

> 来源：创始人第44/46轮"如果合规自检跟文档贴合不好，对自检本身也自检" + 本轮"修的时候报告也要修、skill 也要修"立规。
> FAIL 不许只修一边，必须分清两条线：

- **A 线修内容（报告侧）**：分析目录 `$BASE/` 内的产物问题——补文件/补数/修正结论 → 对受影响层重跑 `complete` + `accept`（遵守 fenginvest 产物修正纪律，下游受影响层连带重跑）→ 重跑本 skill 直到 PASS / CONDITIONAL PASS。
- **B 线修机制（skill/工具侧）**：工具误杀或机制与文档脱节——修 `tools/` / 本 SKILL / `knowledge/基准参考.md` / fenginvest SKILL 对应条款 → 用正反例验证工具改动 → 重跑闸门确认。
- **切片隔离**：A 只碰 `$BASE/` 分析目录，B 只碰机制文件（tools/skills/knowledge），一次只做一边，避免覆盖。
- **判线方法**：先亲验复现（读报告原文 + 重跑失败的门/工具命令），能定位到报告缺东西走 A，能定位到工具认不出正确内容/skill 与基准口径不一走 B，两边都有就两线都修。
- 修完后 `AUDIT_REPORT.md` 更新判定，重跑闸门全绿才算闭环。
**若为 PASS**：确认分析质量合格。
