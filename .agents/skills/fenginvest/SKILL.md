---
name: fenginvest
description: "[FengInvest] 七层决策框架 — 单次执行完整分析入口；买入后交 /fengholding 登记持仓"
when_to_use: "买入前完整分析。当用户要求分析某只股票/标的（给出 TICKER 或公司名）、评估能否买入、走七层框架、或说'分析/研究一下 X'时使用。触发词：分析、七层框架、投资分析、能不能买、值不值得买、研究报告"
allowed-tools:
  - Agent
  - Bash
  - Read
  - Skill
  - Write
triggers:
  - fenginvest
  - 分析
  - 七层框架
  - 投资分析
---
# FengInvest — 七层框架（单一大指令）

> 一次调用完成全部 7 层分析。不再拆分子 skill。
> 用法：`/fenginvest <TICKER>` 或 "分析一下<TICKER>"

## 变量约定

替换以下占位符：
- `<TICKER>` → 标的代码（如 0700.HK）
- `<中文名>` → 公司中文名（如 腾讯）
- `<YYYY-MM-DD>` → 当前日期
- `BASE` → `research/060-companies/<TICKER>-<中文名>/<YYYY-MM-DD>`
- `ROOT` → `cd "$(git rev-parse --show-toplevel)"`
- `SK_DIR` → 搜索工具目录（默认取环境变量 `SEARCH_KING_DIR`；未设置时请自行指向本机 Search-King 克隆目录）

### Search-King 接口速查（2026-09-29 修订，避免再踩误判坑）

- 文字搜索正确用法：`python "$SK_DIR/scraper.py" --search "<关键词>" --limit 5`。**默认后端即 4 源并发**（baidu_lite + ddg_lite + tinyfish + searxng），不要加 `--backend lite`——lite 只跑 DDG 单源，单源瞬断/反爬时会"假性无结果"。
- 输出里出现 `📎 共 N 条结果`（N≥1）即搜索成功；`❌ 无结果` 或超时 = 单次链路退化（换措辞重试 1 次，仍空则降级用其它检索通道并标注"数据未验证"）。
- 自检命令（30 秒内判定链路）：`python "$SK_DIR/scraper.py" --search "ping" --limit 1`，出现 `📎` 即链路可用。**不存在 `--check` 参数**（fengstate 预检已改为同款探针）。
- 出现 `百度安全验证` / DDG 超时告警属正常单源退化，4 源合并仍可能出结果；只有全部源空才算链路失败。

## 执行顺序

### Step 0 — 初始化

```bash
cd "$(git rev-parse --show-toplevel)"
SK_DIR="${SEARCH_KING_DIR:-${SEARCH_KING_DIR:-<Search-King目录>}}"
python tools/fengstate.py init <TICKER>
TICKER=<TICKER>
DATE=$(date +%F)
NAME=$(python tools/fengdata.py $TICKER --financials 2>/dev/null | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('financials',{}).get('sector',''))" 2>/dev/null || echo "未知")
mkdir -p research/060-companies/$TICKER-$NAME/$DATE/sources
BASE=research/060-companies/$TICKER-$NAME/$DATE
```

---

### 产出文档规范（每层必守：双格式 + 总览）

每层完成后，`$BASE/` 内**同时存在**出站文件与可读 MD（人话版），禁止只产出 JSON：

| 层 | 出站文件（complete 参数） | 可读文件（人话版） |
|:---|:---|:---|
| 01-capability | —（本身 MD） | `01-capability.md` |
| 02-market | `02-market.json` | `02-market.md` |
| 03-discipline | `03-discipline.json` | `03-discipline.md` |
| 04-quantitative | `04-quantitative.json` | `04-quantitative.md` |
| 05-qualitative | —（本身 MD） | `05-qualitative.md` |
| 06-collision | `06-collision.json` | `06-collision.md` |
| 07-report | `07-report.md`（分析师版） | `07-narrative.md`（贫嘴版） |
| 08-portfolio | `08-portfolio.json` | `08-portfolio.md` |

规则：
- **出站文件**：JSON 层以工具产出的 JSON 为 `complete` 参数（fengstate 出站验证；**必须传 .json 路径，传 .md 会被结构验证打回**）；**可读 MD** 为同一层的人类可读版本（关键数字 + 来源 + 结论），层 complete 前写好。产物事后被修正 → `complete --force` 重验 + 重新 accept。
- **L4 双版本**：`07-report.md` 分析师版过 report_audit 后，补写 `07-narrative.md` 贫嘴版（口语化论点/风险/结论，给非分析师看）。
- **00-INDEX.md 必产**：全部层完成后生成 `$BASE/00-INDEX.md`（每层一句话结论 + 关键数字 + 文件链接 + 层间关系 + 核心数据速查表）。
- **句内数字与标注口径自洽（159766 单教训，2026-09-13 升为硬闸门）**：写"低于年线 X%（价格 vs 基准）"时 X 必须由括号内两数算出。A 股年线口径=**MA250**（fengdata `ma250` 字段/本地库自算），MA200 不得冒充年线。已由 fengverify_gate Gate 3d 程序强制（扫描分析目录 MD/JSON 句内"方向词+数对+%"互算，矛盾即 report 门 FAIL）。
- **外抓数字入库前必对拍（159766 单教训）**：联网/外源取的任何数值型指标（行情、估值、相关性、偏离度）进层产物前，必须与 `data/market_data.db` 或 sources/ 自算序列对拍；两源分歧 >10% 时以本地序列为准并在 reason 标注分歧源，无第二源则标"未验证"。相关性/β 一律用 ≥250 交易日日收益自算（短窗口出过 0.09 vs 0.333 的假象）。

