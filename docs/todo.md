# FengInvest — 数据库构建 TODO

## 当前数据库状态（⚠️ 下表为 2026-07-23 建库期快照，已过时——终态见文末 T 条：21 市场 / 2,126 只 / 13,053,253 行，活跃标的统一更新至 2026-08-21）

| 市场 | 股票数 | 有数据 | 行数 | unadj_close | 状态 |
|:-----|:------|:------|:-----|:------------|:-----|
| 🇺🇸 US | 503 | 484 | 4,201,955 | 100% ✅ | ✅ |
| 🇯🇵 JP | 225 | 204 | 1,277,641 | — | ✅ |
| 🇭🇰 HK | 85 | 85 | 377,839 | 100% ✅ | ✅ |
| 🇰🇷 KR | 200 | 197 | 961,116 | — | ✅ |
| 🇹🇼 TW | 50 | 50 | 293,762 | — | ✅ |
| 🇮🇳 IN | 50 | 50 | 299,141 | — | ✅ |
| 🇦🇺 AU | 200 | 197 | 1,130,280 | — | ✅ |
| 🇩🇪 DE | 40 | 40 | 248,544 | — | ✅ |
| 🇫🇷 FR | 39 | 39 | 262,320 | — | ✅ |
| 🇬🇧 UK | 96 | 96 | 749,245 | — | ✅ |
| 🇸🇬 SG | 30 | 30 | 164,803 | — | ✅ |
| 🇨🇳 CN | 300 | 300 | 1,251,380 | 100% ✅ | ✅ |
| 🇨🇭 CH | 20 | 19 | 126,974 | — | ✅ (1只退市) |
| 🇳🇱 NL | 24 | 24 | 127,618 | — | ✅ |
| 🇪🇸 ES | 35 | 35 | 187,247 | — | ✅ |
| 🇮🇹 IT | 40 | 40 | 234,030 | — | ✅ |
| 🇸🇪 SE | 30 | 30 | 178,590 | — | ✅ |
| 🇳🇿 NZ | 50 | 47 | 241,341 | — | ⚠️ 3只缺/退市 |
| 🇨🇦 CA | 59 | 53 | 337,070 | — | ⚠️ 源表少1只 |
| **总计** | **2,076** | **2,020** | **13,026,697** | **US/CN/HK 100%** | ✅ |

**数据库大小：** 2,100 MB

**已有总回报指数 (Total Return)：**
- `^SP500TR`（S&P 500 总回报指数）— id=2548, 9,709行 (1988-01-04 ~ 2026-07-21)

**数据库结构新增：**
- `daily_data.unadj_close REAL` — 不复权列 ✅
- `dividends` 表 — 分红记录 ✅
- `fundamentals` 表 — 基本面快照（PE/PB/ROE/FCF/...）✅ 已建表，数据拉取中
- `cn_financials` 表 — CSMAR+fuyao 中国A股财务宽表（203字段, 384,206行, 5,828只全处理）✅
- `stkcd_map` 表 — CSMAR Stkcd → index_id 映射 ✅

---

## 📋 全面数据库审核结果

> 详见 `research/070-reports/DATABASE-AUDIT-20260723.md`

### CSMAR 数据
- ✅ 99.81% 会计恒等式通过率
- ✅ 时间范围: 1990-2025Q1 (35年)
- ✅ 5,828 只含退市 → 支撑幸存者偏差研究
- ✅ 关键股票验证正确 (茅台、宁德、工商银行等)
- ⚠️ 2025Q1 最新，滞后~4个月

### 原始数据库
- ✅ 13M 日线无重复
- ✅ US/CN/HK unadj_close 100% 回填
- ❌ fundamentals.capital_expenditure 100% NULL（需 CSMAR 补充）
- ⚠️ fundamentals 表部分字段 NULL 率 30-65%

---

## 📋 P0 — 数据质量问题

### [x] 1. fundamentals.capital_expenditure 100% NULL 🔴 → **2026-07-23 已修复 ✅**

