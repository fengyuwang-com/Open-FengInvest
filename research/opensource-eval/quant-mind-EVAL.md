# quant-mind 代码级评估

> 评估日期: 2026-09-03
> 仓库: https://github.com/LLMQuant/quant-mind (commit cloned to `research/opensource-eval/quant-mind/`)
> 许可: MIT

---

## 1. 项目总览

QuantMind 定位为"金融知识提取与检索框架"，NeurIPS 2025 Workshop 录用。核心理念：**知识工程 + 驱动工程（harness engineering）**——不仅是一个 Python 库，更是让编码 Agent 在仓库内可靠工作的完整规范体系。

### 架构分层

```
quantmind/
  etl/          # 纯 stdlib ETL 脚手架（独立叶节点）
  knowledge/    # Pydantic 数据标准（BaseKnowledge / FlattenKnowledge / TreeKnowledge）
  preprocess/   # 确定性预处理：fetch / format / clean / time
  configs/      # 操作配置 + 类型化输入模型
  rag/          # LlamaIndex 文档分块 + BM25 检索
  library/      # SQLite 持久化 + 语义检索（embedding + 向量排序）
  mind/         # 纯 Agent 推理层（LLM 决策驱动的结构化检索）
  flows/        # 顶层 API（PaperFlow / collect_news / batch_run）
  magic.py      # 自然语言意图解析 → (input, cfg)
  utils/        # 仅日志
```

### 关键依赖

- `openai-agents` (>=0.14) — Agent runtime
- `llama-index-core` (>=0.14) — 分块与 BM25
- `pydantic` (>=2.0) — 数据标准
- `httpx` — HTTP 取数
- `trafilatura` — HTML → 纯文本
- `pymupdf` — PDF 解析
- `litellm` — 多模型路由

---

## 2. 知识提取管线（Knowledge Extraction Pipeline）

### 2.1 知识类型体系

**三层知识形状**（`quantmind/knowledge/`）：

| 形状 | 基类 | 用途 | 示例 |
|------|------|------|------|
| `FlattenKnowledge` | `BaseKnowledge` | 原子卡片（一个源 → 一个答案） | News / Earnings / Factor / Thesis |
| `TreeKnowledge` | `BaseKnowledge + StructureTree` | 层次结构（监管文件、转录稿） | LegacyPaper |
| `GraphKnowledge` | `BaseKnowledge` | 交叉引用（占位，未来 PR） | — |

**Paper 专用模型**（独立于 BaseKnowledge）：
- `PaperSourceRevision` — 精确源修订（content-hash 锚定，含 blobs）
- `PaperChunkSet` — 分块集合（page-aware，带 source span 引用）
- `PaperGlobalSummary` — 引用全局摘要（citation 逐条校验到 chunk 和 page）
- `PaperStructureTree` — 页保留层次结构（从 LLM draft → code-owned identity）
- `PaperSemanticResult` — V1 结果（source + chunk_set + summary 三件套）

**设计亮点**：
- `as_of` 字段强制：金融知识必须显式信息截止时间
- `available_at`：源何时可观测，防止前视
- `SourceRef`：类型化溯源（kind: arxiv/http/doi/...），不允许裸字符串
- `ExtractionRef`：记录哪个 flow + model 产出
- 所有知识模型 `frozen=True` + `extra="forbid"`
- 内容寻址：SHA-256 content hash 贯穿全文，ID = uuid5(source_hash)，重算产出相同 ID

### 2.2 PaperFlow 管线

`PaperFlow(cfg).build(input)` 的完整流程：

```
arXiv ID / PDF / URL
  → preprocess/fetch/ (httpx + pymupdf)
  → PaperSourceRevision.from_parsed()  [code-owned identity minting]
  → PaperFlow 内部：
      ├── 结构模式 (PaperStructureCfg):
      │     preprocess/outline.py → OutlineSignals
      │     _structure.py → LLM 单次调用 → PaperStructureTreeDraft
      │     PaperStructureTree.from_draft() → code-owned tree
      │
      └── 语义模式 (PaperSemanticCfg):
            rag/document.py → SentenceSplitter → ParsedChunk[]
            PaperChunkSet.from_parsed_chunks() → code-owned chunks
            LLM map-reduce → summary + citations draft
            PaperGlobalSummary.from_draft() → code-owned summary
  → PaperSemanticResult (or PaperStructureTree)
```

**关键设计原则**：
1. **LLM 只产出 draft，code 拥有 identity** — UUID、link、citation 全部由代码解析和铸造
2. **确定性预处理** — fetch/parse/format/clean 无模型参与，溯源精确
3. **配置驱动** — cfg type 选择产出形状（typed dispatch，非继承层级）
4. **自包含 artifact** — 每个产物携带自身文本 + 最小溯源元数据（as_of + source ref）