---

### Step 1 — L0 能力圈确认

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py check <TICKER> 01-capability
if [ $? -ne 0 ]; then echo "状态机拦截"; exit 1; fi
```

Read `docs/01-philosophy.md` 确认核心信条（不接飞刀 / 不蹭热点 / 层优先级权重）。

```bash
cat docs/01-philosophy.md
```

**禁止凭训练知识回答。** 必须先搜索当前信息。

全部执行：
```bash
python "$SK_DIR/scraper.py" --search "<行业> 商业模式 2026" --limit 5
if [ $? -ne 0 ]; then echo "[WARN] Search-King 搜索失败（非阻塞，但分析需标注数据未验证）"; fi
python "$SK_DIR/scraper.py" --search "<公司> 年报 财报 收入结构" --limit 5
if [ $? -ne 0 ]; then echo "[WARN] Search-King 搜索失败"; fi
python "$SK_DIR/scraper.py" --search "<公司> 竞争格局 市场份额" --limit 5
if [ $? -ne 0 ]; then echo "[WARN] Search-King 搜索失败"; fi
```

#### 三问（填充模板 → 写入 01-capability.md）

先创建结构化答题模板：

```bash
cat > "$BASE/三问模板.json" << 'JSONEOF'
{
  "q1": {"question": "一句话说清它怎么赚钱？卖什么？谁买单？为什么选它？", "answer": null, "sources": []},
  "q2": {"question": "它10年后大概率还在吗？需求还在吗？位置会被取代吗？", "answer": null, "sources": []},
  "q3": {"question": "什么能杀了它？监管？技术颠覆？竞争？", "answer": null, "sources": []}
}
JSONEOF
```

每个论断必须有来源引用（sources 数组 ≥ 1）。

#### DK 坐标原则检查

```bash
cat knowledge/principles/坐标原则.md
```

```bash
cat > "$BASE/坐标原则.json" << 'JSONEOF'
{
  "对标标的": null,
  "当前价差": null,
  "坐标类型": null,
  "不变性": null
}
JSONEOF
```

回答上述四个问题后将结果填入 JSON。AI 确认后写入 01-capability.md。

```bash
python "$SK_DIR/scraper.py" --search "<公司> <对标公司> 估值对比" --limit 5
if [ $? -ne 0 ]; then echo "[WARN] Search-King 搜索失败"; fi
```

#### 判定
| 结果 | 含义 | 后续 |
|:-----|:-----|:------|
| 懂 | 三问都能答+有来源 | 继续 |
| 不充分懂 | 能说清赚钱说不清风险 | 学习后重试或PASS |
| 不懂 | 说不清怎么赚钱 | PASS |

#### 输出
写入 `$BASE/01-capability.md`

```bash
python tools/fengstate.py complete <TICKER> 01-capability "$BASE/01-capability.md"
if [ $? -ne 0 ]; then exit 1; fi
```

#### 不懂即止
如果判定为"不懂"，自动跳过后续所有层：

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py skip <TICKER>
if [ $? -eq 0 ]; then
  echo "[PASS] 不懂不碰 — 分析中止"
  exit 0
fi
```

---

### Step 2 — M 层市场数据

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py check <TICKER> 02-market
if [ $? -ne 0 ]; then echo "状态机拦截"; exit 1; fi
```

Read `docs/02-market.md` 确认4灯标准。

```bash
cat docs/02-market.md
```

#### 机器层
```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengdata.py <TICKER> --years 20
if [ $? -ne 0 ]; then
  echo "[RETRY] fengdata.py 失败，切换 JP 节点重试..."
  python tools/clashproxy.py jp && sleep 2
  cd "$(git rev-parse --show-toplevel)" && python tools/fengdata.py <TICKER> --years 20
fi
if [ $? -ne 0 ]; then
  echo "[RETRY] 切换 US 节点重试..."
  python tools/clashproxy.py us && sleep 2
  cd "$(git rev-parse --show-toplevel)" && python tools/fengdata.py <TICKER> --years 20
fi
if [ $? -ne 0 ]; then
  echo "[DEGRADE] fengdata.py 多次重试失败，使用降级标记数据"
  echo '{"price_data":null,"financials":null,"m_layer":{"macro":"🟡","valuation":"🟡","trend":"🟡","sentiment":"🟡"},"source":"degraded","error":"fengdata.py failed after retries"}' > "$BASE/02-market.json"
