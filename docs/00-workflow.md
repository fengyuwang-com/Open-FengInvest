# FengInvest 股票投资全流程

> 本文档描述从零开始使用 FengInvest 系统进行股票投资的完整流程。
> 覆盖：环境准备 → 选股 → 七层分析 → 交易执行 → 持仓监控 → 组合盘面 → 退出复盘。

---

## 一、环境说明

### 项目结构

```
FengInvest/
├── docs/                    ← 分层文档 (01-philosophy ~ 09-portfolio)
├── tools/                   ← Python 工具 (44 feng*.py)
├── knowledge/               ← DK 知识库 (principles + discipline + methodology)
├── research/                ← 分析产出 + 参考知识库
│   ├── 010-macro/           ← 宏观分析参考
│   ├── 020-market/          ← 市场情绪/温度参考
│   ├── 030-asset-classes/   ← 资产类别参考
│   ├── 040-people/named/    ← 43位大师知识
│   ├── 050-strategies/      ← 10种投资策略
│   ├── 060-companies/       ← 个股分析归档（本地 gitignored）
│   ├── 070-reports/         ← 行业深度报告
│   ├── 090-portfolio-management/ ← 组合管理
│   ├── 100-learning-investment/  ← 学习路径
│   └── 110-strategy-verification/ ← 52条论断回测
├── holdings/                ← 持仓数据（本地 gitignored，SCHEMA 见 holdings/SCHEMA.md）
├── alerts/                  ← 触发引擎输出（本地）
├── logs/                    ← 决策日志（本地）
├── reviews/                 ← 复盘存档（本地）
└── fengweb/                 ← Web UI（端口 23456）
```

### 两种入口

| 入口 | 适用场景 | 启动方式 |
|------|---------|---------|
| **AI CLI** | 深度分析、框架全流程 | `/fenginvest <TICKER>` 或 `Skill("fenginvest")` |
| **Web UI** | 日常监控、快速查看数据 | `http://localhost:23456`（双击 start-web.bat） |

### 核心工具

```bash
tools/fengstate.py       # 状态机（强制执行层顺序）
tools/fengdata.py        # M层数据采集 + fx 实时汇率
tools/fengrule.py        # L1纪律检查
tools/fengquant.py       # L2b量化因子
tools/fengcollision.py   # L3碰撞引擎
tools/fengscreen.py      # 多因子全市场筛选
tools/fengwatch.py       # 持仓监控（daily/check/review/sell/history）
tools/fengportfolio.py   # 组合三轴正交盘面 + 买入预算
tools/fengcost.py        # 全球交易规费计算
tools/fengdbrefine.py    # 数据库回填（unadj_close + 分红）
tools/fenginvest.py      # 单命令编排
tools/fengview.py        # 速查工具
tools/leftright.py       # 左侧 vs 右侧买入回测引擎
tools/fix_hk_nodata.py   # AKShare 补爬缺失港股数据
```

---

## 二、完整分析流程（七层框架）

整个流程由 **状态机** 强制执行，跳步自动拦截。

```
/fenginvest <TICKER>
  │
  ├─ 01-capability   → L0 能力圈确认
  ├─ 02-market       → M  市场数据
  ├─ 03-discipline   → L1 硬纪律
  ├─ 04-quantitative → L2b 量化因子（与L2a并行）
  ├─ 05-qualitative  → L2a 定性核心
  ├─ 06-collision    → L3 碰撞 + 反方检查
  └─ 07-report       → L4 最终报告（分析师版 + 贫嘴版）
```

### Step 1: L0 能力圈确认

**三问判断懂不懂：**

1. 一句话说清它怎么赚钱
2. 它10年后大概率还在吗？
3. 知道什么能杀了它吗？

每问必须从搜索结果引用来源，不能凭AI训练知识回答。

**判定结果：**

| 结果 | 后续 |
|:----|:-----|
| **懂** | 继续走框架 |
| **不充分懂** | 先学习行业，再回来 |
| **不懂** | **PASS，不懂不碰** |

> DK 坐标原则在 L0 追加：这个标的在什么坐标系里？
> 对标标的是什么？当前价差多少？格氏坐标还是巴氏坐标？

### Step 2: M 市场数据

**数据收集（工具 + 搜索）：**