CSMAR 原始 `.dta` 文件含资本支出字段（C002006000 / Capexp），但导入 `cn_financials` 时未选入（CF_MAP 只选了7个顶层汇总项）。
**阻塞程度：** 无此则 FCF 计算中断 → DCF 估值不可用 → 价值投资工作流受阻

修复方案：
- [x] `feng_add_capex.py` 编写（增量补填脚本）
- [x] 从 .dta 读取 C002006000 → UPDATE cn_financials（337,332行，46s）
- [x] 回填 fundamentals（298/299 只）
- 耗时：~1分钟

### [ ] 2. 8766.T 负价格数据

13,856 条 close≤0 记录全部来自 Tokai Kanko (8766.T)。需要从 daily_data 清理或标记。

### [ ] 4. CSMAR 增量更新机制（每季度新 .dta → 重新导入）

2025Q1 是最新数据，后续每季度需要增量导入新 .dta 文件。

---

## 📋 P1 — 数据完整性

### [ ] 总回报指数覆盖

| 市场 | 指数 | 数据源 | 目标数据 | 状态 |
|:-----|:-----|:-------|:---------|:-----|
| US | S&P 500 | yfinance | `^SP500TR` | ✅ 已入库 |
| US | Nasdaq 100 | yfinance | `^XNDX` | ❌ 无历史数据 |
| CN | 沪深300 | 待定 | TR 版 | ❌ 待研究 |
| HK | 恒生指数 | yfinance | 3115.HK ETF | ❌ 待评 |

### [ ] US 36 只基本面缺失
### [ ] HK 25 只基本面缺失

---

## 📋 P2 — 策略验证 — 52条投资论断

> 最新结论见 `research/110-strategy-verification/000-CONCLUSIONS.md`（已测 34 条，其中 6 条可信 / 19 条存疑 / 9 条拒绝）
> 跟踪：`research/110-strategy-verification/000-README.md`

**已测：** 34条（截至 2026-08）
**待测：** ~18条

### 最近测试

| ID | 论断 | 结果 | 日期 |
|:--:|:-----|:----|:----:|
| 21 | 上证<2638降仓降回撤 | ✅ 67.2%降低 | 07/23 |
| 22 | 大盘低于年线降仓降回撤 | ✅ ~69%降低（US/CN/HK) | 07/23 |
| 27 | 时间止损退出优于持有 | 🟡 CN支持，US/HK拒绝 | 07/23 |
| 28 | 下跌>15%基本面检查减少回撤 | 🟡 基本面检查优于硬扛6-14%，但简单止损更优；>20%改善不成立 | 07/23 |

### CSMAR 数据使以下论断可测

| ID | 论断 | 数据就绪 | 需先修 CAPEX? |
|:--:|:-----|:---------|:-------------|
| #19 | MA50<MA120+基本面恶化→避免>70%亏损 | CN: FCF/ROE/营收全面可用 | 🟡 #19 含 FCF→需 CAPEX |
| #20 | MA50<MA120+真价值→DCA优于一次性 | CN: PE历史分位+PB+股息率 | ✅ 全部已有 |
| #29 | PE>80%分位减仓减少回撤 | CN: 35年PE分位 | ✅ 全部已有 |
| #30 | PE>95%分位或市值/FCF>50x清仓 | CN: FCF可用(需CAPEX) | 🟡 需 CAPEX |
| #31 | 安全边际>30%胜率>80% | CN: 估值+持有期 | ✅ 全部已有 |
| #32 | 股息率>无风险利率跑赢 | CN: 股息率数据 | ✅ 全部已有 |

---

## 📋 P3 — 基本面数据管道（US/CN/HK）

### 已拉取的指标

| 类别 | 指标 | 状态 |
|:-----|:-----|:----:|
| 估值 | PE/PB/PS/EV-EBITDA | 🟡 US 93%, CN 100%, HK 71% |
| 盈利 | ROE/ROA/利润率 | 🟡 同上 |
| 现金流 | FCF/经营现金流 | ❌ capital_expenditure 100% NULL |
| 财务健康 | D/E/流动比率 | 🟡 同上 |
| 增长 | 营收/利润增长 | 🟡 同上 |
| 分红 | 股息率/派息率 | 🟡 同上 |