fi
```

#### 搜索交叉验证（必须≥2独立来源）
```bash
python "$SK_DIR/scraper.py" --search "<标的> 行业 2026 宏观 趋势" --limit 5
if [ $? -ne 0 ]; then echo "[WARN] Search-King 搜索失败"; fi
python "$SK_DIR/scraper.py" --search "<标的> PE 估值 历史分位" --limit 5
if [ $? -ne 0 ]; then echo "[WARN] Search-King 搜索失败"; fi
python "$SK_DIR/scraper.py" --search "<标的> 新闻 财报 2026" --limit 5
if [ $? -ne 0 ]; then echo "[WARN] Search-King 搜索失败"; fi
```

#### AI 分析 — 4灯判定（填充后写入02-market.json）

```bash
cat > "$BASE/m_layer_prompt.json" << 'JSONEOF'
{
  "macro": {"light": null, "reason": null},    /* 🟢/🟡/🔴 */
  "valuation": {"light": null, "reason": null},
  "trend": {"light": null, "reason": null},
  "sentiment": {"light": null, "reason": null}
}
JSONEOF
```

- 多源验证财务数据，>1%误差标记
- **每个灯必须有数据支撑**（在 reason 中标注来源）

#### DK 家国原则 + 周期定位

```bash
cat knowledge/principles/家国原则.md
```

```bash
cat > "$BASE/dk_policy.json" << 'JSONEOF'
{
  "家国原则": null,       /* 鼓励/限制/中性 + 政策文件来源 */
  "货币周期": null,       /* 宽松/紧缩/中性 + 最新利率信号 */
  "工业利润周期": null,   /* 上行/下行/拐点 */
  "用电量差": null        /* 用电量增速 vs GDP 增速 */
}
JSONEOF
```

Read `knowledge/principles/家国原则.md`：
```bash
python "$SK_DIR/scraper.py" --search "<行业> 政策 2026 国家 鼓励 限制" --limit 5
if [ $? -ne 0 ]; then echo "[WARN] Search-King 搜索失败"; fi
python "$SK_DIR/scraper.py" --search "中国 货币政策 2026 周期" --limit 5
if [ $? -ne 0 ]; then echo "[WARN] Search-King 搜索失败"; fi
```
回答：家国原则（鼓励/限制/中性）、货币周期（宽松/紧缩）、工业利润周期、用电量差。
将结果写入 m_layer 的 dk_policy 扩展字段。

#### 输出
写入 `$BASE/02-market.json`（含 price_data, financials, m_layer(4灯), sources数组）

**质量门禁（必做）：** 写入后立即运行跨源验证。如果 FAIL，返回修正后再提交。

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengquality.py --cross-check <TICKER> --file "$BASE/02-market.json"
QC_EXIT=$?
if [ $QC_EXIT -eq 2 ]; then
  echo "╔════════════════════════════════════════════════════╗"
  echo "║  ❌ 数据质量 FAIL — PE 数据差异 > 10%            ║"
  echo "║  请核查 02-market.json 手动修正后重试             ║"
  echo "╚════════════════════════════════════════════════════╝"
  exit 1
elif [ $QC_EXIT -eq 1 ]; then
  echo "╔════════════════════════════════════════════════════╗"
  echo "║  ⚠️  数据质量 WARNING — PE 数据差异 5-10%        ║"
  echo "║  建议核查数据来源后在报告中标注                     ║"
  echo "╚════════════════════════════════════════════════════╝"
fi
```

```bash
python tools/fengstate.py complete <TICKER> 02-market "$BASE/02-market.json"
```

---

### Step 3 — L1 硬纪律检查

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py check <TICKER> 03-discipline
if [ $? -ne 0 ]; then echo "状态机拦截"; exit 1; fi
```

Read `docs/03-discipline.md` 确认4灯标准。

```bash
cat docs/03-discipline.md
```

#### 机器层
```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengrule.py <TICKER>
if [ $? -ne 0 ]; then
  echo "[RETRY] fengrule.py 失败，重试一次..."
  cd "$(git rev-parse --show-toplevel)" && python tools/fengrule.py <TICKER>
fi
if [ $? -ne 0 ]; then
  echo "[DEGRADE] fengrule.py 重试失败，使用降级纪律数据"
  echo '{"rules":[],"overall_light":"🟡","note":"fengrule.py failed","source":"degraded"}' > "$BASE/03-discipline.json"
fi
```

#### 机器层 ETF 变体（标的为 ETF/基金时，2026-09-13 立）

ETF 无公司科目（ROE/FCF/营收增速），禁用上面的公司模式硬跑——数据盲会被误判 RED。改走：

1. 从 M 层 `02-market.json` / fact sheet / 基金年报（N-CSR）取真实数字，组装 `$BASE/etf_metrics.json`，可用字段（缺的**直接省略，不许编**）：`portfolio_pe, portfolio_pb, sec_net_yield, distribution_rate_ttm, expense_ratio, aum_usd, risk_free_rate`。
2. `python tools/fengrule.py <TICKER> --asset-type etf --etf-metrics "$BASE/etf_metrics.json"`
3. 公司科目规则自动 ABSTAIN；替代规则里 **分配覆盖率（sec_net_yield÷distribution_rate_ttm）<80% 判 RED**——ROC 发息的证据级红灯。
4. L3 碰撞会识别 L1 输出的 `asset_type:"etf"` 自动走 DATA_BLIND 让位逻辑（引擎不再"看不见就 PASS"，而是 WAIT 让位 L2a 安全边际灯），无需额外参数；AI 仲裁只需核对语义。

#### AI 复核（填充模板 → 写入复核段）

```bash
cat > "$BASE/l1_review.json" << 'JSONEOF'
{
  "red_light_rational": null,     /* true/false + why */
  "yellow_conditions": null,      /* 真价值+极端估值满足？ */
  "anomalies": []
}
JSONEOF
```

- 红灯原因合理？（基本面恶化确实存在？）
- 黄灯条件？（真价值+极端估值是否满足？）
- 如有异常标注

#### DK 纪律规则复核

逐条读取定义：

```bash
cat knowledge/discipline/2638法則.md
cat knowledge/discipline/年线法则.md
cat knowledge/discipline/后发制人.md
cat knowledge/discipline/买分歧卖共识.md
cat knowledge/discipline/双账户制.md
```

```bash
cat > "$BASE/dk_discipline_check.json" << 'JSONEOF'
{
  "2638法則":     {"light": null, "note": null},
  "年线法则":     {"light": null, "note": null},
  "后发制人":     {"light": null, "note": null},
  "买分歧卖共识": {"light": null, "note": null},
  "双账户制":     {"light": null, "note": null}
}
JSONEOF
```

#### 快速否决清单（一票否决，触发任一直接 PASS，不再进入后续层）

> 移植自 ai-berkshire investment-checklist 第五步。逐条检查，任何一条触发即标注"否决"：

- [ ] 说不清楚这家公司怎么赚钱
- [ ] 连续 3 年自由现金流为负且看不到改善
- [ ] 管理层有诚信污点
- [ ] 竞争优势正在被不可逆侵蚀
- [ ] 需要靠"下一个接盘者出更高价"来赚钱（博傻）
- [ ] 无法承受这笔投资归零的后果
- [ ] 买入理由主要是"别人都在买"或"最近涨得好"
- [ ] 无法用 200 字以内写清楚买入理由

**AI 偏见自觉（industry-funnel）**：筛选过程中警惕 5 类偏见——
龙头偏好（资料多≠更好，按硬指标打分）、英文偏好（A/H 股必须中英都搜）、
故事偏好（区分"AI 收入占比"vs"AI 故事占比"）、当下偏好（当前财务好≠长期好）、
上市偏好（关注未来 IPO 候选）。偏见影响结论时在报告中注明。

#### 输出
写入 `$BASE/03-discipline.json`

```bash
python tools/fengstate.py complete <TICKER> 03-discipline "$BASE/03-discipline.json"
```

---

### Step 4 — L2b 量化因子分析

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py check <TICKER> 04-quantitative
if [ $? -ne 0 ]; then echo "状态机拦截"; exit 1; fi
```

