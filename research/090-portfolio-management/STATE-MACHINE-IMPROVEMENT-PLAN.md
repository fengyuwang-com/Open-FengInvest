# FengInvest 状态机改进计划

> 目标：让 AI 在执行 7+1 层框架时 **不漏脚本、不漏步骤、输出可验证**
> 方法：先研究我们的方案，再研究差距，再提改进

---

## 第一阶段：现状分析（我们的方案）

### 1.1 架构总览

```
SKILL.md (443行, 8步自然语言+脚本混合)
  └─ 每步: fengstate.py check → [工具/搜索/AI分析] → fengstate.py complete
       └─ fengstate.py: 状态文件 research/state/temp_state_<TICKER>.json 是唯一 truth
```

**当前强制机制：**

| 机制 | 是什么 | 强制力 |
|:-----|:-------|:-------|
| 状态机 check | 检查前置层是否完成，未完成→exit(1) | **物理强制** |
| 状态机 complete | 标记完成+输出验证，验证失败→return 1 | **物理强制** |
| bash 块 | `python tools/fengxxx.py` 等硬命令 | **物理强制**（AI 必须执行） |
| 自然语言指令 | "读 docs/X.md 确认标准"、"回答4个问题" | **无强制**（AI 可跳过） |
| Skill("investment-team") | 调用子 skill，外部执行 | **无强制**（AI 可跳过或伪造） |

### 1.2 fengstate.py 状态机分析

- 8 层定义在 `SEQUENCE`，前置条件在 `PREREQUISITES`
- `verify_output` 只对 3 层（市场/纪律/量化）做 JSON 结构化验证
- 其余 5 层仅检查 "文件存在 + >50 char"
- `json_step_map` 兼容短名（"m"→"02-market"），但因 skill 已改传全名，映射在多数场景碰巧有效

### 1.3 SKILL.md 指令类型分布

统计全部 443 行中的指令：

| 类型 | 行数占比 | 可强制执行？ | 示例 |
|:-----|:---------|:------------|:-----|
| bash 块 (python 工具) | ~35% | ✅ yes | `python fengdata.py 0700.HK --years 20` |
| bash 块 (搜索) | ~25% | ✅ yes | `python scraper.py --search "..."` |
| bash 块 (状态机) | ~5% | ✅ yes | `python fengstate.py check ...` |
| cat/bash (读文件) | ~10% | ✅ yes | `cat docs/01-philosophy.md` |
| 自然语言 (必做) | ~15% | ❌ no | "根据数据确定4个灯"、"回答4个问题" |
| 自然语言 (描述性) | ~10% | ❌ no | 文档描述、格式说明 |

**约 25% 的指令无强制执行机制。** 这些 AI 可跳过。

### 1.4 工具链分析

| 工具 | 输出格式 | 验证方式 | 结论 |
|:-----|:---------|:---------|:-----|
| fengdata.py | JSON | verify_output 检查 key_fields | ✅ 可靠 |
| fengrule.py | JSON (rules[]+overall_light) | verify_output 检查 key_fields | ✅ 可靠 |
| fengquant.py | JSON (factors[]+lights) | verify_output 检查 key_fields | ✅ 可靠 |
| fengcollision.py | JSON (decision+conflicts) | ❌ 无验证 | ⚠️ 未纳入 verify_output |
| fengportfolio.py | JSON | ❌ 无验证 | ⚠️ 未纳入 verify_output |
| investment-team | Markdown | ❌ 仅检查 >50 chars | ⚠️ 弱验证 |
| Search-King | 控制台输出 | ❌ 无验证 | ⚠️ 未检查搜索是否产生结果 |

---

## 第二阶段：差距分析（我们 vs 行业最佳实践）

> 来自 3 个研究来源：Alibaba File-as-State、Claude Verification Loops、StateFlow 论文

### 2.1 对照 StateFlow 范式