```bash
# 运行数据采集
python tools/fengdata.py <TICKER> --years 20

# 搜索交叉验证（Search-King 或等价搜索工具）
python <搜索工具>/scraper.py --search "<标的> 行业 宏观 2026"
python <搜索工具>/scraper.py --search "<标的> PE 估值 历史分位"
python <搜索工具>/scraper.py --search "<标的> 2026 新闻 财报"
```

**M层输出 4 个灯 + DK 扩展：**

| 灯 | 含义 | 数据来源 |
|:--|:-----|:---------|
| 宏观周期 | 扩张/减速/衰退 | 搜索 + 宏观参考库 |
| 市场估值 | PE历史分位 | fengdata + 搜索验证 |
| 市场趋势 | MA50 vs MA200 | fengdata |
| 市场情绪 | 恐贪指数 | 搜索 |
| 家国方向 | 政策鼓励/限制/中性 | DK扩展 / 搜索政策文件 |
| 周期定位 | 货币/工业利润/用电量 | DK扩展 / 搜索 |

**铁律**：无来源 = 不存在。每个判断必须有来源 URL。

### Step 3: L1 硬纪律

**工具：** `python tools/fengrule.py <TICKER>`

**4 个核心灯 + 4 条 DK 纪律规则：**

| 规则 | 说明 |
|:----|:-----|
| 不接飞刀 | MA50 < MA120? |
| 不蹭热点 | 月涨 > 30%? |
| 杠杆=0 | 有杠杆? |
| 真价值 | FCF正? 有营收盈利? |
| **2638法则** | 大盘位置? (DK) |
| **年线法则** | 追高检查 (DK) |
| **后发制人** | 右侧确认 (DK) |
| **买分歧卖共识** | 分歧vs共识 (DK) |

**L1 🔴 不等于公司完了**，触发深度价值路径检查：
A. 好生意 🟢 → B. 极端低估 → C. 非陷阱 → D. 催化剂
A+B+C+D 全满足 → 深度价值路径 (DCA, 30-50%)
任一不满足 → PASS

### Step 4: L2b 量化因子（与 L2a 并行）

**工具：** `python tools/fengquant.py <TICKER> [--peers PEER1 PEER2 ...]`

量化做相对排名，不做绝对价值判断。6个因子：
价值(PE) / 价值(FwdPE) / 质量(ROE) / 利润率 / 收入增长 / 杠杆(D/E)

**输出：** 每个因子的 z-score + BULL/BEAR 信号 + 一致性判断

### Step 5: L2a 定性核心

通过 `Skill("investment-team")` 调用 4 位大师并行分析（investment-team 技能来自 ai-berkshire 集成，见 docs/ai-berkshire-integration.md）：

| 角色 | 大师视角 | 分析维度 |
|:-----|:---------|:---------|
| business-analyst | 段永平 | 商业模式、护城河、差异化 |
| financial-analyst | 巴菲特 | 财务质量、估值安全边际 |
| industry-researcher | 芒格 | 行业格局、竞争态势 |
| risk-assessor | 李录 | 管理层、风险、长期确定性 |

**L2a 6 个灯：** 好生意 / 护城河 / 管理层 / 安全边际 / 需求稳定 / 会计质量

> DK 息价原则追加：安全边际 > 30%？极端压力测试？股息/回购充足？
> 六步法补充：主营业务 → 科技含量 → 重大事项 → 定价 → 催化剂 → 管理层

**整体判定：** ≥3🟢 + 无🔴 = 🟢 好生意
有🔴 = 🔴 整体否定

### Step 6: L3 碰撞引擎

**不产生新信息。** 只从已有数据合成结论。

**强制反方检查**（碰撞前必做）：
1. 列出这个股票让你亏钱的 5 种方式
2. 如果跌 30%，加仓还是割肉？
3. 如果涨 30%，卖不卖？
4. 受什么最近的新闻/价格走势影响？

**碰撞规则（按优先级执行）：**

```
L1 有 🔴?
  ├─ 好生意🟢+极端低估+非陷阱+催化剂 → 深度价值(DCA)
  └─ 其他 → PASS

L1 🟢/🟡:
  好生意🔴           → PASS
  安全边际🔴         → WAIT
  安全边际🟡         → BUY低置信
  全要素🟢           → BUY高置信（按组合约束）

DK 碰撞规则:
  DK 任何 🔴         → PASS（优先级2，最高）
  坐标🔴             → WAIT降置信
  家国🔴             → PASS
  安全边际<30%       → WAIT
  全部 DK 🟢 + L1 🟢 → 调高置信度
```