Read `docs/05-quantitative.md` 确认2灯标准。

```bash
cat docs/05-quantitative.md
```

#### 机器层
```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengquant.py <TICKER>
if [ $? -ne 0 ]; then
  echo "[RETRY] fengquant.py 失败，重试一次..."
  cd "$(git rev-parse --show-toplevel)" && python tools/fengquant.py <TICKER>
fi
if [ $? -ne 0 ]; then
  echo "[DEGRADE] fengquant.py 重试失败，使用降级因子数据"
  echo '{"factors":[],"lights":{"bull":"🟡","bear":"🟡"},"note":"fengquant.py failed","source":"degraded"}' > "$BASE/04-quantitative.json"
fi
```

#### AI 简要点评（填充模板）

```bash
cat > "$BASE/l2b_review.json" << 'JSONEOF'
{
  "bull_factors": [],
  "bear_factors": [],
  "divergence_note": null,   /* 因子分歧说明什么？ */
  "extreme_signals": []       /* z>2.5 或 z<-2.5 的信号 */
}
JSONEOF
```

**abstain 语义（ai-hedge-fund）**：`factors` 中数据缺失的因子不进模板——
- fengquant 输出含 `abstained[]`（原因：无目标数据/同行不足）与 `consensus`（已排除 abstain 的计票）
- **没观点 ≠ 中性**：abstain 因子不得算作 🟡 中性票，也不得计入一致度统计
- 若 abstain ≥ 2 个因子 → 04-quantitative.json 的 `lights.bull/bear` 降半档并注明"数据不全，结论置信度下调"

#### 输出
写入 `$BASE/04-quantitative.json`

```bash
python tools/fengstate.py complete <TICKER> 04-quantitative "$BASE/04-quantitative.json"
```

---

### Step 5 — L2a 定性核心分析

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py check <TICKER> 05-qualitative
if [ $? -ne 0 ]; then echo "状态机拦截"; exit 1; fi
```

Read `docs/04-qualitative.md` 确认6灯标准 + 会计检查清单。

```bash
cat docs/04-qualitative.md
```

**铁律：禁止自己写定性分析。** 必须通过 `Skill("investment-team")` 执行。

> **⚠️ 降级路径（investment-team 不存在时）**：若本机无 `investment-team` skill（`.agents/skills/` 未注册），降级为**四大师视角并行子 Agent**——段永平/巴菲特/芒格/李录各一个 general-purpose agent，读对应大师知识库 + 前置数据产出视角分析，等效于 investment-team，汇总写入 `05-qualitative.md` 的「四大师视角」小节（2026-08-15 腾讯分析已验证此路径）。

**一手资料原则（earnings-review）**：美股公司（US 市场）的财务数据优先取 SEC EDGAR 原始文件——
`python tools/fengsec.py filings <TICKER> --form 10-K/10-Q` 拿提交列表 → `fetch <ACCESSION>` 下载全文；
二手源（yfinance 等）只降级使用。A/H 股维持现有数据管道。

#### 前置数据

```bash
cd "$(git rev-parse --show-toplevel)" && cat "$BASE/02-market.json"
cd "$(git rev-parse --show-toplevel)" && cat "$BASE/03-discipline.json"
cd "$(git rev-parse --show-toplevel)" && cat research/040-people/named/duanyongping.md
cd "$(git rev-parse --show-toplevel)" && cat research/040-people/named/buffett.md
cd "$(git rev-parse --show-toplevel)" && cat research/040-people/named/munger.md
cd "$(git rev-parse --show-toplevel)" && cat research/040-people/named/li-lu.md
```

#### 执行
调用 `Skill("investment-team")`，传入 TICKER、公司中文名、M层+L1数据。
需在调用中注入 DK 补充要求（息价原则检查 + 六步法）。

#### DK 补充要求
**息价原则检查：**
```bash
cat knowledge/principles/息价原则.md
```
- 当前价格比硬资产价值低多少？安全边际 > 30%？
- 持股腰斩后仍低估？
- 股息/回购回报充足？

**六步法补充**：
1. 主营业务：收入从哪里来？结构稳定？
2. 科技含量：研发投入/人员占比
3. 重大事项：解禁/减持/增发/回购
4. 当前定价：市场在博弈什么？
5. 催化剂：什么能触发价值回归？
6. 管理层：能力圈、资本配置历史

#### 管理层承诺兑现追踪（management-deep-dive）

> "看管理层靠不靠谱，最简单的方法就是看他以前说的话做到了没有"（ai-berkshire earnings-review）。

- 提取管理层近 3 年（财报电话会/股东信/公开采访）的**具体承诺**，列承诺→兑现表（✅/⚠️/❌）
- 兑现率四档：>80% 优秀（说到做到）/ 60-80% 合格（大方向对但执行有偏差）/ 40-60% 令人担忧（承诺过多交付不足）/ <40% 严重问题（不可信赖）
- 兑现率 <60% 或出现诚信污点 → 管理层灯降为 🔴，与快速否决清单第 3 条联动

**persona abstain 规则**：4 位大师中某位对某维度**无观点**（数据不足/超出能力圈）→ 标注 `abstain`，不计入该灯投票——"没观点"不得冒充"中性"（ai-hedge-fund 语义）。

#### 输出
收集4个agent输出，汇总写入 `$BASE/05-qualitative.md`，含 dk_assessment 小节。

**机器可读 6 灯（必产，L3 碰撞引擎输入契约）**：同时生成 `$BASE/05-qualitative_lights.json`——键名固定为 `好生意 / 护城河 / 安全边际 / 管理层 / 需求稳定 / 会计质量`，值为 `{"light": "GREEN|YELLOW|RED", "detail": "..."}`。碰撞引擎（`fengcollision.py`）优先查找该文件（`--l2a` 或自动 `05-qualitative_lights`），找不到才退到 MD 版（读不了 → proxy 降级，可能误判——AAPL 案例实测）。**禁止省略**：省略 = L3 碰撞用 proxy 推断安全边际，高 ROE 会对冲高 PE 导致误判 BUY（2026-08-16 已修复 proxy 公式 + 自动查找，但真实灯仍是首选）。

```bash
cat > "$BASE/05-qualitative_lights.json" << 'JSONEOF'
{
  "ticker": "<TICKER>",
  "date": "<DATE>",
  "好生意":  {"light": "GREEN",  "detail": "..."},
  "护城河":  {"light": "GREEN",  "detail": "..."},
  "安全边际": {"light": "RED",    "detail": "..."},
  "管理层":  {"light": "GREEN",  "detail": "..."},
  "需求稳定": {"light": "YELLOW", "detail": "..."},
  "会计质量": {"light": "GREEN",  "detail": "..."}
}
JSONEOF
python tools/fengstate.py complete <TICKER> 05-qualitative "$BASE/05-qualitative.md"
```

---

### Step 6 — L3 碰撞引擎

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py check <TICKER> 06-collision
if [ $? -ne 0 ]; then echo "状态机拦截"; exit 1; fi
```

