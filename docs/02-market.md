# M层 — 市场数据（权重最低）

## 职责

M层不决策。提供信息供其他层参考，不推翻核心判断。

## 4个灯（固定）

| 灯 | 🟢 | 🟡 | 🔴 |
|:--|:--|:--|:--|
| 宏观周期 | 扩张/复苏 | 减速 | 衰退/危机 |
| 市场估值 | PE<历史30%分位 | 30-80% | >80% |
| 市场趋势 | 上升(MA50>MA200) | 震荡 | 下降(MA50<MA200) |
| 市场情绪 | 极恐/偏恐(FG<30) | 中性(30-70) | 极贪(>70) |

## 数据源

```bash
# 机器层
python tools/fengdata.py <TICKER> --years 20  → 价格 + MA + 财务数据

# AI层 — 搜索交叉验证（必须不少于2个独立来源）
python <搜索工具>/scraper.py --search "<标的> 行业 2026 宏观"
python <搜索工具>/scraper.py --search "<标的> PE 估值 历史分位"
python <搜索工具>/scraper.py --search "<标的> 2026 新闻 财报"
```

## DK 扩展维度

在 4 灯之外，追加以下 DK 维度：

| 维度 | 检查内容 | 数据来源 |
|:-----|:---------|:---------|
| **家国方向** | 行业是国家鼓励/限制/中性？ | 搜索政策文件 |
| **货币周期** | 宽松/紧缩/中性？ | 搜索央行信号 |
| **工业利润周期** | 工业利润增速方向 | 统计局/搜索 |
| **用电量差** | 用电量增速 vs GDP 增速 | 能源局/搜索 |

## 输出

写入 `research/060-companies/<TICKER>-<中文名>/<YYYY-MM-DD>/02-market.json`（060-companies 为本地 gitignored 目录），包含：
- `price_data`: price, MA50/120/200, returns
- `financials`: PE, PB, ROE, FCF, revenue
- `m_layer`: macro/valuation/trend/sentiment 四个灯 + 说明
- `sources`: 所有数据来源 URL + 获取时间

---

## Web 市场数据门户

路径：`/market` — FengInvest Web UI 的市场数据页面。

### 使用方式

1. **默认展示** 53 个精选外部数据源链接，分 11 个类别，页面秒开无加载
2. **浏览数据源** — 点击任一卡片直达对应网站（`target="_blank"`），无需登录
3. **加载本地缓存** — 点击底部按钮加载 `research/020-market/latest.json` 中的系统缓存数据（SPY/恒生/沪深300行情 + 美港中市场温度）
4. **缓存数据自动加载** — 页面打开时自动请求缓存，有数据即在顶部展示行情卡片和温度仪表盘

### 11 个分类速览

| 分类 | 个数 | 用途 |
|:----|:----|:-----|
| 📈 宏观 & 市场温度 | 6 | CFGI 恐贪、Buffett 指标、Multpl CAPE、国债收益率 |
| 🌍 全球估值对比 | 4 | World PE Ratio 地图、MSCI 60+国 P/E 排名、Siblis CAPE/P/E 各国对比 |
| 🏢 公司基本面 & 财报 | 8 | MacroTrends、GuruFocus、Tikr、SimplyWallSt、SEC EDGAR |
| 💰 估值 & 大师持仓 | 6 | Dataroma、WhaleWisdom、OpenInsider、Morningstar |
| 💵 分红 & 回购 | 3 | Dividend.com、Dividend History、Nasdaq 分红 |
| 🔬 另类指标 & 开源工具 | 5 | Acumen 宏观仪表盘（GitHub Pages）、GDELT 全球新闻 |
| 🏛️ 美联储 & 宏观经济 | 6 | FRED、World Bank、IMF、ECB、EIA |
| 📊 量化数据 & API | 4 | Polygon.io、Tiingo、Alpha Vantage、Databento |
| 📉 投资组合 & 回测 | 3 | Portfolio Visualizer、TradingView、Koyfin |
| 🏛️ 国会 & 监管数据 | 4 | QuiverQuant 国会交易追踪、USPTO 专利、USAspending |
| 🌏 港股/A股 | 4 | AASTOCKS、东方财富、雪球、港交所披露易 |

### 数据来源原则

- **不自动爬取** — 所有数据需用户主动点击获取
- **外部链接直连** — 点击即跳到数据源网站，不经过中间层
- **缓存配合** — 本地已有 `latest.json` 则在顶部展示摘要，如需最新数据请点击外部链接直达
- **GitHub Pages 开源工具** — Acumen 宏观仪表盘、ARTHA Dashboard、Value Stock Screener 均为免费开源方案
