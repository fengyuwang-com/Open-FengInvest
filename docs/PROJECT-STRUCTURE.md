# FengInvest 项目结构地图（唯一基准）

> **本文是目录结构的唯一事实源**：CLAUDE.md / README.md / AGENTS.md / docs/00-workflow.md 的结构节只放指针和精简摘要，不再各自维护完整树——改结构先改这里。
> 分级基准 = `.gitignore`（什么不传）+ `git ls-files`（什么实际在库里）。
> 图例：🟢 **入库**（随 git 推 GitHub+Gitee，公开可见）｜🔴 **本地**（gitignored，永不上传）。

## 一、全目录树（含分级）

```
FengInvest/
├── CLAUDE.md / README.md / AGENTS.md     🟢 项目入口与协作指令
├── FENGMEM.md / todo.md                  🔴 会话记忆 / 任务账本（本地）
├── docs/                                 🟢 框架文档
│   ├── 00-workflow.md … 09-portfolio.md     七层流程与定义
│   ├── PROJECT-STRUCTURE.md                 本文件（结构唯一基准）
│   ├── DATA-MANAGEMENT.md                   写库铁律（safe_batch）
│   └── standards.md                         结构根本标准
├── tools/                                🟢 63 个 Python 工具（唯一程序层）
├── rules/                                🟢 纪律规则源文件
├── knowledge/                            🟢 DK 知识库（principles/discipline/methodology/market_view）
│   └── personal/                         🔴 个人知识（本地）
├── design/                               🟢 设计决策：CONSTITUTION / DESIGN / FOUNDER-VOICES（创始人原话逐字存档）/ SESSION-INDEX / PROMPT-PLAN
├── Discussion/                           🟢 讨论档案（日期-主题.md + discuss-config.json；已入库公开）
├── research/                             🟢 研究参考与产出（除以下 🔴 外全部入库）
│   ├── 010-macro ~ 050-strategies/          宏观/市场/资产/大师/策略参考
│   ├── 060-companies/                    🔴 个股七层分析（<TICKER>-<中文名>/<日期>/，含个人研究）
│   ├── 070-reports/ 090-/ 100-/ 110-/       行业/组合/学习/论断验证
│   ├── speculative/                      🔴 投机研究（本地）
│   ├── state/                            🔴 状态机文件 temp_state_<TICKER>.json（fengstate.py 专用）
│   ├── fx/                               🟢 汇率研究（2026-09 新增）
│   └── opensource-eval/<克隆仓库>/        🔴 评估用第三方源码克隆
├── data/                                 混合分级（见下）
│   ├── market_data.db                    🔴 金融数据库本体 2.7GB（21 市场 1,305 万行日线 + 财报 38 万行）——太大不入 git
│   ├── market_data.db.snap_* / snapshots/ 🔴 整库快照（VACUUM INTO 导出）
│   ├── changesets/                       🔴 可回滚变更集 cs_*.bin + index.jsonl（对外同步只传这个的增量）
│   ├── cache/ sec/ pit/ reports/ watchlist.json 🔴 抓取缓存 / SEC 原始件 / PIT / 回测产物 / 自选（本地）
│   └── config/                           🟢 清单类入库：research_list / opensource_list / company_names / attention-domains / batch_lists / sector_universe
│       └── llm_config.json               🔴 BYOK 的 LLM key（gitignored，key 永不出本机）
├── holdings/                             🔴 持仓 hold_<TICKER>.json（SCHEMA.md 同目录）
├── portfolio/                            🔴 组合当前盘面 current.md
├── alerts/                               🔴 触发引擎输出 today.json
├── logs/                                 🔴 决策日志 journal.jsonl + 运行日志
├── reviews/                              🔴 复盘 review_*.md
├── fengweb/                              🟢 Web UI（TS+Express+EJS，:23456）
│   ├── views/                               EJS 模板（workspace.ejs=决策台）
│   ├── src/                                 服务端（server.ts / routes/api.ts / services/）
│   │   ├── index.ts                         入口（监听 :23456 启动）
│   │   ├── services/                        三件：python-runner / file-store / job-queue
│   │   └── prompt-templates/                Prompt 模板（<layer>.md，服务端单文件集中）
│   ├── locales/                             中英词条（zh-CN.json / en.json）
│   ├── public/                              css/js 静态资源
│   └── dist/ node_modules/               🔴 构建产物与依赖
├── Temp/                                 🔴 临时文件
├── sys_tmp.html                          🔴 临时草稿
├── start-web.bat/sh                      🟢 Web 启动脚本
└── .env *.key credentials*               🔴 凭据（通配 ignore）
```