Read `docs/06-collision.md` 确认碰撞规则 + 反方检查4问。

```bash
cat docs/06-collision.md
```

#### 前置检查
```bash
for f in "01-capability.md" "02-market.json" "03-discipline.json" "04-quantitative.json" "05-qualitative.md"; do
  if [ ! -f "$BASE/$f" ]; then echo "缺失前置文件: $BASE/$f"; exit 1; fi
done
echo "所有前置文件存在"
```

#### 碰撞前 — 碰撞引擎 + 反方强制检查

先运行碰撞引擎获取规则树输出：
```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengcollision.py <TICKER>
if [ $? -ne 0 ]; then
  echo "[RETRY] fengcollision.py 失败，重试一次..."
  cd "$(git rev-parse --show-toplevel)" && python tools/fengcollision.py <TICKER>
fi
if [ $? -ne 0 ]; then echo "[WARN] fengcollision.py 执行失败，将仅靠 AI 进行碰撞"; fi
```

**引擎输出必须存档（数据可追溯）**：把**最终使用的**引擎输出（含 `--l2a` 等全部参数的那次）保存到 `$BASE/sources/fengcollision_raw.json`（覆盖式）。若中间跑过多次（如发现 proxy 误判后补 `--l2a` 重跑），**只留最终版**，防止数据包与出站决策矛盾（2026-08-16 AAPL 案例：raw 存了被推翻的 proxy BUY 初判，复核者误读）。`confidence_score` 为引擎输出的 0-1 数值（`high→0.85 / medium→0.65 / low→0.35`），出站文件 `06-collision.json` 的 `confidence` 直接抄它，勿自编。`--l2a` 传 `$BASE/05-qualitative_lights.json`（Step 5 必产）即可，引擎会优先自动查找。

然后创建反方检查模板并填充：

```bash
cat > "$BASE/adversarial_check.json" << 'JSONEOF'
{
  "ticker": "<TICKER>",
  "answers": [
    {"q": "列出这个股票让你亏钱的5种方式", "answer": null},
    {"q": "如果当前价格下跌30%，你会加仓还是割肉？", "answer": null},
    {"q": "如果当前价格上涨30%，你会卖吗？", "answer": null},
    {"q": "这个决策受什么最近的新闻/价格走势影响？", "answer": null}
  ],
  "completed": false
}
JSONEOF
```

```bash
# 标记反方检查完成（验证所有回答已填写）
python -c "
import json
d = json.load(open('$BASE/adversarial_check.json'))
assert all(a['answer'] for a in d['answers']), '反方检查未完成：存在未回答的问题'
d['completed'] = True
json.dump(d, open('$BASE/adversarial_check.json', 'w'), indent=2, ensure_ascii=False)
print('[OK] 反方检查全部完成')
"
```

#### 读全部5个前置文件，按 docs/06-collision.md 规则碰撞

