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
    engine: annual-line-crossing-noise   # 已实现（2026-09-10）；复测：python tools/fengverify.py 3
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
    implemented: true   # 引擎已实现（2026-09-10 复测：占比 27.98% 落 25-33% 带）
    retest_path: python tools/fengverify.py 3   # 复测排程：第一批（signal 直接可测），见 000-CLASSIFICATION.md
  - id: 5
    engine: annual-line-duration-ratio   # 已实现（2026-09-10）；复测：python tools/fengverify.py 5
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
    implemented: true   # 引擎已实现（2026-09-10 复测：比 1.1176，CI 含 1.0，缺 1990-98 早期数据）
    retest_path: python tools/fengverify.py 5   # 复测排程：第一批，见 000-CLASSIFICATION.md
  - id: 6
    engine: annual-line-hold-expectation   # 已实现（2026-09-10）；复测：python tools/fengverify.py 6
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
    implemented: true
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
  - id: 9
    engine: volume-pullback-rebound   # 已实现（2026-09-11）；复测：python tools/fengverify.py 9
    folder: 009-volume-pullback
    title: 缩量回踩支撑不破后反弹概率>60%
    statement: >-
      缩量回踩支撑位（MA50）不破后，后续 20 个交易日反弹（上涨）概率 >60%。
    h0: 缩量回踩无预测能力，后续上涨概率 = 50%。
    data_scope:
      markets: [AU, CA, CH, CN, DE, ES, FR, HK, IN, IT, JP, KR, NL, NZ, SE, SG, TW, UK, US]
      category: stock
      survivorship: 本地库仅当前成分快照（幸存者高估源）；volume 缺失标的整只跳过
    signal_def:
      key: >-
        信号日 T：|close_T − MA50_T|/MA50_T ≤ 1%（回踩贴近）且此前 5 日内曾收盘 > MA50×1.01
        （自上方回落）且 volume_T < 0.7 × 前 20 日均量（缩量）；支撑确认 = T+1..T+5 每日收盘
        ≥ 当日 MA50；入场 = T+6 收盘（确认后第一个可交易收盘）
      lookahead: 信号三要素 T 日收盘可得；确认只用 T+1..T+5；入场与结局在其后，无同 bar 双用
    holding_days: [20]
    verdict_metric:
      primary: 信号组入场后 20 交易日上涨概率（判据 >60%）
      secondary: 股票级 bootstrap CI
      note: 概率型论断，主判据即论断声称的量本身（铁律一）
    price_basis: 前复权 close
    cost_bps: 25
    cost_note: 主判据为方向概率，成本不改变涨跌方向；保留字段与 schema 一致
    oos: 每标的后 20% 入场事件单独报告胜率
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md
      - research/070-reports/000-data-biases.md §8.1
      - research/110-strategy-verification/000-FORMAT-SAMPLE-白话卡.md
    implemented: true
  - id: 10
    engine: volume-breakout-ranking   # 已实现（2026-09-11）；复测：python tools/fengverify.py 10
    folder: 010-breakout-volume
    title: 放量突破关键阻力位的成功率在所有技术信号中最高
    statement: >-
      排名型论断：放量突破（收盘创 50 日新高且量 > 1.5×20 日均量）的 20 交易日上涨概率
      在常见技术信号中最高——同台对比：S2 无量突破 / S3 缩量回踩支撑（#9 口径）/
      S4 金叉（MA50 上穿 MA120）。
    h0: 各技术信号 20 日胜率无差异（放量突破不系统性高于其他信号）。
    data_scope:
      markets: [AU, CA, CH, CN, DE, ES, FR, HK, IN, IT, JP, KR, NL, NZ, SE, SG, TW, UK, US]
      category: stock
      survivorship: 本地库仅当前成分快照（幸存者高估源）；volume 缺失标的整只跳过
    signal_def:
      key: >-
        S1 放量突破：close_T > 前 50 日最高收盘 且 vol_T > 1.5×前 20 日均量（前 20 日不含 T）；
        S2 无量突破：同 S1 去掉量条件（S1 ⊂ S2）；S3 缩量回踩：#9 口径原样（含 5 日确认，T+6 入场）；
        S4 金叉：MA50 上穿 MA120。各信号 T 日收盘确定，T+1 收盘入场（S3 为 T+6），
        持 20 交易日，收盘涨为胜
      lookahead: 全部信号只用 T 及之前数据；入场在信号后第一个可交易收盘
    holding_days: [20]
    verdict_metric:
      primary: S1 混合胜率在四信号中最高（pooled 与分市场双口径）
      secondary: S1−S2 胜率差的股票级 bootstrap CI（"放量"是否真能加分）
      note: 排名型论断，主判据是相对排名而非绝对阈值（铁律一：测的就是论断声称的量）
    price_basis: 前复权 close
    cost_bps: 25
    cost_note: 主判据为方向概率排名，成本不改变方向；保留字段与 schema 一致
    oos: 每标的后 20% 入场事件单独报告四信号胜率与排名
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md
      - research/070-reports/000-data-biases.md §8.1
      - research/110-strategy-verification/000-FORMAT-SAMPLE-白话卡.md
    implemented: true
  - id: 2
    engine: annual-line-filter-mdd   # 已实现（2026-09-11）；复测：python tools/fengverify.py 2
    folder: 002-annual-line-filter
    title: 年线过滤策略的最大回撤比买入持有降低 >50%
    statement: >-
      仅当收盘价 ≥ MA200 时持仓（否则空仓现金 0%），其最大回撤（全程 NAV 口径）
      相比始终持仓降低 >50%。
    h0: 回撤降幅 ≤50%（旧口径 2026-08 实测约 43%，与台账"✅7/7"记录冲突，本次复测定谳）。
    data_scope:
      markets: [AU, CA, CH, CN, DE, ES, FR, HK, IN, IT, JP, KR, NL, NZ, SE, SG, TW, UK, US]
      category: stock
      survivorship: 本地库仅当前成分快照（幸存者高估源，对两策略同向影响）
    signal_def:
      key: >-
        策略A（过滤）：第 t 日收益 = close_t/close_{t-1} − 1 若 close_{t-1} ≥ MA200_{t-1}，
        否则 0（现金不计息，保守）；每次仓位切换扣 25bps（2×25bps/往返）。
        策略B（买入持有）：始终全额持仓同口径收益。两策略均从 MA200 有效首日起累计 NAV。
        MDD = max(1 − NAV_t / max_{s≤t} NAV_s)；降幅 = 1 − MDD_A/MDD_B（每股一个值）
      lookahead: 信号用 T-1 收盘（含 MA200_{t-1}），收益落在 T 日——无同bar双用
    holding_days: [全程]
    verdict_metric:
      primary: 每股回撤降幅的股票级 EW 均值 >50%（判据即论断声称的量本身，铁律一）
      secondary: 股票级 bootstrap 95% CI；分市场降幅表
      note: 旧口径"每月采样窗口 MDD"改为主口径全程 NAV MDD（论断未限定窗口，取最直接读法）；
            63/126/252 天窗口 MDD 作为参考列一并报告
    price_basis: 前复权 close
    cost_bps: 25
    cost_note: 策略A每次切换扣 25bps（往返 50bps）；策略B一次性建仓不扣（对降幅判据偏保守）
    oos: 每标的后 20% 交易日子区间内两策略 MDD 单独报告降幅
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md
      - research/070-reports/000-data-biases.md §8.1
      - research/110-strategy-verification/000-FORMAT-SAMPLE-白话卡.md
    implemented: true
  - id: 21
    engine: rule-2638-position-cap   # 已实现（2026-09-11）；复测：python tools/fengverify.py 21
    folder: 021-shanghai-2638
    title: 上证<2638 时仓位≤30%，比不控制的组合 6 个月内回撤低 >30%
    statement: >-
      2638 法则：上证综指收盘 < 2638 时仓位降至 30%（70% 现金不计息），否则 100% 持仓；
      相对始终满仓，126 交易日（约 6 个月）滚动窗口内的最大回撤降低 >30%。
    h0: 仓位控制不降低回撤（窗口回撤降幅 ≤30%）。
    data_scope:
      markets: [CN]   # 仅上证综指 000001.SS
      category: index
      survivorship: 指数本身无幸存者问题；2638 为 2016 年熔断低点的固定价位（规则原文）
    signal_def:
      key: >-
        第 t 日仓位 = 30% 若 close_{t-1} < 2638，否则 100%；日收益 = 仓位×r_t，
        调仓日对交易部分（仓位差）扣 25bps。对照组合 = 始终 100%。
        两策略在每 126 日窗口内从窗口起点累计 NAV，取窗口内 MDD；
        每窗口降幅 = 1 − MDD_rule/MDD_hold，窗口按月滚动（每 21 日一个窗）
      lookahead: 仓位由 T-1 收盘决定，作用于 T 日收益——无同bar双用
    holding_days: [126]
    verdict_metric:
      primary: 全部 126 日窗口降幅均值 >30%（判据即论断声称的量，铁律一）
      secondary: 窗口序列圆形块 bootstrap（块长 22 保窗口重叠结构）95% CI；全程 NAV MDD 降幅参考
      note: 2638 是固定价位非移动均线——这是它与 #2 年线法则的本质区别，两卡结论不可互推
    price_basis: 前复权 close
    cost_bps: 25
    cost_note: 只对仓位变动部分（0%/30%/100% 之间切换的差额）扣 25bps
    oos: 后 20% 交易日的窗口单独报告降幅
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md
      - research/070-reports/000-data-biases.md §8.1
      - research/110-strategy-verification/000-FORMAT-SAMPLE-白话卡.md
    implemented: true
  - id: 22
    engine: annual-line-reduce-mdd   # 已实现（2026-09-11）；复测：python tools/fengverify.py 22
    folder: 022-index-below-ma
    title: 大盘低于年线时降仓位至 <30%，比不降仓位的组合在短期内回撤低
    statement: >-
      定性论断：指数收盘低于 MA200（年线）时把仓位降到 30%，其余时间 100% 持仓，
      相对始终满仓，126 交易日（约 6 个月）滚动窗口内最大回撤更低。
    h0: 不降仓位无额外风险（窗口回撤降幅 <=0）。
    data_scope:
      markets: 全部库内指数（category=index，剔除 ^VIX；含 CN/US/HK/JP/KR/EU/AP/GLOBAL）
      category: index
      survivorship: 指数层面不适用
    signal_def:
      key: >-
        第 t 日仓位 = 30% 若 close_{t-1} < MA200_{t-1}，否则 100%；日收益 = 仓位 x r_t，
        调仓日对交易部分扣 25bps；现金不计息（保守）。对照 = 始终满仓。
        每 126 日窗口（每 21 日滚动一窗）内从窗口起点累计 NAV 取 MDD，
        每窗降幅 = 1 - MDD_reduce/MDD_hold；全部指数的窗口混合同池统计
      lookahead: 仓位由 T-1 收盘（含 MA200_{T-1}）决定，作用于 T 日收益——无同bar双用
    holding_days: [126]
    verdict_metric:
      primary: 全指数窗口池降幅均值 >0 且 bootstrap 95% CI 下限 >0（定性论断，判据=方向而非阈值，铁律一）
      secondary: 分指数全程 NAV MDD 降幅表（与旧口径 ~69% 对照）；窗口中位数
      note: 与 #2（0% 空仓版）的区别在仓位下限 30%——#2 的教训是不给方向性论断硬安阈值
    price_basis: 前复权 close
    cost_bps: 25
    cost_note: 只对仓位变动部分（30/100 之间切换差额）扣 25bps
    oos: 每指数后 20% 交易日的窗口单独报告
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md
      - research/070-reports/000-data-biases.md section 8.1
      - research/110-strategy-verification/000-FORMAT-SAMPLE-白话卡.md
    implemented: true
  - id: 23
    engine: qiancang-rollover   # 已实现（2026-09-11）；复测：python tools/fengverify.py 23
    folder: 023-qiancang-rollover
    title: 浮盈>30% 时执行钱仓滚存（回收本金），在震荡市中终值优于买入持有
    statement: >-
      买入后价格较入场价上涨 >=30% 时，卖出收回初始本金（保留利润部分继续持有），
      在震荡市（窗口末收盘相对入场在 +/-20% 内）中，窗口终值高于买入持有。
    h0: 滚存 vs 买入持有无差异（终值差 <=0）。
    data_scope:
      markets: [AU, CA, CH, CN, DE, ES, FR, HK, IN, IT, JP, KR, NL, NZ, SE, SG, TW, UK, US]
      category: stock
      survivorship: 本地库仅当前成分快照（幸存者偏差使滚存与 BH 同向受益，对差值影响中性偏保守）
    signal_def:
      key: >-
        每股每 504 交易日窗口（步长 126）：BH 终值 = close_end/close_entry。
        滚存 = 窗口内首个收盘 >= 1.3x 入场价之日 T*，卖出价值 1.0 本金
        （保留仓位比例 1 - 1/v*，v* = close_{T*}/入场），卖出额扣 25bps，现金不计息：
        终值 = 1 + (1 - 1/v*) x close_end/入场 - 0.0025。终值差 = 滚存 - BH。
        震荡域 = 窗口末 +/-20% 持平的全部窗口（含未触发窗口，差值恒 0，保守）
      lookahead: 触发用窗口内可得收盘，卖出 T* 当日收盘价执行——T* 由当日收盘判定、当日收盘成交（与实盘可同步执行口径一致，已在红灯注明）
    holding_days: [504]
    verdict_metric:
      primary: 震荡域窗口终值差均值 >0 且股票级 bootstrap 95% CI 下限 >0（定性方向论断，铁律一）
      secondary: 触发子集终值差/中位数；正差值股票占比；触发窗口 MDD 降幅（滚存 NAV 含现金 vs BH）
      note: 震荡域判定使用窗口末结果（outcome-based 条件域），无法事前定义"震荡市"，已作 ⚠️ 披露；无条件全窗口对照一并列出
    price_basis: 前复权 close
    cost_bps: 25
    cost_note: 只在触发卖出时对收回本金（价值 1.0）扣 25bps；保留部分不动
    oos: 每股自有交易日后 20% 的窗口单独报告
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md
      - research/070-reports/000-data-biases.md section 8.1
      - research/110-strategy-verification/000-FORMAT-SAMPLE-白话卡.md
    implemented: true
  - id: 27
    engine: time-stop-6m   # 已实现（2026-09-11）；复测：python tools/fengverify.py 27
    folder: 027-time-stop
    title: 时间止损（6 个月论文未兑现）退出的机会成本低于继续持有的下行风险
    statement: >-
      买入后 126 交易日（约 6 个月）论文未兑现（区间收益 <=0）时退出（空仓），
      相比继续持有后续 126 交易日，机会成本低于继续持有的下行风险。
    h0: 继续持有与退出无差异（后续 126 日收益均值 >=0）。
    data_scope:
      markets: [AU, CA, CH, CN, DE, ES, FR, HK, IN, IT, JP, KR, NL, NZ, SE, SG, TW, UK, US]
      category: stock
      survivorship: 本地库仅当前成分快照（幸存者偏差使"继续持有"偏乐观，对判据保守）
    signal_def:
      key: >-
        每股每 252 交易日窗口（步长 126）：前半 r1 = close_{w+126}/close_w - 1。
        论断域 = r1 <= 0（论文未兑现）。两条路：
        退出 = 空仓 126 日（净 0，卖出成本 25bps 单列参考）；
        继续持有 = r2 = close_{w+252}/close_{w+126} - 1。
        主判据 = 域内 r2 均值与股票级 bootstrap；支持 = 均值 <0 且 CI 上限 <0（继续持有平均为负 → 时间止损胜）
      lookahead: r1 用前 126 日、r2 用后 126 日，序列不重叠——无前视
    holding_days: [126, 252]
    verdict_metric:
      primary: 域内 r2 均值 <0 且股票级 bootstrap 95% CI 上限 <0（定性方向论断，铁律一）
      secondary: 分市场 r2 均值（对照旧 🟡 CN 支持/US·HK 拒绝）；r2 胜率（<0 占比）；域内继续持有半段 MDD
      note: 论断域（r1<=0）为路径条件域，与 #23 同理披露；"机会成本"以退出净 0 为基准
    price_basis: 前复权 close
    cost_bps: 25
    cost_note: 退出一次 25bps 作为机会成本基准单列；继续持有无新增成本
    oos: 每股后 20% 窗口单独报告
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md
      - research/070-reports/000-data-biases.md section 8.1
      - research/110-strategy-verification/000-FORMAT-SAMPLE-白话卡.md
    implemented: true
  - id: 24
    engine: rollover-bull-mark   # 已实现（2026-09-11）；复测：python tools/fengverify.py 24
    folder: 024-rollover-bull
    title: 钱仓滚存在长期牛市中必然大幅跑输买入持有
    statement: >-
      承接 #23 引擎（504 日窗口、浮盈>=30% 收回本金）：在长期牛市域
      （窗口末收盘相对入场涨幅 > +30%，即滚存必然已触发且价格持续走高）中，
      滚存终值差（滚存 - 买入持有）< 0 且幅度随涨幅扩大。
    h0: 滚存可以追上（终值差 >=0）。
    data_scope:
      markets: [AU, CA, CH, CN, DE, ES, FR, HK, IN, IT, JP, KR, NL, NZ, SE, SG, TW, UK, US]
      category: stock
      survivorship: 仅当前成分快照；滚存与 BH 同框架对比，对差值中性
    signal_def:
      key: >-
        与 id=23 完全同构（首个收盘 >=1.3x 入场日卖出收回本金 1.0，保留 1-1/v*，
        25bps，现金不计息），唯一区别：论断域 = final/base - 1 > 0.30（牛市域，
        触发必已发生且期末仍在 trigger 上方）。结构性：v*=1.3 时 diff = 1 - 0.7692x(final/base) - 成本，
        随涨幅单调变负——论断自称"数学必然"，本引擎验证其实证幅度
      lookahead: 同 #23，无前视
    holding_days: [504]
    verdict_metric:
      primary: 牛市域终值差均值 <0 且股票级 bootstrap 95% CI 上限 <0（方向）；"大幅"= 幅度报告（对照中位/分位）
      secondary: 分市场均值；终值差 vs 期末涨幅的幅度表；触发窗口 MDD 降幅（同 #23 口径）
      note: 牛市域为路径条件域（outcome-based），与 #23 同理披露；"必然"部分是结构性质，实证给幅度
    price_basis: 前复权 close
    cost_bps: 25
    cost_note: 同 #23（触发卖出对收回本金 1.0 扣 25bps）
    oos: 每股后 20% 窗口单独报告
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md
      - research/070-reports/000-data-biases.md section 8.1
      - research/110-strategy-verification/000-FORMAT-SAMPLE-白话卡.md
    implemented: true
  - id: 35
    engine: diversification-curve   # 已实现（2026-09-11）；复测：python tools/fengverify.py 35
    folder: 035-diversification
    title: 10-15 只持仓消除大部分非系统风险，超过 15 只后分散化收益急剧递减
    statement: >-
      等权随机组合：持仓数 N=10-15 时已消除"大部分"非系统风险
      （组合方差相对单只平均方差的降幅 >=75%），N>15 后继续加仓的边际降幅
      急剧递减（elim(30)-elim(15) <=5 个百分点）。
    h0: 分散化收益随持仓数线性增加（无平台期）。
    data_scope:
      markets: [AU, CA, CH, CN, DE, ES, FR, HK, IN, IT, JP, KR, NL, NZ, SE, SG, TW, UK, US]
      category: stock
      survivorship: 仅当前成分快照；波动率口径下幸存者偏差影响有限（缺失的高波动退市股会使基数偏高）
    signal_def:
      key: >-
        每市场取最近 750 个交易日；选缺失 <=1% 的股票构造收益矩阵；
        对 N in [1,2,3,5,8,10,12,15,20,25,30] 各随机抽 200 个 N 只等权组合
        （种子固定），elim(N) = 1 - var(组合日收益)/mean(var(单只日收益))。
        报告分市场与全市场平均曲线
      lookahead: 无信号，纯波动结构统计
    holding_days: [750]
    verdict_metric:
      primary: elim(N=12) >= 75%（"大部分"的解释阈值）且 elim(30)-elim(15) <= 5pp（"急剧递减"的解释阈值）
      secondary: 全曲线 elim(N) 表；分市场 N=12/15/30 消除率
      note: 论断的"大部分/急剧递减"为定性词，75%/5pp 为本复测解释阈值，已在红灯披露（铁律一：先引论断自己的量）
    price_basis: 前复权 close
    cost_bps: 25
    cost_note: 纯波动统计，成本不适用；保留字段与 schema 一致
    oos: 后 20% 交易日窗口单独算曲线（oos 消除率 @N=12/30）
    protocol_refs:
      - knowledge/methodology/backtest-methodology.md
      - research/070-reports/000-data-biases.md section 8.1
      - research/110-strategy-verification/000-FORMAT-SAMPLE-白话卡.md
  - id: 37
    engine: kelly-fraction   # 已实现（2026-09-11）；复测：python tools/fengverify.py 37
    folder: 037-kelly-quarter
    title: Fractional Kelly（1/4）的复合增长率接近全 Kelly，而最大回撤降低约一半
    statement: >-
      每只股票估 f* = mu/sigma^2（日频连续 Kelly），模拟 f* vs c*f*（c=0.5/0.25）
      的对数财富路径（窗口 504 步 126，现金收益 0）。判据（解释阈值已披露）：
      cagr(0.25f*)/cagr(f*) 股票级中位数 >=0.9（"接近"），
      MDD 降幅中位数在 [40%, 60%]（"约一半"）。理论参照 g(f*/4)=0.4375*g(f*)。
    h0: 分数 Kelly 不改变风险收益。
    data_scope:
      markets: [US, CN, JP, HK, KR, TW, IN, AU, CA, CH, DE, ES, FR, IT, NL, NZ, SE, SG, UK]
      category: stock
    protocol:
      fractions: [1.0, 0.5, 0.25]
      window_days: 504
      step_days: 126
      bootstrap: 股票级折叠中位数重抽 2000 次 seed=20260820
      oos: 每只股票历史后 20% 的窗口
      robustness: f* 封顶 2.0 变体对照
      infeasible_windows: log(1+f*r) 无定义的窗口跳过并计数披露
    primary_metric: cagr(0.25*f*)/cagr(f*) 中位数
  - id: 36
    engine: core-satellite   # 已实现（2026-09-11）；复测：python tools/fengverify.py 36
    folder: 036-core-satellite
    title: 核心-卫星范式（核心50-80% ETF + 卫星20-50% 个股）的收益风险比优于纯 ETF 或纯个股
    statement: >-
      每市场主指数 + 随机 12 只个股等权（#35 甜点位），窗口 504 步 126，每日再平衡。
      核心-卫星 65/35 vs 纯指数 vs 纯 12 只个股组合的窗口 Sharpe（rf=0，年化）。
      判据：vs 两者的窗口配对差中位数 >0 且 block bootstrap(BLOCK=22, 2000 次,
      seed=20260820) CI low >0；每市场 50 组随机抽样降噪；OOS=窗口池后 20%。
    h0: 所有范式的夏普比相同。
    data_scope:
      markets: [US, CN, JP, HK, KR, TW, IN, AU, CA, DE, ES, FR, IT, NZ, SE, SG, UK]
      category: stock
    primary_metric: Sharpe(core-sat 65/35) - Sharpe(对照) 配对差
  - id: 38
    engine: cash-buffer   # 已实现（2026-09-11）；复测：python tools/fengverify.py 38
    folder: 038-cash-buffer
    title: 现金比例<10% 的组合在暴跌时失去加仓能力，3 年收益跑赢保持 15% 现金的概率 <60%
    statement: >-
      每市场主指数，3 年窗口（756 交易日步长 126）。A=满仓指数；B=85% 指数+15% 现金
      （现金 0 收益、每日再平衡），指数从窗口内滚动高点回撤 >=20% 时 15% 现金一次入市。
      主指标 = 满仓 CAGR 跑赢 B 的窗口频率 P。判据：P < 0.60（原话"3 年收益跑赢...<60%"
      的量化），block bootstrap(BLOCK=22, 2000 次, seed=20260820) CI 上限 <0.60。
      附口径：现金按 0 收益（未计利息，偏乐观于满仓一侧已保守）。
    h0: 满仓 vs 15% 现金无长期差异。
    data_scope:
      markets: [US, CN, JP, HK, KR, TW, IN, AU, CA, DE, ES, FR, IT, NZ, SE, SG, UK]
      category: index
    primary_metric: P(满仓 CAGR > 15%现金+暴跌加仓 CAGR)
  - id: 41
    engine: sector-concentration   # 已实现（2026-09-11）；复测：python tools/fengverify.py 41
    folder: 041-sector-concentration
    title: 组合行业集中度 >40% 时，发生 -30% 回撤的概率 >50%
    statement: >-
      US 个股（fundamentals.sector 覆盖 472 只，唯一市场足量；HK 71 只不足披露），
      3 年窗口 756/126。每窗口抽 100 个集中组合（10 只等权中同行业 >=4 只 = >=40%）
      与 100 个分散组合（每行业 <=2 只）。主指标 = 集中组合 MDD>=30% 的窗口级频率。
      判据：均值 >0.50 且 block bootstrap(BLOCK=22, 2000 次, seed=20260820) CI low >0.50。
      幸存者偏差方向：退市股缺失 → 回撤概率被低估，若仍 >50% 则结论更稳。
    h0: 行业集中度与回撤无关。
    data_scope:
      markets: [US]
      category: stock
    primary_metric: P(MDD >= 30% | 行业集中度 >= 40%)
    implemented: true
  - id: 11
    engine: vix-panic-buy   # 已实现（2026-09-11）；复测：python tools/fengverify.py 11
    folder: 011-vix-panic-buy
    title: VIX>30 买入 6 个月跑赢
    data_scope:
      markets: [US]
      category: index
    test_spec:
      vix_ticker: ^VIX
      index_ticker: ^GSPC
      vix_threshold: 30.0
      horizon_days: 126
    key_fields:
      - n_episodes
      - event_mean
      - baseline_mean
      - diff_ci
    implemented: true

  - id: 32
    engine: dividend-vs-rf   # 已实现（2026-09-11）；复测：python tools/fengverify.py 32
    folder: 032-dividend-riskfree
    title: 股息率>无风险利率且可持续派息的公司长期跑赢不派息公司
    data_scope:
      markets: [US]
      category: stock
    test_spec:
      rf_ticker: ^TNX
      hold_days: 252
      first_year: 2012
      sustain_years: 3
    key_fields:
      - cohorts
      - mean_diff
      - diff_ci
    implemented: true

  - id: 12
    engine: vix-depth   # 已实现（2026-09-11）；复测：python tools/fengverify.py 12
    folder: 012-vix-higher-better
    title: VIX 越高恐慌期买入未来收益越强（>40 > >30 > >25）
    data_scope:
      markets: [US]
      category: index
    test_spec:
      vix_ticker: ^VIX
      index_ticker: ^GSPC
      horizon_days: 126
    key_fields:
      - buckets
      - hi_minus_lo
      - hi_minus_lo_ci
    implemented: true

```