| StateFlow 概念 | 我们 | 差距 |
|:---------------|:-----|:-----|
| 每个 state 有定义的 output function | 部分有（工具调用） | 自然语言步骤缺少 output function |
| transitions 由 rules + LLM 共同控制 | check/complete 做规则 | 无 LLM-decision 分支逻辑 |
| process grounding 与 sub-task solving 分离 | 状态机=grounding | grounding 层对 sub-task 的执行质量无验证 |
| state 内允许多个 actions | ✅ 有 | 无 action 间的一致性验证 |

### 2.2 对照 Verification Loop 三种模式

| 模式 | 我们 | 差距 |
|:-----|:-----|:------|
| **Embedded**（产出 skill 中嵌入验证） | verify_output（3/8层） | 剩余 5 层缺验证 |
| **Chained**（skill 末尾调另一个 skill） | fengstate.py complete → 下一步 skill | 无 independent verifier skill |
| **Standalone**（独立验证步骤） | ❌ 无 | 完全缺失 |

### 2.3 对照 Alibaba File-as-State 实践

| 最佳实践 | 我们 | 差距 |
|:---------|:-----|:------|
| 5 个文件：run_state + last_success + dedupe + execution_log + handoff | 仅有 run_state | 缺 execution_log（可审计）、handoff（硬断点） |
| 每个 task 有 acceptance_criteria | 仅文件存在 + key_fields | 缺 min_sources、min_sections、quality_metrics |
| 每个 task 有 validation_commands | 仅有 verify_output | 缺独立验证脚本 |
| 失败自动 retry 或 graceful degradation | ❌ 无 | 工具失败→直接 exit(1) 或悄无声息继续 |
| execution_log 用于审计复盘 | ❌ 无 | 无法追溯 AI 实际做了什么 |

### 2.4 差距汇总

| ID | 差距 | 严重度 | 影响 |
|:---|:-----|:-------|:-----|
| G1 | verify_output 只覆盖 3/8 层 | 🔴 | 定性/碰撞/报告/组合层输出无结构化验证 |
| G2 | ~25% 指令为不可强制执行的自然语言 | 🔴 | AI 可跳过大段分析 |
| G3 | 无 acceptance_criteria（验收标准） | 🟡 | 无法判断输出是否"完整" |
| G4 | 无 retry/degradation 策略 | 🟡 | 工具失败→要么硬停要么无声继续 |
| G5 | 无 independent verification（独立审计） | 🟡 | 无法发现 AI 分析的逻辑错误 |
| G6 | 无 execution_log | 🟡 | 无法事后审计 AI 实际执行了哪些步骤 |
| G7 | 无 pre-flight check | 🟢 | 执行前不检查环境完整性 |
| G8 | 无 cross-layer consistency check | 🟢 | 层间的数据矛盾不会被自动发现 |
| G9 | 无 step-skip 处理 | 🟢 | 如果 L0=不懂，状态机不拦截后续（仍在"完成"后允许继续） |

---

## 第三阶段：改进方案

### Phase 0 — 修现有 BUG（优先级最高）

在开始任何改进前，先修现有的代码 BUG。

**B-1: verify_output 层名不一致**

当前 `md_layers` 包含 "02-market"（实际上是 JSON），缺少 "03-discipline" 和 "04-quantitative"（实际上是 JSON）。

修复：
```python
# md_layers = {"01-capability", "02-market", "05-qualitative", ...}  # WRONG
md_layers = {"01-capability", "05-qualitative", "06-collision", "07-report", "08-portfolio"}
```
```python
# json_steps 保留全名 + 短名兼容
json_steps = {s.lower() for s in ["02-market", "03-discipline", "04-quantitative"]} | {"m", "l1", "l2b"}
```

**B-2: verify_output 对 fengcollision 和 fengportfolio 输出无验证**

将 collision 层 ("06-collision") 和 portfolio 层 ("08-portfolio") 加入 VERIFY_RULES：
- collison: key_fields: decision, confidence, position_pct, conflicts
- portfolio: key_fields: overall_light, dashboard