### 2.3 News 管线

`collect_news` 的流程：

```
NewsWindow(source="pr-newswire", start, end)
  → _collect_pr_newswire()
      → _discover_pr_newswire()  [HTML 列表页分页发现]
          → _ListingParser (纯 HTMLParser，零外部依赖)
          → PRNewswireObservation[]
      → 并发 _collect_observation()  [每篇文章]
          → HttpFetcher.fetch_url()
          → news_document_from_fetched() → RawNewsDocument
          → preprocess_news_document() → NewsCandidate
              ├── normalize_news_text() [unicode + whitespace + dedupe]
              ├── canonicalize_source_url() [去 tracking params]
              ├── build_news_identity() [SHA-256 确定性 identity]
              └── extract_exchange_ticker_hints() [正则提取交易所 ticker]
  → NewsBatch(documents, failures, observed_count, complete)
```

**亮点**：
- 纯 HTMLParser 解析列表页（零外部依赖），鲁棒性高
- `NewsCandidate` 携带 content_hash、identity、ticker_hints
- 失败分级追踪（discovery_fetch / discovery_parse / article_fetch / article_parse）
- cache-bust 机制应对 PR Newswire 缓存

---

## 3. RAG / 检索层

### 3.1 rag/ — 文档分块与 BM25

`quantmind/rag/document.py`：

- 使用 LlamaIndex `SentenceSplitter` 按页分块
- 每个 chunk 携带 page_number、start_char、end_char、block_boxes（页面坐标）
- `chunk_parsed_document()` → `ParsedChunk[]`
- `retrieve_parsed_document()` → LlamaIndex `BM25Retriever` 排序

**评价**：干净的 thin wrapper，page-aware 是核心价值。但只支持 BM25，无向量检索。

### 3.2 library/ — SQLite 持久化 + 语义检索

`LocalKnowledgeLibrary` 是核心：

**写入路径**：
```
put(item) 或 put_paper(result)
  → _project_knowledge() / _project_paper()  [知识 → 检索目标投影]
  → 比对现有 embedding（模型/配置/hash 变化检测）
  → OpenAI embedding API 批量向量化
  → SQLite 原子写入（canonical + projections + embeddings）
```

**读取路径**：
```
search(SemanticQuery)
  → _LlamaIndexRetriever.filter()  [按类型/来源/置信度过滤]
  → OpenAI embedding(query)
  → _LlamaIndexRetriever.rank()  [余弦相似度排序]
  → SemanticHit[]（含 locator + projection + citations）
```

**SQLite Schema（v5）**：
- `knowledge_items` / `knowledge_nodes` / `semantic_records` — 常规知识
- `paper_sources` / `paper_source_assets` / `paper_artifacts` / `paper_artifact_members` / `paper_artifact_lineage` / `paper_projections` — Paper 专用
- 完整外键 + CASCADE 删除 + schema 版本迁移（v2→v3→v4→v5）
- 每条记录都有 canonical_hash 校验

**亮点**：
- 投影机制：知识类型定义数据，library 定义检索文本（分离关注点）
- 向量失效检测：embedding_model / projection_hash / source_content_hash / schema_version 任一变化即重算
- 事务性：写入前准备（prepare），embedding 失败不污染 canonical 数据

### 3.3 mind/ — Agent 推理检索

`AgenticRetriever` 是纯 Agent 层：

```
retrieve(retrievable, question)
  → _serialize_structure()  [tree → JSON，token budget 限制]
  → Agent（OpenAI Agents SDK）
      ├── tool: get_document_structure() → 树结构 JSON
      └── tool: get_node_content(node_ids) → 节点内容
  → _RetrievalSelectionDraft（LLM 选择的 node UUIDs）
  → _validate_selection() → RetrievalEvidence[]
```

**设计原则**：
- LLM 按推理选择相关节点（非相似度），适合文档结构检索
- Agent 必须先调用 `get_document_structure()`（强制 tool_choice）
- 读取结构自带内容（纯值操作，不依赖 library）
- 支持 seed_node_ids 为未来 hybrid 路径预留

---

## 4. Skill 架构

### 4.1 quantmind-dev skill

位于 `.agents/skills/quantmind-dev/SKILL.md` 和 `.claude/skills/quantmind-dev/SKILL.md`（镜像复制）。

**结构**：
```
SKILL.md          # 入口：选择工作流 + 规则 + 边界
references/
  setup.md        # 环境搭建 + hooks
  commit.md       # 提交规范
  pull-request.md # PR 规范
  develop-components.md  # 组件开发流程
  write-contexts.md      # contexts 页面编写规范
  tests.md        # 测试规范
```

