# Open-FengInvest — 工作区指令（开源版）

> 本文件 = **私有版 FengInvest 的全部原则** + **open 版新增的改写原则**（见 §开源改写原则，最高优先级之一）。
> 完整文档见 [CLAUDE.md](CLAUDE.md) 与 [docs/00-workflow.md](docs/00-workflow.md)。

---

## 一、开源改写原则（本仓特有，最高优先级）

> 创始人 2026-10-08 口述定稿。这是**私有版 → 开源版**的改写规则，与任何文档冲突时以本节为准，并回头修订被冲突的文档。

### 1. 能开源的东西尽量开源

- **默认动作是往开源仓搬**，除非它明确属于个人隐私数据。
- 不要因为"拿不准"就留空、占位、跳过——拿不准的先搬，搬之前过一遍第 2 条边界。
- 覆盖范围：框架文档、工具层、研究参考库（不含个人交易字段）、选股机制说明书、外部框架台账、Web、知识库、设计文档、规则、启动脚本。
- **空目录 = 没做到**。开源版不能是空壳，缺的部分按第 3 条用虚拟物补。

### 2. 不公布的是个人隐私**数据**，不是个人的**方法**

这是两条不同的线，不许混为一谈：

| | 结论 | 例子 |
|:--|:--|:--|
| **方法 / 框架 / 思想** | ✅ 尽量开源 | 七层流程、状态机铁律、DK 四原则、六信条、六条纪律、工具表、skill 入口、筛选逻辑、组合三轴算法、退出六类理由、复盘方法、台账规矩 |
| **个人隐私数据** | ❌ 不公布 | 真实持仓标的与份额、真实成本、真实盈亏、真实决策日志、真实个股研究过程与判断、DB 本体、凭据、私人配置、会话记忆 |

判不准时问一句：**"这是他怎么做的，还是他做了什么？"** —— 前者开源，后者不公开。

### 3. 影子替代原则（不能开源的，用虚拟影子顶上）

不能开源的东西**不留空**，用一个**影子**替代：**结构/字段/格式与真实完全一致，标的换掉、数据编造**。

> 创始人原话示例：「我假如说投的是腾讯的话，我就是阿里巴巴的那个是虚拟的」

- 真实持仓 `hold_0700.HK.json`（腾讯）→ 公开仓放 `hold_09988.HK.json`（阿里巴巴），字段齐全、份额/成本/盈亏全部为编造的自洽数据。
- 影子标的必须**不在真实持仓里**，且不得是真实持仓标的的改名版。
- 影子数据必须**自洽**（份额 × 价格 = 市值、各项合计对得上），能被工具真读、真算。
- 影子文件头部带一行演示标注（`"demo": true` 或注释 `<!-- DEMO 数据 -->`），防止被误读为真实持仓或投资建议。
- 适用范围：`holdings/`、`portfolio/`、`logs/`、`reviews/`、`alerts/`、`research/060-companies/`、`research/state/`。
- 无法影子替代的（如 2.7GB DB 本体）→ 用小样例数据集或"如何自建"说明书替代，不放本体。**开源版已内置样例库**：`data/market_data.db` = schema 自真仓只读导出 + 19 市场×2 合成标的×875 交易日合成行情（固定种子可复现，`indices.name` 均带「合成样例·非真实行情」标记），使 `fengverify.py`/`fengprobe.py` 开箱可跑；真库本体与真实行情行永不入库。

### 4. 所有原来的工具都要能跑

- 私有版 `tools/` 下的每个工具，开源版**都要能跑**——不是只把文件搬过去就算完。
- 搬完必须验证：`python tools/<tool>.py --help` 或该工具的 selfcheck/冒烟能出结果，不报 ImportError、不因缺文件崩溃。
- 因影子替代或路径差异跑不起来的，**改代码适配开源版路径**，不许留着坏工具（工具崩溃时修依赖，不手工填坑）。
- 验证方式：`python tools/fengprobe.py`（工具链冒烟，任一 fail 即 exit 1）。

### 5. 边界（与第 1 条配套的硬限制）

以下**永不入 git**（见 `.gitignore`）：真实持仓/交易数据、DB 本体及伴生物、凭据与密钥、`FENGMEM.md` / `todo.md` / `Temp/`、`data/config/llm_config.json`、会话记录与私人评估过程。
公开文档禁止写本机绝对路径，只写本仓相对路径或上游 URL。

---

## 二、创始人原话存档（最高优先级）