**行为偏误检查**（碰撞后必做）：
确认偏误 / 锚定效应 / 近因偏误 / 过度自信

### Step 7: L4 最终报告

双报告并行，同一数据源：

| 版本 | 风格 | 用途 |
|:-----|:-----|:------|
| **分析师版** (07-report) | 结构化、数据驱动、正式 | 快速理解投资逻辑 |
| **贫嘴版** (07-narrative) | 口语化、犀利、一刀见血 | 自我检验、不留情面 |

**核心内容：**
1. 结论行（机器可读）：`TICKER — 🟢/🟡/🔴 BUY/WAIT/PASS @ X%`
2. 投资论点 + 业务概览 + 行业分析
3. 财务分析（3-5年表格）
4. 估值分析（相对+绝对+目标价）
5. 量化因子信号
6. 风险矩阵 + 反方观点
7. DK 原则审计表
8. 催化剂日历 + 建仓策略 + 退出条件
9. 行为偏误检查

---

## 三、交易执行

### 买入

根据 L4 报告的仓位建议执行：

| 置信度 | 仓位 | 建仓方式 |
|:------|:----|:---------|
| 高置信 | 60-80% | 一次性或2批 |
| 中置信 | 30-50% | 分批（2-3个月） |
| 低置信 | 10-20% | 试探性建仓 |
| 深度价值 | 30-50% | DCA（价格越低越买） |

> 仓位上限以组合盘面为准：单标的不超过总资产 20%（黄线 15%），详见 docs/09-portfolio.md。

**记录持仓：**

```bash
# 手动写 holdings/hold_<TICKER>.json（字段定义见 holdings/SCHEMA.md）
# 关键：market / segment / qualifier 三轴 + capital_zone / market_access
python tools/fengportfolio.py check   # 写入后重跑组合盘面验证集中度
```

### 持有期监控

**每日提醒（Web UI 自动）：**

```bash
python tools/fengwatch.py daily    # 跑所有持仓的退出检查
python tools/fengwatch.py check <TICKER>  # 单只检查
```

**触发引擎输出到 `alerts/today.json`**，在 Web UI 持仓监控页显示。

**组合盘面（P 层，每次调仓后必跑）：**

```bash
python tools/fengportfolio.py check   # 三轴集中度 + 资金池 + 买入预算
python tools/fengdata.py fx           # 实时汇率（USDCNY/HKDCNY/USDHKD）
```

- 风险按**人民币一盘棋**计算（跨币种实时汇率折算），不按账户域分割
- 集中度阈值（占总资产%）：market 红>35%/黄>28%；segment 红>25%/黄>20%；market×segment 红>20%/黄>15%；单标 红>20%/黄>15%
- **资金池** = 真现金 + 准现金（低波高息 ETF 等 qualifier=quasi_cash），不参与权益集中度
- **资金墙**（境内池/境外池）只约束现金划转 → 买入预算提示，不产生风险告警
- 板块词汇表可扩展：同行业不同风险驱动必须分 segment（如半导体.AI算力 vs 半导体.存储）

**退出规则（docs/08-exit.md）：**

| 类型 | 触发 | 动作 |
|:-----|:-----|:-----|
| 价格止损 | 买入后跌 > 20% | 强制退出 |
| 基本面止损 | FCF由正转负 / 营收连续降 | 退出或降50% |
| 时间止损 | 6个月论文未兑现 | 重新评估 |
| 估值回归 | PE > 80%分位 | 减至半仓 |
| 估值泡沫 | PE > 95%分位 | 清仓80% |
| 论文失效 | 核心论点推翻 | 立即清仓 |

### 卖出

```bash
python tools/fengwatch.py sell <TICKER> --price X --shares Y --reason "原因"
```

自动完成：
- 计算盈亏
- 写入决策日志（logs/journal.jsonl）
- 归档持仓文件为 hold_<TICKER>_closed_<DATE>.json

### 钱仓滚存

当浮盈 > 30% 时：

```bash
python tools/fengwatch.py check <TICKER>  # 查看滚存建议
```

回收本金，剩余零成本筹码继续持有。

---

## 四、复盘与回顾

### 定期复盘

- **每月**：跑 daily 检查，看 alerts/today.json
- **每季度**：检查每只持仓的论文 + 新闻
- **每半年**：对每只持仓完整重跑 01→07 + 组合盘面（P 层）
- **股价异动 > 5%**：触发检查

