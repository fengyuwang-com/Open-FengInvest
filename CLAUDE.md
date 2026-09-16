# FengInvest — 七层决策框架

> 结构根本标准：[docs/standards.md](docs/standards.md) — 改动必须满足全部标准
> 持仓数据模型：[holdings/SCHEMA.md](holdings/SCHEMA.md) — 三轴正交分类 + 资金墙语义（本地，不开源）

## 简介

AI+代码协作投资分析系统。7层：能力圈(L0)→市场数据(M)→硬纪律(L1)→量化(L2b)→定性(L2a)→碰撞(L3)→报告(L4)，外加组合层(P)。状态机物理卡死执行顺序。双界面：AI 界面 tools/，人类界面 fengweb/ (TS+Express+EJS)。

**风险盘面 = 正交维度（非资金墙）**：每笔持仓标注三根正交轴 `market`(CN_A/CN_HK/CN_OVS/US/GLOBAL) × `segment`(可扩展细分板块词汇) × `qualifier`(cash/quasi_cash)。集中度按轴计算（`python tools/fengportfolio.py check`），词汇表可扩展、不预设命名桶。`capital_zone` 仅作**买入预算**（境内池/境外池），不产生风险告警。跨币种统一折算人民币（`python tools/fengdata.py fx` 实时汇率，失败回退持仓快照）。

## 目录结构

> **结构唯一基准 = [docs/PROJECT-STRUCTURE.md](docs/PROJECT-STRUCTURE.md)**（全目录树 + 入库🟢/本地🔴分级 + "什么文件写到哪里"速查表）。本节只留摘要，改结构先改基准文件再同步这里。

```
FengInvest/
├── docs/ tools/ rules/ knowledge/   🟢 框架文档 / 71 工具 / 纪律规则 / DK知识库
├── design/ Discussion/              🟢 设计决策+创始人原话存档 / 讨论档案（入库公开）
├── research/                        🟢 研究参考（060-companies/state/speculative 除外）
├── data/config/                     🟢 清单类（research_list/opensource_list/…）；llm_config.json 除外🔴
├── fengweb/                         🟢 Web UI (TS/Express/EJS, 端口 23456)
├── data/market_data.db 2.7GB        🔴 金融数据库本体不入 git；对外只传 data/changesets/ 增量
├── holdings/ portfolio/ logs/ reviews/ alerts/   🔴 个人持仓与决策（本地）
├── research/060-companies/ state/ speculative/   🔴 个股分析/状态机/投机（本地）
├── FENGMEM.md todo.md Temp/         🔴 会话记忆/任务账本（本地）
└── start-web.bat/sh                 🟢 启动脚本
```

## 入口

```bash
/fenginvest <TICKER>    # 买入前：完整七层分析（状态机强制执行）
/fengscreen             # 买入前：去劣筛选（7硬指标+3豁免，候选池体检/行业扫描）
/fengbatch              # 批量选股：公开list→规则粗筛→规则精筛→幸存者→逐只七层→汇总报告
/fengholding            # 持有期：总览/登记分析(四段)/单只检查/后管理
/fengexit <TICKER>      # 卖出：触发源→理由分类→卖出前检查→滚存/清仓执行
/fengreview <TICKER>    # 复盘：论文有效性评估→写回 reviews→推进下次回顾
/fengverify <N>         # 论断验证/复测：跑引擎+12项协议红绿灯→出白话论断卡
/fengdiscuss            # 观点交锋：读 Discussion/discuss-config.json 建锚→基于框架+事实辩论→落档 Discussion/（独立于个股分析）
/fengdiscusslog         # 讨论记录员：客观记录讨论过程，不发表意见，写入 Discussion/
```

五 skill 全景：买入前（fengscreen 去劣 → fenginvest 七层）→ 持有期（fengholding）→ 卖出（fengexit）→ 复盘（fengreview）。另设 `/fengbatch`（批量选股流水线）、`/fengverify`（论断验证）与 `/fengdiscuss` + `/fengdiscusslog`（观点交锋/记录，落档 `Discussion/`，独立于个股分析）。



## 引用文档

