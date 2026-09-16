# FengInvest — 路线图

> 当前状态：核心系统（七层框架 + 状态机 + 52 工具 + Web UI + 三轴正交盘面）已就绪；
> 数据库审计完成（2.2GB/13M 日线/19 市场）；52 条论断已测 34 条。
> 本文件为进行中清单，**已完成的旧条目定期清理归档**，避免堆积过时计划。

---

## ✅ 已完成（历史里程碑）

- 七层决策框架 + 状态机（fengstate.py）强制执行层顺序
- 62 个 Python 工具全链路：数据采集（yfinance/AKShare/baostock/FinMind/CSMAR/fuyao/SEC EDGAR）→ 量化 → 纪律 → 碰撞 → 报告
- Web UI（fengweb，TS+Express+EJS，端口 23456）：总览/市场/持仓/研究/知识库/滚存/日志/系统图
- 多市场数据库（2026-08 终态）：1,305 万日线、21 市场、2,126 只统一更新至最新交易日；A 股财报 5,828 只全处理（cn_financials 38.4 万行）
- 52 条投资论断回测验证（已测 34 条，结论见 `research/110-strategy-verification/000-CONCLUSIONS`）
- **组合盘面纠偏（2026-08）**：废弃「资金域=风险维度」旧模型 → 三轴正交（market×segment×qualifier）+ 资金池 + 资金墙=买入预算 + 实时汇率 fx
- **持仓域独立（2026-08）**：fengholding.py（登记/校验/组合影响）+ 四 skill 全景（fenginvest 买入前 → fengholding 持有期 → fengexit 卖出 → fengreview 复盘）+ 卖出闭环（realized_pl/trades/归档）+ 滚存 15%/30% 两级 + daily 输出 alerts[] + 08-portfolio.json 出站验证
- 公开仓库 Open-FengInvest 重建：框架/工具/知识库公开，个人数据（holdings/portfolio/logs/060-companies 等）零泄露
- **开源吸收第三批（2026-08）**：fengpit PIT 双轴（companyfacts/cn_financials）+ fengvaluation 多方法估值（预期法移植）+ fengfactor 因子验证三件套 + hrp 层次风险平价（σ² 修正，skfolio 对照）+ risk 下行风险贡献（CVaR/回撤有限差分）+ 回测 T+1 对齐/quantstats 报告 + report_audit 质量三件套 + 复盘 outcome 追踪闭环
- **论断验证机制 + 双钱包终态（2026-08-20）**：自建共享回测引擎 `backtest_core.py`（算数）+ 论断配方 `000-claims-def.md` + 12 项协议 `000-PROTOCOL.md`（判据对齐/复权/成本/显著性/样本外/幸存者/文献对标/A股制度……）+ 白话论断卡 `000-FORMAT-SAMPLE-白话卡.md`，入口 `/fengverify`（喊一句人话自动复测 → 出 0 代码白话卡；0 个开源回测仓库入库，只借鉴 tickflow 样本外/网格 + pwb 指标思想）；投机性买入 = 交易买入（TRADING 轨 `/fengspec`，右侧/事件驱动，-20% 机械止损，试盘 ≤3% / 单票 ≤10% / 总仓 ≤30%），与 INVESTMENT（价值/论文止损）两轨并立，`trade_entry` 进 holdings/SCHEMA.md；tickflow 投机侧车 `fengtick.py`（T0/T2/T4，只供数据）+ FinEval 知识门禁 `fengbench.py`（待数据集）；docs/10-discussion.md 归档 3 场讨论（判据错位 / 回测路线 / 双钱包终态，69→181 行）
- **批量选股流水线（2026-08-29）**：`/fengbatch`（fengbatch.py plan/status/summary）+ `fengscreen.py --hard-rules` 纯规则精筛（7硬指标+3豁免）+ 内置 list 字典 `data/config/batch_lists.json`；首跑中证红利 50→24 幸存者。配套研究清单 `data/config/research_list.json`（独立于持仓的研究/候选/观察）+ 讨论 skill 通用化（`/fengdiscuss` / `/fengdiscusslog`，锚配置 `Discussion/discuss-config.json`）
- **通宵自动化收割（2026-09-10）**：全站 i18n（1053 键/33 文件，fengwebcheck D 维双向对账）合入 master；fengverify 事件计数引擎 #3/#5/#6 实现并复测（#3 ✅27.98% / #5 🟡1.12 / #6 ✅2.43倍）；7 个 overnight 分支逐一审查后并回 master，全量回归 134 pass / 0 fail（master 6a884c8 双推）

---

## 进行中 / 待办

### 知识库补全

- [ ] 填充 `knowledge/market_view/` — A股生态、周期观、政策观
- [ ] 所有知识库文件添加 `type` 和 `source` frontmatter

### Web UI 增强

- [ ] 持仓详情页 Thesis 完整展示（含滚存计算、回顾按钮）
- [ ] API 端点文档（当前 REST API 接口无文档）
- [ ] 卖出前检查清单 Web 交互版
- [ ] 复盘编辑表单 Web 版

### 触发引擎完善

- [ ] 触发引擎增强：价格阈值推送 / 自动回顾日期提醒 / 大盘年线全局提醒（当前 daily 已做 10 条退出规则检查 + 滚存检测 + 输出 `alerts/today.json`，缺自动调度与推送）

### 数据管道

- [ ] 8766.T 负价格清理（P0，13,856 行）
- [ ] 其他 16 市场基本面（P1 非核心，待定）
- [ ] FinEval 知识门禁（tools/fengbench.py）接入数据集后启用（当前待数据集）

---

## Phase 4 — 深化

- [ ] 市场价格推送（日频数据自动抓取）
- [ ] 持仓盈亏实时计算（Web UI 显示）
- [x] 双账户（投资账户 + 交易账户）支持 — ✅ 已完成（2026-08-20 双钱包终态，见上方里程碑）：概念定稿见 [docs/11-speculation-track.md](11-speculation-track.md)（独立 `/fengspec` 交易钱包轨道，不做改 /fenginvest）
- [ ] 钱仓滚存计算器增强（从静态表单 → 联动持仓数据）

## Phase 5 — 云端（可选）

- [ ] Docker 化部署
- [ ] 定时任务（每日触发引擎自动运行）
- [ ] 移动端适配

---

## 当前已知问题

1. `knowledge/market_view/` 为空
2. 持仓详情页 Thesis 展示不完整
3. 8766.T 负价格数据未清理
4. investment-team 技能依赖外部 ai-berkshire 集成（见 docs/ai-berkshire-integration.md）
