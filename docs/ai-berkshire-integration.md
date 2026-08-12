# AI Berkshire 知识库集成 — 映射与使用方法

> **源项目**：[xbtlin/ai-berkshire](https://github.com/xbtlin/ai-berkshire) | MIT License
> **同步基准**：commit `bf21649` (2026-07-23)
> **更新日期**：2026-07-23
>
> **AI 中立法则**：本文档描述的方法全部可在任何 AI 工具中执行——不依赖 Claude Code 特有功能。
> 纯 Markdown 指令在 `skills/`，Python 工具在 `tools/`，任何 AI 只需读文件或跑命令即可使用。

---

## 总览

ai-berkshire 提供 **19 个 AI 分析技能** + **7 个 Python 工具** + **150+ 份研究报告**，覆盖从快速排除到深度拆解的全流程价值投资研究。

```
                    ai-berkshire 能力全景
    ┌─────────────────────────────────────────────┐
    │  全市场筛选 → 个股分析 → 持仓纪律 → 报告输出  │
    │                                             │
    │  quality-screen    investment-research       │
    │  industry-funnel   investment-team    报告   │
    │  bottleneck-hunter financial-data            │
    │                     management-deep-dive     │
    │  买入前:            earnings-review/team     │
    │  investment-checklist  news-pulse            │
    │                      thesis-tracker/drift    │
    │                      deep-company-series     │
    │                      private-company-research│
    │                      dyp-ask                 │
    │                      portfolio-review        │
    │                      wechat-article          │
    └─────────────────────────────────────────────┘
```

以下映射说明每个 skill 在 FengInvest 框架中的位置和使用方式。

---

## 一、工具 (Tools) — 已导入 FengInvest/tools/

7 个零依赖 Python 工具已物理复制到本项目 `tools/`，源文件保留在 ai-berkshire 作为 canonical 版本。

| 工具 | 功能 | 用法示例 |
|:-----|:-----|:---------|
| `financial_rigor.py` | 市值验算/估值验算/三情景估值/本福特定律 | `python tools/financial_rigor.py verify-market-cap --price 510 --shares 9.11e9 --reported 4.65e12 --currency HKD` |
| `report_audit.py` | 报告数据抽检准出流程 | `python tools/report_audit.py extract --report <path>` → 检查 → `verdict` |
| `stock_screener.py` | 动量发现+价值验证双层筛选 | `python tools/stock_screener.py` (读取 data/watchlist.json 或内置默认) |
| `xueqiu_scraper.py` | 雪球用户时间线爬虫 | `python tools/xueqiu_scraper.py --user-id <id> --keywords "<词>" --output <path>` |
| `morningstar_fair_value.py` | 晨星公允价值 API 抓取 | `python tools/morningstar_fair_value.py` (依赖 curl) |
| `twstock_data.py` | 台股行情/估值/财务/月营收 | `python tools/twstock_data.py quote 2330` |
| `star_history_chart.py` | GitHub Star 历史 SVG 图 | `python tools/star_history_chart.py` (输出到 data/) |

**集成状态**：✅ 全部可用。`stock_screener.py` 依赖 `data/watchlist.json` 和 `data/fundamentals.json`（ai-berkshire 侧），首次运行自动从内置默认值创建。

---

## 二、技能 (Skills) — 方法映射

### 2.1 全市场筛选层（前置过滤器）

| Skill | 文件 | 说明 | FengInvest 位置 |
|:------|:-----|:------|:---------------|
| **quality-screen** | `ai-berkshire/skills/quality-screen.md` | 7 条硬指标快速排除非一流公司（ROE < 8%、FCF 为负、利息覆盖 < 2x、毛利率 < 15%、利润质量 < 0.7、净利率 < 5%、股本膨胀 > 20%） | `research/050-strategies/` — 新入口筛选层 |
| **industry-funnel** | `ai-berkshire/skills/industry-funnel.md` | 全市场→行业→3 家漏斗：搜索行业→10-20 家→quality-screen→护城河→管理层→深入 3 家 | `research/050-strategies/` — 与 quality-screen 配合 |

**AI 使用方式**：直接读 `.md` 文件，按指令执行。支持三种输入模式：个股、行业、市场/指数。

### 2.2 个股深度分析层（L2a 扩展）

| Skill | 文件 | 说明 | FengInvest 位置 |
|:------|:-----|:------|:---------------|
| **investment-team** | `~/.claude/skills/investment-team/SKILL.md`（ai-berkshire 提供，需本地安装） | 四大师并行 Agent 分析（段永平/巴菲特/芒格/李录） | ✅ 已集成至 L2a |
| **investment-research** | `ai-berkshire/skills/investment-research.md` | 四大师综合分析框架（非并行，适合单轮对话） | `research/040-people/` — 补充方法论 |
| **management-deep-dive** | `ai-berkshire/skills/management-deep-dive.md` | 管理层纵深研究：CEO 能力圈/诚信度/资本配置/历史决策 | 增强 L2a 李录视角 |
| **financial-data** | `ai-berkshire/skills/financial-data.md` | 财务数据多源交叉验证规范 | `docs/` — 数据质量参考 |
| **earnings-review** | `ai-berkshire/skills/earnings-review.md` | 财报精读方法论 | `research/070-reports/` |
| **earnings-team** | `ai-berkshire/skills/earnings-team.md` | 四大师并行财报解读+公众号发布 | `research/070-reports/` |

**AI 使用方式**：个股深度分析时，按需读取对应 `.md` 作为执行指令。

### 2.3 买入前检查（L3 碰撞补充）

| Skill | 文件 | 说明 | FengInvest 位置 |
|:------|:-----|:------|:---------------|
| **investment-checklist** | `ai-berkshire/skills/investment-checklist.md` | 巴菲特买入前 10 项 Checklist：护城河/ROE/安全边际/管理层/估值/催化剂等 | 增强 L3 碰撞规则 |
| **private-company-research** | `ai-berkshire/skills/private-company-research.md` | 未上市公司研究框架（1071 行，最详细） | `research/070-reports/` |

### 2.4 持仓监控与纪律（P 层补充）

| Skill | 文件 | 说明 | FengInvest 位置 |
|:------|:-----|:------|:---------------|
| **news-pulse** | `ai-berkshire/skills/news-pulse.md` | 股价异动快速归因：4 并行 Agent 侦察事件/政策/对手/情绪 | 增强 `fengwatch.py` → 持仓监控 |
| **thesis-tracker** | `ai-berkshire/skills/thesis-tracker.md` | 买入后纪律追踪：论文条件跟踪/催化剂/退出信号 | `research/090-portfolio-management/` |
| **thesis-drift** | `ai-berkshire/skills/thesis-drift.md` | 论文漂移检测——识别早期卖出信号 | `research/090-portfolio-management/` |
| **portfolio-review** | `ai-berkshire/skills/portfolio-review.md` | 组合回顾分析框架 | `research/090-portfolio-management/` |

### 2.5 宏观与行业研究（M 层补充）

| Skill | 文件 | 说明 | FengInvest 位置 |
|:------|:-----|:------|:---------------|
| **bottleneck-hunter** | `ai-berkshire/skills/bottleneck-hunter.md` | 全球产业链瓶颈扫描（地缘/供需/技术/气候） | `research/010-macro/` |

### 2.6 深度研究与内容输出

| Skill | 文件 | 说明 | FengInvest 位置 |
|:------|:-----|:------|:---------------|
| **deep-company-series** | `ai-berkshire/skills/deep-company-series.md` | 8 篇长文深度拆解：适应公司复杂度，篇内结构模板 | `research/070-reports/` |
| **dyp-ask** | `ai-berkshire/skills/dyp-ask.md` | 段永平式思考问答框架 | `research/070-reports/` |
| **income-investment** | `ai-berkshire/skills/income-investment.md` | 收息投资分析法（高股息/REITs/优先股） | `research/050-strategies/` |
| **wechat-article** | `ai-berkshire/skills/wechat-article.md` | 公众号文章排版与发布 | 内容产出工具 |

---

## 三、研究报告 — 导入指南

ai-berkshire 有 150+ 研究报告目录（`reports/`），按以下规则选择性导入：

| 报告类型 | 目标位置 | 导入规则 |
|:---------|:---------|:---------|
| 个股深度研究（腾讯/阿里/茅台/美团等） | `research/060-companies/<TICKER>-<中文名>/` | 如 FengInvest 已有该标的的 7 层分析，合并；否则新建目录 |
| 行业全景扫描（AI 产业/大模型六强等） | `research/070-reports/` | 直接导入，按主题命名 |
| 方法论研究（DCF/凯利公式等） | `research/070-reports/` | 导入并更新 REFERENCE-TREE.md |
| 筛选清单（召回池/破净股等） | `research/050-strategies/` | 按策略类型归类 |
| 组合/实盘记录 | 暂不导入 | FengInvest 有独立的 holdings/ 系统 |
| 公众号文章 | 暂不导入 | 内容产出，非分析参考 |

---

## 四、同步策略

保持与 upstream 一致的机制：

```bash
# 手动同步（需要时运行；AI_BERKSHIRE 环境变量可指定源项目路径）
git -C <AI_BERKSHIRE路径> pull --ff-only origin main

# 检查更新
python tools/sync-ai-berkshire.py check

# 同步工具（增量复制新版本）
python tools/sync-ai-berkshire.py update
```

详见 `tools/sync-ai-berkshire.py`（Phase 4）。

---

## 五、许可证与来源

- ai-berkshire：MIT License，© 2026 xbtlin
- 已导入工具在文件头标注 Source + Commit Hash
- 方法映射仅做路径引用，不复制 skill 内容
- 研究报告选择性导入，保留原格式和来源