**设计亮点**：
- SKILL.md 是路由页，指引 Agent 加载哪个 reference
- 两份镜像（Codex + Claude）保持同一内容
- 规则分层：advisory guidance（rules/skill references）vs hard guarantees（hooks）

### 4.2 确定性验证（verify.sh）

```bash
#!/usr/bin/env bash
set -euo pipefail
# 1. ruff format --check    # 格式
# 2. ruff check             # lint
# 3. basedpyright           # 类型
# 4. lint-imports           # 架构边界合同
# 5. pytest --cov           # 测试 + 覆盖率 75%
```

**关键**：
- fast-fail：第一步失败立即停止
- CI 运行完全相同的脚本
- `lint-imports` 编码了架构边界（etl 是独立叶 / knowledge 是叶 / configs 只依赖 knowledge / ...）
- 覆盖率门槛 75%（`--cov-fail-under=75`）

### 4.3 驱动工程（Harness Engineering）

三层执行机制：

| 层 | 机制 | 捕获对象 | 角色 |
|---|---|---|---|
| CI | `.github/workflows/ci.yml` 运行 `verify.sh` | 所有人，不可跳过 | 底线 |
| 本地 git hooks | `.pre-commit-config.yaml` | 安装了 pre-commit 的人 | 快速本地反馈 |
| Agent controls | `.claude/rules/`, `.claude/settings.json` hooks, `.codex/hooks.json` | 仅在仓库内运行的 Agent | 过程守卫 |

**反绕过 hook**：`pre_tool_use_no_bypass.py` 阻止 Agent 使用 `--no-verify`。机械检查（shlex tokenize），不处理 shell 间接引用。

### 4.4 Progressive Disclosure contexts

`contexts/` 目录是 Agent 面向的渐进式加载参考：
- 每页前 80 行有 Quick Summary + Contents
- Agent 先读 preview 决定是否需要该页
- 设计合约、开发流程、组件文档分类存放

---

## 5. 模块级评估与适用性判定

### 5.1 knowledge/ — 知识数据标准

**判定：可参考（部分可直接复用）**

| 子模块 | 判定 | 理由 |
|--------|------|------|
| `BaseKnowledge` (as_of / available_at / source / extraction / confidence / citations) | 可直接复用 | 概念完美匹配 FengInvest 需求；as_of / available_at / Citation 模型可直接导入 |
| `FlattenKnowledge` → `News` / `Earnings` / `Factor` / `Thesis` | 可参考 | 类型设计好，但 FengInvest 已有自己的 holding schema 和 analysis 框架，不会直接用 |
| `TreeKnowledge` / `StructureTree` / `TreeNode` | 可直接复用 | 树结构 + 验证（环检测/子页包含/page ownership）非常成熟，七层分析报告可借鉴 |
| `PaperSourceRevision` / `PaperChunkSet` / `PaperGlobalSummary` | 可参考 | Paper 专属，FengInvest 不处理 PDF 论文；但 content-addressed identity + draft→code-owned 模式值得学习 |
| `SourceRef` / `ExtractionRef` / `Citation` | 可直接复用 | 溯源模型极好，FengInvest 的每个分析结论都应有类似引用链 |

**核心借鉴点**：
- `as_of` 强制金融时间属性
- content-hash → uuid5 identity（重算不变）
- LLM 只出 draft，code 拥有 identity 的模式

### 5.2 preprocess/ — 确定性预处理

**判定：可直接复用（新闻部分）/ 不适用（Paper 部分）**

| 子模块 | 判定 | 理由 |
|--------|------|------|
| `pr_newswire.py` | 可直接复用 | PR Newswire 新闻采集管线，如果 FengInvest 需要采集英文新闻/公告，可直接 import 或复制 |
| `news.py` (normalize / identity / ticker hints) | 可直接复用 | `build_news_identity` / `extract_exchange_ticker_hints` / `canonicalize_source_url` 是通用工具 |
| `clean.py` (normalize_unicode / collapse_whitespace / dedupe_lines) | 可直接复用 | 文本清洗工具箱，零依赖 |
| `format/pdf.py` / `format/html.py` | 可参考 | PDF/HTML → 结构化文本；FengInvest 已有自己的 data 取数层 |
| `fetch/` (http / arxiv / doi / rss / local) | 可参考 | 通用 fetcher 带 retry/backoff/rate-limit；FengInvest 已有 fengthrottle.py |
| `fetch/http.py` (HttpFetcher + FetchPolicy) | 可直接复用 | 设计优秀的 HTTP 取数器（并发控制 / cache-bust / 指数退避），可替代 FengInvest 部分手写取数 |

