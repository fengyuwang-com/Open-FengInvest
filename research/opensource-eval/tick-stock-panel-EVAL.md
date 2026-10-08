# tick-stock-panel (原 tickflow-stock-panel) Evaluation

> Repo: https://github.com/shy3130/tick-stock-panel
> 调研日期: 2026-09-11（网络调研，未 clone）
> 判定: **可借鉴（抄思想为主），不直接跑、不集成代码**

## 仓库判定（先澄清"哪个是正身"）

| 仓库 | 判定 |
|---|---|
| **shy3130/tick-stock-panel** | **原仓**：4,562 stars / 1,105 forks，2026-06-18 创建，2026-09-11 仍在 push，MIT |
| hzy1522/tickflow-stock-panel | 衍生副本（detached fork，自述落后上游 ~67 commits），增量=多市场支持（A/HK/US），106 stars，2026-08-31 后停更 |
| jingtuabc/tickflowstockpanel、hanweibo4531/tickflow-stock-panel | 纯 fork，零活动，0 star |

上游原名 tickflow-stock-panel，2026-07 后改名 tick-stock-panel。**与 FengInvest fengtick.py 的"tickflow"只是同名撞车——那是我们自己的投机侧车协议，与此项目无代码关系；TickFlow（行情商）只是本项目的数据源插件之一。**

## 是什么

自托管、零运维的 A 股「选股 + 回测 + 盘中监控」Web 工作台：

- **选股**：18 个内置策略筛选引擎 + 指标管线 + 因子挖掘（Polars 全市场扫描）
- **回测**：vectorbt + A 股真实约束（T+1、手续费、滑点、涨跌停），蒙特卡洛回撤估算、因子归因
- **监控**：盘中价格/信号/异常告警、涨停连板梯队、市场情绪周期分析
- **AI 层克制**：LLM 只做策略生成/个股分析/复盘；"因子候选永不自动上线，需人工确认"
- **栈**：FastAPI + Polars + DuckDB + Parquet（本地文件单一数据管道）；React 18 + TS + Lightweight Charts；Docker 单容器部署
- **数据源可插拔（能力路由）**：插件声明能力（K线/财务/盘口），TickFlow 主源 + fuyao/stock-sdk/自定义 YAML 混用；无 API key 也有基础功能

## FengInvest 增益评估

**定位错位**：它是盘中/连板/情绪周期向的 A 股短线工作台；我们是日线低频、价值+质量、人工下单。且 fengweb(:23456) + 71 工具已在位，跑第二面板是冗余运维负担，TickFlow 数据源还要订阅。

**可借鉴四点（思想层）**：
1. **能力路由数据源插件**——插件声明支持能力、多源混用，比 fengdata 多源交叉更系统，可反哺 fengdata/fengstockintl 适配器设计。
2. **选股/回测/监控共用同一落盘数据管道**（Parquet/DuckDB 单一 truth）——与 fengverify"统一事实包=唯一填数源"哲学同构，可借鉴到 fengscreen/fengbatch 与 fengbacktest 的数据一致性。
3. **AI 克制原则**——"因子候选永不自动上线、需人工确认"，可写进 fengbatch/fengscreen 准入措辞。
4. **回测约束清单**（T+1/滑点/涨跌停过滤）——fengbacktest 已对齐（execution-lag/涨跌停/冲击成本），可对拍验证。

**可集成代码：基本无必要。** hzy1522 分支的港美股适配思路（无涨跌停市场用"强度梯队"替代连板梯队、52/60 日高低点动量分层）将来 fengsector/fengscreen 扩港美股时可参考，但整栈移植成本高于自写。

## 已知风险（第三方 Hysen Labs 评估转述）

上手门槛高、无 release 版本、单人维护、无数据源仲裁、README"严禁商用"与 MIT 冲突、数据准确性自担。

## 来源

- github.com/shy3130/tick-stock-panel + api.github.com 四仓元数据
- raw.githubusercontent.com/hzy1522/tickflow-stock-panel README
- hysenlabs.com/zh-cn/projects/shy3130-tick-stock-panel