- **一切设计/产品决策以创始人原话为准**（2026-09-05 定调："我说的话是真正的这个项目的参考，这个项目就以我说的话所有东西为准"）。
- 原话与任何文档冲突时以原话为准，并回头修订 todo / FENGMEM / 设计文档。
- 每轮对话轮末，只有当用户本轮的话**对系统指明方向**时，才把原话**逐字**追加到原话存档（日期 + 轮次 + 原话全文），不概括、不改写、只追加不覆盖。纯操作词（push/继续/好/收到等）不入档，只在 `SESSION-INDEX.md` 留痕；判不准时宁可收入，不漏方向。

## 三、项目一句话

AI+代码协作的投资决策系统：7 层（能力圈 L0 → 市场 M → 硬纪律 L1 → 量化 L2b → 定性 L2a → 碰撞 L3 → 报告 L4）+ 组合层 P。哲学底座 = 6 信条 + DK 四原则（坐标/家国/息价/取舍）+ 六条纪律。双界面：AI 界面 `tools/`、人类界面 `fengweb/`（TS+Express+EJS，端口 23456）。

## 四、skill 入口（标的发现 + 全生命周期接力 + 论断验证）

| Skill | 阶段 | 用法 |
|:------|:-----|:-----|
| `/fengsource` | 标的发现 | thesis-first 自主选股：五条发现路径 → 三道闸门（证据/周期/护城河）→ 候选卡 → 排队七层；**入口禁止跑筛子**（fengbatch 降级为给定名单的执行器、fengscreen 后移为闸门 3），机制说明书 `research/120-idea-sourcing/README.md` |
| `/fengscreen` | 买入前 | 去劣筛选：7 硬指标 + 3 豁免（宁可漏网不可误杀），通过者进 fenginvest；亦为 /fengsource 的**闸门 3** |
| `/fengbatch` | 批量筛选 | 公开list→规则粗筛→规则精筛→幸存者名单→逐只七层→汇总报告；深挖单只走 /fenginvest |
| `/fenginvest <TICKER>` | 买入前 | 完整七层分析（状态机强制顺序），买入后交 /fengholding |
| `/fengholding` | 持有期 | 持仓总览 / 登记新持仓（add 四段+论文建立）/ 单只检查 / 后管理（滚存检测） |
| `/fengexit <TICKER>` | 卖出 | 触发源识别 → 六类理由 → 偏误自查 → 执行卖出闭环 |
| `/fengreview <TICKER>` | 复盘 | 四态假设+红线+健康度评分 → 写回 reviews → 推进下次回顾日期 |
| `/fengverify <N>` | 验证 | 论断复测 → 跑引擎 + 按 000-PROTOCOL 12 项打红绿灯 → 出白话论断卡 |
| `/fengdiscuss` | 观点交锋 | 有锚的讨论对手——读 `Discussion/discuss-config.json` 建锚 → 基于框架+事实辩论 → 落档 `Discussion/` |
| `/fengdiscusslog` | 讨论记录 | 纯记录员——客观记录讨论过程，不发表意见，写入 `Discussion/` |

> skill 正文在 `.agents/skills/<name>/SKILL.md`（本仓已入库，含 13 个 skill）。

## 五、状态机铁律（最高优先级）

状态文件 `research/state/temp_state_<TICKER>.json` 是唯一 truth，**只能经 fengstate.py 修改**。

```bash
python tools/fengstate.py init <TICKER>       # 开始（已存在则拒绝）
python tools/fengstate.py check <TICKER> <层>  # 前置检查，缺前置 exit(1) 打回
python tools/fengstate.py complete <TICKER> <层> <输出文件>  # 出站验证：结构不符拒绝标记
python tools/fengstate.py status <TICKER>      # 进度
python tools/fengstate.py renew <TICKER>       # 每日重分析（归档旧状态）
python tools/fengstate.py skip <TICKER>        # L0=不懂 → 全层跳过
python tools/fengstate.py verify <TICKER>      # 全量验证 + 跨层一致性
```

- 八层顺序：`01-capability → 02-market → 03-discipline → (04-quantitative ∥ 05-qualitative) → 06-collision → 07-report → 08-portfolio`，跳步自动拦截。
- complete 时对输出文件做结构验证（key_fields/min_items），缺关键字段 exit(1)。
- 工具崩溃时：**修依赖，不手工填坑**。每层结果必须由对应工具产生，AI 不得冒充（L1→fengrule.py / L2b→fengquant.py / M→fengdata.py）。

## 六、关键工具