| 层 | 文档 | 工具 | AI做 |
|:---|:-----|:-----|:------|
| L0 | docs/01-philosophy.md | 搜索 | 三问判断懂不懂 |
| M | docs/02-market.md | fengdata.py+搜索 | 交叉验证 |
| L1 | docs/03-discipline.md | fengrule.py | 纪律检查 |
| L2b | docs/05-quantitative.md | fengquant.py | 因子解读 |
| L2a | docs/04-qualitative.md | Skill("investment-team")·skill 引用非 tools/ 文件 | 四大师分析 |
| L3 | docs/06-collision.md | — | 反方检查+碰撞 |
| P | docs/09-portfolio.md | fengportfolio.py | 三轴集中度+预算 |
| L4 | docs/07-report.md | — | 双报告 |

## 状态机

```bash
python tools/fengstate.py init <TICKER>       # 开始
python tools/fengstate.py check <TICKER> <层>  # 前置检查
python tools/fengstate.py complete <TICKER> <层> <文件> # 完成
python tools/fengstate.py status <TICKER>      # 进度
python tools/fengstate.py reset <TICKER>       # 重置
```

状态文件在 `research/state/`（gitignored）。

## Web UI

```bash
cd fengweb && npm run build && node dist/index.js  # 或双击 start-web.bat → :23456
```

11 页 + 5 详情路由：总览 / 系统架构 / 持仓总览+详情 / 研究 / 知识库 / 钱仓滚存 / 决策日志 / 市场数据(53源) / 持仓监控(exit+复盘+卖出) / 持仓历史 / 股票分析。持仓页显示市场/板块徽章 + 准现金标注 + 实时汇率脚注（快照回退）。

## Python 工具集（71 个）