### 执行步骤

- [x] 1. 设计 fundamentals 表结构（30个字段）
- [x] 2. 写批量拉取脚本（tools/fengfundamentals.py）
- [x] 3. US 503只 全量拉取 → 入库 ✅ 467/503 (93%)
- [x] 4. CN 300只 全量拉取 → 入库 ✅ 299/300 (100%) ✅ CSMAR源
- [x] 5. HK 85只 全量拉取 → 入库 ✅ 60/85 (71%)
- [x] 6. CSMAR 季度财务数据库导入 → cn_financials 宽表（356,728行, 5,828只）
- [x] 7. 从 cn_financials 补充 fundamentals.capital_expenditure ✅ **已修复（2026-07-23）**
- [ ] 8. 价值投资者分析工作流 — fengvalue.py
- [ ] 9. 写增量更新机制（每季新 .dta → 重新导入）

---

## 📋 P4 — 价值投资者分析工作流（原计划）

> **状态变更（2026-08）**：原计划新建 `tools/fengvalue.py` 未落地——价值筛选能力已由 `fengscreen.py`（多因子全市场筛选）+ `financial_rigor.py`（市值验算/三情景估值）覆盖。以下条目保留为历史计划，不再单独建工具。

### 阶段 1 — 数据接入工具 (fengvalue.py) — 已并入 fengscreen.py

- [x] 直查 cn_financials
  - `--screen` 格雷厄姆/Buffett/深度价值筛选 ✅ **现有数据可做**
  - `--dcf` DCF 估值 ✅ **CAPEX 已补，可做**
  - `--peers` 行业对标分析 ✅ **现有数据可做**
  - 集成到 fengscreen.py 四维排名

### 阶段 2 — 全市场价值扫描

- [ ] Net-Net 营运资本扫描：`市值 < 流动资产 - 总负债`
- [ ] 巴菲特式：ROE>15% × 5年 + D/E<0.5 + OCF>NP
- [ ] 深度价值：PE<历史20%分位 + PB<1 + 股息率>3%
- [ ] 行业龙头：高ROIC + 高毛利率 + 低杠杆

### 阶段 3 — 价值策略回测

- [ ] Net-Net 策略在 A 股 1990-2025 回测
- [ ] 高 ROE 低负债组合 vs 市场
- [ ] 低 PE/PB 深度价值组合 vs 市场
- [ ] 股息率策略 vs 成长策略

### 阶段 4 — 集成到 FengInvest 框架

- [ ] L2b 量化因子增加价值因子维度 (格雷厄姆指数、FCF收益率)
- [ ] L3 碰撞引擎整合价值分析结果
- [ ] L4 报告模板增加价值分析章节

---

## 📋 当前进展 (2026-07-23)

```
已完成:
  1. ✅ unadj_close 数据修复 - US/HK/CN 全部 100%
  2. ✅ fundamentals 表建好 + fengfundamentals.py
  3. ✅ fengcost.py 回测扣费模块（19市场三档）
  4. ✅ US/CN/HK 基本面数据拉取完成（476+299+71=846只，覆盖率US 95%/CN 100%/HK 84%）
  5. ✅ CSMAR 季度数据库导入（356,728行, 5,828只, 1990-2025Q1）
  6. ✅ CN fundamentals 升级为 CSMAR 官方审计数据(100%)
  7. ✅ Claim #8-#10, #21-#24, #27-#28 回测验证
  8. ✅ CSMAR + 原始数据库全面审核报告 (research/070-reports/DATABASE-AUDIT-20260723.md)
  9. ✅ 数据库价值投资评估 + 未导入数据必要性分析 (CLAUDE.md / DATA-INVENTORY.md)
 10. ✅ **CAPEX 补填完成**（feng_add_capex.py，337K行 94.6%，fundamentals 298只）

待做:
  A. ✅ ~~导入 capital_expenditure 从 CSMAR~~ ← **K-PAX 已修好 (2026-07-23)**
     - 解锁: FCF计算、DCF估值、FCF收益率筛选、#19/#30论断 → **全部解锁**
  B. 🟡 策略验证剩余 ~18条论断（已测 34 条，见 000-CONCLUSIONS.md）
  C. ❌ 8766.T 负价格清理
  D. ❌ 幸存者偏差研究（CSMAR 已含退市股票，可推进）
  E. ⏸️ 价值投资者分析工作流（原 fengvalue.py 计划）— 并入 fengscreen.py + financial_rigor.py
  F. ❌ US 27 + HK 14 基本面缺失
  G. ❌ 总回报指数扩展（HK/CN）
```

