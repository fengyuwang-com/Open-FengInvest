# FengInvest 知识库参考树

知识库主索引。显示所有参考文档、它们之间的关联关系、以及每份文档支持的框架层。

> **如何使用：** 每个 FengInvest 层（L0 → M → L1 → L2a → L2b → L3 → L4）在执行时可查阅本索引定位所需的参考文档。

---

## 目录树

```
research/
│
├── REFERENCE-TREE.md              ← 本文件（主索引/知识库地图）
├── README.md
│
├── 040-people/                         ═══ L0 / L2a / L3 ═══
│   ├── README.md
│   └── named/
│       ├── buffett.md            巴菲特 · 财务估值分析
│       ├── munger.md             芒格 · 行业竞争分析
│       ├── duanyongping.md       段永平 · 商业模式分析
│       ├── li-lu.md              李录 · 长期价值/管理层判断
│       ├── klarman.md            卡拉曼 · 安全边际/深度价值
│       ├── graham.md             格雷厄姆 · 价值投资基础
│       ├── peter-lynch.md        彼得·林奇 · 成长价值
│       ├── simons.md             西蒙斯 · 量化投资
│       ├── soros.md              索罗斯 · 反身性/宏观
│       ├── dalio.md              达利欧 · 全天候/宏观
│       ├── druckenmiller.md      德鲁肯米勒 · 宏观交易
│       ├── howard-marks.md       霍华德·马克斯 · 周期/风险
│       ├── cathie-wood.md        Cathie Wood · 颠覆式创新
│       ├── livermore.md          利弗莫尔 · 趋势交易
│       ├── serenity.md           白毛股神 · 技术分析
│       ├── liyien.md             李一恩 · ???（待确认）
│       ├── (26 more master30 profiles...)
│       │
│       └── [标准格式：世界观 → 心智模型 → 决策启发式 → 分析框架]
│
├── 050-strategies/                     ═══ L1 / L2a ═══
│   ├── README.md
│   ├── quality-growth.md         质量成长派
│   ├── contrarian.md             逆向价值派
│   ├── dividend.md               股息价值派
│   ├── quantitative-factor.md    量化因子派
│   ├── low-vol-dividend.md       低波股息派
│   ├── macro-cycle.md            宏观周期派
│   ├── sector-rotation.md        板搯轮动派
│   ├── growth-track.md           成长跟踪派
│   ├── momentum-trading.md       动力交易派
│   └── research-team/            研究团队
├── leftright/                左侧vs右侧回测
├── 破净股-Top100-20260519.md  ← ai-berkshire 导入（四大市场破净股）
├── BNP-收息投资-20260715.md   ← ai-berkshire 导入（收息投资分析）
│
├── 010-macro/                          ═══ M层 / L3 ═══
│   ├── 001-macro-analysis-reference.md  宏观概览（总纲）
│   ├── 002-business-cycle.md            经济周期 → sector-rotation / yield-curve
│   ├── 003-yield-curve.md               收益率曲线 → monetary-policy / business-cycle
│   ├── 004-inflation.md                 通胀分析 → monetary-policy / commodities / gold
│   ├── 005-monetary-policy.md           货币政策 → yield-curve / inflation
│   ├── 006-credit-cycle.md              信用周期 → corporate-bonds / market-phases
│   ├── 007-employment-indicators.md     就业指标 → business-cycle
│   └── 008-fiscal-policy.md             财政政策 → treasury-bonds / inflation
│
├── 020-market/                          ═══ M层 / L3 ═══
│   ├── market-sentiment-reference.md 市场概览（总纲）
│   ├── vix.md                       VIX/恐慌指数 → fear-greed / market-phases
│   ├── put-call-ratio.md            Put/Call 比率 → vix / fear-greed
│   ├── fear-greed-index.md          恐惧与贪婪指数 → vix / market-breadth
│   ├── 005-market-breadth.md            市场广度 → market-phases / sector-rotation
│   ├── 006-sector-rotation.md           板搯轮动 → business-cycle / market-phases
│   ├── cot-report.md                COT 持仓 → market-sentiment
│   └── 008-market-phases.md             市场阶段 → ibd / all market indicators
│
├── 030-asset-classes/                   ═══ M层 / L3 / 组合管理 ═══
│   ├── asset-class-reference.md      资产类别概览（总纲）
│   ├── 002-gold.md                      黄金 → inflation / monetary-policy
│   ├── 003-equities.md                  股票/权益 → sector-rotation / business-cycle
│   ├── 004-treasury-bonds.md            国债 → yield-curve / monetary-policy
│   ├── 005-corporate-bonds.md           公司债 → credit-cycle / market-phases
│   ├── 006-commodities.md               商品 → inflation / business-cycle / gold
│   ├── 007-real-estate.md               房地产 → monetary-policy / inflation
│   └── 008-cash-equivalents.md          现金/货币等价物 → monetary-policy
│
├── 060-companies/                       ═══ 个股分析产出（本地 gitignored）═══
│   └── <TICKER>-<中文名>/<YYYY-MM-DD>/
│       ├── 01-capability.md
│       ├── 02-market.json
│       ├── ...
│       └── 07-report.md / 07-narrative.md
│
├── 070-reports/                          ═══ 跨领域报告 ═══
│   ├── 000-awesome-quant.md                ← awesome-quant 全量镜像（712 行工具清单）
│   ├── 001-awesome-quant-value-investing.md ← 价值投资适配分析（集成优先级+行动项）
│   ├── AI算力产业链全景研究-20260509.md       ← ai-berkshire 导入
│   ├── AI五层蛋糕-产业全景研究-20260605.md    ← ai-berkshire 导入
│   ├── 全球AI公司估值与护城河全景扫描-20260519.md ← ai-berkshire 导入
│   ├── 核电-industry-20260409.md              ← ai-berkshire 导入
│   ├── 游戏-industry-20260410.md              ← ai-berkshire 导入
│   ├── AI时代创业公司的结构性机会-20260523.md   ← ai-berkshire 导入
│   ├── AI模型行业漏斗筛选-20260509.md          ← ai-berkshire 导入
│   ├── 中国大模型六强横向研究-20260721/        ← ai-berkshire 导入（8篇）
│   └── (持续补充)
│
├── state/                                ═══ 状态暂存（gitignored）═══
│   └── temp_state_<TICKER>.json  (fengstate.py 自动管理)
│
├── 090-portfolio-management/             ═══ P层 / L3 / L4 ═══
│   ├── 001-portfolio-construction.md     组合构建哲学
│   ├── 002-position-sizing.md            仓位计算
│   ├── 003-rebalancing.md                再平衡策略
│   ├── 004-sell-framework.md             卖出决策
│   ├── 005-macro-regime-map.md           宏观体制映射表
│   └── 000-README.md                     目录说明
│
├── 100-learning-investment/              ═══ 学习投资（书单/AI辅助/学习路径）═══
│
├── 110-strategy-verification/            ═══ 52条论断回测 ═══
│   ├── 000-README.md / 000-CONCLUSIONS.md
│   └── 001-above-annual-line/ ... 052-policy-cycle/
│
├── 000-QUICK-REFERENCE.md                ═══ 决策速查总表 ═══
│
└── ai-berkshire/                          ═══ 外部集成（AI 中立法则）═══
    ├── 集成主文档：docs/ai-berkshire-integration.md
    ├── 19技能映射 → 详见 docs/ai-berkshire-integration.md
    ├── 7工具已导入 → FengInvest/tools/
    └── 研究报告选择性导入 → 060-companies/ / 070-reports/ / 050-strategies/
```

