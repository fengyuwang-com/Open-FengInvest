# 双钱包终态：投机与交易是同一回事（TRADING 轨道），与价值投资才是两轨

> 状态：定稿
> 日期：2026-08-20
> 来源：由文档 docs/10-discussion.md「2026-08-20 双钱包终态」迁移而来

## 议题

投机和交易是同一回事吗？两个钱包（投资/交易）怎么处理？——拍板：投机 = 交易，合并为 TRADING 一轨，与 INVESTMENT（价值投资）才是真正的两轨。

## 立场（系统所有者）

抛出问题——"投机和交易是同一回事吗？两个钱包怎么处理"；讨论后定稿：投机性买入即交易买入，统一归 TRADING 轨道。

## 支持证据（docs/11-speculation-track.md + 投机大师体系）

- 现状 `docs/11-speculation-track.md` 已是双账户制：INVESTMENT（价值论文 / 1–5 年+ / 论文止损）vs TRADING（/fengspec 投机性买入 / 右侧突破 / 事件驱动 / 3–12 个月 / −20% 机械止损）。
- 投机大师（Sperandeo / Williams / Elder / Livermore / Thorpe / Taleb）体系里，"投机"（speculation）即"交易"（trading）——买的是**价差 + 纪律**，与"投资"（价值、论文）是两种范式，不是两种可再拆的类别。
- 2026-08-16 已定：机械价格止损从投资账户拿走、放进交易账户——交易轨道本就是"机械止损"的家，投机走 TRADING 名正言顺。

## 反方（讨论中最强反对论点）

1. **强行拆成"投机/交易"两个钱包，边界模糊**：右侧突破算投机还是交易？事件驱动算哪个？硬拆只会徒增记账复杂度；且两轨各自内部一样是短线 + 机械止损，没有实质区别。
2. **投机失控会污染价值账户纪律**：若投机混进投资账户，机械止损/追热点会腐蚀"论文止损"的长期纪律——所以必须把投机关进 TRADING 这个笼子，与 INVESTMENT 隔离。

## 结论（定稿，写入 docs/11-speculation-track.md）

- **投机性买入 = 交易买入**，统一归 `TRADING` 一条轨道；与 `INVESTMENT` 才是真正的两轨（价值论文 vs 价差纪律）。
- **同票可双轨各持**：同一只股票可同时出现在两个钱包（投资长线 + 交易波段），隔离记账、互不干扰，登记时按 `account_type` 给"同标双钱包"警示。
- **轨道分流规则**：投机标的**绕开 fengscreen** 走 `/fengspec`（T1 环境闸 + T2 结构确认 + T3 纪律捆）；交易级复盘走 `/fengspec`（手气 vs 结构），**不进** `/fengreview` 的四态论文复盘。

## 系统改动

- ✅ 已实施：docs/11-speculation-track.md（双账户制落地为可运行两轨）
- ✅ 已实施：.agents/skills/fengspec（本地独立 skill：六步流程 + 纪律集 + 两钱包隔离）
- ✅ 已实施：trade_entry 结构落地（holdings/SCHEMA.md + fengholding.py TRADING 分支：entry_trigger / stop_line / time_window / 证伪触发 / 滚存线）
- ⏳ 待实施：投机监控细化（无条件止损 / 时间窗 / 事件证伪）/ 分钱包归因 / 小仓试点（≤试盘 3%）
