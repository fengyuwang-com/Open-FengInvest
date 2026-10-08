# Holdings 持仓格式标准

所有持仓文件放在 `holdings/` 目录下。

## 文件命名

| 类型 | 模式 | 示例 |
|:-----|:-----|:-----|
| 进行中 | `hold_<TICKER>.json` | `hold_0700.HK.json` |
| 已关闭 | `hold_<TICKER>_closed_<YYYY-MM-DD>.json` | `hold_0700.HK_closed_2026-08-15.json` |

非股票资产用唯一标识代替 TICKER（如 `hold_cmb_deposit_001.json`）。

---

## 完整字段定义

```jsonc
{
  // ─── 基础信息 ────────────────────────────────────
  "id": "0700.HK",                        // 唯一标识，股票用 TICKER
  "name": "腾讯控股",                      // 中文名称
  "asset_type": "stock",                  // 资产类型: stock|fund|cash|deposit|bond|other
  "currency": "HKD",                      // 计价货币 ISO 4217
  "capital_zone": "OVERSEAS",             // 资金域: CN_IN=境内 | OVERSEAS=境外（仅作买入预算，见"资金墙"章节）
  "market": "CN_OVS",                     // 资产类别/家国市场: CN_A=A股 | CN_HK=港股通 | CN_OVS=中概境外 | US=美股 | GLOBAL=全球多市场（可扩展）
  "segment": "互联网",                    // 细分板块（粒度需能区分不同风险驱动，如 半导体·AI算力 vs 半导体·存储；可扩展）
  "qualifier": null,                      // 现金属性: cash=真现金 | quasi_cash=准现金(低波高息当现金) | 缺省=权益
  "broker": "FUTUSECURITIES",             // 托管券商/机构
  "account_type": "INVESTMENT",           // 账户类型: INVESTMENT|TRADING|RETIREMENT|SAVINGS
  "lifecycle_phase": "holding",           // 阶段: research|buying|holding|exiting|closed

  // ─── 持仓明细（按资产类型） ────────────────────────
  "position": {
    // --- stock (股票) ---
    // "shares": 1000,                     // 股数
    // "avg_cost": 380.0,                  // 均价
    // "current_price": 420.5,             // 当前市价
    // "market_value": 420500,             // 市值 = shares * current_price

    // --- fund (基金/ETF) ---
    // "units": 5000,                      // 份额
    // "nav": 12.5,                        // 最新净值
    // "market_value": 62500,              // 市值 = units * nav

    // --- cash (现金/活期) ---
    // "amount": 100000,                   // 金额
    // "currency": "HKD",                  // 币种
    // "bank": "恒生银行",                  // 银行名

    // --- deposit (定存/理财) ---
    // "principal": 500000,                // 本金
    // "rate": 3.5,                        // 年化利率%
    // "term_months": 12,                  // 期限(月)
    // "start_date": "2026-01-15",         // 起息日
    // "maturity_date": "2027-01-15",      // 到期日
    // "expected_interest": 17500,         // 预期利息
    // "auto_renew": false,                // 是否自动续期
    // "bank": "招商银行",                  // 银行名

    // --- bond (债券) ---
    // "face_value": 100,                  // 面值
    // "price": 98.5,                      // 买入净价
    // "coupon_rate": 2.8,                 // 票面利率%
    // "quantity": 100,                    // 张数
    // "maturity_date": "2028-06-01",      // 到期日
    // "market_value": 9850,               // 市值

    // --- other (其他资产) ---
    // "description": "XXX 私募股权",       // 描述
    // "cost": 200000,                     // 成本
    // "estimated_value": 250000,          // 估算价值
    // "valuation_method": "cost|market",  // 估值方法
    // "remark": "备注"
  },

  // ─── 财务追踪 ────────────────────────────────────
  "capital": {
    "total_invested": 380000,             // 累计投入本金
    "total_fees": 500,                    // 累计交易费用
    "total_dividends": 2500,              // 累计股息/利息收入
    "realized_pl": 0,                     // 已实现盈亏（部分卖出）
    "cost_basis": 380000,                 // 成本基数 = total_invested - recovered
    "currency": "HKD"                     // 本位币
  },

  // ─── 钱仓滚存 ────────────────────────────────────
  "capital_rollover": {
    "total_invested": 380000,             // 累计投入本金
    "recovered": 0,                       // 已回收金额
    "recoverable_at_price": 450,          // 可回收本金的触发价
    "zero_cost_shares": 0,               // 零成本股数
    "phase": "capital_at_risk"            // at_risk|partial_recovery|capital_recovered
  },

  // ─── 交易记录 ────────────────────────────────────
  "trades": [
    {
      "date": "2026-05-20",
      "type": "buy",
      "shares": 1000,
      "price": 380.0,
      "fees": 500,
      "currency": "HKD",
      "note": "首次建仓，L4报告推荐高置信买入"
    }
  ],

  // ─── 投资论点 ────────────────────────────────────
  "thesis": {
    "original": "对标腾讯估值，比价效应折价约20%，看好AI产品化能力",
    "summary": "比价 MSFT，AI 变现驱动估值修复",
    "principles": ["坐标原则", "家国原则"],
    "benchmark": "MSFT",                  // 对标标的
    "valuation_gap": 0.20,               // 预期价差
    "expected_return": 0.30,             // 预期回报率
    "time_horizon_months": 12,           // 持有期限
    "exit_conditions": [                  // 退出条件
      "价差收敛到<10%",
      "政策重大变化",
      "护城河被侵蚀"
    ],
    "mirror_test": "我以__元买入__，因为：1生意本质…2护城河…3管理层…4价格相当于内在价值_折…5即使错了下行风险可控",  // 镜子测试，5句话说不完整=不买
    "financials_asof": "2025Q4",          // PIT 点及时：分析所依据的最新财报期（可选，缺省=latest）
    "hypotheses": [                       // 可证伪假设（3-7条，每条含可证伪预期+验证方式+频率）
      { "id": "H1", "statement": "收入增速≥15%", "verify": "季报", "freq": "每季度", "status": "valid",
        "outcome": {                       // 预测-结果闭环：登记时必填 expected+horizon，复盘必判 status+evidence
          "expected": "FY2026 营收 ≥ 520 亿",  // 可证伪的量化/可观察预期（登记时必填，附来源更佳）
          "horizon": "12个月",                 // 预期验证期限（如 90d / 12个月）
          "status": "pending",                // pending|hit|falsified|partial（复盘判定）
          "evaluated_date": null,             // 判定日期 YYYY-MM-DD（复盘时必填）
          "evidence": null                    // 事后事实，具体数字/来源（复盘时必填，禁止"大概还行"）
        } }
      // status: valid(🟢成立) | weakened(🟡弱化) | damaged(🔴受损) | broken(⚫破裂)
      // outcome.status: pending(⏳未到期) | hit(✅命中) | falsified(❌证伪) | partial(⚠️部分兑现)
    ],
    "redlines": [                         // 红线清单（触发动作预写，恐慌时不现场决策）
      { "id": "R1", "severity": "fatal", "trigger": "核心论点被证伪", "action": "立即清仓" }
      // severity: fatal=清仓 | severe=减50%重评 | warning=调查
    ]
  },
  "health_score": 10,                     // 论文健康度 10 分制 = 10 - 破裂×3 - 受损×2 - 弱化×1 - 红线×5 - outcome.falsified×1（脱节条目才扣，见"outcome 判定"章）

  // ─── 检查/复盘记录 ──────────────────────────────
  "reviews": [
    {
      "date": "2026-07-01",
      "type": "monthly",                 // buy|monthly|quarterly|exit|ad_hoc
      "thesis_valid": true,
      "triggers_ok": true,
      "notes": "AI 产品线持续深化，继续持有",
      "action": "hold",                  // hold|add|reduce|exit
      "health_score": 8,                 // 10 - 破裂*3 - 受损*2 - 弱化*1 - 红线*5 - falsified*1
      "outcome_check": {                 // 本次复盘 outcome 判定汇总（复盘必填，见"outcome 判定"章）
        "hypotheses_evaluated": 2,       // 本次判定的假设条数
        "hit": 1, "falsified": 0, "partial": 0, "pending": 1,
        "outcome_score": 8               // 0-10 = 10 - falsified*2 - partial*1（下限 0）
      }
    }
  ],

  // ─── 触发条件 ────────────────────────────────────
  "triggers": {
    "price_up_alert": 0.15,              // 涨15%提醒
    "price_down_alert": -0.10,           // 跌10%提醒
    "next_review_date": "2026-08-01",    // 下次必审日期
    "thesis_invalidation": false,        // 论文失效标记
    "stop_loss_pct": -0.20               // 止损线
  },
  // TRADING 交易钱包可增选: "trade_entry"（触发源/机械止损线/时间窗/证伪触发/滚存线，见下文「trade_entry」节；可选，缺省不报错）

  // ─── 元数据 ──────────────────────────────────────
  "meta": {
    "created_at": "2026-05-20",
    "updated_at": "2026-07-19",
    "version": 2,
    "source": "manual|fengwatch_import|futu_sync"
  }
}
```