#### 人物知识库（辅助反方视角）
```bash
cd "$(git rev-parse --show-toplevel)" && cat research/040-people/named/simons.md
if [ $? -ne 0 ]; then echo "[WARN] 西蒙斯知识库读取失败"; fi
cd "$(git rev-parse --show-toplevel)" && cat research/040-people/named/cathie-wood.md
if [ $? -ne 0 ]; then echo "[WARN] Cathie-Wood 知识库读取失败"; fi
cd "$(git rev-parse --show-toplevel)" && cat research/040-people/named/klarman.md
if [ $? -ne 0 ]; then echo "[WARN] 卡拉曼知识库读取失败"; fi
```
用这些视角交叉验证，记录冲突信号。

#### DK 碰撞规则
```bash
cd "$(git rev-parse --show-toplevel)" && cat knowledge/principles/坐标原则.md
if [ $? -ne 0 ]; then echo "[WARN] 坐标原则读取失败"; fi
cd "$(git rev-parse --show-toplevel)" && cat knowledge/principles/家国原则.md
if [ $? -ne 0 ]; then echo "[WARN] 家国原则读取失败"; fi
cd "$(git rev-parse --show-toplevel)" && cat knowledge/principles/息价原则.md
if [ $? -ne 0 ]; then echo "[WARN] 息价原则读取失败"; fi
cd "$(git rev-parse --show-toplevel)" && cat knowledge/principles/取舍原则.md
if [ $? -ne 0 ]; then echo "[WARN] 取舍原则读取失败"; fi
```
- 规则10：任一 DK 原则红灯 → PASS
- 规则11：坐标原则红灯 → 降置信度
- 规则12：家国原则红灯 → PASS
- 规则13：安全边际<30% → 强WAIT建议（**判断依据非机械裁决**，2026-09-30 创始人立规"30%只是判断的一个依据，不是杀猪的刀"；引擎出站附 rule13_suggestion（binding=false），规则树判定照常输出，**L3 必须做 AI 仲裁**：采纳默认 WAIT 或凭书面补偿证据（股息底/质量溢价/不对称赔率）改判，论证写入 06-collision；息价原则红灯仍走规则10硬拦截）
- 规则14：全部绿灯+L1绿灯 → 调高置信度和仓位
- 在输出中记录 dk_assessment

#### 行为偏误检查（填充模板 → 写入输出）

```bash
cat > "$BASE/bias_check.json" << 'JSONEOF'
{
  "ticker": "<TICKER>",
  "biases": [
    {"bias": "确认偏误", "risk": null, "evidence": null},
    {"bias": "锚定效应", "risk": null, "evidence": null},
    {"bias": "近因偏误", "risk": null, "evidence": null},
    {"bias": "过度自信", "risk": null, "evidence": null}
  ]
}
JSONEOF
```

#### 输出（双格式，状态机要求 JSON）
1. 写入 `$BASE/06-collision.json`（出站文件，**必须含 `decision` + `confidence` + `position_pct` + `conflicts[]` 四个键**，fengstate 出站验证要求 JSON）：
```bash
cat > "$BASE/06-collision.json" << 'JSONEOF'
{
  "decision": "<BUY/HOLD/WAIT/PASS — 抄引擎 decision>",
  "confidence": <0-1 — 抄引擎 confidence_score，勿自编>,
  "position_pct": <建议仓位 — 抄引擎 position_pct>,
  "conflicts": [{"source": "<冲突来源>", "message": "<冲突点>", "resolution": "<处理方式>"}],
  "dk_assessment": "<DK 原则红灯/绿灯摘要>"
}
JSONEOF
```
2. 补写 `$BASE/06-collision.md` 可读版（反方人物视角 + 偏误检查 + 规则树命中明细）。
3. 以 JSON 为 complete 参数：
```bash
python tools/fengstate.py complete <TICKER> 06-collision "$BASE/06-collision.json"
```

---

### Step 6.5 — 独立验证（质量门禁）

在生成报告前，对所有已完成的 6 层输出做全量验证。

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py verify <TICKER>
if [ $? -ne 0 ]; then
  echo "╔═══════════════════════════════════════════════╗"
  echo "║  ⚠️  部分层验收未通过                         ║"
  echo "║  review 各层输出后，可单独修复或重新 complete  ║"
  echo "║  继续到 L4，但须在报告中标注未验收通过的层     ║"
  echo "╚═══════════════════════════════════════════════╝"
fi
```

逐层验收标准检查（通过 `accept` 命令单独复查）：

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py accept <TICKER> 01-capability
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py accept <TICKER> 02-market
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py accept <TICKER> 03-discipline
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py accept <TICKER> 04-quantitative
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py accept <TICKER> 05-qualitative
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py accept <TICKER> 06-collision
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py accept <TICKER> 07-report
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py accept <TICKER> 08-portfolio
```

**验证清单：**
- [ ] L0 — 三问完整、坐标原则、懂/不懂判定
- [ ] M 层 — 4灯（宏观/估值/趋势/情绪）都有数据支撑
- [ ] L1 — rules≥8条、overall_light 有效
- [ ] L2b — factors≥4个、因子信号解读
- [ ] L2a — 定性报告含 dk_assessment 小节 + `05-qualitative_lights.json` 必产
- [ ] L3 — 反方检查全部回答、偏误检查、碰撞决策 + `sources/fengcollision_raw.json` 为最终版

⚠️ **顺序铁律（2026-08-16 起）**：本步（verify + 8 层 accept）**必须在写 L4 报告之前全部完成**，不得推迟到收尾——报告只能建立在已验收的层上。任一产物后续被修正（如抽检抓错），修正后**立即重跑该层 `complete` + `accept`**，再继续。

如果所有层验收通过 → 继续到 L4。
如果有警告 → 在 L4 报告中标注降级项。

---

### Step 7 — L4 研究报告