---

## 框架层 ↔ 参考文档映射

### L0 — 能力圈确认（这个生意你懂吗？）

| 需要什么 | 使用什么参考文档 | 查找方式 |
|:--------|:---------------|:--------|
| 这个行业怎么赚钱？ | — | **搜索**（实时获取行业信息）|
| 这家公司怎么赚钱？ | — | **搜索**（实时获取公司财报/资料）|
| 竞争格局如何？ | — | **搜索**（实时获取竞争数据）|
| 大师怎么判断？ | `040-people/named/`（43 位大师的判断方法论）| 按需读取特定大师文档 |
| 快速排除非一流公司 | `ai-berkshire: quality-screen`（7条硬指标：ROE/FCF/毛利率等） | 见 `docs/ai-berkshire-integration.md` §2.1 |
| 行业漏斗筛选 | `ai-berkshire: industry-funnel`（全市场→行业→3家） | 见 `docs/ai-berkshire-integration.md` §2.1 |

> L0 主要依赖搜索（Search-King/open-webSearch），大师文档为辅助。

### M 层 — 市场数据收集

| 维度（四灯） | 需要什么 | 使用什么参考文档 |
|:-----------|:--------|:---------------|
| 🟢🟡🔴 **宏观** | 经济周期位置、政策方向、宏观指标解读 | `010-macro/002-business-cycle.md`, `010-macro/005-monetary-policy.md`, `010-macro/003-yield-curve.md`, `010-macro/006-credit-cycle.md`, `010-macro/001-macro-analysis-reference.md` |
| | 全球产业链瓶颈扫描 | `ai-berkshire: bottleneck-hunter`（地缘/供需/技术/气候） | 见 `docs/ai-berkshire-integration.md` §2.5 |
| 🟢🟡🔴 **估值** | 历史估值百分位、与收益率的关联 | `030-asset-classes/003-equities.md`（估值方法部分）|
| 🟢🟡🔴 **趋势** | 市场阶段判断、广度指标、板块轮动 | `020-market/008-market-phases.md`, `020-market/005-market-breadth.md`, `020-market/006-sector-rotation.md` |
| 🟢🟡🔴 **情绪** | VIX、PCR、恐惧贪婪、COT | `020-market/vix.md`, `020-market/put-call-ratio.md`, `020-market/fear-greed-index.md`, `020-market/cot-report.md` |

