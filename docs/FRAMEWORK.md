# FengInvest — 七层决策框架（完整参考）

> 投资既是工程问题，也是艺术。
> 工程：工具、数据、算法，全部落地。
> 艺术：多个思想的碰撞与融合，包括你最讨厌的人的视角。
>
> 纪律先行、并行分析、按权碰撞、结论不模棱两可。

## 文档索引

| # | 文档 | 内容 | 行数 |
|:-:|:-----|:-----|:---:|
| 01 | `docs/01-philosophy.md` | 核心信条 + 架构总览 + 灯色标准 | < 100 |
| 02 | `docs/02-market.md` | M层 市场数据 + 4灯标准 | < 100 |
| 03 | `docs/03-discipline.md` | L1 硬纪律 + 深度价值路径 | < 100 |
| 04 | `docs/04-qualitative.md` | L2a 定性核心 + 会计清单 | < 100 |
| 05 | `docs/05-quantitative.md` | L2b 量化因子 | < 100 |
| 06 | `docs/06-collision.md` | L3 碰撞 + 反方检查 + 偏误检查 | < 100 |
| 07 | `docs/07-report.md` | L4 报告模板 | < 100 |
| 08 | `docs/08-exit.md` | 卖出纪律 | < 100 |
| 09 | `docs/09-portfolio.md` | P层 组合管理 | < 100 |
| 速查 | `research/000-QUICK-REFERENCE.md` | 所有关键决策一页看完 | < 170 |

## 执行入口

见 [CLAUDE.md](CLAUDE.md)。

## 知识库依赖

主索引：`research/010-REFERENCE-TREE.md` — 框架层↔文档映射 + 文档间关联关系。

| 领域 | 来源 | 位置 | 许可证 |
|------|------|------|--------|
| **主索引** | `research/010-REFERENCE-TREE.md` | 框架层↔文档映射 | — |
| 人物（43位大师） | `research/040-people/named/` | L2a/L3 大师判断依据 | 详见 DEPENDENCIES.md |
| 投研模板 | ai-berkshire（[GitHub](https://github.com/xbtlin/ai-berkshire)） | 含李录/四大师框架 | MIT |
| 策略（10种流派） | `research/050-strategies/` | 投资风格参考 | 详见 DEPENDENCIES.md |
| 宏观分析（总纲+7专题） | `research/010-macro/` | M层 宏观判断 + L3 碰撞参考 | 详见 DEPENDENCIES.md |
| 市场情绪/温度（总纲+7专题）| `research/020-market/` | M层 趋势/情绪判断参考 | 详见 DEPENDENCIES.md |
| 资产类别（总纲+7专题） | `research/030-asset-classes/` | M层 估值参考 + 组合管理 | 详见 DEPENDENCIES.md |
| 组合管理（仓位/卖出/再平衡） | `research/090-portfolio-management/` | P层 组合+仓位+体制映射 | 详见 DEPENDENCIES.md |
| 策略验证（52条论断回测） | `research/110-strategy-verification/` | 52条可证伪论断的系统性回测验证 | — |
| 速查总表 | `research/000-QUICK-REFERENCE.md` | 一页看完所有关键阈值+决策 | — |
| 外部依赖清单 | `DEPENDENCIES.md` | 全部外部项目跟踪 | — |

## 目录规范

| 内容 | 路径 |
|------|------|
| 个股7层分析文件 | `research/060-companies/<TICKER>-<中文名>/<YYYY-MM-DD>/`（本地 gitignored） |
| 状态机 + 临时层文件 | `research/state/`（gitignored） |
| 各层文档 | `docs/` |
| 工具脚本 | `tools/` |
| DK 知识库 | `knowledge/` (principles/discipline/methodology/market_view) |
| 持仓数据 | `holdings/` (hold_<TICKER>.json，本地 gitignored) |
| 触发引擎输出 | `alerts/` (today.json，本地) |
| 策略论断回测验证 | `research/110-strategy-verification/<NNN>-<论断名>/` |
| 决策日志 | `logs/` (journal.jsonl，本地) |
| 复盘存档 | `reviews/` (review_*.md，本地) |
| 纪律规则 | `rules/` (discipline.md，仍为 000-52-claims 引用源) |
| 持仓盘面 | `portfolio/` (current.md，P层日常盘面) |
| Web UI | `fengweb/` (TypeScript + Express + EJS) |

每个 skill 必须在其指令中写死输出路径，不允许 AI 自由选择目录。

## 风险盘面：正交维度

持仓按 `market × segment × qualifier` 三轴正交分类（见 `holdings/SCHEMA.md`），集中度由 `fengportfolio.py check` 运行期计算：
- 阈值（占总资产%）：market 红>35%/黄>28%；segment 红>25%/黄>20%；market×segment 红>20%/黄>15%；单标 红>20%/黄>15%
- 资金池 = 真现金 + 准现金（qualifier=quasi_cash），不参与权益集中度
- 资金墙（capital_zone）仅作买入预算（境内池/境外池），**不是风险维度，不产生告警**
- 人民币一盘棋：跨币种实时汇率折算（`python tools/fengdata.py fx`）