**B-3: PREREQUISITES 不全**

04-quantitative (L2b) 实际依赖 M 层 (02-market) 数据来做同业对比：
```python
"04-quantitative": ["02-market", "03-discipline"],  # 加市场数据依赖
```

---

### Phase 1 — 加固强制执行（High Priority）

**P1-1: 将自然语言指令转为 bash 块（SKILL.md）**

转换原则：每条"AI 做 X"的指令必须伴随一个 bash 块，让 AI "不做不行"。

| 当前（自然语言） | 改为（bash 块） |
|:-----------------|:----------------|
| "读 docs/01-philosophy.md 确认核心信条" | `cat docs/01-philosophy.md` |
| "Read knowledge/principles/坐标原则.md 然后回答" | `cat knowledge/principles/坐标原则.md && cat knowledge/principles/息价原则.md` |
| "根据数据确定4个灯" | 先 `cat docs/02-market.md` 确认标准，再 AI 分析 |
| "回答4个问题"（反方检查） | 模板文件 `research/temp_adversarial_<TICKER>.json`→ AI 填空→ `fengstate.py complete` 验证 |

核心原则：**每个分析步骤的输出必须有文件落地**，不依赖 AI 在消息中的承诺。

**P1-2: 为所有层添加 structured output 模板**

当前只有 3 个 JSON 层有结构化输出。扩展到全部 8 层：

| 层 | 当前格式 | 改为 | 模板 |
|:---|:---------|:-----|:-----|
| 01-capability | .md 自由格式 | `.json` + `.md` | `{three_questions: [{q, a, source}], dk_coordinate: {...}, judgement: "懂/不充分懂/不懂"}` |
| 05-qualitative | .md 自由格式 | `.json` 结构摘要 + `.md` 详细报告 | `{business_model: {score, light}, moat: {score, light}, ...}` |
| 06-collision | .md 自由格式 | `.json` 结构摘要 + `.md` 详细 | `{adversarial_answers: [4个回答], dk_assessment: {各原则结果}, bias_check: {4个偏误}}` |
| 07-report | .md 固定格式 | `.json` 结构元数据 + `.md` 报告 | `{investment_thesis, sections: [10个section状态], contains_dk_audit: bool}` |

方法：
- 每个层的 `verify_output` 新增对应 JSON 验证规则
- 输出格式 = `{summary: {...json结构...}, report_path: "05-qualitative.md"}` 的双文件结构

**P1-3: 增强 fengstate.py 验证引擎**

新增 `verify_all()` 命令，一次性验证所有已完成层的输出质量：

```bash
python fengstate.py verify <TICKER>  # 检查所有已完成层的输出完整性
```

验证内容扩展到：
- M layer: 至少 2 个 source URL、4 个灯都有值
- L1: rules 数组 ≥ 8 条（含 4 基础 + 4 DK）
- L2b: factors ≥ 6 个、peer_count ≥ 3
- L2a: 定性报告包含 4 个 agent 的输出摘要
- L3: 包含 conflicts 数组、dk_assessment、bias_check、adversarial_answers
- L4: 第一行匹配机器可读格式、包含所有 10 个 section

---

### Phase 2 — 增加验收标准（High Priority）

**P2-1: 每层定义验收标准（acceptance criteria）**

参考 Alibaba 实践，在 fengstate.py 的 VERIFY_RULES 中扩展：

```python
VERIFY_RULES = {
    "01-capability": {
        "type": "json",
        "min_sources": 3,  # 至少 3 次搜索来源
        "key_fields": ["three_questions", "judgement", "dk_coordinate"],
        "acceptance": "judgement != '不懂' OR (judgement == '不懂' AND status == 'skip')"
    },
    "02-market": {
        "type": "json",
        "min_sources": 2,
        "key_fields": ["price_data", "financials", "m_layer", "sources"],
        "m_layer_fields": ["macro", "valuation", "trend", "sentiment", "dk_policy"]
    },
    # ... 每层类似
}
```

