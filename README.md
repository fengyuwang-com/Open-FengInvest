# Open-FengInvest — 开源投资分析框架

> 七层决策框架 · 多市场数据库管道 · Python 工具集 · Web UI

---

## 概述

Open-FengInvest 是一个 AI 协作投资分析框架。核心是一个**七层状态机**，强制按序执行分析流程，确保每层输出可追溯、可验证、可碰撞。

设计目标不是自动化决策，而是**结构化分析**：把模糊的"这个股票能不能买"分解为 8 个可执行的步骤，每步由专用工具+AI 完成，结果被下一层验证或挑战。

---

## 七层流程

```
L0 能力圈确认 → M 市场数据 → L1 硬纪律 → L2b 量化因子
    ↘ L2a 定性分析（并行）→ L3 碰撞引擎 → P 组合检查 → L4 报告
```

| 层 | 做什么 | 产出 |
|:---|:-------|:-----|
| **L0** | 三问确认"懂不懂"：怎么赚钱？10 年后还在？什么能杀了它？ | 懂/不充分懂/不懂判定 |
| **M** | 市场数据采集（fengdata.py）+ 4 灯判定（宏观/估值/趋势/情绪） | 02-market.json |
| **L1** | 硬纪律检查（fengrule.py），8 条规则逐一校验 | 03-discipline.json |
| **L2b** | 10 因子 z-score 量化分析（fengquant.py） | 04-quantitative.json |
| **L2a** | 4 AI Agent 并行：段永平/巴菲特/芒格/李录四视角定性分析 | 05-qualitative.md |
| **L3** | 碰撞引擎：反方 4 问 + 行为偏误检查 + 规则树碰撞 | 06-collision.md |
| **P** | 组合约束检查 + 仓位管理 + 压力测试 | portfolio 更新 |
| **L4** | 结构化研究报告（华尔街分析师格式） | 07-report.md |

状态机拦截跳步：未完成 L0 无法进入 M，未完成 L3 无法出报告。

---

## 核心设计

### 状态机（fengstate.py）

```bash
python tools/fengstate.py init <TICKER>       # 初始化分析
python tools/fengstate.py check <TICKER> <层>  # 检查前置条件
python tools/fengstate.py complete <TICKER> <层> <文件> # 标记完成
python tools/fengstate.py status <TICKER>      # 查看进度
python tools/fengstate.py verify <TICKER>      # 全量验证
```

关键特性：
- 输出验证：complete 时自动检查关键字段是否存在
- 跨层一致性：PE 值跨 M/L2b 一致性检查（差异 >5% 报警）
- 数据质量门禁：M 层写入后调用 fengquality.py 交叉验证 PE/Forward PE
- 降级传播：数据源降级时自动降低下游权重

### 数据质量

**验证哲学**：数据正确性必须在摄入时用独立信源验证，不能仅做结构检查。

- `fengquality.py` — 从 stockanalysis.com 拉取 PE/Forward PE 与本地对比
- 差异 <5% → PASS，5-10% → WARNING，>10% → FAIL
- `fengcollision.py` — 检测降级数据并自动半权传播

### 工具完整性铁律

```
工具崩溃时：修依赖，不手工填坑。
```

每层结果必须由对应工具产生，AI 不得冒充结果。

---

## 工具集

### 数据管道

| 工具 | 功能 |
|:-----|:------|
| fengdata.py | yfinance 数据采集（含重试+代理切换） |
| fengfundamentals.py | 基本面数据批量拉取 |
| fengdbrefine.py | 分红回填修正 |
| fengindexdb.py | 指数数据构建 |
| fengstockdb.py | 股票数据库构建 |
| feng10k.py | 年报分析 |
| fill_hk_gaps.py / fix_hk_nodata.py | 港股数据修复 |

### 分析工具

| 工具 | 功能 |
|:-----|:------|
| fengquant.py | 10 因子 z-score 量化分析 |
| fengrule.py | 8 条纪律规则检查 |
| fengquality.py | PE/Forward PE 跨源交叉验证 |
| fengscreen.py | 多因子全市场筛选 |
| financial_rigor.py | 市值验算 + 三情景 DCF |
| leftright.py | 左侧/右侧信号回测 |

### 组合管理

| 工具 | 功能 |
|:-----|:------|
| fengportfolio.py | 组合约束检查 |
| fengwatch.py | 持仓监控 |
| fengcost.py | 19 市场交易规费计算 |

### 辅助工具

| 工具 | 功能 |
|:-----|:------|
| fengview.py | 知识库速查/搜索 |
| fenghealth.py | 系统健康检查 |
| clashproxy.py | 代理节点切换 |
| report_audit.py | 报告准出抽检 |

---

## 数据管道

| 市场 | 范围 | 基本面 |
|:-----|:-----|:-------|
| US (NYSE/NASDAQ) | 500+ | 93% |
| CN (沪深京) | 5800+（CSMAR 35 年） | 100% |
| HK | 85 | 71% |
| 其他 16 市场 | ~2000 | — |

多源交叉验证：yfinance / AKShare / baostock / CSMAR

---

## Web UI

`fengweb/` — TypeScript + Express + EJS

```bash
cd fengweb
npm install
npm run build
node dist/index.js
```

访问 `http://localhost:3000`

---

## 技术栈

| 层 | 技术 |
|:---|:-----|
| AI 分析 | Claude Agents / 4 Agent 并行定性分析 |
| 后端 | Python 3.8+ |
| Web | TypeScript + Express + EJS |
| 数据 | SQLite / yfinance / AKShare / CSMAR |
| 搜索 | Search-King |

---

## 快速开始

```bash
# 安装依赖
pip install yfinance matplotlib numpy pandas scipy openpyxl

# 完整七层分析（需 AI 入口 + Search-King）
python tools/fengstate.py init <TICKER>
python tools/fengstate.py check <TICKER> 01-capability
# ...各层按序执行...

# 速查
python tools/fengview.py --search <关键词>
python tools/fengstate.py status <TICKER>
```

---

## 许可

MIT License — 仅限研究参考，不构成投资建议。

---

*项目源自个人投资研究系统，核心框架与工具已开源。部分本地配置、持仓记录和公司分析报告不在此仓库中。*