| 类别 | 工具 | 功能 |
|:-----|:-----|:------|
| **引擎** | fengstate.py | 状态机 |
| | fenginvest.py | 快查 screen/status（纯数据，非编排；完整七层由 skill 驱动）；fenginvest 强依赖 |
| | fengcollision.py | L3 碰撞引擎(规则树) |
| **数据** | fengdata.py | 行情采集 + `fx` 实时汇率模式 |
| | fengmarket.py / fengmarketdata.py | 市场数据 |
| | fengfundamentals.py | 基本面管线 |
| | fengdbrefine.py | 分红回填 |
| | fengindexdb.py (+akshare/verify) | 指数数据 |
| | fengstockdb.py / fengstockcnfix.py | 股票 DB 构建/补爬 |
| | fengdb.py | 统一安全写库：safe_batch 自动产可回滚变更集 + undo/snapshot/status（批量写库必经）。safe_batch 为 Python import 接口（上下文管理器），CLI 仅 undo/snapshot/status，见 docs/DATA-MANAGEMENT.md |
| | fengfuyao.py | A股财报回填（同花顺 fuyao 免费接口，全市场 5,828 只断点续传） |
| | fengastock.py | A股 12 端点按需取数（估值史/申万行业变迁/复权因子/社融PMI/龙虎榜等，不入库） |
| | fengstockintl.py | 国际日线四源适配器（probe/fetch/fill，默认 dry-run） |
| | fengsector.py | 板块轮动三层（US SPDR/全球 ETF/申万31）：update 入库 + analyze RRG 象限 + longterm 沉寂体检；GUI 页 /sector（ECharts 本地 vendor） |
| | feng10k.py | 年报分析 |
| | feng_add_capex.py / feng_import_csmar.py | CSMAR 导入 |
| | fill_hk_gaps.py / fix_hk_nodata.py | HK 数据修复 |
| | feng_total_return.py | 总回报指数 |
| | xueqiu_scraper.py / twstock_data.py | 数据采集 |
| **回测** | fengbacktest.py | 信号驱动组合回测（vnpy 范式+成本+T+1+涨跌停过滤+quantstats 报告 + `--sig-csv`/`--walkforward-fold`/`--grid` 三参数） |
| | backtest_core.py | 共享回测引擎库（前复权/防前视/前向收益/2000 次 bootstrap/成本 25bps/样本外 20%/协议打标/统一事实包=白话卡唯一填数源） |
| | fengverify.py | 论断复核引擎（cli: `fengverify.py <claim_id>`；#1 年线 → ❌、#8 月暴涨 → ❌；#3 ✅27.98%落带 / #5 🟡1.12有条件 / #6 ✅2.43倍，2026-09-10 复测） |
| | data_inventory.py | data/ 只读盘点（体积/可回收快照清单，报告落 data/inventory_report.md 不入库） |
| | fengverify_gate.py | 五门快败闸门（state/structure/report/pipeline/consistency）；fengcheck 强依赖 |
| | fengdoclint.py | 文档结构合规扫描（双格式+总览，--strict 作闸门）；fengcheck 强依赖（Gate 2） |
| | fengquality.py | M 层数据质量交叉验证（stockanalysis PE 对比，>10% FAIL）；fenginvest/fengcheck 强依赖 |
| **侧车** | fengtick.py | tickflow 投机侧车薄桥（T0 候选/T2 防线位/T4 监控，纯本地零依赖，幽灵原则） |
| **门禁** | fengbench.py | FinEval 金融知识门禁（学术 dev/val/test 集本地就绪，selfcheck 全绿；评分需 API key） |
| **分析** | fengquant.py | 量化因子 z-score |
| | fengrule.py | 纪律检查 |
| | fengscreen.py | 多因子全市场筛选 + `--hard-rules` 纯规则精筛（7硬指标+3豁免） |
| | fengbatch.py | 批量选股流水线：plan/status/summary（公开list→粗筛→精筛→幸存者→逐只七层）；幸存者七层走 fenginvest，fengbatch/fenginvest 强依赖 |
| | financial_rigor.py | 市值验算+三情景估值+多源交叉；fenginvest 强依赖 |
| | morningstar_fair_value.py | 晨星公允价值 |
| | leftright.py | 左侧/右侧回测 |
| | star_history_chart.py | 明星股历史回测 |
| | stock_screener.py | 选股筛选器 |
| | fengvaluation.py | 多方法估值（预期法/两阶段 DCF/敏感性/综合） |
| | fengfactor.py | 因子验证（IC/分位收益/换手） |
| | fengpit.py | PIT 双轴可见性（companyfacts/cn_financials） |
| | fengsec.py | SEC EDGAR 一手资料（facts PIT 双轴/financials/ownership 内部人/13f，edgartools 数据层） |
| **持仓** | fengwatch.py | 持仓监控（10 退出规则/卖出闭环） |
| | fengholding.py | 持仓域入口：登记分析四段/SCHEMA 校验/查询 |
| | fengportfolio.py | 组合三轴正交盘面+买入预算+optimize 再平衡+risk 下行贡献+hrp 层次风险平价 |
| **辅助** | fengview.py | 速查搜索 |
| | fenglearn.py | 学习路径 |
| | fenghealth.py | 系统健康检查 |
| | fengcost.py | 交易规费(19市场三档) |
| | clashproxy.py | Clash 代理切换（yfinance 限流时主动切）；fenginvest 数据采集强依赖 |
| | report_audit.py | 报告准出抽检（check+sources+csvdetect）；fenginvest（L4）/fengcheck 强依赖（Gate 3） |
| | sync-ai-berkshire.py | AI Berkshire 同步 |
| | fengquick.py | 快速查询 |
| | renumber_refs.py | 编号重排 |

## ⚠️ Proxy 主动切换

yfinance限流时主动切 Clash 节点，不等待自动解除。

```bash
python tools/clashproxy.py status|list|jp|us|sg
```

触发：`YFRateLimitError` / 连续3+ nodata / `consecutive_fails >= 3`。>50只批次中途至少换一次节点。API端口9097不可用时手动切 Clash Verge GUI。

## 知识库引用

主索引：`research/010-REFERENCE-TREE.md`