工具缺陷待修（2026-08-15 记录）:
  H. ✅ fengcollision L2a proxy 缺陷 — 已修 (2026-08-16)：引擎自动查找 05-qualitative_lights.json（含 060-companies 路径修复）+ proxy 安全边际去掉 ROE 混入改用 PE 5 年分位（AAPL 案例 RED ✓，腾讯回归不变）+ 引擎输出 confidence_score 数值：L2a 正常输出为 MD（05-qualitative.md），碰撞引擎 `_read_json` 读不了 → l2a_raw=None → 用 proxy_l2a_lights 从量化数据推断安全边际。AAPL 案例实测：ROE 148.8% 对冲高 PE 导致安全边际误判 GREEN → 初判 BUY high/100%；人工补 05-qualitative_lights.json 才纠正为 WAIT。修复方向：引擎应自动查找 `05-qualitative_lights.json`（或解析 MD），而不是退到 proxy。
  I. ✅ report_audit 抽取器负号缺陷 — 已修 (2026-08-16)：三处正则（_KV_TABLE_RE/_KV_LABEL_RE/_parse_md_tables）支持 -? 前缀：`_parse_md_tables` 正则 `[\d,，\.]+` 不含负号，`-1.28` 被剥离符号成 `1.28`（AAPL z 分数抽检遇例）。修复：正则支持 `-?` 前缀。

