# Open-FengInvest — 七层决策框架

> 开源版投资分析框架。AI+代码协作，状态机强制按序执行。
> 结构标准：[docs/standards.md](docs/standards.md)

## 简介

AI+代码协作投资分析系统。7层：能力圈(L0)→市场数据(M)→硬纪律(L1)→量化(L2b)→定性(L2a)→碰撞(L3)→报告(L4)→组合(P)。状态机物理卡死执行顺序。

## 目录结构

```
Open-FengInvest/
├── docs/              ← 分层文档 + 结构标准
├── tools/             ← Python 工具集
├── knowledge/         ← 投资知识库（原则/纪律）
├── research/          ← 研究参考（宏观/市场/大师/策略）
├── fengweb/           ← Web UI（TS/Express/EJS）
├── rules/             ← 纪律规则源文件
├── start-web.bat/sh   ← Web UI 启动脚本
└── .gitignore
```

## 七层框架

| 层 | 执行者 | 产出 |
|:---|:-------|:-----|
| **L0 能力圈** | AI + 搜索 | 三问判断：懂/不充分懂/不懂 |
| **M 市场数据** | fengdata.py + AI | 4 灯（宏观/估值/趋势/情绪） |
| **L1 硬纪律** | fengrule.py + AI | 规则红黄灯 |
| **L2b 量化因子** | fengquant.py | 因子 z-score |
| **L2a 定性分析** | 4 AI Agent 并行 | 四大师视角 |
| **L3 碰撞引擎** | AI | 反方检查 + 行为偏误检查 |
| **P 组合管理** | AI | 仓位约束 + 压力测试 |
| **L4 报告** | AI | 结构化研究报告 |

## 状态机

```bash
python tools/fengstate.py init <TICKER>
python tools/fengstate.py check <TICKER> <层>
python tools/fengstate.py complete <TICKER> <层> <文件>
python tools/fengstate.py status <TICKER>
python tools/fengstate.py reset <TICKER>
```

## Python 工具集

| 类别 | 工具 | 功能 |
|:-----|:-----|:------|
| **引擎** | fengstate.py | 状态机 |
| | fengcollision.py | L3 碰撞引擎（规则树） |
| **数据** | fengdata.py | yfinance 数据采集 |
| | fengfundamentals.py | 基本面管线 |
| | fengmarket.py / fengmarketdata.py | 市场数据 |
| | fengdbrefine.py | 分红回填 |
| | fengindexdb.py | 指数数据 |
| | fengstockdb.py / fengstockcnfix.py | 股票 DB 构建/修复 |
| | feng10k.py | 年报分析 |
| | feng_add_capex.py / feng_import_csmar.py | CSMAR 导入 |
| | fill_hk_gaps.py / fix_hk_nodata.py | HK 数据修复 |
| **分析** | fengquant.py | 量化因子 z-score |
| | fengrule.py | 纪律检查 |
| | fengscreen.py | 多因子全市场筛选 |
| | financial_rigor.py | 市值验算+三情景估值 |
| | leftright.py | 左侧/右侧回测 |
| | fengquality.py | 数据质量交叉验证 |
| **组合** | fengwatch.py | 持仓监控 |
| | fengportfolio.py | 组合管理 |
| | fengcost.py | 交易规费（19 市场三档） |
| **辅助** | fengview.py | 速查搜索 |
| | fenghealth.py | 系统健康检查 |
| | clashproxy.py | 代理切换 |
| | report_audit.py | 报告准出抽检 |

## 数据原则

- 多源交叉验证（yfinance/AKShare/baostock/CSMAR）
- 数据质量门禁：PE/Forward PE 写入前自动验证

## Web UI

```bash
cd fengweb && npm install && npm run build && node dist/index.js
```

启动后访问 `http://localhost:3000`

## 技术栈

| 层 | 技术 |
|:---|:-----|
| 语言 | Python 3.8+ |
| Web | TypeScript + Express + EJS |
| 数据库 | SQLite |
| 数据源 | yfinance / AKShare / baostock / CSMAR |
| AI 分析 | Claude AI Agents |
| 搜索 | Search-King |