### 5.3 rag/ — 文档分块与检索

**判定：可参考**

- LlamaIndex SentenceSplitter + BM25Retriever 的 thin wrapper
- page-aware chunk 设计（bbox / start_char / end_char）对论文检索有价值
- **但 FengInvest 不做论文检索**，我们的检索对象是股票数据和分析报告
- 如果未来需要对七层分析报告做 RAG 检索，这个 pattern 可参考

### 5.4 library/ — 语义知识库

**判定：可参考（架构模式）/ 不适用（直接导入）**

| 方面 | 判定 | 理由 |
|------|------|------|
| SQLite schema 设计（canonical + projections + embeddings） | 可参考 | 分离 canonical 知识和检索投影是好模式；FengInvest 的 market_data.db + fengdb.py 可借鉴 |
| 向量失效检测（embedding_model / projection_hash / content_hash） | 可直接复用 | 思路可直接应用于 fengcache.py 的决策缓存 |
| 知识投影 `_project_knowledge()` | 可参考 | 不同知识类型 → 不同检索文本的策略，FengInvest 可为不同分析层设计类似投影 |
| `LocalKnowledgeLibrary` 整体 | 不适用 | 太重，FengInvest 已有自己的 SQLite + JSON 持仓体系；不需要 embedding-based 语义检索 |

### 5.5 mind/ — Agent 推理检索

**判定：可参考**

- `AgenticRetriever` 的"LLM 读结构 → 选分支 → drill down"模式是好设计
- `get_document_structure` + `get_node_content` 的 tool 设计清晰
- token budget 控制（序列化时 truncation）实用
- **但 FengInvest 不需要这种推理检索**：我们的分析是确定性工具驱动（fengstate.py / fengrule.py / fengquant.py），不需要 LLM 在树上推理

### 5.6 flows/ — 顶层 API

**判定：可参考**

- `PaperFlow(cfg).build(input)` 的 cfg-type → output-shape dispatch 模式
- `batch_run(flow, inputs, concurrency=N)` 的通用扇出
- `collect_news` 的 intent-oriented API 设计
- `magic.py` 的自然语言 → (input, cfg) 解析
- **但 FengInvest 已有自己的工具层**（fengdata.py / fengrule.py / ...），不需要替换

### 5.7 etl/ — ETL 脚手架

**判定：可参考**

- `ETLPipeline` 的 extract → transform → load 三阶段 + dry_run + 观测性
- `RunRecord` 的原子状态快照 + events.jsonl 审计日志
- **FengInvest 的 fengdb.py safe_batch 已有类似变更集 + undo 模式**
- 如果未来需要更复杂的 ETL 编排，可参考其 dry_run + progress 上报

---

## 6. 针对性问题回答

### 6.1 有没有可以适配到我们市场层的新闻/论文解析代码？

**有，但主要是新闻采集，不是论文解析。**

可直接利用的部分：
1. **`pr_newswire.py`** — 完整的 PR Newswire 新闻采集器（发现 → 抓取 → 清洗 → 结构化），可直接 import 用于采集英文公司新闻/财报公告
2. **`news.py` 中的 `extract_exchange_ticker_hints()`** — 从新闻文本中正则提取交易所 ticker 提及（`(NASDAQ: NVDA)` 格式），FengInvest 的新闻监控可直接用
3. **`build_news_identity()`** — 确定性新闻 identity 生成，可用于去重
4. **`canonicalize_source_url()`** — URL 标准化（去 tracking params），通用工具
5. **`HttpFetcher` + `FetchPolicy`** — 带并发控制、指数退避、cache-bust 的 HTTP 取数器

不适用的部分：
- Paper 解析（PDF → page blocks → structure tree）— FengInvest 不处理学术论文
- LLM 驱动的结构提取（`_structure.py` / summary generation）— 我们的分析是确定性工具驱动

**结论**：如果 FengInvest 需要增加"新闻监控"能力（采集公司公告、财报新闻、市场事件），quant-mind 的 news 模块是**可直接复用的生产级代码**。

### 6.2 它的 skill+contract 模式比我们 SKILL.md 更好吗？

**更成熟、更系统化，但 FengInvest 已有自己的等价体系。**

