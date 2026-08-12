# research/ — 知识库入口

**先看 `000-QUICK-REFERENCE.md`** — 一页看完所有关键决策。**然后** `010-REFERENCE-TREE.md` 看完整索引。

## 目录结构

```
research/
├── 000-README.md           ← 本入口
├── 000-QUICK-REFERENCE.md   → 决策速查总表（一页看完关键阈值）
├── 010-REFERENCE-TREE.md   → 知识库主索引（层映射 + 文档关联图）
├── 010-macro/              → 宏观指标研究（总纲 + 7大主题参考文档）
├── 020-market/             → 市场温度/情绪研究（总纲 + 7大指标参考文档）
├── 030-asset-classes/      → 资产类别研究（总纲 + 7类资产参考文档）
├── 040-people/             → 投资人物/方法论研究（43位大师，含 named/ 子目录）
├── 050-strategies/         → 投资策略研究（10种流派，含左侧vs右侧）
├── 060-companies/          → 个股分析数据（本地 gitignored，每家公司一个子目录）
├── 070-reports/            → 跨领域研究报告
├── 090-portfolio-management/ → 组合与决策管理（仓位、再平衡、卖出、宏观体制映射）
├── 100-learning-investment/  → 学习投资（书单、路径规划、AI 学习工具）
├── 110-strategy-verification/ → 52条投资论断回测验证（新范式：主动策略验证）
└── state/                  → 状态暂存（gitignored，fengstate.py 自动管理）
```

## 用法

每个编号目录内有 `000-README.md` 作为入口，推荐阅读顺序按 010→020→... 排列。

**速查：** `python ../tools/fengview.py <章节>` 不用翻文件，终端直接看关键决策。
层映射详见 `010-REFERENCE-TREE.md`。

## companies/ 命名规范

`<TICKER>-<中文名>/<YYYY-MM-DD>/`

例：`1810.HK-小米集团/2026-07-16/`

每日分析在该日期的目录下，包含 01-capability.md → 07-report.md / 07-narrative.md 完整7层输出。
