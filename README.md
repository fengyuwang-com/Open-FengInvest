# FengInvest — 个人投资研究操作系统

> 七层决策框架 · 多市场数据库 · 62 个 Python 工具 · Web UI · 52 条论断验证 · 43 位大师知识库
> 📖 读不懂？先看 [docs/00-system-guide.md](docs/00-system-guide.md)（人话版系统指南）

---

## 目录结构

> 完整分级地图见 [docs/PROJECT-STRUCTURE.md](docs/PROJECT-STRUCTURE.md)（🟢入库 / 🔴本地 不上传 + "什么文件写到哪里"速查表）。

```
FengInvest/
├── CLAUDE.md / AGENTS.md — 项目入口 + 协作指令
├── docs/               — 框架文档（七层定义 + 标准 + 结构图谱）
├── tools/              — 63 个 Python 工具
├── knowledge/          — DK 投资知识库（原则/纪律/市场观/方法论）
├── design/             — 设计决策档案（宪法/创始人原话存档/会话索引）
├── Discussion/         — 观点交锋档案（/fengdiscuss 落档）
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
│   ├── 110-strategy-verification/ — 52 条论断回测验证
│   └── fx/             — 汇率研究
├── fengweb/            — Web UI（TS/Express/EJS，端口 23456）
├── rules/              — 纪律规则源文件
├── data/config/        — 清单配置（研究清单/开源项目登记/公司名表，入库）
├── start-web.bat/sh    — Web UI 启动脚本
```

**以下为项目一部分、但只存本机不上传**（gitignored）：

- `data/market_data.db`（2.7GB 金融数据库：21 市场 1,305 万行日线 + A股财报 38 万行）——太大不入 git，对外同步只传 `data/changesets/` 增量变更集
- `holdings/` `portfolio/` `logs/` `reviews/` `alerts/` — 个人持仓、决策日志、复盘、提醒
- `research/060-companies/` `research/state/` `research/speculative/` — 个股分析 / 状态机 / 投机研究
- `data/config/llm_config.json` — BYOK 的 LLM key，永不出本机
- `FENGMEM.md` `todo.md` `Temp/` — 会话记忆与任务账本

---

## 核心信条

> **认知不变现等于没认知** —— 确信正确的机会必须重仓，否则认知只是自我感动。

- **集中投资立场**：研究一家公司极其困难；一旦经框架确信公司没问题，就该买。好机会不抓住 = 便宜货扔掉、好东西扔掉、烂货买进来、贵的买进来（巴菲特："对懂行的投资者，传统分散化没有意义"；段永平：苹果曾占 80% 仓位）。
- **不因价格卖，但因论文卖**：亏损本身不是卖出理由；论文（基本面判断）证伪才是。论文缺失的"亏损持有" = 处置效应。
- **仓位 = 确定性 × 安全边际**：确定性越高仓位越重，但设绝对上限，防单一判断错误毁灭组合。
- 完整论述见 [docs/01-philosophy.md](docs/01-philosophy.md)（定稿）与 [Discussion/](Discussion/README.md)（观点交锋档案，含反方证据；`/fengdiscuss` 入口）。

---

## 七层决策框架

状态机强制执行：跳步自动拦截，工具崩溃修依赖不手工填坑。

| 层 | 执行者 | 产出 |
|:---|:-------|:-----|
| **L0 能力圈** | AI + 搜索 | 三问判断：懂/不充分懂/不懂 |
| **M 市场数据** | fengdata.py + AI | 4 灯（宏观/估值/趋势/情绪）+ DK 周期定位 |
| **L1 硬纪律** | fengrule.py + AI | 8 规则 + 4 DK 规则红黄灯 |
| **L2b 量化因子** | fengquant.py | 6 因子 z-score vs 同业 |
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

**7 条核心信条** — 不接飞刀 / 不蹭热点 / 不信噪音（噪音=对内在价值判断零增量的短周期信号，如股评、涨停榜） / 水则资车旱则资舟 / 识别真价值 / 结论不模棱两可 / **执行 > 判断**（系统存在的意义是强迫执行纪律，不是收集信息）。