| 类别 | 工具 | 功能 |
|:-----|:-----|:-----|
| 状态机 | fengstate.py | 流程强制（见上；complete 时自动跑跨层一致性检查 + 决策缓存） |
| 数据 | fengdata.py | 行情采集 + `fx` 实时汇率（USDCNY/HKDCNY/USDHKD，失败回退快照）+ `--sina-financials` A股三表 |
| 纪律 | fengrule.py | L1 四灯 + 四 DK 纪律 |
| 量化 | fengquant.py | 6 因子 z-score |
| 技术因子 | fengtechnicals.py | Qlib Alpha158 六因子 20 日滚动 + 历史分位数；纯 Pandas |
| 碰撞 | fengcollision.py | L3 规则树 |
| 筛选 | fengscreen.py | 多因子全市场筛选 |
| 持仓 | fengholding.py | 持仓域入口：登记分析四段/SCHEMA 校验/查询 |
| 监控 | fengwatch.py | daily/check（10 退出规则）/review/sell（卖出闭环）/history/outcome |
| 组合 | fengportfolio.py | 三轴正交盘面 + 买入预算（check）+ 约束再平衡（optimize）+ 风险归因（risk）+ 层次风险平价（hrp） |
| 回测 | fengbacktest.py | 信号驱动组合回测（vnpy 范式 + 基准对比 + 成本模型 + T+1 对齐 + 报告） |
| 回测 | backtest_core.py | 共享回测引擎库（前复权装载/防前视/2000 次 bootstrap/成本 25bps/样本外后 20%/统一事实包） |
| 验证 | fengverify.py | 确定性论断复核引擎（`fengverify.py <claim_id>`） |
| 侧车 | fengtick.py | tickflow 投机侧车薄桥（T0/T2/T4；幽灵原则：只供数据，纪律/卖出留主框架） |
| 门禁 | fengbench.py | FinEval 金融知识门禁 |
| 缓存 | fengcache.py | 决策缓存（内容指纹一致 → 跳过重复验证） |
| 限流 | fengthrottle.py | 限流 + TTL 缓存取数 |
| 写库 | fengdb.py | 统一安全写库入口：safe_batch 可回滚变更集 / undo / snapshot / status |
| 数据 | fengfuyao.py | A股财报回填（同花顺 fuyao） |
| 数据 | fengastock.py | a-stock-data 后端 12 端点按需取数 |
| 数据 | fengstockintl.py | 国际日线四源适配器 probe/fetch/fill |
| 板块 | fengsector.py | 全球板块轮动：universe/update/analyze/longterm/dashboard |
| 一手资料 | fengsec.py | SEC EDGAR 美股一手资料 |
| 估值 | fengvaluation.py | 多方法估值：预期法/两阶段 DCF/敏感性/综合（不编造数字） |
| 因子 | fengfactor.py | 因子验证三件套：Spearman IC/分位收益/换手率 |
| PIT | fengpit.py | PIT 双轴可见性：us / cn / verify 对拍 |
| 引擎 | fenginvest.py | 快查 screen/status（纯数据，非编排） |
| 批量 | fengbatch.py | 批量选股流水线 plan/status/summary |
| 发现 | fengsweep.py | 零输入发现协议游标引擎：需求格子表 + sweep.jsonl 台账 |
| 队列 | fengqueue.py | 自主选股接力调度台账：四态 + CLI status/claim/release |
| 门禁 | fengverify_gate.py | 五门快败闸门（state/structure/report/pipeline/consistency） |
| 探针 | fengprobe.py | 工具链每日冒烟：11 项铁律工具真跑，任一 fail 即 exit(1) |
| 合规 | fengdoclint.py | 文档结构合规扫描（--strict 作闸门） |
| 审计 | report_audit.py | 报告质量三连 check+sources+csvdetect |
| 质量 | fengquality.py | M 层数据质量交叉验证 |
| 严谨 | financial_rigor.py | 市值验算+三情景估值+多源交叉 |
| 代理 | clashproxy.py | Clash 代理节点切换 |
| 速查 | fengview.py | 章节/搜索 |
| 绩效 | fengmetrics.py | 绩效/统计度量工具箱（pwb-toolbox 合并，MIT 归属） |
| 旁路 | fengfinviz.py | finviz 美股旁路数据源 |
| 台账 | fengoslist.py | 开源项目决策台账四子命令：validate/list/stats/due |
| 台账 | fengadopt.py | 外部框架并入对账：verify/list/stats |

> L2a 定性走 `Skill("investment-team")`（skill 引用，非 tools/ 下 .py 文件）。

## 七、输出路径铁律