数据管理待做（2026-08-23 定稿，规范见 docs/DATA-MANAGEMENT.md；同日二次修订：**网盘客户端暂不开，改为本地双份备份+定时复制**）:
  J. ✅ 数据库改造+session 包装回填（2026-08-24 两步全部完成）：第一步 tools/fengdb.py 统一安全写库入口（safe_batch 自动产 cs 变更集 + undo/snapshot/status，临时副本回滚演练 PASS）；第二步 ~/fuyao_backfill.py 转正为 tools/fengfuyao.py 走 safe_batch 写库（2026-08-24 验收：test-conn 密钥验证通过；4 只持仓重跑 backfill --force 幂等 UPSERT 80 行；首轮同值刷新产 0 字节空变更集证明幂等、修正 MAP 现金流字段名后二轮产真实 diff cs=13793 字节可 undo；进度文件迁 data/cache/fuyao_progress.json 旧档自动迁移；发现并修复两处 API 字段名——cash 端点实际为 act_cash_flow_net/invest_cash_flow_net，旧脚本经营/投资现金流一直静默漏采，补采后 600036 operating_cf_net 非空 115/121 期）
  K. ❌ 本地双备份+定时复制（替代原 BaiduPCS-Go 方案）：①建 data/changesets/ ②tools/fengbackup.py 用 robocopy 增量镜像 cs 小文件 → ~/FengInvest/backup/（该目录在百度网盘同步范围内，将来开客户端即自动上云、零改动升级）③schtasks 每日定时复制（只复制几MB小文件；活库本体不进定时任务）④全量快照低频手动触发，必须用 VACUUM INTO 安全导出——库已是 WAL 模式，裸 cp 会丢 -wal 未合并数据
  K2. ✅ invert 回滚演练完成（2026-08-24）：真实变更集在临时副本上 invert→apply 验证精确撤销（55 ops→3,516B 变更集→undo 后 sha256 与操作前完全一致），全程不碰真库
  L. ✅ 全市场A股5828只财报回填完成（2026-08-24 三班接力收工，主 Agent 独立对账验收）：done 5,129 + failed 699 = 5,828 账目自洽；failed 全部为 code=1002 查无此码（退市老票/沪B 900xxx/北交所无数据段），网络与整批回滚失败 0。cn_financials 总行数 364,961 → 384,206（+19,245）；近五季覆盖从 ~1,758 提升至 ~5,128/5,828（2026Q1/2025Q4/2025Q3/2025Q2），2026H1 1,566 只；近期质量 100%（营收/净利/资产/经营现金流/公告日全非空）。变更集共 142 个可回滚。复测失败票需 --tickers 显式列票（见 S 条 bug）。
  M. ❌ 衍生列 ETL：fuyao 仅提供 34 原始科目，cn_financials ~170 衍生指标(pe/roe/行业等)需另写重算管线

  N. ✅ a-stock-data 整合完成（2026-08-24，tools/fengastock.py 1290行，12端点全部实跑验证）：第一批6端点全过——quote(腾讯,招行38.90/PE6.51/PB0.89/is_stale机制)/valuation-hist(baostock,茅台PE-TTM 19.54处2016以来4.9%分位;招行PB分位6.1%)/ipo-date(招行2002-04-09;920号段登录前拦截exit1)/sw-industry(平安银行1991→2014→2021三次变迁+as-of消前视;本地适配:申万站点缺GeoTrust中间证书,SSL降级重试+ssl_verify_skipped标注)/adj-factor(新浪qfq33条,茅台最新除权2026-06-26,newest=1.0自检过)/macro(2026-07社融增量14017亿+PMI 49.2/49.0/49.3带stats.gov.cn来源)。第二批6端点全部落地——lhb(空窗口语义+山东黄金8-21净买8.56亿席位明细双验)/lhb-market(68条)/limit-pool(8-21涨停池54只含连板/封单/炸板字段)/unlock(空+603028非空双验)/margin(招行融资余额104.1亿)/moneyflow(120日,近20日主力净流入14.12亿)。CYQ未做（上游为本地推演非真实数据，暂无需求方）。不入库原则守住：全部端点只打印JSON。原定位保留——按需取用补缺口，不做批量回填。注意 O 项文档重写仍待执行。原开工记录（2026-08-24，用户拍板"把后端整合进系统"）：SKILL.md vendor 至 research/070-reports/vendor/（注明 Apache-2.0 出处）+ 抽内嵌 Python 建正式工具 tools/fengastock.py。第一批端点：估值历史(baostock)/上市退市日/申万行业变迁史/复权因子qfq-hfq/腾讯实时估值/社融+PMI 宏观；第二批投机轨(龙虎榜/涨停池/解禁/两融/资金流/CYQ) best-effort。不装 mootdx、不做新浪三表（已有 --sina-financials）、不入库（入库统一走 fengdb）。原评估结论保留 —— 2026-08-23：零鉴权54端点/A股专用/AI-agent Skill形态。定位=不做批量回填（CSMAR/fuyao 保留），按需取用补真实缺口：①申万行业变迁史（PIT去前视→回测v3/fengpit）②上市/退市日（唯一零鉴权源→幸存者偏差）③新浪复权因子qfq/hfq（unadj_close修复）④社融/PMI官方宏观数据（M层）⑤打板/龙虎榜/解禁/两融/资金流（fengspec数据层）。注意：单文件SKILL.md按需读章节省token，勿装自动触发skill避免与自有技能抢触发；mootdx需国内IP、httpx<0.26冲突可--no-deps绕过；东财系必须走em_get()限流防封

  O. ✅ 全量文档重写完成（2026-08-24，子 Agent 实施 + 主 Agent 验收补刀）：DATA-MANAGEMENT.md 新增「安全写入与变更集流程」+「数据源清单」两章；根/docs 两份 DEPENDENCIES.md 更新依赖实况（apsw/baostock/FinMind/yfinance 口径警示/数据源可用性现状）；CLAUDE.md+AGENTS.md 工具表补 fengdb/fengfuyao/fengastock/fengstockintl 四行；README 数据管道换终态数字；DATA-INVENTORY.md 新增 §十六（终态验收表/fuyao/a-stock-data 端点表/国际四源适配矩阵/口径备注）；FENGMEM.md 追加收工轮。主 Agent 验收：8 文件改动属实、无密钥泄露、FENGMEM 规范；另修正全仓 9 处过时"56 个工具"→62 个、ROADMAP 数据库里程碑刷新终态。遗留小项见 U。
  U. ❌ 文档验收扫出的小尾巴（非阻塞）：①requirements.txt 未固定新依赖版本（apsw/baostock/FinMind/xlrd/openpyxl）②README Web UI 段"53 数据源可视化"为旧口径未随源清单扩充 ③FENGMEM 第 40 轮编号重复出现两次（历史遗留）④docs/todo.md 顶部建库期快照表已标注过时但未删（保留原貌）

  抽查与体检发现（2026-08-24，报告见 research/070-reports/DATA-SPOTCHECK-20260824.md）:
  P. ✅ 日线坏行修复完成（2026-08-24）：KR 07-21 空洞197行 + AZN 孤立坏行 + SAP.DE 边缘行共 199 行，经 safe_batch 单变更集 UPDATE 修复（cs_20260824_064541_daily_repair_20260824.bin 12KB 可 undo）；验收=空洞复扫0行+naver独立源三只对拍逐分一致+连续性护栏全过。遗留建议：①"07-21 volume 显著低于邻行"的全市场盘中污染扫描②两代管道口径混用（07-21前裸价/07-22后前复权锚定）待统一重灌或补 unadj_close——并入 Q 项处理
  Q. ❌ unadj_close 结构性缺口：AU/CA/CH/DE/ES/FR/IN/IT/JP/KR/NL/NZ/SE/SG/TW/UK 等16市场整列为空（当年建库未灌；TW 本轮补的也只含复权价）。日线追平后统一评估各市场未复权价来源（FinMind原价/腾讯不复权档/东财不复权）
  R. 📝 口径备注（非缺陷）：operating_revenue_s 实为"营业收入"口径（非营业总收入）；少量财报行 if_correct=0 或 declare_date 空但数值无误；baostock 单socket无锁无超时是结构性隐患（fengstockdb 已串行规避，其他脚本待排查）；东财 WAF 掐 Python TLS 指纹，HK 已改走新浪源
  S. ❌ fengfuyao flush_batch 缺陷（三班发现，待修）：整块 fetch 全败时不落盘进度文件——第19批 200 只沪B全败后 failed 清单原样丢失，直接重跑会死循环。已用 workaround 收尾：锚点法（--tickers 尾段,600036 --force，让锚点成功入批触发提交）。修复方向：存在 failed 记录时 flush_batch 也强制写进度。
  T. ✅ 数据新鲜度终审（2026-08-24，看门狗目标达成后删除巡检 cron）：indices 2,126 只 / 2,118 只有行情；全部市场活跃标的日线最新=2026-08-21（上周五全球收盘），指数/ETF/宏观 50 条同日。仅两只有"滞后"且均属标的灭失而非漏采：EA 2026-08-04 私有化退市（stockanalysis 核实）、QUB.AX 麦格理财团 ~A$117亿协议收购停牌（stockanalysis 核实 Inactive）；另 7205.T/9613.T/IFL.AX/NSR.AX/XYX.AX/ARV.NZ/GMT.NZ/MNW.NZ 共 8 只为此前已验明的退市股（不做无中生有）。

