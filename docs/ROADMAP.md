# FengInvest — 路线图

> 当前状态：核心系统（七层框架 + 状态机 + 44 工具 + Web UI + 三轴正交盘面）已就绪；
> 数据库审计完成（2.2GB/13M 日线/19 市场）；52 条论断已测 34 条。
> 本文件为进行中清单，**已完成的旧条目定期清理归档**，避免堆积过时计划。

---

## ✅ 已完成（历史里程碑）

- 七层决策框架 + 状态机（fengstate.py）强制执行层顺序
- 44 个 Python 工具全链路：数据采集（Futu/yfinance/AKShare/CSMAR）→ 量化 → 纪律 → 碰撞 → 报告
- Web UI（fengweb，TS+Express+EJS，端口 23456）：总览/市场/持仓/研究/知识库/滚存/日志/系统图
- 多市场数据库：13M 日线、19 市场、2,020 只；CSMAR A股基本面 5,828 只（1990-2025Q1）
- 52 条投资论断回测验证（已测 34 条，结论见 `research/110-strategy-verification/000-CONCLUSIONS`）
- **组合盘面纠偏（2026-08）**：废弃「资金域=风险维度」旧模型 → 三轴正交（market×segment×qualifier）+ 资金池 + 资金墙=买入预算 + 实时汇率 fx
- 公开仓库 Open-FengInvest 重建：框架/工具/知识库公开，个人数据（holdings/portfolio/logs/060-companies 等）零泄露

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

- [ ] 触发引擎支持：价格阈值 / 回顾日期 / thesis失效 / 大盘年线（当前 daily 只做退出检查）

### 数据管道

- [ ] 8766.T 负价格清理（P0，13,856 行）
- [ ] 其他 16 市场基本面（P1 非核心，待定）

---

## Phase 4 — 深化

- [ ] 市场价格推送（日频数据自动抓取）
- [ ] 持仓盈亏实时计算（Web UI 显示）
- [ ] 双账户（投资账户 + 交易账户）支持
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