### L1 — 硬纪律检查

| 纪律检查 | 需要什么 | 使用什么参考文档 |
|:--------|:--------|:---------------|
| no_knife（不接飞刀）| 下跌性质判断、价值陷阱识别 | `050-strategies/`（各策略的陷阱识别部分），`040-people/named/klarman.md` |
| no_fomo（不追涨）| 市场情绪过热判断 | `020-market/vix.md`, `020-market/fear-greed-index.md`, `020-market/008-market-phases.md` |
| no_leverage（不加杠杆）| 规则本身不依赖外部参考 | 自有纪律 |
| true_value（安全边际）| 估值方法和安全边际框架 | `040-people/named/klarman.md`, `040-people/named/buffett.md` |

### L2a — 四大师定性核心

| 大师 Agent | 需要什么 | 使用什么参考文档 |
|:----------|:--------|:---------------|
| 段永平（商业模式）| "好生意"判断 | `040-people/named/duanyongping.md`, `050-strategies/` |
| 巴菲特（财务估值）| 财务报表分析、估值、护城河 | `040-people/named/buffett.md`, `030-asset-classes/003-equities.md` |
| 芒格（行业竞争）| 行业格局、竞争态势、心理模型 | `040-people/named/munger.md`, `020-market/006-sector-rotation.md` |
| 李录（风险/管理层）| 能力圈、管理层判断、长期主义 | `040-people/named/li-lu.md` |
| **外部补充** | | |
| 四大师综合（非并行）| `ai-berkshire: investment-research`（单轮对话版） | 见 `docs/ai-berkshire-integration.md` §2.2 |
| 管理层纵深研究 | `ai-berkshire: management-deep-dive`（CEO能力圈/历史决策） | 增强李录视角 |

### L2b — 量化因子分析

| 因子分析 | 需要什么 | 使用什么参考文档 |
|:--------|:--------|:---------------|
| 财务因子 | ROE/PB/PE 等行业中位数参考 | `030-asset-classes/003-equities.md`（估值部分）+ 动态数据 |
| 市场因子 | 市场环境因子背景 | `020-market/005-market-breadth.md`, `020-market/vix.md` |

### L3 — 碰撞引擎

