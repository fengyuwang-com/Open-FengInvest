# finvizfinance Evaluation

> Repo: https://github.com/lit26/finvizfinance · PyPI `finvizfinance` 1.5.0
> 调研日期: 2026-09-11（网络调研，未 clone）
> 判定: **可借鉴（倾向"有限可集成"）——美股侧旁路数据源，不进核心链路**

## 基本面（已验证）

- 1,636 stars / 269 forks / 仅 2 open issues；65 个 release，最新 1.5.0（2026-08-29 发布，两周前），维护活跃
- MIT；依赖 requests + beautifulsoup4 + lxml + pandas + xlsxwriter（纯爬虫栈，轻）
- 原理：requests + bs4 直接解析 **finviz.com 网页 HTML**，无官方 API——finviz 改版即坏，65 个 release 的主要工作就是跟随修复。免费版有页面限速（具体阈值未验证），低频单线程没问题
- **只覆盖美股**（finviz.com 本身仅美股 + 外汇/加密）

## 能取什么

- **Quote 个股**：fundament 全景（P/E、EPS、Insider Own、市值、各周期涨幅…）、公司描述、peer 同业、ETF 持有人、**分析师评级汇总（outer ratings）**、**个股新闻 df**、**内部人交易 df**、K线图（图片）
- **全站 News/Blogs**；**Insider** 全市场（latest / top week / top owner trade）
- **Screener**：六视图（Overview/Valuation/Financial/Ownership/Performance/Technical）+ filters_dict 条件筛选（等价 finviz 网页几十个条件）
- **Group**（行业/板块/国家聚合）、**Calendar**（经济日历）、**Earnings**（财报日期分桶）、Forex/Crypto
- **没有 13F 明细**（只有 Ownership 视图比例字段和 ETF holders）

## 与现有工具重叠矩阵

| 维度 | finvizfinance | 现有工具 | 判断 |
|---|---|---|---|
| 行情/K线 | 图片级 + Performance 字段 | fengstockintl（yfinance 四源日线） | 重叠且更差，不用 |
| 估值/基本面 | 快照级 fundament | fengdata/fengvaluation/fengsec XBRL（PIT 双轴） | 重叠且无 PIT，不用 |
| 分析师评级 | ✅ outer ratings 汇总 | 无 | **补缺** |
| 内部人交易 | ✅ 现成整理视图 | fengsec Form 3/4/5（EDGAR 一手 PIT） | 半重叠：缺的是"易读汇总"不是数据 |
| 新闻情绪 | ✅ ticker_news / News | 无系统化新闻源 | **补缺** |
| 机构持仓 | 仅比例字段 | fengsec 13f 全量 | 重叠，不用 |
| Screener | 现成条件库 | fengscreen（质量哲学）+ fengbatch | 可作美股候选池快速粗筛补充 |

## 落地建议

做成 `tools/fengfinviz.py` 旁路薄封装（仿 fengastock.py / fengfuyao.py 模式），给 L2a 定性层供三张参考表：**评级分布 + 近期新闻标题 + insider 动向**。低频（日线级）调用 + fengthrottle 限流，失败可降级不阻塞；绝不让 fenginvest 七层依赖它（网页爬虫无 API 承诺，一次 finviz 改版就断）。集成成本约半天。

## 来源

- github.com/lit26/finvizfinance（README 全文经 Search King 抓取）
- pypi.org/pypi/finvizfinance/json（版本/许可证/依赖）
- api.github.com/repos/lit26/finvizfinance（stars/pushed_at）