quant-mind 的优势：
1. **镜像 skill**（`.agents/skills/` + `.claude/skills/`）确保 Codex 和 Claude 同一内容 — FengInvest 目前只在 `.agents/skills/` 下
2. **渐进式 contexts**（`contexts/` 目录 + CONTEXT_MAP.md）— Agent 按需加载，不预加载整个 AGENTS.md — FengInvest 的 AGENTS.md 较长但一次性加载
3. **分层执行机制**（CI → git hooks → agent hooks）— 三层防御，尤其是反绕过 hook 很实用
4. **lint-imports 编码架构边界** — 用 import-linter 在 pyproject.toml 中声明模块依赖图 — FengInvest 没有等价机制

FengInvest 的优势：
1. **状态机铁律**（fengstate.py）— 更强的流程强制（八层顺序不可跳步）— quant-mind 没有等价物
2. **hook 拦截直接 Write/Edit** — 防止 AI 手工填坑 — quant-mind 没有等价物
3. **七层分析框架 + 62 个工具** — 远比 quant-mind 的知识提取复杂

**可借鉴的具体点**：
- 把 SKILL.md 镜像到 `.claude/skills/` 以支持 Claude Code
- 引入 `lint-imports` 编码 FengInvest 的模块依赖图（tools/ vs research/ vs holdings/）
- 引入渐进式 contexts（将 CLAUDE.md 拆分为按需加载的 pages）
- 引入反绕过 hook（阻止 `--no-verify` 或等价操作绕过 fengstate.py）

### 6.3 能不能借用它的 verify.sh 方法给 fengcheck/fengverify？

**可以借鉴思路，但需要重新设计。**

quant-mind 的 verify.sh：
```bash
ruff format --check → ruff check → basedpyright → lint-imports → pytest
```

5 步 fast-fail，纯代码质量门禁。

FengInvest 的 fengcheck/fengverify：
- `fengcheck` — 对照基准参考清单验证七层分析报告（内容质量审计）
- `fengverify` — 论断复测引擎（回测 + 12 项红绿灯）

**可借鉴的模式**：

1. **fast-fail 顺序执行** — verify.sh 的 `set -euo pipefail` + 顺序步骤模式可直接用于 fengcheck：
   ```bash
   # fengcheck_verify.sh
   set -euo pipefail
   echo "==> [1/4] schema validation (fengstate.py verify)"
   python tools/fengstate.py verify $TICKER
   echo "==> [2/4] structural check (key_fields / min_items)"
   python tools/fengcheck.py structure $TICKER
   echo "==> [3/4] cross-layer consistency"
   python tools/fengcheck.py consistency $TICKER
   echo "==> [4/4] content quality audit"
   python tools/fengcheck.py content $TICKER
   ```

2. **CI 同一脚本** — CI 和本地运行完全相同的 verify 脚本（quant-mind 的核心原则）

3. **覆盖门槛** — `--cov-fail-under=75` 的思路可用于 fengcheck 的通过率门槛

4. **架构边界合同** — `lint-imports` 的模式可用于 FengInvest：
   - `tools/` 不依赖 `research/`
   - `holdings/` 不依赖 `tools/fengstate.py` 以外的工具
   - `fengdb.py` 是唯一写 market_data.db 的入口

---

## 7. 总结评分

| 维度 | 评分 (1-5) | 说明 |
|------|-----------|------|
| 代码质量 | 5 | 极高：类型完整、frozen Pydantic、content-hash、事务性、schema 迁移、75% 覆盖率 |
| 架构设计 | 5 | 分层清晰、关注点分离、依赖图严格（import-linter 编码）、确定性 vs LLM 边界明确 |
| 与 FengInvest 相关性 | 3 | 新闻采集可直接用；知识标准可借鉴；但整体定位不同（学术论文 vs 投资分析） |
| 可复用代码量 | 中 | news 模块 + preprocess 工具箱 + knowledge 基类 + verify.sh 模式 |
| 可借鉴设计模式 | 高 | content-addressed identity、draft→code-owned、三层执行机制、渐进式 contexts |

### 建议 Action Items

1. **[高优先] 引入 `lint-imports`** — 在 FengInvest 的 pyproject.toml 中编码模块依赖边界
2. **[高优先] 镜像 skill 到 `.claude/skills/`** — 支持 Claude Code 用户
3. **[中优先] 引入反绕过 hook** — 阻止 Agent 跳过 fengstate.py 检查
4. **[中优先] 借鉴 verify.sh 模式** — 创建 `scripts/verify_analysis.sh` 作为分析质量门禁
5. **[低优先] 复用 news 采集模块** — 如果 FengInvest 需要新闻监控能力，直接 import `quantmind.preprocess`
6. **[低优先] 借鉴渐进式 contexts** — 将 CLAUDE.md 拆分为按需加载的 pages
7. **[参考] content-hash identity 模式** — 应用于 FengInvest 的分析报告去重和缓存