**DK 四大原则** — 坐标（坐标系？）、家国（与国家利益一致？）、息价（安全边际>30%？）、取舍（有更好去处？）——任一红灯即 PASS。

**六条纪律规则** — 2638 法则、年线法则、后发制人、买分歧卖共识、钱仓滚存、双账户制。

**43 位大师知识库** — `research/040-people/named/`，含段永平/巴菲特/芒格/李录/卡拉曼/林奇/西蒙斯等。

---

## 数据管道

SQLite · 13,053,253 行日线 · 19 国 21 市场活跃标的统一至最新收盘（2026-08-21）· 指数主档 2,126 只（2,118 只有行情）· A股财报 cn_financials 384,206 行（全市场 5,828 只含退市）· 管理规范 [docs/DATA-MANAGEMENT.md](docs/DATA-MANAGEMENT.md)

| 市场 | 范围 | 基本面 |
|:-----|:-----|:-------|
| US (NYSE/NASDAQ) | 503 只 | 93% |
| CN (沪深京) | 5,828 只（CSMAR 35 年 + fuyao 增量至 2026Q1/Q2） | 100% |
| HK (蓝筹) | 85 只 | 71% |
| 其他海外市场 | 日线已追平最新收盘 | unadj_close 待补 |

**写入安全**：所有批量入库必经 `tools/fengdb.py safe_batch` —— 自动产生可回滚变更集（`data/changesets/`，`fengdb undo` 精确撤销）；整库快照走 VACUUM INTO 安全导出；回填断点进度存 `data/cache/`。

**数据源**：yfinance / Futu OpenD / AKShare / baostock / FinMind / 同花顺 fuyao / a-stock-data / CSMAR，多源交叉验证。

---

## 分析能力

**量化**：6 因子（价值/质量/成长/财务健康）z-score 排名 + 52 条投资论断回测。

**公司研究**：`research/060-companies/`（本地）——每只含四大师分析 + 10 年利润预测 + 安全边际压力测试。

**行业报告**：`research/070-reports/` — AI 全产业链、中国汽车、核电、游戏等深度研究。

**策略研究**：`research/050-strategies/` — 破净股、AI 赛道、晨星估值、回购池等 10 种策略。

---

## 工具集（62 个 Python 工具）

