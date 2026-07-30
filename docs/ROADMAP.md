# FengInvest — 路线图

> 当前状态：Phase 2 (Web UI MVP) 完成，进入 Phase 3 (系统完善)

---

## Phase 3 — 当前阶段：系统完善

### P3.1 清理废墟

- [x] 删除 `fengweb.py`（旧 Flask） — 已迁移到 `fengweb/`
- [x] 删除 `web/` 目录（旧 Flask 模板） — 已迁移到 `fengweb/views/`
- [ ] 确认 `rules/discipline.md` 内容已整合到 `knowledge/discipline/`，删旧文件
- [ ] 确认 `portfolio/current.md` 是否还需要，或整合到持仓JSON

### P3.2 知识库补全

- [ ] 填充 `knowledge/methodology/` — 六步分析法、比价效应、极端压力测试、产业资本定价
- [ ] 填充 `knowledge/market_view/` — A股生态、周期观、政策观
- [ ] 填充 `knowledge/personal/` — 个人原则、交易复盘模板、学习笔记
- [ ] 所有知识库文件添加 `type` 和 `source` frontmatter

### P3.3 触发引擎上线

- [ ] `alerts/today.json` 生成脚本（定时检查 holdings/，输出提醒）
- [ ] Web UI 首页提醒卡片接入真实数据（目前为空）
- [ ] 触发引擎支持：价格阈值 / 回顾日期 / thesis失效 / 大盘年线

### P3.4 决策日志 + 复盘系统

- [ ] `logs/journal.jsonl` 写入脚本（卖出/买入时自动记录）
- [ ] `reviews/` 复盘模板 + 自动存档（退出时生成 review_*.md）
- [ ] Web UI 决策日志页接入真实数据

### P3.5 Web UI 增强

- [ ] **市场数据页** — 显示大盘指数（恒指/上证/标普）、市场温度、宏观指标
- [ ] **股票分析页** — 输入TICKER显示快速数据卡片（价格/PE/PB/ROE）
- [ ] **持仓详情页** — Thesis 完整展示、滚存计算、回顾按钮
- [ ] **API 端点文档** — 当前 REST API 接口没有文档

### P3.6 TradingView Scraper 集成

- [ ] 评估 [svetlozardraganov/tradingview.com-scraper](https://github.com/svetlozardraganov/tradingview.com-scraper)
  - 技术面数据（RSI/MACD/均线）
  - 基本面数据（PE/PB/市值）
  - 能否替代/补充 fengdata.py 的 yfinance 数据
- [ ] 如果可用 → 集成到 M 层数据流程
- [ ] 如果不可用 → 搜索替代方案或自己写一个轻量版

### P3.7 文档更新

- [ ] `docs/` 下各层文档同步最新规则
- [ ] FRAMEWORK.md 同步目录结构
- [ ] fengweb/ 添加 README（如何开发/部署）
- [ ] API 端点文档

---

## Phase 4 — 深化

- [ ] 市场价格推送（日频数据自动抓取）
- [ ] 持仓盈亏实时计算（Web UI 显示）
- [ ] 卖出前检查清单 Web 交互版
- [ ] 复盘编辑表单 Web 版
- [ ] 双账户（投资账户 + 交易账户）支持
- [ ] 钱仓滚存计算器增强（从静态表单 → 联动持仓数据）

## Phase 5 — 云端 (可选)

- [ ] Docker 化部署
- [ ] 数据持久化（文件系统 → SQLite/Postgres）
- [ ] 定时任务（每日触发引擎自动运行）
- [ ] 移动端适配

---

## 当前已知问题

1. 知识库 methodology/ market_view/ personal/ 为空
2. alerts/ logs/ reviews/ 目录存在但没有数据文件
3. CLAUDE.md 最近已更新，FRAMEWORK.md 待同步
4. fengweb.py + web/ 旧Flask占用空间
5. 持仓详情页 Thesis 展示不完整
6. 没有市场总览数据（大盘指数/市场温度）
7. README.md 未反映完整项目结构
