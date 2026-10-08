---
name: fengscreen
description: "[FengInvest] 去劣筛选 — 7 条硬指标排除非一流公司 + 3 条豁免规则，宁可漏网不可误杀。买入前用 fenginvest 深度分析，本 skill 用于候选池体检/行业扫描。"
when_to_use: "选股/去劣。当用户要求筛选股票池、行业扫描、市场扫描、检查某只公司是否够格进入深度分析时使用。触发词：筛选、去劣、质量筛查、quality-screen、股票池、行业漏斗、哪些公司值得研究"
allowed-tools:
  - Agent
  - Bash
  - Read
  - Skill
  - Write
triggers:
  - fengscreen
  - 筛选
  - 去劣
  - 质量筛查
  - 股票池
---
# FengInvest — 去劣筛选（quality-screen）

> 哲学：**宁可漏网，不可误杀**——不错杀任何一流好公司，但能排除确定的非一流公司。
> "通过筛选 ≠ 确定好"，去劣只是第一步，通过者才进入 `/fenginvest` 深度分析。
> 机制移植自 ai-berkshire quality-screen（上游开源框架，7 硬指标 + 3 豁免）。

## 变量约定

- `<TICKER>` → 标的代码；`ROOT` → `cd "$(git rev-parse --show-toplevel)"`

## 1. 输入模式

| 模式 | 用法 | 扫描范围 |
|:-----|:-----|:---------|
| 个股 | `/fengscreen <TICKER>` | 单只体检 |
| 行业 | `/fengscreen 行业:半导体` | 自动扩展到 15-30 家，并行逐家取数 |
| 市场 | `/fengscreen 市场:港股` | 市场范围扫描 |
| 主题 | `/fengscreen 主题:AI算力` | 主题成分扫描 |

## 2. 数据获取（全部工具取数，禁止心算）

```bash
python tools/fengdata.py <TICKER> --years 20    # 价格/财务
python tools/fengfundamentals.py <TICKER>       # 财务指标（ROE/FCF/毛利率/净利率/OCF）
python tools/financial_rigor.py cross-validate ...   # 关键数字多源交叉
```

10 年 ROE / 5 年 FCF / 利息覆盖 / 毛利率 / OCF-NI / 净利率 / 股本变化 需要多年财务序列。

## 3. 七条硬指标（任一命中 = 排除 ❌）

| # | 指标 | 排除阈值 | 含义 |
|:-:|:-----|:---------|:-----|
| 1 | 10 年平均 ROE | < 8% | 资本效率不足 |
| 2 | 5 年累计自由现金流 | 为负 | 没赚到真金白银 |
| 3 | 利息覆盖倍数 | < 2x | 偿债不安全 |
| 4 | 长期毛利率 | < 15% | 无定价权 |
| 5 | 经营现金流/净利润 5 年均值 | < 0.7 | 利润质量差 |
| 6 | 长期净利率 | < 5% | 抗风险能力弱 |
| 7 | 5 年总股本膨胀 | > 20%（非并购） | 股东被稀释 |

## 4. 三条豁免规则（指标命中但豁免 → ⚠️ 继续考察）

| 豁免 | 适用场景 | 条件 | 典型 |
|:-----|:---------|:-----|:-----|
| A | 战略投入期 | 上市<10年 + 毛利率>30% + 近2年OCF为正 | 美团 |
| B | 主动低利润率 | 毛利率>30% + 净利率回升 | 亚马逊 |
| C | 高周转薄利 | ROE>20% + OCF/NI>1.0 + 会员/平台模式 | Costco |

豁免必须逐条记录理由，不得默认豁免。

## 5. 输出

汇总表：每家公司 ✅ 通过 / ❌ 排除（命中哪条指标）/ ⚠️ 豁免（豁免类型+理由）+ 通过率统计 + 质量分层。

```bash
# 输出到研究目录（可追溯）
research/060-companies/<TICKER>-<中文名>/<YYYY-MM-DD>/00-quality-screen.md   # 个股
# 行业/市场模式 → research/050-strategies/<日期>-<主题>-screen.md
```

## 6. 通过者去向

- ✅ 通过 → `/fenginvest <TICKER>` 七层深度分析
- ❌ 排除 → 记录排除理由（供未来复查），不再浪费时间
- ⚠️ 豁免 → 标注豁免类型，进入分析时在 L2a 重点验证豁免假设

## 完成后

向用户汇报：扫描范围、通过/排除/豁免清单、通过率、被排除公司的命中指标（留痕）。

开源登记：提到开源项目即登记 data/config/opensource_list.json（提到=入表）。