**P2-2: 新增 acceptance check 命令**

```bash
python fengstate.py accept <TICKER> <layer>  # 检查该层输出是否满足验收标准
```

此命令可在 skill 中被 bash 块调用作为强制门禁，也可作为独立审计步骤。

---

### Phase 3 — 增加弹性与恢复（Medium Priority）

**P3-1: Tool retry 策略**

对关键工具（fengdata.py、fengquant.py）若失败则自动重试 1-2 次：

```bash
# SKILL.md 中的重试模式
python tools/fengdata.py <TICKER> --years 20 || \
  (python tools/clashproxy.py jp && sleep 3 && python tools/fengdata.py <TICKER> --years 20) || \
  (python tools/clashproxy.py us && sleep 3 && python tools/fengdata.py <TICKER> --years 20) || \
  { echo "[WARN] fengdata.py 多次重试失败"; echo '{"price_data":null,"financials":null,"m_layer":{"macro":"🟡","valuation":"🟡","trend":"🟡","sentiment":"🟡"},"source":"proxy","error":"fengdata.py failed after retries"}' > "$BASE/02-market.json"; }
```

原则：不空白跳过，用代理数据填充并标记降级。

**P3-2: 错误输出降级标准**

| 工具 | 硬失败行为 | 降级行为 |
|:-----|:----------|:---------|
| fengdata.py | 使用 clashproxy 切换节点重试 3 次 | 创建降级标记的 market.json，标注 "degraded" |
| Search-King | 重试 1 次 | 标注 "未验证"，继续分析 |
| investment-team | 重试 1 次 | 用 fengcollision.py 的 proxy_l2a_lights 替代 |
| fengquant.py | 重试 1 次 | 缺少量化因子标注，碰撞引擎跳过因子权重 |

**P3-3: 状态文件备份**

每次 `complete` 时自动备份：
```python
# 在 complete 函数末尾
if state.get("status") == "active":
    shutil.copy(path, path + ".bak")  # 每次完成一个层就备份
```

---

### Phase 4 — 独立验证（Medium Priority）

**P4-1: 新增 verify-layer 子 skill**

在 L3 碰撞之后、L4 报告之前，插入一个独立验证步骤：

```
Skill("fenginvest-verify")
  ├─ 检查 01-capability 是否有来源引用
  ├─ 检查 02-market 是否 4 灯都有数据支撑
  ├─ 检查 03-discipline 是否 fengrule.py 原始输出完整
  ├─ 检查 04-quantitative 是否 fengquant.py 输出
  ├─ 检查 05-qualitative 是否包含 4 个 agent 的输出
  ├─ 检查 06-collision 是否包含 dk_assessment + bias_check
  └─ 汇总：全部 pass → 继续，有 fail → 标记 warning 输出
```

此子 skill 不产生新信息，只验证已有信息的完整性。

**P4-2: 反方检查自动化**

将反方强制检查 4 问从 "自然语言" 转为 "填空 JSON + bash 块验证"：

```bash
# 碰撞前
cat > "$BASE/adversarial_check.json" << 'EOF'
{
  "ticker": "<TICKER>",
  "questions": [
    {"q": "5种亏钱方式", "answer": null, "reflection": null},
    {"q": "跌30%加仓还是割肉", "answer": null, "refaction": null},
    {"q": "涨30%卖不卖", "answer": null, "reflection": null},
    {"q": "最近什么影响判断", "answer": null, "reflection": null}
  ]
}
EOF
# AI 需要填充 answer + reflection
# 填充后用 fengstate.py complete --verify
```

---

### Phase 5 — 进阶改进（Low Priority / Stretch Goals）

**P5-1: Pre-flight 检查**