板块轮动模块（2026-08-24 用户需求："研究所有开源方案后直接实施，全球板块"）:
  V. ✅ fengsector.py 板块轮动模块完成（调研→自建→验收全链路当日闭环）：
     - 调研结论：GitHub 全景 ≥8 候选无一可直接用——OpenBB 72k★ 但 AGPL-3.0 传染+重型平台不引入；RRG-Lite GPL 勿拷码；唯一可合法参考=MIT 的 deeleeramone/RRG-Dashboard 算法 + stockanalysis.com 形态。定自建。
     - 数据：新增 category='sector' 三层 universe——L-US 11 行业 SPDR（基准^GSPC）/ L-GLOBAL 8 只 iShares 全球行业 ETF 实测收编（IXN/IXJ/IXG/EXI/KXI/MXI/RXI/JXI，基准 ACWI）/ L-CN 申万一级 31 行业新浪源全量（1999 起，基准沪深300）。共入库 217,449 行，三市场统一到 2026-08-21；走 fengdb.safe_batch 共 11 个变更集。
     - 工具：tools/fengsector.py 四子命令 universe/update/analyze/dashboard；analyze 输出 RRG 四象限（RS-Ratio z-score×100、RS-Momentum、26 周尾迹、象限迁移信号）+3/6/12M 动量排名；dashboard=单文件自包含 plotly HTML（4.9MB 离线可开）research/070-reports/SECTOR-DASHBOARD.html。
     - 验收与修复：幂等复跑 new=0 通过；主 Agent 跨源复核（stockanalysis.com）抓出 IXJ 名称错误（实为 iShares Global Healthcare ETF 全球医疗保健，非金融科技）——DB/config/代码三处已修并重出 dashboard，其余 7 只 GLOBAL 名称全部核实无误。东财板块接口因 WAF 本轮禁用，A 股行业资金流叠加留待后续。
     - UI 归一（用户纠偏 2026-08-24：所有 UI 统一进 fengweb GUI，不做散装 HTML）：fengsector.py 增 longterm 子命令（沉寂榜/年度收益矩阵/CAGR/回撤曲线）+ analyze/longterm 的 --json 纯净输出；fengweb 新增 GET /sector 页面（ECharts 6.1 本地 vendor 走 npmmirror；RRG 三层切换/年度收益热力图/回撤水下图/沉寂榜/CAGR 排名）+ GET /api/sector/rotation、/api/sector/longterm 两端点；tsc 零错误，主 Agent curl 三重验证+浏览器目视截图验收通过。独立 HTML 文件降级为 CLI 副产品保留。长周期结论（申万 26 年）：深度沉寂 19 行业——钢铁 2007 峰 18.9 年未回（-70%）、2015-06 峰 12 行业（房地产 -75% 连续 74 月低于 200 周线、商贸零售 -81%）、2021 峰 6 行业（食品饮料 -59% 等）；活跃组 9 个（通信 5Y CAGR +30% 等）。已知边界：库内 000300.SS 自 2021-03 起（10Y 超额 null），环保/美容护理/石油石化为 2021 新序列。