```bash
ls "$BASE/"
```

Read `docs/07-report.md` 确认报告标准与格式规范。

```bash
cat docs/07-report.md
```

把以下数据全部读一遍（逐文件强制读取）：

```bash
echo "=== 01-capability.md ===" && cat "$BASE/01-capability.md"
echo "=== 02-market.json ===" && cat "$BASE/02-market.json"
echo "=== 03-discipline.json ===" && cat "$BASE/03-discipline.json"
echo "=== 04-quantitative.json ===" && cat "$BASE/04-quantitative.json"
echo "=== 05-qualitative.md ===" && cat "$BASE/05-qualitative.md"
echo "=== 06-collision.md ===" && cat "$BASE/06-collision.md"
```

#### 写作规范
**第一行格式（固定，机器可读）：**
```
# {TICKER} — BUY/HOLD/WAIT/PASS @ {仓位}% — {日期}
> 一句话投资论点
```
**来源引用：** 所有数据必须有来源。禁止无来源论断、禁止"我觉得"。

#### 报告结构（10个部分）

1. **投资论点** — 核心判断、当前价格反映的预期、非共识在哪、催化剂
2. **业务概览** — 收入结构表、商业模式、竞争地位、管理层评分
3. **行业与竞争** — 行业规模/增速/集中度、核心对手对比表
4. **财务分析** — 3年趋势表（营收/毛利率/经营利润率/净利润/ROE/FCF）
5. **估值分析** — 相对估值（PE/PB/PS vs 行业+历史）、绝对估值（DCF/三情景）、目标价
6. **量化因子信号** — 各因子 z-score 表、最强 BULL/BEAR、一致度
7. **风险矩阵** — 概率×影响表、反方观点摘要
8. **催化剂日历** — 时间/事件/影响
9. **建仓策略与退出条件** — 仓位/价格区间、加仓条件≥3、退出条件≥3
10. **DK 四大原则审计** — Read `knowledge/principles/` 逐一审计（坐标/家国/息价/取舍）
11. **DK 纪律规则检查** — Read `knowledge/discipline/`（2638/后发制人/买分歧卖共识/年线/钱仓滚存）
12. **行为偏误检查** — 确认偏误/锚定效应/近因偏误/过度自信

所有数据有来源引用。

#### 数据验算（禁止心算）

报告中所有估值/财务数字必须经工具验算，AI 不得心算：
```bash
python tools/financial_rigor.py verify-market-cap --price <现价> --shares <总股本> --reported <报告市值> --currency <币种>   # 市值验算
python tools/financial_rigor.py verify-valuation --price <现价> --eps <EPS> --bvps <每股净资产>                                # 估值验算
python tools/financial_rigor.py three-scenario ...                                                                             # 三情景估值
python tools/financial_rigor.py cross-validate ...                                                                             # 多源交叉
```
验算结论写入"估值分析"节（偏差>5% 必须查原始财报）。

#### 报告准出抽检（report_audit gate）

报告发布前必须过准出 gate，不得跳过：
```bash
# 1) 提取数据点 + 随机抽样 15%（固定 seed 可复现同一批样本）
python tools/report_audit.py extract --report "$BASE/07-report.md" --seed 42
# 2) 对抽检清单逐项核数：回源各层 JSON / financial_rigor 验算 / 联网对拍，
#    填入 fetched_value / fetched_source（fetched_value2 为副来源，可选），
#    存为 $BASE/audit_results.json（extract 输出的 JSON 模板填好值即可）
# 3) 准出判定：verdict 参数是【内联 JSON 字符串】，不是文件路径（2026-08-16 文档修正）
python tools/report_audit.py verdict --results "$(cat $BASE/audit_results.json)" --report "$BASE/07-report.md"
```
verdict 打回 → 修正后重跑抽检，直到 pass 才 complete。抽检抓到的数字错误必须在报告与相关层同时修正，修正后重跑该层 complete + accept。

**抽取器误抓登记口径（159766 单教训）**：样本含名称内嵌数字（"沪深300"、"6因子"等）会被抽成伪数据点。此类项不许删样本：`fetched_value` 填报告原值，`fetched_source` 写明"抽取器误抓：<数字> 出自名称 <词>，非独立数据点"并附该行真实断言的实际来源；真实断言（如相关性 β）另立项核。行内来源标注统一用"来源：<URL 或 本地DB/文件路径>"格式，供 sources 清零检查识别。

#### 输出
写入 `$BASE/07-report.md`

```bash
python tools/fengstate.py complete <TICKER> 07-report "$BASE/07-report.md"
```

---

### Step 8 — P 组合检查

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengstate.py check <TICKER> 08-portfolio
if [ $? -ne 0 ]; then echo "状态机拦截"; exit 1; fi
```

Read `docs/09-portfolio.md` 确认约束标准（三轴正交模型）。

```bash
cat docs/09-portfolio.md
```

Read `docs/08-exit.md` 确认退出策略框架。

```bash
cat docs/08-exit.md
```

#### 组合盘面（运行期计算，不预设桶）

先刷新实时汇率，再跑组合检查：

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengdata.py fx
if [ $? -ne 0 ]; then echo "[WARN] 实时汇率失败（将回退持仓快照）"; fi
cd "$(git rev-parse --show-toplevel)" && python tools/fengportfolio.py check
if [ $? -ne 0 ]; then echo "[WARN] fengportfolio.py 执行失败"; fi
```