## 二、🔴 不上传的是什么、为什么

| 类别 | 路径 | 原因 | 替代同步方式 |
|:-----|:-----|:-----|:-------------|
| **金融数据库** | data/market_data.db（2.7GB）+ 快照 | 体积超 git 承受，且含全部行情缓存 | 对外只传 `data/changesets/` 增量变更集，对端 fengdb invert 回放 |
| **个人持仓与决策** | holdings/ portfolio/ logs/ reviews/ alerts/ | 交易隐私 | 永不同步 |
| **个股研究** | research/060-companies/ research/speculative/ research/state/ | 个人研究过程 + 状态机运行态 | 永不同步 |
| **个人知识/记忆** | knowledge/personal/ FENGMEM.md todo.md Temp/ | 个人认知与工作账本 | 永不同步 |
| **凭据** | data/config/llm_config.json .env *.key … | key/密钥 | 永不同步 |
| **缓存/构建** | data/cache data/sec data/pit data/reports fengweb/dist node_modules | 可再生产物 | 不需要 |

**结论：公开仓库 = 完整的"系统"（工具+框架+文档+Web），零个人数据；"系统的产出"（库、持仓、研究）全部留在本机。**

## 三、"什么文件写到哪里"速查（AI 写文件前先查这张表）

| 要写什么 | 写到哪 | 经谁写 |
|:---------|:-------|:-------|
| 行情/财报/汇率入库 | data/market_data.db | **必经 tools/fengdb.py safe_batch**（可回滚） |
| 七层状态推进 | research/state/temp_state_<TICKER>.json | **只经 tools/fengstate.py**（hook 拦截手改） |
| 个股七层分析产出 | research/060-companies/<TICKER>-<中文名>/<YYYY-MM-DD>/ | 各层工具 + AI |
| 持仓登记/检查 | holdings/hold_<TICKER>.json | tools/fengholding.py |
| 决策日志 | logs/journal.jsonl | fengwatch/fengholding 追加 |
| 复盘 | reviews/review_<TICKER>_<日期>.md | /fengreview |
| 当日提醒 | alerts/today.json | tools/fengwatch.py daily |
| 研究/候选/观察清单 | data/config/research_list.json | 直接编辑（入库） |
| 开源项目登记 | data/config/opensource_list.json | 提到即登记（入库） |
| 公司中英文名 | data/config/company_names.json | tools/fengnames.py 生成 |
| LLM key（BYOK） | data/config/llm_config.json | fengweb 设置弹窗（本机） |
| 讨论档案 | Discussion/<日期>-<主题>.md | /fengdiscusslog（入库） |
| 创始人原话 | design/FOUNDER-VOICES.md | 每轮轮末逐字追加（入库） |
| 决策台 Prompt 模板 | fengweb/src/prompt-templates/<layer>.md | 服务端集中，GUI 只取不改 |
| 回测/报告产物 | data/reports/ | 工具自动（本地） |
| 汇率研究 | research/fx/<日期>/ | 研究产出（入库） |
| 任务账本 / 会话记忆 | todo.md / FENGMEM.md | 每轮入账（本地） |

## 四、维护规则

1. **新增任何目录/文件类**：先按 `.gitignore` 定分级 → 再更新本文件树 → 完事。三处指针文档（CLAUDE/README/AGENTS/workflow）不用动。
2. 本文件与任何其他文档的结构描述冲突时，**以本文件 + git 实际状态为准**，并回头修那份错的。
3. 想把某个 🟢 转 🔴：`.gitignore` 加行 + `git rm --cached` + 更新本文件，并向创始人确认（已推送的历史在远端仍有痕迹）。