### 历史分析

```bash
python tools/fengwatch.py history        # 总览（胜率、总盈亏）
python tools/fengwatch.py history losses # 亏损排序
python tools/fengwatch.py review <TICKER> # 单只复盘
```

Web UI 路径：`/watch/history` — 查看历史持仓和亏损分析。

### 决策日志

所有操作（买入、卖出、滚存、检查）自动写入 `logs/journal.jsonl`。
Web UI 路径：`/journal` — 查看完整决策日志。

---

## 五、Web UI 快速导航

| 页面 | 路径 | 用途 |
|:----|:-----|:-----|
| 系统总览 | `/` | Dashboard：概况、信号灯、最新提醒 |
| 系统架构 | `/system` | system-map 可视化（Mermaid + 互动图） |
| 市场数据 | `/market` | 53个外部数据源门户 + 缓存行情摘要 |
| 持仓总览 | `/holdings` | 持仓表（市场/板块/准现金徽章 + 实时汇率） |
| 持仓详情 | `/holdings/:ticker` | 单只持仓全字段 |
| 持仓监控 | `/watch` | 每日退出检查结果、警报灯、卖出表单 |
| 股票分析 | `/analyze` | 快速查看个股数据：价格、MA、基本面 |
| 研究 | `/research` | 个股七层分析结果 |
| 知识库 | `/knowledge` | DK 知识库 + 框架文档 |
| 钱仓滚存 | `/rollover` | 本金回收计算器 |
| 决策日志 | `/journal` | 全部操作日志 |
| 历史持仓 | `/watch/history` | 历史盈亏、亏损分析 |

---

## 六、原则性文档索引

所有原则性文档集中在两个位置：

### `knowledge/` 目录

| 文件 | 状态 | 说明 |
|:-----|:-----|:------|
| principles/坐标原则.md | ✅ | 坐标系、对标标的、价差测量 |
| principles/家国原则.md | ✅ | 政策方向、周期定位、国际关系 |
| principles/息价原则.md | ✅ | 安全边际、股息/回购、兑现路径 |
| principles/取舍原则.md | ✅ | 机会成本、仓位管理、集中度 |
| discipline/2638法則.md | ✅ | 大盘空头区间仓位控制 |
| discipline/年线法则.md | ✅ | 牛熊分界、追高检查 |
| discipline/后发制人.md | ✅ | 右侧确认、不抢跑 |
| discipline/买分歧卖共识.md | ✅ | 分歧来源安全边际 |
| discipline/钱仓滚存.md | ✅ | 回收本金、零成本持仓 |
| discipline/双账户制.md | ✅ | 投资账户 vs 交易账户隔离 |
| methodology/ | ✅ | 回测方法论 + 文献图谱 + 结论汇总 |
| market_view/ | ❌ 空 | 待补充市场观 |

> `knowledge/personal/` 为个人认知（本地，gitignored，不开源）。

### `docs/` 目录（分层框架）

| 文件 | 说明 |
|:-----|:------|
| 01-philosophy.md | 核心信条 + 架构总览 |
| 02-market.md | M层：市场数据 + 家国/周期扩展 |
| 03-discipline.md | L1：纪律规则 + 深度价值路径 |
| 04-qualitative.md | L2a：定性核心 + 六步法 + 息价扩展 |
| 05-quantitative.md | L2b：量化因子 |
| 06-collision.md | L3：碰撞规则 + DK扩展 |
| 07-report.md | L4：分析师版报告模板 |
| 07-narrative.md | L4：贫嘴版报告风格 |
| 08-exit.md | 退出纪律 |
| 09-portfolio.md | 组合管理：三轴正交 + 资金池 + 买入预算 |

### 参考知识库（`research/`）

| 目录 | 内容 |
|:-----|:------|
| 010-macro/ | 宏观分析（总纲+7专题） |
| 020-market/ | 市场情绪/温度（总纲+7专题） |
| 030-asset-classes/ | 资产类别（总纲+7专题） |
| 040-people/named/ | 43位大师框架 |
| 050-strategies/ | 10种投资策略（含左侧vs右侧） |
| 090-portfolio-management/ | 仓位/卖出/再平衡/体制映射 |
| 110-strategy-verification/ | 52条论断回测 |
| 000-QUICK-REFERENCE.md | 速查总表：所有关键阈值一页看完 |