**三轴正交模型**（每持仓标注 `market × segment × qualifier`，见 holdings/SCHEMA.md）：
- `market`：CN_A / CN_HK / CN_OVS(中概) / US / GLOBAL
- `segment`：细分板块词汇（互联网 / 半导体.AI算力 / 半导体.存储 / 保险 / 银行 / 医药 / 家电 / 低波高息 …），**可扩展，不设专属桶**
- `qualifier`：cash / quasi_cash（准现金=当现金用，如低波高息 ETF）

**集中度检查**（`check` 输出，占总资产 %，权益口径）：

| 维度 | 🟡 黄 | 🔴 红 | 备注 |
|:-----|:---:|:---:|:-----|
| market 轴 | >28% | >35% | 警示 + 重审 |
| segment 轴 | >20% | >25% | 警示 + 重审 |
| market×segment 组合 | >15% | >20% | 警示 + 重审 |
| 单只标的 | >15% | >20% | 警示 + 重审；确定性极高可破黄线 |
| **单标绝对上限** | — | **>40%** | **⛔ 不可突破** |

- **超限语义（2026-08-16 定稿）**：红/黄灯 = 警示，触发"重新审视论文是否仍成立"，**不是自动否决**；单标可破 20% 黄线，条件是七层框架走完 + 论文与证伪条件（redlines）齐备，破线理由记入 journal 与盘面；40% 绝对上限任何情况不可破；集中度超标**不是卖出理由**（只约束买入）
- 资金池（真现金+准现金）**不参与权益集中度**——低波高息等准现金是"等机会栖身"，不是境外权益超配
- **资金墙 = 买入预算**：`check` 输出境内池/境外池可动用余额，**不产生风险告警**；人民币可买 QDII/中概/港股基金，港币可买 A 股 ETF——资金墙不限制市场敞口
- 跨币种**人民币一盘棋**：实时汇率（`fengdata.py fx`：USDCNY/HKDCNY/USDHKD）失败时回退持仓 `meta.fx_rates` 快照

#### 相关性检查

```bash
cd "$(git rev-parse --show-toplevel)" && python tools/fengportfolio.py correlate
if [ $? -ne 0 ]; then echo "[WARN] correlate 执行失败"; fi
```

- 与现有持仓相关系数>0.8 → 降仓位；>0.9 → 不增
- 组合平均相关系数应<0.6

#### 宏观情景压力测试
回答4个情景：通胀/衰退/地缘/监管对组合的影响。

#### 回撤响应
当前组合回撤在哪个区间？是否需要响应？

#### 输出
1. 更新 `portfolio/current.md` 组合仪表盘（三轴分布 + 资金池 + 买入预算）。
2. 生成 `$BASE/08-portfolio.json` 出站验证文件（**必须含 `overall_light` + `dashboard` 两个顶层键**，fengstate 出站验证要求 JSON 格式；`portfolio/current.md` 是 md 过不了验证，勿作 complete 参数）：

```bash
cat > "$BASE/08-portfolio.json" << 'EOF'
{
  "ticker": "<TICKER>",
  "date": "<DATE>",
  "overall_light": "<🟢/🟡/🔴 来自 fengportfolio.py check 的 overall_light>",
  "dashboard": {
    "total_position_pct": <权益占比>,
    "cash_pct": <资金池占比>,
    "holding_count": <持仓数>,
    "max_single_pct": <最大单标占比>,
    "sector_concentration_pct": <最高 segment 占比>,
    "max_drawdown_pct": <最大回撤>,
    "avg_correlation": null
  },
  "note": "组合盘面结论（三轴集中度/资金池/预算/情景压力测试要点）"
}
EOF
python tools/fengstate.py complete <TICKER> 08-portfolio "$BASE/08-portfolio.json"
```

---

## 完成后

**收尾（必做，缺一不算完成）：**
1. 补写 `$BASE/07-narrative.md`（贫嘴版，若 L4 audit 通过）。
2. 生成 `$BASE/00-INDEX.md` 总览（每层一句话结论 + 关键数字 + 文件链接 + 层间关系 + 核心数据速查表）。
3. 逐层 `accept`（含 07/08）全部通过后，跑 `python tools/fengdoclint.py <TICKER>` 自检整目录合规（双格式 + 00-INDEX + L4 双版本）；任一层 ❌ 须补齐 MD/00-INDEX 后再交付。
4. 向用户汇报。

⚠️ **产物修正纪律（2026-08-16 起）**：任何层产物在 complete 之后被修正（抽检抓错、数据更新、口径调整），**必须立即重跑该层 `complete` + `accept`**，并检查下游引用该文件的层是否受影响（如 02-market 的 pe_ttm 变了 → 04/06 需重跑）。状态机记录的是最后一次校验结果，修正后不重跑 = 状态机与实际产物脱节。

向用户简要汇报结果：哪些层完成、关键发现、最终建议。

**⚡ 审计自检（必跑，2026-09-09 创始人立规）**：汇报前必须用 Skill 工具实跑 `/fengcheck <TICKER>`，`$BASE/AUDIT_REPORT.md` 落盘且判定为 PASS / CONDITIONAL PASS 后才算完成；汇报末尾附审计结论（判定+通过率+关键问题）。FAIL 则先修后报，不许跳过、不许只提醒不跑。修复按 fengcheck §8 双线纪律：A 线修报告内容（重 complete+accept+重检），B 线修 skill/工具机制（正反例验证+重跑闸门），判线不清两边都修。

**若结论为买入（BUY/ADD）且用户确认执行**：提示下一步用 `/fengholding` 登记持仓（add 四段校验 + 组合影响 + 回填默认 triggers），完整生命周期为 `fenginvest`（买入前）→ `fengholding`（持有期）→ `fengexit`（卖出）→ `fengreview`（复盘）。

开源登记：提到开源项目即登记 data/config/opensource_list.json（提到=入表）。
