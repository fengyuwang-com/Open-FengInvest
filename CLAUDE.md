# FengInvest — 七层决策框架

> 结构根本标准：[docs/standards.md](docs/standards.md) — 改动必须满足全部标准
> 持仓数据模型：[holdings/SCHEMA.md](holdings/SCHEMA.md) — 三轴正交分类 + 资金墙语义（本地，不开源）

## 简介

AI+代码协作投资分析系统。7层：能力圈(L0)→市场数据(M)→硬纪律(L1)→量化(L2b)→定性(L2a)→碰撞(L3)→报告(L4)，外加组合层(P)。状态机物理卡死执行顺序。双界面：AI 界面 tools/，人类界面 fengweb/ (TS+Express+EJS)。

**风险盘面 = 正交维度（非资金墙）**：每笔持仓标注三根正交轴 `market`(CN_A/CN_HK/CN_OVS/US/GLOBAL) × `segment`(可扩展细分板块词汇) × `qualifier`(cash/quasi_cash)。集中度按轴计算（`python tools/fengportfolio.py check`），词汇表可扩展、不预设命名桶。`capital_zone` 仅作**买入预算**（境内池/境外池），不产生风险告警。跨币种统一折算人民币（`python tools/fengdata.py fx` 实时汇率，失败回退持仓快照）。

## 目录结构

```
FengInvest/
├── CLAUDE.md, README.md
├── docs/              ← 分层文档 + 结构标准
├── tools/             ← 44 个 Python 工具
├── knowledge/         ← DK知识库(principles/discipline/methodology/market_view)
├── holdings/          ← 持仓 (hold_<TICKER>.json) — 本地，gitignored
├── alerts/            ← 触发引擎输出 — 本地
├── logs/              ← 决策日志 (journal.jsonl) — 本地
├── reviews/           ← 复盘 (review_*.md) — 本地
├── portfolio/         ← 持仓管理 (current.md 盘面) — 本地
├── rules/             ← 纪律规则
├── research/          ← 分析产出+参考(010-macro ~ 110-strategy-verification; 060-companies 本地)
├── fengweb/           ← Web UI (TS/Express/EJS, 端口 23456)
├── start-web.bat/sh   ← 启动脚本
└── start-system-map.bat/sh ← 系统架构图静态服务
```

## 入口

```bash
/fenginvest <TICKER>    # 完整七层
Skill("fenginvest")      # skill 入口
```

自动走7层，状态机强制执行（单 skill 统一调度）：
```
/fenginvest <TICKER>    # 完整七层
```

## 引用文档

| 层 | 文档 | 工具 | AI做 |
|:---|:-----|:-----|:------|
| L0 | docs/01-philosophy.md | 搜索 | 三问判断懂不懂 |
| M | docs/02-market.md | fengdata.py+搜索 | 交叉验证 |
| L1 | docs/03-discipline.md | fengrule.py | 纪律检查 |
| L2b | docs/05-quantitative.md | fengquant.py | 因子解读 |
| L2a | docs/04-qualitative.md | investment-team(4 Agent) | 四大师分析 |
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

## Python 工具集（44 个）

| 类别 | 工具 | 功能 |
|:-----|:-----|:------|
| **引擎** | fengstate.py | 状态机 |
| | fenginvest.py | 单命令编排 |
| | fengcollision.py | L3 碰撞引擎(规则树) |
| **数据** | fengdata.py | 行情采集 + `fx` 实时汇率模式 |
| | fengmarket.py / fengmarketdata.py | 市场数据 |
| | fengfundamentals.py | 基本面管线 |
| | fengdbrefine.py | 分红回填 |
| | fengindexdb.py (+akshare/verify) | 指数数据 |
| | fengstockdb.py / fengstockcnfix.py | 股票 DB 构建/补爬 |
| | feng10k.py | 年报分析 |
| | feng_add_capex.py / feng_import_csmar.py | CSMAR 导入 |
| | fill_hk_gaps.py / fix_hk_nodata.py | HK 数据修复 |
| | feng_total_return.py | 总回报指数 |
| | xueqiu_scraper.py / twstock_data.py | 数据采集 |
| **分析** | fengquant.py | 量化因子 z-score |
| | fengrule.py | 纪律检查 |
| | fengscreen.py | 多因子全市场筛选 |
| | financial_rigor.py | 市值验算+三情景估值 |
| | morningstar_fair_value.py | 晨星公允价值 |
| | leftright.py | 左侧/右侧回测 |
| | star_history_chart.py | 明星股历史回测 |
| | stock_screener.py | 选股筛选器 |
| **持仓** | fengwatch.py | 持仓监控 |
| | fengportfolio.py | 组合三轴正交盘面+买入预算 |
| **辅助** | fengview.py | 速查搜索 |
| | fenglearn.py | 学习路径 |
| | fenghealth.py | 系统健康检查 |
| | fengcost.py | 交易规费(19市场三档) |
| | clashproxy.py | Clash 代理切换 |
| | report_audit.py | 报告准出抽检 |
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

多市场 SQLite（`data/market_data.db`，gitignored）：2.2GB/13M 日线/19 市场/2,020 只。完整性审核见 `research/070-reports/DATABASE-AUDIT-20260723.md`，数据清单见 `research/070-reports/DATA-INVENTORY.md`，构建记录见 `docs/todo.md`。

## 数据原则

- 数据源不限，哪个准用哪个(Futu OpenD/yfinance/AKShare/baostock)。多源交叉验证。
- 搜索优先：不凭训练知识回答，先搜再说。没搜到就说没搜到

## ⚠️ 工具完整性铁律

```
工具崩溃时：修依赖，不手工填坑。
```

每层结果必须由对应工具产生，AI不得冒充：
- L1→fengrule.py / L2b→fengquant.py / M→fengdata.py
- 搜索→Search-King，失败标"未验证"
- 定性→investment-team 4 Agent并行

状态机 cmd_complete 已配备输出验证(缺关键字段 exit(1))。
