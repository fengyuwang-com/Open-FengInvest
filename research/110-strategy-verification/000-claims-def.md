# FengInvest 论断定义登记（Claims Registry）

> 每条论断的**定义**只在本文件维护一次，`tools/fengverify.py` 按 `id` 读取定义并执行回测。
> 定义即契约：脚本逐字实现本文件的字段语义；改定义 = 改版本，须留档。
> **登记 ≠ 已实现**：`implemented: false` 的条目仅完成定义登记（契约），引擎会明确报
> "已登记未实现"而不误跑；复测排程见 000-CLASSIFICATION.md。当前引擎已实现 #1。
> 复制下方 YAML 数组里一个条目并在 `claims:` 追加即可登记新论断。

## 字段语义

| 字段 | 含义 |
|:-----|:-----|
| `id` | 论断编号，对应 `000-52-claims.md` 的 ID |
| `statement` | 论断原文（可证伪陈述） |
| `h0` | 零假设（H₀） |
| `data_scope` | 数据域：市场清单 / 类别 / 幸存者说明 |
| `signal_def` | 信号定义：用什么算（close vs MA200） |
| `holding_days` | 持有期（交易日）清单 |
| `verdict_metric` | 判据：主判据（唯一裁决依据）/ 辅助 / 仅参考 |
| `price_basis` | 价格口径（前复权） |
| `cost_bps` | 交易成本（基点，1 bp = 0.01%） |
| `oos` | 样本外定义 |
| `protocol_refs` | 方法准则引用（铁律 + §8.1 协议） |

---

## YAML 定义（机器读）

