# 项目结构根本标准（不可改动）

> 以下标准是本项目结构的**根本要求**。任何改动（refactor、重构、新增文件夹）都必须满足全部标准，一条不可违反。
> **本文件本身也不可随意修改**——修改须经明确确认。

---

## §1 文件夹整洁

**根目录**只允许：
- `.gitignore`
- `CLAUDE.md`（项目入口）
- `README.md`（项目简介）
- 启动脚本（`start-*.sh` / `start-*.bat`）
- 标准 git 文件（`.gitattributes` 等）
- **禁止** 其他散落文件

**`docs/`** 只放框架文档（`.md` + `architecture.html`）。不含配置文件、数据、代码。

**`tools/`** 只放 `.py` 工具。

**`research/` 根目录** 只放 README 和 REFERENCE-TREE 这类索引文件。所有实质内容在编号子目录中。

## §2 编号命名体系

`research/` 下所有子目录使用 **3 位数字前缀**（`010-`、`020-`、`...`、`110-`）：

```
010-macro/
020-market/
030-asset-classes/
040-people/
050-strategies/
060-companies/
070-reports/
090-portfolio-management/
100-learning-investment/
110-strategy-verification/
```

**规则：**
- 前缀数字按 10 递增，中间预留空间
- 目录名 = 数字前缀 + `-` + 英文短名（小写+中划线）
- **禁止** 无编号目录存在于 `research/` 下
- **禁止** 编号跳跃插入（如新增目录必须在 010-110 范围，且不与已有编号冲突）

## §3 个股目录标准

路径格式：
```
research/060-companies/<TICKER>-<中文名>/<YYYY-MM-DD>/
```

**强制规则：**
- **必须** 包含中文名（TICKER 后加 `-` + 中文）
- 不允许纯英文或无中文名的目录
- 日期目录使用 ISO 格式（`YYYY-MM-DD`）
- **注意**：`research/060-companies/` 含个人分析数据，已 gitignore，**不在公开仓库中**。文档中引用该路径时须标注"本地 gitignored"。

## §4 引用正确

所有跨文件路径引用必须满足：

1. **指向存在的位置** — 引用路径的目标文件/目录必须实际存在
2. **指向正确的位置** — 使用完整的编号路径（如 `research/020-market/latest.json` 而非 `research/market/latest.json`）
3. **所有文档更新** — 移动/重命名文件后，必须同步更新所有引用它的文档
4. **相对位置不变** — 文件移动后，保持内部相对引用有效

## §5 Skill 路径正确

本项目的 AI Skill 文件统一放 `.agents/skills/<skill>/`（ZCode 工作区为唯一真相源，不再维护 `.claude/skills` 副本）。Skill 五件套：`fengscreen`（去劣筛选）/ `fenginvest`（买入前七层）/ `fengholding`（持有期）/ `fengexit`（卖出）/ `fengreview`（复盘）。Skill 中硬编码路径必须与实际项目结构一致：

| Skill | 关注路径 |
|:----------|---------|
| fengscreen | `research/060-companies/`（输出）、`research/050-strategies/`（行业扫描）、`tools/financial_rigor.py`（验算） |
| fenginvest | `research/060-companies/`（非 `companies/`）、`research/040-people/named/`、`portfolio/current.md`（P 层输出走 `$BASE/08-portfolio.json`） |
| fengholding | `holdings/`、`holdings/SCHEMA.md`、`research/060-companies/`（thesis 联动） |
| fengexit | `holdings/`（sell 闭环）、`docs/08-exit.md` |
| fengreview | `holdings/`（reviews 写回）、`reviews/`、`research/060-companies/<T>-*/thesis.md` |
| 所有 Skill | `tools/feng*.py`、`knowledge/`、`docs/` |

**规则：**
- Skill 中的路径必须始终指向带编号的完整路径
- 每次目录结构调整后必须同步更新所有相关 Skill
- 新增 Skill 只建 `.agents/skills/<skill>/SKILL.md`，不建 `.claude` 副本

## §6 内部自洽

以下三组描述必须完全一致：

1. **实际目录结构** — 磁盘上的文件和文件夹
2. **CLAUDE.md 中的目录树** — 项目 README 层级的目录描述
3. **research/010-REFERENCE-TREE.md** — 知识库索引的映射关系

任意一处与实际不符即为违反标准。

## §7 文档对齐

项目文档（`docs/`、`CLAUDE.md`、`research/` 内的 README）中的路径、编号、描述必须与实际情况一一对应。

**检查清单：**
- [ ] `CLAUDE.md` 中的 `research/` 树与实际一致
- [ ] `README.md` 中的 `research/` 树与实际一致
- [ ] `research/010-REFERENCE-TREE.md` 的映射表与实际一致
- [ ] `research/000-README.md` 的目录清单与实际一致
- [ ] 所有 `.md` 文件中引用的路径前缀正确（如 `070-reports/` 而非 `reports/`）

## §8 .gitignore 覆盖

以下内容必须被 `.gitignore` 覆盖：
- 数据库文件（`*.db`、`*.sqlite`）
- 日志文件（`logs/*.log`）
- 检查点 / 临时状态文件（`data/*checkpoint*`、`research/state/temp_*`）
- 生成的文件（`skills-lock.json`）
- 缓存（`__pycache__/`、`*.pyc`）

**禁止** 将以上类型的文件提交到 git。

---

## 验证命令

修改后执行以下命令快速验证：

```bash
# 1. 检查 research/ 下无编号目录
ls -d research/*/ | grep -v "^research/[0-9][0-9][0-9]-"

# 2. 检查 060-companies 下无中文名的目录
ls research/060-companies/ | grep -v "-"

# 3. 检查 root 散落文件（白名单外）
ls -la | grep "^-" | grep -v "\.gitignore\|CLAUDE\.md\|README\.md\|start-\|\.gitattributes"

# 4. 检查技能文件中的路径旧名
grep -rn "research/companies\|research/people/\|research/market/\|research/state/\|research/reports/\|research/strategies/\|research/macro/\|research/portfolios/\|100-strategy-verification" .agents/skills/fenginvest*/SKILL.md research/*.md 2>/dev/null
```

---

*建立日期：2026-07-23*
*本文件记录项目结构的不变约束。修改须经明确确认。*