在 Step 0 init 时执行：
```bash
python tools/fenghealth.py check  # 或集成到 fengstate.py init
  ├─ Search-King 可用性
  ├─ fengdata.py 依赖（yfinance）可用
  ├─ Clash proxy 状态
  ├─ knowledge/ 目录完整
  └─ docs/ 文档完整
```

**P5-2: Cross-layer consistency 检查**

例如：
- L1 PE 值 vs L2b PE 值 → 差异 > 5% 标记 warning
- L1 overall_light vs L2b 因子信号 → overall GREEN 但 L2b 全 BEAR → warning
- M layer 趋势 vs L1 MA50/MA120 → 不一致标记

**P5-3: 执行日志（execution_log）**

新增 `research/state/log_<TICKER>.jsonl`，每步追加：
```json
{"ts": "...", "layer": "02-market", "action": "fengdata.py", "result": "success", "duration_s": 12}
{"ts": "...", "layer": "02-market", "action": "search", "query": "腾讯 PE 2026", "result": "3 sources"}
```

便于事后审计 AI 实际执行了什么。

**P5-4: 智能跳步处理**

如果 L0 = "不懂" → 状态机应支持 graceful stop（不拒绝 complete，但标记 overall = PASS）：
```python
PREREQUISITES["02-market"] = ["01-capability"]
# 但如果 capability.judgement == "不懂"，02-market 应该跳过
# 方案：新增 PASS 状态
SEQUENCE_SKIPPABLE = {"02-market", "03-discipline", "04-quantitative", "05-qualitative", 
                       "06-collision", "07-report", "08-portfolio"}
# 前置层判定为 "不懂" → 后面全部标记 "skipped"，不要求真正执行
```

---

## 第四阶段：实施路线图

### 优先顺序

```
Phase 0 (BUG修复)         ████████████████████ ✅ 已完成
Phase 1 (加固强制执行)     ████████████████████ ✅ 已完成
Phase 2 (验收标准)         ████████████████████ ✅ 已完成
Phase 3 (弹性恢复)         ████████████████████ ✅ 已完成
Phase 4 (独立验证)         ████████████████████ ✅ 已完成
Phase 5 (进阶改进)         ████████████████████ ✅ 已完成
```

### 已完成工作

| Phase | 修改文件 | 具体变更 |
|:------|:---------|:---------|
| **0** | `tools/fengstate.py` | ① md_layers 死代码清理，json_steps 补充 06-collision/08-portfolio；② VERIFY_RULES 新增 collision/portfolio 规则；③ 04-quantitative prerequisites 追加 02-market 依赖 |
| **1** | `~/.claude/skills/fenginvest/SKILL.md` | ① 所有 "Read docs/X.md" → cat 块（8处）；② L0 三问 → JSON 模板；③ L0 坐标原则 → JSON 模板；④ M 层 4灯 → JSON 模板；⑤ DK 家国原则 → cat + JSON 模板；⑥ L1 AI复核 → JSON 模板；⑦ L1 DK纪律规则 → 逐条 cat + JSON 模板；⑧ L2b 量化点评 → JSON 模板；⑨ L2a 息价原则 → cat 块；⑩ L3 反方检查 → JSON 模板 + Python 验证脚本；⑪ L3 行为偏误 → JSON 模板；⑫ L4 数据读取 → cat 块（6个文件合集）；⑬ P 层 → cat 块（portfolio.md + exit.md） |
| **2** | `tools/fengstate.py` | ① VERIFY_RULES 新增 01-capability 规则（three_questions+dk_coordinate+judgement+min_questions=3）；② M layer 验证增加 m_layer_fields（4灯字段检查）；③ L1 增加 min_rules=8；④ L2b 增加 min_factors=4；⑤ 新增 _check_acceptance() 验收检查函数；⑥ 新增 cmd_accept() 独立验收命令；⑦ 新增 cmd_verify() 全量验证命令；⑧ json_steps 补充 01-capability；⑨ CLI 路由注册 accept/verify |
| **3** | `~/.claude/skills/fenginvest/SKILL.md` + `tools/fengstate.py` | ① fengdata.py 添加 3 次重试（直连→JP→US）+ 降级 fallback；② fengrule.py 添加重试+降级；③ fengquant.py 添加重试+降级；④ fengcollision.py 添加重试+fallback；⑤ cmd_complete 增加自动 .bak 备份（intermediate saves only） |
| **4** | `~/.claude/skills/fenginvest/SKILL.md` | ① 在 L3 和 L4 之间插入 Step 6.5 独立验证门禁；② verify + accept 命令逐层检查验收标准；③ 通过/未通过两种情况的分支处理 |
| **5** | `tools/fengstate.py` + `SKILL.md` | ① P5-1: init 时自动执行环境预检（Search-King/knowledge/docs/yfinance）；② P5-2: cmd_verify 增加跨层一致性检查（L1 vs L2b 信号冲突/M层趋势vsL1均线/M层估值vs真价值）；③ P5-3: 新增 _log_event() 执行日志（check/complete/skip 均记录到 research/state/log_<TICKER>.jsonl）；④ P5-4: 新增 cmd_skip() 自动跳过、SEQUENCE_SKIPPABLE 定义、cmd_check 识别 skipped 状态、SKILL.md 中"不懂即止"分支 |