| 碰撞规则 | 需要什么 | 使用什么参考文档 |
|:--------|:--------|:---------------|
| 深度价值路径（L1🔴时）| 是否好生意 + 极端低估 + 非陷阱 + 催化剂 | `040-people/named/klarman.md`, `040-people/named/buffett.md` |
| 买入前 Checklist | `ai-berkshire: investment-checklist`（10项：护城河/ROE/安全边际/催化剂等）| 见 `docs/ai-berkshire-integration.md` §2.3 |
| 安全边际判定 | 当前估值 vs 历史 | `030-asset-classes/003-equities.md`, `020-market/008-market-phases.md` |
| 仓位建议 | 市场整体风险 + 置信度→仓位计算 | `020-market/005-market-breadth.md`, `010-macro/006-credit-cycle.md`, `020-market/vix.md`, `090-portfolio-management/002-position-sizing.md` |
| 冲突解决 | 不同大师结论冲突 | `040-people/named/`（了解各自框架局限性）|

### L4 — 报告生成

| 报告版式 | 参考文档角色 |
|:--------|:-----------|
| 分析师版 | 全部参考文档作为数据校验和信息来源 |
| 贫嘴版 | 不直接引用，但结论应来自前面的分析 |

### P 层 — 组合管理

| 组合操作 | 需要什么 | 使用什么参考文档 |
|:--------|:--------|:---------------|
| 组合构建 | 确定组合范式和角色分配 | `090-portfolio-management/001-portfolio-construction.md` |
| 仓位计算 | 置信度→仓位映射 | `090-portfolio-management/002-position-sizing.md` |
| 再平衡 | 何时调整、如何调整 | `090-portfolio-management/003-rebalancing.md` |
| 卖出决策 | 论文到期、机会成本、税务 | `090-portfolio-management/004-sell-framework.md` |
| 宏观配置 | 当前体制→组合倾向 | `090-portfolio-management/005-macro-regime-map.md`, `docs/09-portfolio.md` |
| 持仓监控 | 股价异动快速归因 | `ai-berkshire: news-pulse`（4 Agent并发侦察事件/政策/对手/情绪）|
| 论文追踪 | 买入后条件跟踪/退出信号 | `ai-berkshire: thesis-tracker`, `ai-berkshire: thesis-drift` |
| 组合回顾 | 定期组合复盘分析 | `ai-berkshire: portfolio-review` |

---

## 文档间的关联关系图

```
      010-macro/                       020-market/
    business-cycle ─────────────── sector-rotation
         │                              │
    yield-curve                     market-breadth
         │                              │
  monetary-policy                   market-phases
         │                              │
      inflation ──────── vix ───── fear-greed-index
         │                              │
    credit-cycle ──────────────── put-call-ratio
         │
   employment-indicators
         │
    fiscal-policy
         │
         ▼
  030-asset-classes/
    treasury-bonds ──── yield-curve
    corporate-bonds ─── credit-cycle
    equities ────────── business-cycle, sector-rotation
    commodities ─────── inflation, business-cycle
    gold ────────────── inflation, monetary-policy
         │
         ▼
   040-people/named/ (43 master frameworks)
         │
         ▼
   050-strategies/ (9 strategy types)
         │
         ▼
   090-portfolio-management/
    position-sizing ──── conviction level
    macro-regime-map ─── all macro/market/asset signals
    sell-framework ───── thesis, opportunity cost, tax
    portfolio-construction
         │
         ▼
   ───── FengInvest 7-Layer Framework ─────
```

---

## 使用说明

### 对于 AI（FengInvest 框架执行时）

1. **确定当前层**（L0 → M → L1 → L2a → L2b → L3 → L4 → P）
2. **查映射表** 找出该层需要哪些参考文档
3. **读取参考文档** 获取相关方法论、阈值、判定标准
4. **搜索获取实时数据**（用 Search-King/open-webSearch 获取最新信息）
5. **结合参考框架 + 实时数据 → 做出判断**

### 对于用户（手动查阅）

- 每个参考文档采用统一格式：特性表格 → 核心指标 → 解读方法 → 在 FengInvest 中的使用
- 文档末尾有 "相关文档" 和 "关键数据源" 章节
- 本索引会随着知识库扩展持续更新
