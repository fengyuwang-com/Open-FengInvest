# 零 key Prompt 计划 — 决策台全流程网页版免费模型化

> 2026-09-07 R37 定稿。路线：零 key——GUI 生成 Prompt → 一键复制 → 一键打开 chat.deepseek.com / 智谱网页版 → 结果贴回 → 结构验证推进状态机。全程不碰 API key。
> 本文只圈"哪里需要写 Prompt"，Prompt 文本本身待创始人点头计划后再写。

## 一、总原则

1. **程序能算的绝不写 Prompt**：M 市场数据（fengdata）、L1 硬纪律（fengrule 四灯）、L2b 量化（fengquant 六因子）是确定性工具，卡片只展示工具结果，不设 Prompt。LLM 只用在"判断"和"说人话"上。
2. **Prompt 是写给网页版免费模型的**，四条硬约束：
   - **自包含**：模型没有文件、没有联网，Prompt 里必须把公司简介/数据摘要直接嵌进去（GUI 自动预填，用户不用自己找料）。
   - **小上下文**：每条 Prompt 控制在 2000–4000 字，长数据由 GUI 预先截取摘要。
   - **强制 JSON 输出**：每条 Prompt 末尾给输出 schema + 一个完整示例 + "只输出 JSON、不要废话"，因为贴回 /prompt/submit 有结构验证，验证不过状态机不推进。
   - **按创始人原则写**：6 信条 + DK 四原则 + 六条纪律逐条化进 Prompt（"不可乱写，按我原来的原则重写"），并内置反敷衍条款（"数据不足就写'不知道'，禁止编造数字"）。

## 二、Prompt 清单（12 条）

### A. 决策台七层（每层一张独立卡）

| # | 层 | 要不要 Prompt | 输入预填 | 输出 JSON 要点 |
|---|---|---|---|---|
| 1 | L0 能力圈 (01-capability) | ✅ | 公司名 + 业务简介 + 收入结构（GUI 从本地库自动带出） | understand_verdict (懂/不懂/半懂) + 理由 + 不懂点清单 |
| 2 | M 市场数据 | ❌ 纯工具 | — | — |
| 3 | L1 硬纪律 | ❌ 纯工具 | — | — |
| 4 | L2b 量化 | ❌ 纯工具 | — | — |
| 5 | L2a 定性 (05-qualitative) | ✅ 最重的一条 | L0 结论 + 财报三表摘要（fuyao 已有）+ 行业地位描述 | 护城河五问逐答 + moat_rating + 结构性壁垒论证（必须穿透，不许"品牌好"敷衍） |
| 6 | L3 碰撞 (06-collision) | ✅ 红队角色 | L1 四灯 + L2b 因子 + L2a 结论全文嵌入 | 质疑清单 + 每条质疑的严重度 + final_check |
| 7 | L4 报告 (07-report) | ✅ 白话成文 | 前面所有层结果 JSON 全文嵌入 | markdown 白话报告书（人读版，非 JSON；单独通道贴回） |

### B. 决策台之外的 Prompt 场景（同样一张卡 + 四按钮）

| # | 场景 | 输入预填 | 输出 |
|---|---|---|---|
| 8 | 复盘 (review) | 持仓 thesis + 买入理由 + 最新数据摘要 | thesis_valid 判定 + 四态假设复核 JSON |
| 9 | 卖出自查 (exit) | 持仓 + 触发事件描述 | 六类理由归类 + 偏误自查问答 JSON |
| 10 | 讨论对手 (fengdiscuss) | discuss-config.json 锚点 + 用户观点 | 有锚反驳（守锚不投降版） |
| 11 | 白话翻译器（通用） | 任意工具输出（回测白话卡/筛选结果/审计报告） | 大白话解释，零术语（用户不是程序员） |
| 12 | 投机侧车解读 (fengspec) | tickflow T0/T2/T4 输出 | 交易级风险大白话 + 机械止损位复述 |