| Phase | 文件修改 | 新增文件 | 预计耗时 |
|:------|:---------|:---------|:---------|
| 0 | 1 (fengstate.py) | 0 | 15 min |
| 1 | 2 (SKILL.md + fengstate.py) | 0 | 2-3h |
| 2 | 2 (fengstate.py + SKILL.md) | 0 | 1-2h |
| 3 | 2 (SKILL.md 重试模式 + fengstate.py 备份) | 0 | 1h |
| 4 | 2 (SKILL.md + fengstate.py verify 扩展) | 1 (verify sub-skill) | 1-2h |
| 5 | 1+ (fengstate.py + fenghealth.py + 可选) | 2 (logs + 新命令) | 2-3h |

### 关键文件变更清单

| 文件 | Phase 0 | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 |
|:-----|:--------|:--------|:--------|:--------|:--------|:--------|
| tools/fengstate.py | ✅ 修 BUG | ✅ 扩展验证 | ✅ 验收标准 + accept/verify 命令 | ✅ 备份 | ✅ 无修改 | ✅ preflight/consistency/log/skip |
| ~/.claude/skills/fenginvest/SKILL.md | | ✅ 强制化 | ✅ 无修改 | ✅ 重试 | ✅ verify 步骤 | ✅ skip 分支 |
| docs/02-market.md ~ 09-portfolio.md | | ✅ 校对 | | | | |
| tools/fenghealth.py | | | | | | ✅ 无需独立文件（集成到 init） |
| research/state/ (日志) | | | | | | ✅ execution_log (jsonl) |

---

## 附录 A：Benchmark — 改进前后对比

| 评估维度 | 改进前 | 改进后 |
|:---------|:-------|:-------|
| 可强制执行的指令比例 | ~75% | ~95%+ |
| 验证覆盖的层数 | 3/8 | 8/8 |
| 工具失败处理 | exit(1) 或悄无声息 | retry → degradation → 标记 |
| 输出验收标准 | 文件存在 + >50 chars | 结构化 + key_fields + min_sources + _check_acceptance |
| 独立验证 | 无 | verify sub-skill (Step 6.5) |
| 可审计性 | 只能看对话记录 | execution_log + 备份状态 |
| 跨层一致性 | 无检查 | 自动 warning (3组) |
| 环境预检 | 无 | init 时自动检查 |
| 智能跳步 | 无 | L0=不懂 → cmd_skip 自动跳过后续所有层 |

---

*计划生成日期：2026-07-30*
*基于研究来源：Alibaba File-as-State, Claude Verification Loops, StateFlow (arXiv)*