- 个股分析 → `research/060-companies/<TICKER>-<中文名>/<YYYY-MM-DD>/`（**开源版放影子**，见 §一.3）
- 状态文件 → `research/state/`（fengstate.py 自动管理，勿手改）
- 持仓 JSON → `holdings/hold_<TICKER>.json`（字段见 holdings/SCHEMA.md；**开源版放影子**）
- 决策日志 → `logs/journal.jsonl`；复盘 → `reviews/review_*.md`；提醒 → `alerts/today.json`（**开源版放影子**）
- 金融数据库 → `data/market_data.db`（**开源版 = 合成样例库，已入 git**（见 §一.3，`.gitignore` 白名单例外）；真库本体不入 git；批量写必经 fengdb.py safe_batch，对外只传 `data/changesets/` 增量）
- 研究清单 → `data/config/research_list.json`（只写"研究谁"，禁个人交易字段）
- **开源项目清单 → `data/config/opensource_list.json`**（v2 台账，校验器 `tools/fengoslist.py`）：提到 = 入表，一次都不许漏；结论必须落进结构化字段（`verdict` / `salvage` / `reused_into`）

## 八、外部框架并入铁律（2026-09-17 立）

任何外部项目/框架进入本系统，只有四种状态。**禁止使用"已集成"这类没有落点的说法**：

- **absorbed（并入）** = 正文物理在本仓 + 落在本仓可读路径 + 有明确的自有承接者（`owner` 必须是本仓真实存在的 skill 或工具）。三条全中才算。
- **kept（留档）** = 正文物理在本仓、供人与 Agent 查阅，但本系统**没有**自有承接者、也不注册任何入口（`owner` 必须为空）。
- **referenced（引用）** = 本仓无正文副本，仅文档写明上游仓库 + 上游文件路径。公开文档禁止写本机绝对路径，只写本仓相对路径或上游 URL。
- **superseded（自有承接）** = 上游有该能力，但本系统已用自有 skill/工具承接，不再引用上游。`owner` 必须写明承接者。

台账落点：`data/config/opensource_list.json`（登记）+ `research/130-external-frameworks/<项目>/ADOPTION.json`（逐文件归属）。对账器：`python tools/fengadopt.py verify`。

## 九、提交与验证规矩（2026-09-09 立规）

- 用户没有明确要求时，commit / push **一律不跑回归测试**（`tools/fengwebcheck.py` 等体检脚本）。只有用户明确说了"跑回归/体检/验证一下"才跑。
- 默认提交流程 = 改完 → 保证能编译 → commit → 双远端 push。不自行加戏跑全站体检。
- **例外（本仓特有）**：按 §一.4「所有原来的工具都要能跑」，工具搬入后须做一次冒烟验证（`fengprobe` 或该工具 selfcheck），这属于交付验收而非全站体检。

## 十、数据与搜索原则

- 数据源不限，哪个准用哪个（Futu OpenD / yfinance / AKShare / baostock），多源交叉验证。
- **不凭训练知识硬答，先搜再说；没搜到就说没搜到**，失败标"未验证"。
- 铁律：无来源 = 不存在。每个判断必须有来源 URL。
- **数据管理铁律**：批量写 `data/market_data.db` 必须经 `tools/fengdb.py safe_batch` 可回滚；对外同步只传增量 changeset。规范见 [docs/DATA-MANAGEMENT.md](docs/DATA-MANAGEMENT.md)。

## 十一、Windows 编码

读写含中文文件一律显式 `encoding="utf-8"`（默认 GBK 会乱码）。打印到 stdout 同理（emoji/中文会抛 `UnicodeEncodeError`）。

## 十二、隐私红线（开源版口径，配合 §一 使用）

- **不入 git**：真实持仓/交易数据、`research/060-companies/` 真实个股研究、`research/state/` 真实运行态、`research/speculative/`、DB 本体及伴生物（`.snap*`/changesets/cache/sec/pit/reports）、`knowledge/personal/`、`FENGMEM.md`、`todo.md`、`Temp/`、`data/config/llm_config.json`、`.env*`、密钥、会话记录。
- **入 git**：框架文档、工具、`Discussion/`（只有观点交锋，无交易数据）、`data/config/research_list.json`（只写研究谁）、`data/config/opensource_list.json`、`.agents/skills/`（skill 正文）、以及按 §一.3 制作的**影子数据**。
- 公开仓库（Open-FengInvest）必须**零真实个人数据**——影子不算个人数据，但影子必须真的是影子（换标的、编数据），不许拿真实数字改个名就放出去。