## 三、GUI 改动（决策台完全重做，R35a 遗留合并进本次）

1. **workspace.ejs 推倒重来**：七层各一张独立卡（顺序 L0→M→L1→L2b∥L2a→L3→L4），纯工具层显示数据结果 + "去工具跑"按钮；Prompt 层卡内四按钮：**生成 Prompt / 一键复制 / 打开网页版模型（新标签，可选 DeepSeek 或智谱，记住上次选择）/ 贴回验证**。卡内常驻粘贴区。
2. **服务端**：`/api/prompt/generate` 扩展为按层出完整 Prompt（模板 + 数据预填 + 原则注入）；`/api/prompt/submit` 结构验证保留并按层补齐 schema。
3. **L4 与通用翻译器走 markdown 通道**：贴回后不进状态机，只渲染成白话卡。
4. 每卡记住上次贴回结果（localStorage），刷新不丢。

## 四、实施顺序

1. workspace.ejs 七卡重做 + 四按钮 + 粘贴区（骨架先通）
2. 写 12 条 Prompt 模板（每条附 JSON schema + 示例，逐条按创始人原则注入）——**这一步单独给创始人过目再上线**
3. /prompt/submit 分层 schema 验证补齐
4. L4 markdown 通道 + 白话翻译器入口（挂在报告书架和回测页旁）

## 五、兼容性审核结论（2026-09-07 审计通过，附两处修订）

- **BYOK 契约**：`/api/llm/config|test` 与设置弹窗是独立代码路径。**移植时不可丢的三条语义**：GET config 只回 `api_key_masked`（永不回明文）；POST config 空字符串 `api_key` = 保留旧 key（`file-store.ts` `saveLlmConfig` 的 guard，防打码回传洗掉已存 key）；`/api/llm/test` 服务端读本机已存配置，不接受前端传 key。
- **现有 prompt 管线零破坏**：`/api/prompt/generate` 本来就吃 `src/prompt-templates/<layer>.md` 模板 + `{{TICKER}}/{{NAME}}/{{EVIDENCE}}` 占位符，重写模板内容、机制不变；`/api/prompt/submit` → fengstate complete 这道状态机真门一字不动，贴回不合规照样被拒，状态机不可能被网页污染。
- **影响面收窄**：全站只有 workspace.ejs 消费 /prompt/*（层下拉同样从 `/api/prompt/templates` 渲染，层清单唯一来源 = `PROMPT_LAYERS`，加层不改视图文件），layout.ejs 只是侧栏导航链接 `/workspace`（路由保留）。改决策台不波及任何其他页面。
- **修订 1（L4 通道）**：L4 报告是 markdown 非 JSON，不得塞进现有 `/prompt/submit`（它强制 JSON.parse + fengstate complete）——新增独立端点 `/api/prompt/submit-md`，只存档渲染，不动状态机。
- **修订 2（新增场景）**：白话翻译器/卖出自查/讨论对手不在现有 PROMPT_LAYERS 表里，走新增端点，不修改现有 8 个 layer 的行为。（2026-09-13 注：三者后来已并入 PROMPT_LAYERS，共 12 层。）
- **修订 3（2026-09-13 收敛，覆盖本节"页内直跑保留"提法）**：创始人点名"聊天直跑"旧路线残骸属收敛不彻底，**已删净**——`POST /api/llm/chat`、`GET /analyze(/:ticker)` + `views/analyze.ejs`、`POST /api/analysis/:ticker/run` + `GET .../status` 及 runner 侧 `runAnalysis/runStateCheck`，fengwebcheck.py 探测清单同步摘除。"页内直跑按钮"设想随之作废，将来若做须按上面 BYOK 契约重新设计。

## 六、不做什么

- 不建 API 代理、不碰 key、不做浏览器自动化操控网页聊天。
- 不把 M/L1/L2b 交给 LLM——数字必须出自工具。
- Prompt 一次不写两遍：模板集中在服务端一个文件里，GUI 只取不改。