| 领域 | 位置 | 用途 |
|:------|:------|:------|
| 速查总表 | research/000-QUICK-REFERENCE.md | 关键阈值 |
| 主索引 | research/010-REFERENCE-TREE.md | 文档映射 |
| 宏观 | research/010-macro/ | M层宏观判断 |
| 市场情绪 | research/020-market/ | M层趋势/情绪 |
| 资产类别 | research/030-asset-classes/ | M层估值参考 |
| 大师视角 | research/040-people/named/(43位) | L2a/L3判断 |
| 投资策略 | research/050-strategies/(10种) | 风格参考 |
| 公司分析 | research/060-companies/ — **本地 gitignored** | 个股七层分析 |
| 行业报告 | research/070-reports/ | 行业深度 |
| 组合管理 | research/090-portfolio-management/ | P层仓位/卖出 |
| 学习路径 | research/100-learning-investment/ | 投资学习 |
| 策略验证 | research/110-strategy-verification/ | 52条论断回测 |

## 目录铁律

- 个股分析 → `research/060-companies/<TICKER>-<中文名>/<YYYY-MM-DD>/`（本地，gitignored）
- 状态文件 → `research/state/temp_state_<TICKER>.json`（fengstate.py 自动管理）
- 每层 skill 输出路径写死在 skill 指令中
- 持仓 JSON → `holdings/hold_<TICKER>.json`（本地，gitignored；三轴字段见 holdings/SCHEMA.md）
- 研究清单 → `data/config/research_list.json`（独立于持仓的研究/候选/观察清单，status: researching/candidate/watching/parked/holding）
- **开源项目清单 → `data/config/opensource_list.json`**：任何对话/文档中提及的开源项目（无论是否采用）必须登记入表，status: adopted/evaluating/noted/rejected。规则：提到 = 入表，一次都不许漏。

## 速查工具

```bash
python tools/fengview.py                    # 列出章节
python tools/fengview.py macro|position|sell|all
python tools/fengview.py --search <词>      # 全文搜索
python tools/fenginvest.py screen <TICKER>  # 纯数据
python tools/fenginvest.py status <TICKER>  # 状态
python tools/fengdata.py fx                 # 实时汇率（USDCNY/HKDCNY/USDHKD）
python tools/fengportfolio.py check         # 三轴集中度盘面+买入预算
```

## ⚠️ Windows GBK 编码

`open()` 默认 GBK，写中文以 UTF-8 读则乱码。所有 `open()` 显式指定编码：
```python
with open(path, "w", encoding="utf-8") as f:
with open(path, "r", encoding="utf-8") as f:
```
诊断：`python -c "open('f.py', encoding='utf-8').read()"` 抛 UnicodeDecodeError → GBK。修复：GBK 读出→UTF-8写回。

## 数据库状态

多市场 SQLite（`data/market_data.db`，gitignored）：13,053,253 行日线 / 19 国 21 市场活跃标的最新统一至 2026-08-21 收盘；指数主档 2,126 只（2,118 只有行情）。完整性审核见 `research/070-reports/DATABASE-AUDIT-20260723.md`，数据清单见 `research/070-reports/DATA-INVENTORY.md`，构建记录见 `docs/todo.md`。

**数据管理铁律**见 [docs/DATA-MANAGEMENT.md](docs/DATA-MANAGEMENT.md)：任何批量写入必须经 `tools/fengdb.py safe_batch` 可回滚（自动产 changeset 变更集可 invert 精确撤销 + 文件快照 + 分批事务）；对外同步只传增量。

## 数据原则

- 数据源不限，哪个准用哪个(Futu OpenD/yfinance/AKShare/baostock)。多源交叉验证。
- 搜索优先：不凭训练知识回答，先搜再说。没搜到就说没搜到
- 批量写 market_data.db 必须可回滚；对外同步只传增量 changeset。详见 docs/DATA-MANAGEMENT.md

## ⚠️ 工具完整性铁律

```
工具崩溃时：修依赖，不手工填坑。
```

每层结果必须由对应工具产生，AI不得冒充：
- L1→fengrule.py / L2b→fengquant.py / M→fengdata.py
- 搜索→opencli（或等价搜索工具），失败标"未验证"
- 定性→Skill("investment-team") 4 Agent并行（skill 引用，非 tools/ 下 .py 文件）

状态机 cmd_complete 已配备输出验证(缺关键字段 exit(1))。
