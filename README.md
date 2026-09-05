# FengInvest — 个人投资研究操作系统

> 七层决策框架 · 多市场数据库 · 44 个 Python 工具 · Web UI · 52 条论断验证 · 43 位大师知识库

---

## 目录结构

```
FengInvest/
├── CLAUDE.md           — 项目入口 + 协作指令
├── docs/               — 框架文档（七层定义 + 标准 + 路线图）
├── tools/              — 44 个 Python 工具
├── knowledge/          — DK 投资知识库（原则/纪律/市场观/方法论）
├── research/           — 研究产出 + 参考
│   ├── 010-macro/      — 宏观（经济周期/利率/通胀）
│   ├── 020-market/     — 市场（VIX/情绪/资金流）
│   ├── 030-asset-classes/ — 资产（股票/债券/商品/房产）
│   ├── 040-people/     — 43 位投资大师知识库
│   ├── 050-strategies/ — 10 种策略深度研究
│   ├── 060-companies/  — 个股七层分析（本地，gitignored，不开源）
│   ├── 070-reports/    — 行业深度报告
│   ├── 090-portfolio-management/ — 组合构建/仓位/卖出框架
│   ├── 100-learning-investment/  — 投资学习路径
│   └── 110-strategy-verification/ — 52 条论断回测验证
├── fengweb/            — Web UI（TS/Express/EJS，端口 23456）
│   └── views/          — 17 个 EJS 模板
├── rules/              — 纪律规则源文件
├── holdings/           — 持仓记录（本地 / 不开源）
├── portfolio/          — 组合当前状态（本地）
├── alerts/             — 触发引擎输出（本地）
├── logs/               — 决策日志/运行日志（本地）
├── reviews/            — 投资复盘
├── data/               — SQLite 数据库（gitignored）
└── start-web.bat/sh    — Web UI 启动脚本
```

> 说明：`holdings/`、`portfolio/`、`logs/`、`reviews/`、`alerts/`、`research/060-companies/` 等含个人数据，已 gitignore，不在公开仓库中。

---

## 七层决策框架

状态机强制执行：跳步自动拦截，工具崩溃修依赖不手工填坑。

| 层 | 执行者 | 产出 |
|:---|:-------|:-----|
| **L0 能力圈** | AI + 搜索 | 三问判断：懂/不充分懂/不懂 |
| **M 市场数据** | fengdata.py + AI | 4 灯（宏观/估值/趋势/情绪）+ DK 周期定位 |
| **L1 硬纪律** | fengrule.py + AI | 8 规则 + 4 DK 规则红黄灯 |
| **L2b 量化因子** | fengquant.py | 10 因子 z-score vs 同业 |
| **L2a 定性分析** | 4 AI Agent 并行 | 段永平/巴菲特/芒格/李录四视角 |
| **L3 碰撞引擎** | AI | 反方检查 + DK 审计 + 偏误检查 |
| **P 组合检查** | fengportfolio.py + AI | 三轴集中度 + 相关性 + 压力测试 |
| **L4 报告** | AI | 华尔街分析师版结构化报告 |

---

## 风险盘面：正交维度（非资金墙）

持仓按三根**正交轴**分类，集中度由运行期计算生成，不预设命名桶：

| 轴 | 含义 | 参考词汇（可扩展） |
|:---|:-----|:-------------------|
| **market** 家国市场 | 经济暴露在哪 | CN_A / CN_HK / CN_OVS(中概) / US / GLOBAL |
| **segment** 细分板块 | 行业细分（够细，能区分同行业内不同风险驱动） | 互联网 / 半导体.AI算力 / 半导体.存储 / 保险 / 银行 / 医药 / 家电 / 低波高息 … |
| **qualifier** 表现质 | 现金属性 | cash(真现金) / quasi_cash(准现金，如低波高息 ETF) |

**关键语义**：
- 资金墙（境内/境外账户资金池）**只约束现金划转**，是买入预算，不是风险维度——不产生"境外超配"类告警。
- 准现金（如 LVHI 低波高息 ETF）当现金使用，与真现金一起进**资金池**，不参与权益集中度。
- 跨币种统一折算人民币：`python tools/fengdata.py fx` 实时汇率（USDCNY/HKDCNY/USDHKD），失败回退持仓快照。

**集中度阈值**（占总资产 %，`python tools/fengportfolio.py check` 计算）：

| 维度 | 🟡 黄（关注） | 🔴 红（超配） |
|:-----|:---:|:---:|
| market 轴 | >28% | >35% |
| segment 轴 | >20% | >25% |
| market×segment 组合 | >15% | >20% |
| 单只标的 | >15% | >20% |

---

## 投资哲学

**DK 四大原则** — 坐标（坐标系？）、家国（与国家利益一致？）、息价（安全边际>30%？）、取舍（有更好去处？）——任一红灯即 PASS。

**五条纪律规则** — 2638 法则、年线法则、后发制人、买分歧卖共识、钱仓滚存。

**43 位大师知识库** — `research/040-people/named/`，含段永平/巴菲特/芒格/李录/卡拉曼/林奇/西蒙斯等。

---

## 数据管道

