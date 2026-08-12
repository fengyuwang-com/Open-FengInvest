# L2b — 量化因子（权重中高）

## 职责

计算标的相对于同业的因子z-score。纯计算，不调LLM。

量化做相对排名，不做绝对价值判断。定性轨的结论不能因为量化反对就被推翻。

## 工具

```bash
# 自动识别同业组
python tools/fengquant.py <TICKER>

# 手动指定同业
python tools/fengquant.py <TICKER> --peers PEER1 PEER2
```

## 2个灯（固定）

| 灯 | 🟢 | 🟡 | 🔴 |
|:--|:--|:--|:--|
| 因子一致 | 全部方向一致 | 有分歧 | 严重分歧 |
| 关键警告 | 无异常 | 轻微异常 | z>2.5或z<-2.5 |

## 因子（6个）

价值(PE)、价值(FwdPE)、质量(ROE)、利润率、收入增长、杠杆(D/E)
动量(6m)单独计算（非横截面）

z-score → continuity-corrected (rank-0.5)/n → norm.ppf

## 输出

写入 `research/060-companies/<TICKER>-<中文名>/<YYYY-MM-DD>/04-quantitative.json`（060-companies 为本地 gitignored 目录）