---

批量选股流水线 + 研究域定稿（2026-08-29）:
  W. ✅ /fengbatch 自动选股流水线建成（当日验收通过）：tools/fengbatch.py（plan/status/summary）+ fengscreen.py 新增 --hard-rules 纯规则精筛（7硬指标+3豁免）+ data/config/batch_lists.json 内置 list（cn_dividend/us_quality/us_dividend）+ .agents/skills/fengbatch/SKILL.md；首跑中证红利 50 只 → 24 只幸存者。深挖单只仍走 /fenginvest。
  W2. ✅ 讨论 skill 改名+通用化：fenginvestdiscuss → fengdiscuss（读 Discussion/discuss-config.json 建锚，framework_files 可配置，任何项目可用）+ 新增 fengdiscusslog（纯记录员）。各入口文档同步更新。
  W3. ✅ 研究清单 data/config/research_list.json 新建：独立于持仓的研究/候选/观察清单，status: researching/candidate/watching/parked/holding，当前 26 家（含中证红利 24 只 candidate + NVDA watching + 9992.HK parked）。
  W4. ✅ 关注领域确立：knowledge/关注领域.md 新建（垄断性收费/资源型/成长引擎三领域，非偏好非白名单），docs/01-philosophy.md 信条5 只留指引；估值闸门提案被否定稿——筛选层保持纯质量口径不加 PE 上限（"研究谁≠何时买"，Discussion/2026-08-29-valuation-gate-rejected.md）；泡泡玛特 9992.HK 退出研究队列转带复活条件的观察（赛马机制讨论定稿，Discussion/2026-08-29-popmart-horse-racing.md）。
  X. ❌ 待做：中证红利 24 只幸存者候选池待用户挑选后逐只 /fenginvest 七层分析。