SQLite · 13M 行日线 · 19 市场 · 2,020 只

| 市场 | 范围 | 基本面 |
|:-----|:-----|:-------|
| US (NYSE/NASDAQ) | 503 只 | 93% |
| CN (沪深京) | 5,828 只（CSMAR 35 年） | 100% |
| HK (蓝筹) | 85 只 | 71% |
| 其他 16 市场 | ~2,020 只 | ❌ |

**数据源**：yfinance / Futu OpenD / AKShare / baostock / CSMAR，多源交叉验证。

---

## 分析能力

**量化**：10 因子（价值/质量/成长/财务健康）z-score 排名 + 52 条投资论断回测。

**公司研究**：`research/060-companies/`（本地）——每只含四大师分析 + 10 年利润预测 + 安全边际压力测试。

**行业报告**：`research/070-reports/` — AI 全产业链、中国汽车、核电、游戏等深度研究。

**策略研究**：`research/050-strategies/` — 破净股、AI 赛道、晨星估值、回购池等 10 种策略。

---

## 工具集（44 个 Python 工具）

| 类别 | 工具 | 功能 |
|:-----|:-----|:------|
| **引擎** | fengstate.py | 状态机（init/check/complete/status/reset） |
| | fenginvest.py | 单命令编排 |
| | fengcollision.py | L3 碰撞引擎（规则树） |
| **数据** | fengdata.py | 行情采集 + `fx` 实时汇率（USDCNY/HKDCNY/USDHKD） |
| | fengmarket.py / fengmarketdata.py | 市场数据 |
| | fengfundamentals.py | 基本面管线 |
| | fengdbrefine.py | 分红回填 |
| | fengindexdb.py / fengindexdb_akshare.py / fengindexdb_verify.py | 指数数据 |
| | feng_add_capex.py / feng_import_csmar.py | CSMAR 导入 |
| | fengstockcnfix.py / fill_hk_gaps.py / fix_hk_nodata.py | 补爬修复 |
| | fengstockdb.py | 股票数据库构建 |
| | feng_total_return.py | 总回报指数 |
| | feng10k.py | 年报分析 |
| **分析** | fengquant.py | 量化因子 z-score |
| | fengrule.py | 纪律检查 |
| | fengscreen.py | 多因子全市场筛选 |
| | financial_rigor.py | 市值验算 + 三情景估值 |
| | morningstar_fair_value.py | 晨星公允价值 |
| | leftright.py | 左侧/右侧回测 |
| | star_history_chart.py | 明星股历史回测 |
| | stock_screener.py | 选股筛选器 |
| **持仓** | fengwatch.py | 持仓监控（daily/check/review/sell/history） |
| | fengportfolio.py | 组合三轴正交盘面 + 买入预算 |
| **工具** | fengview.py | 速查/搜索 |
| | fenglearn.py | 学习路径 |
| | fenghealth.py | 系统健康检查 |
| | fengcost.py | 交易规费（19 市场三档） |
| | clashproxy.py | Clash 代理切换（yfinance 限流绕过） |
| | report_audit.py | 报告准出抽检 |
| | sync-ai-berkshire.py | AI Berkshire 同步 |
| | xueqiu_scraper.py / twstock_data.py | 数据采集 |

---

## Web UI

`fengweb/` — TypeScript + Express + EJS，端口 **23456**：

| 页面 | 功能 |
|:-----|:------|
| 总览 | 系统状态 + 快速入口 |
| 系统架构 | system-map 可视化 |
| 持仓总览/详情 | 三轴徽章（市场/板块/准现金）+ 实时汇率 |
| 市场数据 | 53 数据源可视化 |
| 持仓监控 | exit/复盘/卖出决策 |
| 持仓历史 | 胜率/亏损统计 |
| 研究文档 | 检索浏览 |
| 大师知识库 | 43 位大师浏览 |
| 钱仓滚存 | 仓位管理 |
| 决策日志 | 投资决策记录 |
| 股票分析 | 个股分析入口 |

启动：`cd fengweb && npm install && npm run build && node dist/index.js` → `localhost:23456`

---

## 快速开始

```bash
# 安装可选增强依赖（核心工具零依赖）
pip install -r requirements.txt

# 实时汇率
python tools/fengdata.py fx

# 组合盘面（三轴集中度 + 买入预算）
python tools/fengportfolio.py check

# 完整七层分析
/fenginvest <TICKER>        # CLI 入口，AI 自动执行全流程

# 速查
python tools/fengview.py              # 系统速查
python tools/fengview.py --search <词> # 全文搜索
python tools/fenginvest.py screen <TK> # 纯数据
python tools/fenginvest.py status <TK> # 状态
```

---

## 技术栈

| 层 | 技术 |
|:---|:-----|
| 语言 | Python 3.8+ |
| Web | TypeScript + Express + EJS |
| 数据库 | SQLite |
| 数据源 | yfinance / Futu / AKShare / baostock / CSMAR |
| AI 分析 | Claude AI Agents（四大师并行） |
| 回测 | 自研（leftright.py + 52 论断） |

---

GNU AGPL-3.0v3 — 仅限研究参考，不构成投资建议。