## 投机/交易账户（TRADING）· trade_entry

交易钱包（`account_type: "TRADING"`，见 [docs/11-speculation-track.md](docs/11-speculation-track.md)）不强制投资钱包的完整 thesis，
改用轻量交易纪律 `trade_entry` 记录「触发源 / 机械止损线 / 时间窗 / 证伪触发 / 滚存线」。

**可选字段**：缺少该字段的旧 JSON 正常读取、不报错；建议 TRADING 账户补齐 `entry_trigger` 与 `stop_line`
（机械止损是交易钱包唯一的退出按钮，见六条纪律「双账户制」）。

```jsonc
"trade_entry": {                        // 可选：TRADING 交易钱包的交易纪律捆（T3 纪律捆落地）
  "entry_trigger": "右侧突破：周线站上 60 日高点 + 放量确认",  // 触发源：右侧突破 | 事件驱动（禁止投井、A/B 点）
  "stop_line": 345.0,                   // 机械止损线（价格水平，跌破强制退出；亦可写跌幅如 -20%）
  "time_window": "3个月",                // 时间窗上限（事件交易 1-3 个月 / 波段 3-12 个月，到点未兑现退出）
  "disproof_trigger": "重组失败/业绩证伪/题材降温",  // 证伪触发：事件方向反转即时退出（事件证伪 ≠ 等价格止损）
  "rollover_line": 480.0                // 滚存线：回收本金 / 滚存的触发价（联动「钱仓滚存」）
}
```