- [x] W5（2026-08-29）fengdocsync 通用文档同步 skill 建成——开源调研无合身方案故自建；配置驱动 docs/doc-sync.json + 历史档案只读 + 手术式更新

理念缺口补全（2026-09-06，七项全落地）:
  Y. ✅ 纪律执行账本 /ledger 建成（信条 7 化身）：/api/discipline/ledger 从 holdings/state/journal 算出论文齐备率、回顾拖欠、监控出勤（30 天窗口+最大断档）、分析烂尾（30 天未动未走完）、历史红灯台账；侧栏"延伸"组新增 🪞 纪律账本入口。
  Y2. ✅ 论文卡升 C 位（退出纪律"论文止损"化身）：持仓详情 thesis 原文+summary 大字+证伪红线红条清单+假设验证表+mirror_test 折叠；INVESTMENT 浮亏自动出"因论文卖不因价格卖"守卫条；无论文持仓出黄条警告（处置效应）。
  Y3. ✅ 市场页摘噪音（信条 3 执法）：领涨领跌榜+港美涨跌家数删除，新增"噪音防火墙"声明卡（判别标准：会不会改变长期价值判断）。
  Y4. ✅ 机会成本对手盘（DK 取舍原则化身）：组合页 overview 新增持仓对手盘表（市值占比/PE/浮盈亏/论文齐备），配"新钱先比加仓"提示；40% 上限注脚。
  Y5. ✅ 旱灾计时器（信条 4"防一直旱"化身）：组合页显示资金池占比+距上次买入天数（meta.buy_date/created_at 兜底），>90 天黄条自查。
  Y6. ✅ L1 红灯深度价值路径核对单（docs/03-discipline.md 化身）：研究详情页 L1 RED 时出 A+B+C+D 四条件卡（DCA 30-50%、红灯可上推不可下忽略）。
  Y7. ✅ 关注领域徽章（knowledge/关注领域.md 上 UI）：data/config/attention-domains.json 创始人可编辑映射（ticker→领域，NVDA=成长引擎已标），研究列表+报告中心显示。

## R21（2026-09-06）UI 纠错 + 数据一键/自动更新

- Z1. ✅ 组合页算法纠错：总投入漏算基金成本（units×avg_cost 不入账）、现金混进总市值、港币/美元未换汇 → /api/portfolio/overview 重写（统一换 CNY、现金单列、浮盈亏=持仓对成本）。实测 155.0万/144.6万/155.6万/-6.6%。
- Z2. ✅ 提醒中心贴身间距：.alert-item 统一 margin-bottom（宪法册二间距刻度）。
- Z3. ✅ 按钮统一原则：.btn=36px/.btn-sm=28px 一档变体；内联 padding 覆盖全站收编；表格内按钮垂直居中。
- Z4. ✅ 数据库一键+自动更新（创始人重大任务）：JobQueue 真跑 fx→持仓现价→国际日线实写（safe_batch）→财报增量；顶栏「⟳ 更新数据」按钮+进度轮询；启动超 12h 自动更新+每 30 分钟巡检；时间戳 data/cache/last_update.json。
- Z5. 待验收：创始人点顶栏按钮看全链；文档同步（00-system-guide/宪法 1.4/FENGMEM/FOUNDER-VOICES）。