| 类别 | 工具 | 功能 |
|:-----|:-----|:------|
| **引擎** | fengstate.py | 状态机（init/check/complete/status/reset） |
| | fenginvest.py | 单命令编排 |
| | fengcollision.py | L3 碰撞引擎（规则树） |
| **数据** | fengdata.py | 行情采集 + `fx` 实时汇率（USDCNY/HKDCNY/USDHKD）+ `--sina-financials` A股三表（含公告日期） |
| | fengmarket.py / fengmarketdata.py | 市场数据 |
| | fengfundamentals.py | 基本面管线 |
| | fengdbrefine.py | 分红回填 |
| | fengindexdb.py / fengindexdb_akshare.py / fengindexdb_verify.py | 指数数据 |
| | feng_add_capex.py / feng_import_csmar.py | CSMAR 导入 |
| | fengstockcnfix.py / fill_hk_gaps.py / fix_hk_nodata.py | 补爬修复 |
| | fengstockdb.py | 股票数据库构建 |
| | fengdb.py | 统一安全写库：safe_batch 自动产可回滚变更集 + undo/snapshot/status |
| | fengfuyao.py | A股财报回填（同花顺 fuyao 免费接口，全市场 5,828 只断点续传） |
| | fengastock.py | A股 12 端点按需取数（估值史/申万行业变迁/复权因子/社融PMI/龙虎榜等，不入库） |
| | fengstockintl.py | 国际日线四源适配器（probe/fetch/fill，默认 dry-run） |
| | feng_total_return.py | 总回报指数 |
| | feng10k.py | 年报分析 |
| **分析** | fengquant.py | 量化因子 z-score |
| | fengrule.py | 纪律检查 |
| | fengscreen.py | 多因子全市场筛选 + `--hard-rules` 纯规则精筛（7硬指标+3豁免） |
| | fengbatch.py | 批量选股流水线：plan/status/summary（公开list→粗筛→精筛→幸存者→逐只七层→汇总报告） |
| | financial_rigor.py | 市值验算 + 三情景估值 |
| | morningstar_fair_value.py | 晨星公允价值 |
| | leftright.py | 左侧/右侧回测 |
| | fengbacktest.py | 信号驱动组合回测（vnpy 范式 + 基准对比 + 成本模型 + T+1 对齐/涨跌停过滤/冲击成本 + quantstats 报告 + `--sig-csv` 信号权重表/`--walkforward-fold` 前向验证/`--grid` 参数网格） |
| | backtest_core.py | 共享回测引擎库（前复权/防前视/前向收益/2000 次 bootstrap/成本 25bps/样本外 20%/协议打标/统一事实包=白话卡唯一填数源） |
| | fengverify.py | 论断复核引擎（cli: `fengverify.py <claim_id>`；#1 年线复测 → ❌、#8 月度暴涨 → ❌；#3 ✅27.98%落带 / #5 🟡1.12有条件 / #6 ✅2.43倍，2026-09-10 复测） |
| | data_inventory.py | data/ 只读盘点（体积/可回收快照清单，报告落 data/inventory_report.md 不入库） |
| | fengtick.py | tickflow 投机侧车薄桥（T0 候选/T2 防线位/T4 监控，纯本地零依赖，幽灵原则） |
| | fengbench.py | FinEval 金融知识门禁（学术 dev/val/test 集本地就绪，selfcheck 全绿；评分需 API key） |
| | fengcache.py | 决策缓存（内容指纹一致跳过重复验证） |
| | fengthrottle.py | 限流 + TTL 缓存取数（OpenBB fred 范式） |
| | fengsec.py | SEC EDGAR 一手资料：10-K/10-Q/13F + facts PIT 双轴/financials XBRL/内部人交易（edgartools 数据层） |
| | fengvaluation.py | 多方法估值：预期法（逆向 DCF）/两阶段 DCF/敏感性/综合 |
| | fengfactor.py | 因子验证三件套（Spearman IC/分位收益/换手率） |
| | fengpit.py | PIT 双轴可见性（SEC companyfacts + A股 cn_financials，as-of 查询防前视） |
| | star_history_chart.py | 明星股历史回测 |
| | stock_screener.py | 选股筛选器 |
| **持仓** | fengwatch.py | 持仓监控（daily/check/review/sell/history/outcome，10 退出规则） |
| | fengholding.py | 持仓域入口：登记分析四段/SCHEMA 校验/查询 |
| | fengportfolio.py | 组合三轴正交盘面 + 买入预算 + optimize 再平衡 + risk 风险归因（含 CVaR/回撤下行贡献）+ hrp 层次风险平价 |
| **工具** | fengview.py | 速查/搜索 |
| | fenglearn.py | 学习路径 |
| | fenghealth.py | 系统健康检查 |
| | fengcost.py | 交易规费（19 市场三档） |
| | clashproxy.py | Clash 代理切换（yfinance 限流绕过） |
| | report_audit.py | 报告准出抽检 + check/sources/csvdetect 质量三件套 |
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

# 持仓全生命周期（skill 接力）
/fengbatch                # 批量选股：公开list→规则筛→幸存者名单→逐只七层→汇总报告
/fengscreen               # 买入前：去劣筛选（7硬指标+3豁免）→ 通过者进分析
/fenginvest <TICKER>      # 买入前：七层分析（状态机强制）
/fengholding              # 持有期：登记新持仓（含论文建立）/ 单只检查 / 后管理
/fengexit <TICKER>        # 卖出：触发源识别 → 理由 → 偏误自查 → 执行
/fengreview <TICKER>      # 复盘：四态假设+红线+健康度 → 写回 reviews → 推进下次回顾

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
| 数据源 | yfinance / Futu / AKShare / baostock / FinMind / 同花顺 fuyao / a-stock-data / CSMAR |
| AI 分析 | Claude AI Agents（四大师并行） |
| 回测 | 自研（leftright.py + 52 论断） |

---

MIT License — 仅限研究参考，不构成投资建议。