- `stop_line` 与 `triggers.stop_loss_pct` 是同一纪律的两面：前者是登记时的绝对价格预案（预写条件单），后者是 fengwatch 百分比兜底；两者任一触发即按机械止损执行。
- `time_window` 到点未兑现 = 结构性失败，即便价格未破 stop_line 也应退出（投机有刹时限，投资无时间窗）。

## outcome 判定（预测-结果闭环）

复盘的核心动作：登记时写下**可证伪预期**（`outcome.expected`），复盘时对照**事后事实**判定命中/证伪（hit/falsified/partial/pending），形成纪律闭环（借鉴 decision_signal_outcome_service 的"预测落库 → 事后判定"模式）。

### 字段示例（纯 JSON，可作校验基准）

```json
{
  "thesis": {
    "hypotheses": [
      {
        "id": "H1",
        "statement": "AI 云收入保持高速增长",
        "status": "valid",
        "outcome": {
          "expected": "FY2026 营收 ≥ 520 亿（管理层指引下限）",
          "horizon": "12个月",
          "status": "falsified",
          "evaluated_date": "2026-08-15",
          "evidence": "FY2026H1 营收 480 亿，全年达不到 520 亿下限（2026-08-12 中报）"
        }
      },
      {
        "id": "H2",
        "statement": "毛利率维持在 50% 以上",
        "status": "valid",
        "outcome": {
          "expected": "FY2026 全年毛利率 ≥ 50%",
          "horizon": "12个月",
          "status": "pending",
          "evaluated_date": null,
          "evidence": null
        }
      }
    ]
  },
  "reviews": [
    {
      "date": "2026-08-15",
      "type": "monthly",
      "thesis_valid": false,
      "triggers_ok": false,
      "notes": "H1 预期被中报证伪，论文降级",
      "action": "reduce",
      "health_score": 6,
      "outcome_check": {
        "hypotheses_evaluated": 2,
        "hit": 0,
        "falsified": 1,
        "partial": 0,
        "pending": 1,
        "outcome_score": 8
      }
    }
  ]
}
```

### 规则

- **登记必填 `expected`**：`thesis.hypotheses[].outcome.expected`（可证伪的量化/可观察预期）+ `horizon`（验证期限）在登记时必填——"没有可证伪预期的假设不是假设"（见 fengholding 论文建立段）。
- **复盘必判 `outcome`**：每条 hypothesis 复盘时对照 expected vs actual 事实判定四档 `hit/falsified/partial/pending`，`evidence` 必填具体数字/事实+来源，禁止"大概还行"；`evaluated_date` 必填判定日期；判不了写 `pending` 并注明缺什么数据。
- **outcome 是证据，thesis_valid 是结论**：单条假设的 outcome 只记录"预期兑现没有"，不等于论文结论；`thesis_valid` 由四态（valid/weakened/damaged/broken）+ 红线综合得出。但证据必须驱动结论：
  - `falsified` 或 `partial` 累计 ≥2 → `thesis_valid` 必须降级（或设红线 `triggers.thesis_invalidation = true`），不许证据层已两次未兑现、结论层仍"有效"
  - `pending` 超过该条 `horizon` 的 2 倍 → 强制判定（数据实在拿不到 → 判 `falsified` 并注明"不可验证"，不允许无限挂起）
- **outcome_score**（0-10，`reviews[].outcome_check.outcome_score`）= `10 − falsified×2 − partial×1`（下限 0）。outcome_score 是**证据层分数**（只度量预测兑现率），health_score 是**结论层分数**（论文整体健康，含四态与红线）；两者并行记录。health_score 公式中的 `− outcome.falsified×1` 只针对"outcome 已判 falsified 但四态未同步降级"的脱节条目；该假设已按 damaged/broken 扣分则不重复扣。

