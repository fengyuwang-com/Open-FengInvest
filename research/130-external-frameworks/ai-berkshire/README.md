# ai-berkshire — 外部框架并入台账（本仓自持）

> 上游：[xbtlin/ai-berkshire](https://github.com/xbtlin/ai-berkshire) | commit `6354c68`（2026-08-20）| MIT (c) 2026 xbtlin
> 台账：`UPSTREAM.json`（上游指纹）/ `ADOPTION.json`（逐文件归属）
> 对账器：`python tools/fengadopt.py verify`

---

## 一、为什么并入

此前 ai-berkshire 的 skill 正文只存在于**本机另一个目录**（同级 sibling 克隆）。后果有三条：

1. **脖子上拴在别人家**：`.agents/skills/investment-team/SKILL.md` 曾把 canonical 指向本机用户全局目录，项目外的一次改动能让本仓 L2a 静默失效。
2. **残缺而不自知**：装到 `.agents/skills/` 的那份是**派生残本**（184 行），比上游真身（229 行）少 45 行——丢掉的恰好是防失败的部分（WebSearch 权限预检、AI 研究偏见评估表、金融严谨性验证、两源交叉信源规范、巴菲特买入前 Checklist、报告数据抽检准出、团队清理）。没有任何机制会发现这件事。
3. **对账无锚**：说"已吸收"时，无法回答"吸收的是哪一版、哪几个文件、正文在哪"。

并入解决的是这三件事：**正文进本仓 + 上游版本指纹进台账 + 漂移有人管（fengadopt.py）**。

## 二、目录结构

```
research/130-external-frameworks/ai-berkshire/
├── README.md          # 本文（说人话：口径、对照表、更新办法）
├── UPSTREAM.json      # repo / commit / license / synced_at / file_count / files{上游相对路径: sha256}
├── ADOPTION.json      # 逐文件归属：upstream_file / status / owner / landing / note
├── import_skills.py   # 重导脚本（上游 pull 后重跑，幂等；见 §五）
└── skills/            # 全部 21 个 skill 正文（逐字原文 + 2 行来源标注头）
    ├── …20 个取自上游 skills/*.md
    └── investment-memo-craft.md   ← 取自上游 codex-skills/investment-memo-craft/SKILL.md
```

- **正文逐字照搬**：每个文件头部只有 2 行 `<!-- ... -->` 来源标注 + 1 个空行，其后是上游原文的**逐字节副本**。
- **sha256 只对上游原文计算**（不含标注头）。`UPSTREAM.json` 记录上游原文哈希；`fengadopt.py verify` 会剥掉标注头、重算本仓副本正文的哈希与之对拍——**本地被偷改会当场报错**。
- **本目录是纯参考物**：21 个 skill 中只有 `investment-team` 另有发现路径入口（`.agents/skills/investment-team/SKILL.md`）。其余 20 个**故意不放进 `.agents/skills/`**——那会造出能绕过七层状态机的平行入口，是本项目的红线。

## 三、四档口径（与 `AGENTS.md`「外部框架并入铁律」同源）

> 命名注记：本档名 2026-09-17 改过——旧名 `archived`，而本仓该词另指"已清仓持仓 / 旧状态归档"（见 `tools/fengwatch.py`、`tools/fengstate.py renew`），与本档"逐字原文、永久有效、只是没有承接者"**意思相反**；同名会误导后人把留档正文当过期资料清掉，故改用 `kept`（留档）。旧文档或旧会话里见到 `archived`，指的就是本档。

| status | 定义 | 本台账判别 |
|:---|:---|:---|
| **absorbed**（并入） | 正文物理在本仓 + 落在本仓可读路径 + 有明确的**自有承接者**（`owner` 必须指向本仓真实存在的 skill/tool）；三条全中才算 | 正文在 `skills/` + `owner` 能在 `.agents/skills/` 或 `tools/` 解析到 |
| **kept**（留档） | 正文物理在本仓、供人与 Agent 查阅，但本系统**没有**自有承接者、也不注册任何入口；`owner` 必须为空 | 正文在 `skills/` + `owner: null`（本系统不消费它） |
| **referenced**（引用） | 本仓**无**正文副本，仅文档写明上游仓库 + 上游文件路径 | 本台账 0 条（21 个正文全在本仓） |
| **superseded**（自有承接） | 上游有该能力，但本系统已用自有 skill/工具承接，不再引用上游；必须写 `owner` | 有明确自有承接者，`owner` 必填 |

**四档判据一把尺子**：正文是否在本仓（`absorbed` / `kept` 都要求在本仓；`referenced` 要求不在；`superseded` 看承接关系），以及**有没有人用它**——`absorbed`（有承接者、被调用）与 `kept`（无承接者、纯留档）的唯一区别就在 `owner` 有无（`tools/fengadopt.py` 据此硬校验：`absorbed` / `superseded` 的 `owner` 必须非空且逐个可解析，`kept` 的 `owner` 必须为空，任一不符即 exit 1）。

### superseded 的含义（别读歪）

`superseded` 不等于"这份原文没用"：上游正文仍全量留在 `skills/`。它表达的是**引流去向**——用户要找这个能力时应该去自有承接者，不要再走上游 skill。参考价值与引流关系是两件事。

## 四、上游 skill ↔ 自有承接者对照表（21 条全量）

> 下表「本仓正文」列省略前缀 `research/130-external-frameworks/ai-berkshire/`；「上游文件」列是上游仓库内的相对路径。canonical 机器可读版 = `ADOPTION.json`，本表是人读版。

| # | 上游文件 | status | 自有承接者（owner） | 本仓正文 |
|:--|:---|:---|:---|:---|
| 1 | `skills/bottleneck-hunter.md` | superseded | `fengsource`（发现路径 2 产业链瓶颈） | `skills/bottleneck-hunter.md` |
| 2 | `skills/deep-company-series.md` | kept | —（无承接者，纯留档） | `skills/deep-company-series.md` |
| 3 | `skills/dyp-ask.md` | superseded | `fengdiscuss` | `skills/dyp-ask.md` |
| 4 | `skills/earnings-review.md` | superseded | `fenginvest`（L2a/L4） | `skills/earnings-review.md` |
| 5 | `skills/earnings-team.md` | superseded | `fenginvest`（L2a/L4） | `skills/earnings-team.md` |
| 6 | `skills/financial-data.md` | superseded | `fengquality` + `fengdata.py` | `skills/financial-data.md` |
| 7 | `skills/income-investment.md` | kept | —（无承接者，纯留档） | `skills/income-investment.md` |
| 8 | `skills/industry-funnel.md` | superseded | `fengsource` + `fengbatch` | `skills/industry-funnel.md` |
| 9 | `skills/industry-research.md` | kept | —（无承接者，纯留档） | `skills/industry-research.md` |
| 10 | `skills/investment-checklist.md` | superseded | `fengscreen` + `fengrule.py`（L1） | `skills/investment-checklist.md` |
| 11 | `skills/investment-memo-craft.md` ※ | kept | —（无承接者，纯留档） | `skills/investment-memo-craft.md` |
| 12 | `skills/investment-research.md` | superseded | `investment-team` | `skills/investment-research.md` |
| 13 | `skills/investment-team.md` | **absorbed** | **`investment-team`（本台账唯一 absorbed：唯一进发现路径者）** | `skills/investment-team.md` |
| 14 | `skills/management-deep-dive.md` | superseded | `investment-team`（risk-assessor 管理层） | `skills/management-deep-dive.md` |
| 15 | `skills/news-pulse.md` | superseded | `fengwatch` | `skills/news-pulse.md` |
| 16 | `skills/portfolio-review.md` | superseded | `fengportfolio` | `skills/portfolio-review.md` |
| 17 | `skills/private-company-research.md` | kept | —（无承接者，纯留档） | `skills/private-company-research.md` |
| 18 | `skills/quality-screen.md` | superseded | `fengscreen` | `skills/quality-screen.md` |
| 19 | `skills/thesis-drift.md` | superseded | `fengreview` | `skills/thesis-drift.md` |
| 20 | `skills/thesis-tracker.md` | superseded | `fengreview` | `skills/thesis-tracker.md` |
| 21 | `skills/wechat-article.md` | kept | —（无承接者，纯留档） | `skills/wechat-article.md` |

※ 上游第 21 个 skill 的真身是 `codex-skills/investment-memo-craft/SKILL.md`（上游 `skills/` 目录下**没有**同名文件）。

**分布**（实测，2026-09-17）：absorbed 1 / kept 6 / referenced 0 / superseded 14（合计 21）。实时数字用 `python tools/fengadopt.py stats`。

## 五、如何更新（上游 pull 后重跑）

1. 拉上游到同机 sibling 目录（本地克隆，不入库；默认 `../ai-berkshire`，可用环境变量 `AI_BERKSHIRE` 覆盖），记下新 commit：
   ```bash
   cd ../ai-berkshire && git pull && git rev-parse --short HEAD
   ```
2. 重导 21 份正文 + 刷新 `UPSTREAM.json`（标注头与 sha256 约定都固化在脚本里，不会靠人手复现）：
   ```bash
   python research/130-external-frameworks/ai-berkshire/import_skills.py
   python tools/fengadopt.py verify          # 必须 exit 0
   python tools/sync-ai-berkshire.py check   # 工具侧（7 个 Python 工具）的同步状态
   ```
   `import_skills.py` 做的事情：按映射表把上游 `skills/*.md`（19 个）+ `codex-skills/investment-memo-craft/SKILL.md` 逐字节重抄到 `skills/`（落点文件名 = 上游文件名，memo-craft 落为 `investment-memo-craft.md`），标注头的 Commit 换新值，`files` 的 sha256 **一律对上游原文**计算，`commit` / `commit_full` / `commit_date` / `synced_at` 一并更新。脚本是**幂等**的：上游没变时重跑，21 份正文逐字节不变。
3. 如果上游新增/删除/改名的 skill（脚本会打印警告）：同步改 `import_skills.py` 的映射表 + `ADOPTION.json` 的 `entries`（新条目要判 status、填 owner、给依据），否则 `verify` 会以"上游文件未被台账覆盖"或"本仓无对应正文"报错退出。
4. 上游若改了 `investment-team`：`.agents/skills/investment-team/SKILL.md` 的**上游正文部分**要跟着同步，同时**保留** ZCode 适配改写与 FengInvest 适配注记（哪些是原文、哪些是适配，见该文件注记末尾的清单）。

## 六、对账器

```bash
python tools/fengadopt.py verify            # 四项检查全过 → ✅ exit 0；任一漂移 → 逐条明细 + exit 1
python tools/fengadopt.py stats             # 四档计数 + 按 owner 分组（absorbed / superseded）
python tools/fengadopt.py list --status absorbed
python tools/fengadopt.py list --status kept
python tools/fengadopt.py verify --json     # 任一子命令均可 --json
```

四项检查：① `absorbed` / `kept` 的落点文件存在且非空；② `owner` 硬校验——`absorbed` / `superseded` 的 `owner` 非空且逐个能在 `.agents/skills/<owner>/` 或 `tools/<owner>.py` 解析到，`kept` 的 `owner` 必须为空（正文在本仓却没人用它，不许写 absorbed 糊过去）；③ 台账与正文对应**按 status 分派**——`absorbed` / `kept` / `superseded` 的 `upstream_file` 在本仓 `skills/` 下必须有对应非空正文（反向亦然：要求有正文的上游文件不得缺正文），`referenced` 本仓无正文是合法的、不作要求，但若写了 `landing` 就必须指向存在且非空的路径；④ 正文 sha256 与 `UPSTREAM.json` 记录一致（防偷改）。