```yaml
claims:
  - id: 1
    folder: 001-above-annual-line
    title: 年线之上买入收益优于下方
    statement: >-
      指数/个股收盘价在 200 日均线（年线）上方时买入持有，其（风险调整后）
      收益显著优于在年线下方买入；持有期越长优势越明显。
    h0: 年线上下买入的持有期收益无差异（above 均值 − below 均值 = 0）。
    data_scope:
      markets: [AU, CA, CH, CN, DE, ES, FR, HK, IN, IT, JP, KR, NL, NZ, SE, SG, TW, UK, US]
      category: stock
      survivorship: >-
        本地库 indices 仅含当前成分股快照，不含退市/被剔除股票（见
        survivorship-bias-report.md）；结果存在幸存者偏差，方向为高估收益。
    signal_def:
      key: close > MA200(200 交易日收盘移动平均)
      lookahead: >-
        信号在 T 日收盘后可确定；成交从 T+1 交易日开始持有，避免"当日收盘价
        又做信号又做成交"的前视。
    holding_days: [20, 60, 120]
    verdict_metric:
      primary: 平均收益（above 组·扣除成本后均值 − below 组·未扣成本均值）
      secondary: 中位收益
      reference_only: 胜率
      note: >-
        原论断承诺"收益"，故主判据必须用收益（铁律一）。原脚本用胜率裁决属
        判据错位。"风险调整后"在本条 v1 复测中操作化为持有期平均收益（未做
        波动率口径调整，见 audit-notes）。
    price_basis: 前复权 close（daily_data.close，见 000-data-biases.md A.1 已确认）
    cost_bps: 25
    cost_note: >-
      信号组（年线上买入策略）在持有期满卖出时扣 25 bps（0.25%，FEE 0.15% +
      SLIPPAGE 0.1% 单边口径，简化按一次扣减）成本；对照组（年线下买入）不扣，
      收益差为净差 vs 毛差口径，偏向保守于信号组。
    oos: 每标的自有交易日后 20% 数据单独跑同口径，报告收益差与 CI
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md   # 铁律一~四
      - research/070-reports/000-data-biases.md §8.1      # 可信回测协议
      - research/110-strategy-verification/000-FORMAT-SAMPLE-白话卡.md
  - id: 3
    folder: 003-annual-line-noise
    title: 年线穿越噪音占比
    statement: >-
      各市场年线（MA200）穿越事件中，约 25-33% 为 1 日噪音（假突破：信号
      后 1 个交易日内即被反向穿越还原）。
    h0: 年线穿越事件中 1 日噪音占比为 0（无假突破）。
    data_scope:
      markets: [AU, CA, CH, CN, DE, ES, FR, HK, IN, IT, JP, KR, NL, NZ, SE, SG, TW, UK, US]
      category: stock
      survivorship: 本地库仅含当前成分快照（幸存者高估源）
    signal_def:
      key: 收盘价上穿/下穿 MA200 的穿越事件（事件计数型）
      lookahead: 事件在 T 日收盘后确定，噪音判定只涉及 T 与 T+1 两日
    holding_days: []
    verdict_metric:
      primary: 1 日噪音占全部穿越事件的比例（论断口径 25-33%）
      note: 事件统计型论断，主判据是占比而非收益差
    price_basis: 前复权 close
    cost_bps: 25
    cost_note: 事件统计不涉及交易成本（保留字段与 schema 一致）
    oos: 后 20% 样本单独报告噪音占比
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md   # 铁律一~四
      - research/070-reports/000-data-biases.md §8.1      # 可信回测协议
    implemented: false
  - id: 5
    folder: 005-shanghai-annual-symmetry
    title: 上证年线持续期对称
    statement: >-
      上证指数年线上方与下方持续期对称（上/下比≈1.0），与 #4 美股 2.8x 构成反例对照。
    h0: 上证年线上下持续期比例 ≠ 1.0。
    data_scope:
      markets: [CN]
      category: index
      survivorship: 指数为全历史连续序列，无退市问题
    signal_def:
      key: 指数收盘价站上/跌破 MA200 的持续期（连续交易日数）
      lookahead: 持续期按 T 日收盘后可确定的信号分段
    holding_days: []
    verdict_metric:
      primary: 上方持续期总和 / 下方持续期总和（判据≈1.0，给出 95% CI 说明容差）
      note: 事件统计型论断
    price_basis: 前复权 close（指数）
    cost_bps: 25
    cost_note: 事件统计不涉及交易成本
    oos: 后 20% 样本单独报告比例
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md
      - research/070-reports/000-data-biases.md §8.1
    implemented: false
  - id: 6
    folder: 006-annual-line-hold
    title: 年线上停留条件期望
    statement: >-
      指数已站上年线 10 天后，额外停留的期望天数 ≥ 无条件期望的 2 倍。
    h0: 条件额外停留期望 ≤ 无条件期望（倍数 ≤ 1）。
    data_scope:
      markets: [AU, CA, CH, CN, DE, ES, FR, HK, IN, IT, JP, KR, NL, NZ, SE, SG, TW, UK, US]
      category: stock
      survivorship: 本地库仅含当前成分快照（幸存者高估源）
    signal_def:
      key: 站上年线 ≥10 天后继续停留的额外天数 vs 无条件停留天数
      lookahead: 条件判定在 T 日收盘后可确定
    holding_days: []
    verdict_metric:
      primary: 条件额外期望天数 / 无条件期望天数 的倍数（判据≥2）
      note: 事件统计型论断
    price_basis: 前复权 close
    cost_bps: 25
    cost_note: 事件统计不涉及交易成本
    oos: 后 20% 样本单独报告倍数
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md
      - research/070-reports/000-data-biases.md §8.1
    implemented: false
  - id: 8
    engine: monthly-surge-prob
    folder: 008-monthly-surge
    title: 月度暴涨后动量反转
    statement: >-
      单月涨幅 >30% 的标的，次月继续上涨的概率 <40%（月度动量反转）。
    h0: 月涨幅>30% 无预测能力（次月上涨概率 = 50%）。
    data_scope:
      markets: [AU, CA, CH, CN, DE, ES, FR, HK, IN, IT, JP, KR, NL, NZ, SE, SG, TW, UK, US]
      category: stock
      survivorship: 本地库仅含当前成分快照（幸存者高估源）
    signal_def:
      key: 过去 20 个交易日（≈1 月）涨幅 >30% → 信号组；其余为对照组
      lookahead: 信号 T 日收盘确定；评估 T+1 起 20 个交易日（次月）内上涨与否
    holding_days: [20]
    verdict_metric:
      primary: 信号组"次月上涨概率"是否 <40%（判据=概率阈值，非收益差）
      secondary: 信号组与对照组上涨概率之差 + 显著性
    price_basis: 前复权 close
    cost_bps: 25
    cost_note: 动量统计，成本列为保守口径参考
    oos: 后 20% 样本单独报告上涨概率
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md   # 铁律一~四
      - research/070-reports/000-data-biases.md §8.1      # 可信回测协议
    implemented: true   # 引擎已实现（fengverify.py monthly-surge-prob 模式）
```
