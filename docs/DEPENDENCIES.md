# FengInvest — 外部依赖清单

本清单跟踪所有 FengInvest 知识库中引用的外部项目及其许可证。

> **原则：** 所有外部内容均经过改编、结构化后融入 FengInvest 框架，非直接复制。各项目的原始许可证在其对应文件中有注明。

## 大师人物知识库

| 来源 | 贡献 | 许可证 | 集成位置 |
|------|------|--------|---------|
| **Finance_Toolkit**（本地私有项目） | 14 位大师的 12 段式结构化蒸馏 | MIT | `research/040-people/named/`（14 个文件） |
| **master30**（[hgsz2003/master30](https://github.com/hgsz2003/master30)） | 27 位大师的角色化思维框架（Cursor Skill 格式） | MIT | `research/040-people/named/`（27 个独立文件） |
| **ai-berkshire**（[xbtlin/ai-berkshire](https://github.com/xbtlin/ai-berkshire)） | 李录/四大师定性分析框架，被 `investment-team` skill 调用 | MIT | `research/040-people/named/li-lu.md` + 投研模板引用 |
| **Klarman 公开演讲/书籍**（第三方 James Clear 摘要） | 安全边际投资体系、清算价值框架、催化剂分析 | 公开资料（非本人授权） | `research/040-people/named/klarman.md` |
| **李录公开演讲/访谈**（新浪财经等第三方来源） | 长期主义投资体系、能力圈、15 年时间维度 | 公开资料（非本人授权） | `research/040-people/named/li-lu.md` |

## 投资策略知识库

| 来源 | 贡献 | 许可证 | 集成位置 |
|------|------|--------|---------|
| **Finance_Toolkit**（本地私有项目） | 10 种投资流派的策略描述 | MIT | `research/050-strategies/`（10 个文件） |

## 市场与宏观参考

| 来源 | 贡献 | 许可证 | 集成位置 |
|------|------|--------|---------|
| **tradermonty/claude-trading-skills**（[GitHub](https://github.com/tradermonty/claude-trading-skills)） | 市场体制检测方法论、广度分析框架、板块轮动参考 | MIT | `research/020-market/` + `research/010-macro/` |
| **weijie-chen/Notes_For_Macroeconomic_Analyst**（[GitHub](https://github.com/weijie-chen/Notes_For_Macroeconomic_Analyst)） | 宏观经济指标分析笔记（Jupyter）—— 补充参考 | MIT | `research/010-macro/` |

## 资产类别参考

| 来源 | 贡献 | 许可证 | 集成位置 |
|------|------|--------|---------|
| **sun-btc/biga**（[GitHub](https://github.com/sun-btc/biga)） | 周期股/商品/价值/成长/高股息分析框架 | MIT | `research/030-asset-classes/` + `research/050-strategies/` |

## 搜索工具

| 工具 | 用途 | 来源 |
|------|------|------|
| **opencli** | AI 各层执行时的联网搜索/读网页（opencli-browser / opencli-usage skill 驱动） | 本地工具 |
| **open-webSearch** | 备选搜索引擎（Exa/DDG/Baidu/Sogou） | 本地工具（MCP 服务器） |
| **Agent Reach** | 社交平台（小红书/Reddit/B站/Twitter）数据收集 | 本地工具 |

## 数据工具链

| 工具 | 用途 | 来源 |
|------|------|------|
| **apsw** | SQLite session 扩展绑定：changeset 增量捕获 + invert 回滚；统一入口 `tools/fengdb.py`（safe_batch 自动产变更集 + undo/snapshot/status，临时副本回滚演练 PASS；规范见 [DATA-MANAGEMENT.md](DATA-MANAGEMENT.md)） | PyPI 清华镜像（内置 SQLite 公有领域内核） |
| **fuyao API**（同花顺） | A股财报增量源（34 原始科目 → 24 映射字段入 cn_financials；X-api-key 鉴权，key 存仓库外 credentials.env）；全市场 5,828 只回填已完成（tools/fengfuyao.py） | 商业服务（现用免费额度） |
| **a-stock-data**（[simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data)） | A股按需取数后端：12 端点整合为 `tools/fengastock.py`（实时估值/估值史/上市退市日/申万行业变迁/复权因子/社融 PMI/龙虎榜/涨停池/解禁/两融/资金流），SKILL 存档 `research/070-reports/vendor/` | Apache-2.0 |
| **baostock** | A股日线 / PE·PB 估值历史源（单 socket 无锁，必须串行使用） | 开源（PyPI） |
| **FinMind** | 台湾日线数据源（TW 市场补数路径） | 开源（PyPI） |
| **BaiduPCS-Go** | 百度网盘 CLI：changeset 增量上传/回滚取回（方案调整为本地双备份 + 定时复制至网盘同步目录，见 [todo.md](todo.md) K 条） | 开源（接入中） |
| **CSMAR** | A股全历史财务冷数据（含退市股，35 年三表+衍生因子） | 本地私有数据 |