## 多币种资产

当持仓涉及多币种时，`position` 内 currency 字段区分。市值/成本汇总统一用**人民币等值**记录在 `capital.market_value_equiv_cny` / `capital.cost_basis_equiv_cny`（等值按 `meta.fx_rates` 汇率快照折算，更新快照时同步重算）。

### 汇率（实时 vs 快照）

- **实时**：`python tools/fengdata.py fx --mode fx` 取 Yahoo `USDCNY=X`/`HKDCNY=X`/`USDHKD=X`（零依赖 stdlib），失败自动回退快照。
- **快照**：`meta.fx_rates` 字段记录折算用汇率与日期（`USD_CNY` / `HKD_CNY`），供离线/离线兜底。

```jsonc
"meta": {
  "fx_rates": {
    "date": "2026-08-12",
    "USD_CNY": 6.7414,
    "HKD_CNY": 0.8586,
    "source": "Yahoo Finance (USDCNY=X, HKDCNY=X)"
  }
}
```

## 资金墙（外汇管制 · 仅限资金划转）

**资金墙约束的是"现金本体能否跨账户划转"，不约束"获得市场敞口"。** 境内人民币可买纳斯达克 QDII/中概基/港股基金，港币可买 A 股 ETF，美元可买中概——敞口由标的下层决定，不由账户决定。因此资金墙**绝不用于风险告警或配置维度**，只回答「一笔新买入该从哪个池子掏钱」：

| 资金域 | 含义 | 买入预算池 |
|:-------|:-----|:----------|
| `CN_IN` 境内 | 人民币账户，现金不可直接出境（但可经基金/港股通获得境外敞口） | 境内池 |
| `OVERSEAS` 境外 | 港币/美元账户，现金不可直接入境（同理可经工具获得境内敞口） | 境外池 |

**港股通特例（境内资金投港股）**：`CN_IN` 资金通过港股通可投港股（如 0700.HK），此时 `capital_zone=CN_IN` 且加标 `market_access: "hksi"`。资金虽标的市场在境外，但**实质未出境**（可随时回境）。

`capital_zone` 缺省推断规则：`currency = CNY → CN_IN`，`HKD/USD → OVERSEAS`；**港股通手动标 `CN_IN` + `market_access: "hksi"`**；显式填写优先。

## 风险盘面：正交维度 · 人民币一盘棋

**风险一律合并全部币种（人民币等值）按正交维度看整体，不按账户域、不预设命名桶。** 每个持仓沿三根正交轴标注，运行期由 `fengportfolio.py` 分组求和生成分布与集中度告警：

| 轴 | 含义 | 参考词汇（可自由扩展，不写死） |
|:---|:-----|:------|
| `market` 资产类别/家国市场 | 经济暴露在哪（家国原则） | `CN_A` A股 / `CN_HK` 港股通 / `CN_OVS` 中概境外 / `US` / `GLOBAL` |
| `segment` 细分板块 | 行业细分，粒度需能区分不同风险驱动 | `互联网` `消费电子` `半导体·AI算力` `半导体·存储` `代工·晶圆` `保险` `银行` `医药` `家电` `旅游` `低波高息` |
| `qualifier` 现金属性 | 现金/准现金 | `cash` 真现金 / `quasi_cash` 准现金(低波高息当现金) / 缺省=权益 |

要点：
- **不预设命名桶**（如"中概专属桶"）——买新标的/新板块直接加词，轴照算，桶自动变。
- 分类词汇参考 GICS 层级但**不受其限制**：GICS 把 NVDA 与美光同归 `Semiconductors`，粒度太粗；应细到能区分**逻辑/AI算力(fabless)** vs **存储(内存IDM，强周期)** 等不同风险驱动。
- `qualifier` 决定"资金池"：真现金 + 准现金（低波高息当现金）不参与权益集中度，单列为**资金池**（空仓等待的机会储备，符合取舍原则"手上要有钱"）。
- 集中度阈值：market 红>35%/黄>28%，segment 红>25%/黄>20%，组合(market×segment) 红>20%/黄>15%，单标 红>20%/黄>15%（占总资产%）。

## 闭仓流程

当卖出清仓时：
1. 文件重命名：`hold_<TICKER>.json` → `hold_<TICKER>_closed_<YYYY-MM-DD>.json`
2. `lifecycle_phase` → `"closed"`
3. `trades` 追加卖出记录和最终盈亏
4. `capital.realized_pl` 更新最终盈亏

## 向后兼容

`fengwatch.py` 的 `load_holdings()` 读取时，缺失字段统一填充 `None` 或合理默认值。新加字段不影响旧文件读取。
