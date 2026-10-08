# 接力派单模板（RELAY-PROMPT）

> 本文件是 `tools/fengqueue.py` 接力机制的**派单模板唯一出处**。
> 每 20 分钟的接力定时任务读本文件，把 `<TICKER>` / `<NAME>` / `<MARKET>` 替换后
> 派给一个 `general-purpose` 后台子代理。
>
> **为什么单独成文**：模板里每一条硬要求都是踩过坑换来的（伪造状态、假跑工具、
> 数据源已死、同句数字自相矛盾……）。把它放进 cron 的 prompt 字符串里没法评审、
> 没法 diff、改了没人看得见。落到版本库就变成了可审阅的项目资产。

---

## 一、占位符

| 占位符 | 含义 | 示例 |
|:---|:---|:---|
| `<TICKER>` | 行情代码（含市场后缀） | `MU` / `000660.KS` / `600012.SS` |
| `<NAME>` | 中文名 | `美光科技` / `SK海力士` / `皖通高速` |
| `<MARKET>` | 市场归属 | `US` / `KR` / `CN` / `HK` / `JP` |

---

## 二、各市场数据通道（**先查表，别硬试**）

| 市场 | 主通道 | 有效命令 | 已证的坑 |
|:---|:---|:---|:---|
| CN | 本地 DB + 腾讯/东财/新浪 | `python tools/fengdata.py <TICKER>`；`--sina-financials` 取三表 | A 股年线口径 = **MA250**，MA200 不得冒充 |
| HK | 本地 DB + 腾讯 | 同上 | — |
| US | 本地 DB + 腾讯 + SEC | `python tools/fengsec.py facts <TICKER>`（PIT 双轴）；EDGAR 需 `FENG_HTTP_UA` | **`yfinance` 在本机不可靠**，优先腾讯/SEC |
| KR | **naver** | `python tools/fengstockintl.py fetch <TICKER> --keep-data` | ⚠️ **yfinance `.KS` 已死**（`possibly delisted; no price data found`）；naver 约 3000 行 ≈ 12 年，复权语义未验证，标 `unverified(疑似拆股复权)` |
| JP | 东证名单 `data/config/universe_JP.json` | 同上 | — |

搜索：`python "$SEARCH_KING_DIR" --search "关键词" --limit 5`（`SEARCH_KING_DIR` = 项目外兄弟目录里 scraper.py 的绝对路径，环境变量指定；本仓 `tools/fengstate.py` 探针用同一变量），
读正文 `--read <URL>`。**非英语市场必须用当地语言搜**（韩语/日语），英文源对
韩日中小市值覆盖极差。

---

## 三、派单模板（逐字使用，只替换占位符）

````text
你是 FengInvest 七层分析执行子代理。工作目录 C:\Projects\FengInvest（Windows + Git Bash；
读写含中文文件一律显式 encoding="utf-8"）。

任务：对 <TICKER>（<NAME>，市场 <MARKET>）执行完整七层决策分析
（L0 能力圈 → M 市场 → L1 硬纪律 → L2b 量化 ∥ L2a 定性 → L3 碰撞 → L4 报告 → P 组合），
并按项目规矩自审。

【0. 先读这两份，它们是流程权威】
- .agents/skills/fenginvest/SKILL.md（Step 0 → Step 8 的完整流程）
- AGENTS.md（工作区铁律）与 research/120-idea-sourcing/README.md（本标的从哪来）

【1. 状态机是唯一 truth】
只用 `python tools/fengstate.py init/check/complete/status/verify <TICKER>` 改状态。
严禁手写 research/state/temp_state_*.json，严禁用 Write/Edit 碰 research/state/。
逐层顺序不得跳步、不得合并层。

【2. 每层必须真跑工具并留原始证据】
L1=fengrule.py；L2b=fengquant.py；M=fengdata.py；L3=fengcollision.py；L4=report_audit.py。
原始输出（含 stderr）落到 <BASE>/sources/，**必须保留工具自带的溯源时间戳字段**
（fengrule 的 checked_at / fengquant 的 fetched_at / fengcollision 的 collided_at /
fengdata 的 fetched_at）——禁止改写、禁止手填，它们是事后对账的唯一锚点。

【3. 双格式出站】
每层 JSON 出站文件 + 同层可读 MD。L4 双版本：07-report.md（分析师版）+
07-narrative.md（贫嘴版）。全部完成后写 00-INDEX.md。
`fengstate.py complete` 的 output 必须是该层 .json 产物路径（01/05/07 层除外）。

【4. L2a 定性一律走 investment-team】
铁律：**禁止自己写定性分析**。必须通过 Skill("investment-team") 执行四大师并行
（段永平/巴菲特/芒格/李录）。该 skill 已装在本项目 .agents/skills/investment-team/。
⚠️ **Skill 发现不到时的兜底（"找不到"不等于"可以自己写"）**：若 Skill 工具报"未知 skill"
（该 skill 建于本会话中，会话开头的 skill 清单可能还没刷新），**不要就地自己编定性分析**：
改用 Read 直接读 `.agents/skills/investment-team/SKILL.md`，按其中四角色的分工与提问协议
人工执行同样的四路并行，并在 05 层产物里如实标注「investment-team 以文件读取方式执行，
未经 Skill 调度」。**唯一禁止的是跳过四大师框架、自说自话当定性结论。**
除 05-qualitative.md 外，**必须**额外产出 05-qualitative_lights.json，
键名固定为：好生意 / 护城河 / 安全边际 / 管理层 / 需求稳定 / 会计质量。

【5. 不凭训练知识硬答】
每个数字必须有来源（本地 data/market_data.db、工具输出、或搜索证据 URL）；
拿不到就标「未验证」，不许编造。外抓数字入库前必与本地对拍，偏离 >10% 以本地为准。

【6. 数字自洽硬闸门】
写"低于年线 X%"时 X 必须由括号内两个数字算出（fengverify_gate Gate 3d 会强制对拍，
同句矛盾即 report 门 FAIL）。A 股年线 = MA250。

【7. 收尾必跑，两条都要原文粘贴回报】
- `python tools/fengstate.py verify <TICKER>`
- `python tools/fengverify_gate.py <TICKER> --json`（五门 state/structure/report/
  pipeline/consistency，任一 HALT 即未完成）
- 再读 .agents/skills/fengcheck/SKILL.md 跑 fengcheck，把 AUDIT_REPORT.md 落到分析目录，
  修到 PASS 或 CONDITIONAL PASS 为止。

【8. 自证 ≠ 验收（这条最容易翻车）】
项目已实测确认：`fengstate verify` 与五门闸门**只查"文件在不在、键在不在、
数组够不够长"，不查数值来源**——八层纯手拼 JSON 也能全绿。所以回报里**必须**
额外给出 raw↔layer 对拍证据，否则主代理判为"不可信、返工"：
- sources/fengquant_raw.json 与 04-quantitative.json 的 engine_raw 字段逐键相等（含 fetched_at）
- sources/fengrule_raw.json 与 03-discipline.json 的 rules 条数、overall_light 一致
- sources/fengcollision_raw.json 与 06-collision.json 的 decision / conflicts 条数一致
- 上述 raw 的 mtime 与 research/state/temp_state_<TICKER>.json 中该层 timestamp 的
  对应关系（raw 是本地 CST，state 是 UTC，相差 8 小时）

【9. 市场数据通道】见 research/120-idea-sourcing/RELAY-PROMPT.md 第二节表。重点：
- US：本地 DB + 腾讯 + `python tools/fengsec.py`（SEC 一手资料）；yfinance 不可靠
- KR：**yfinance `.KS` 已死**；用 `python tools/fengstockintl.py fetch <TICKER> --keep-data`
  （naver 源）。复权语义未验证，必须标注。**必须用韩语搜索**，英文源覆盖极差。

【10. 回报格式（必须给全，缺项视为未完成）】
- TICKER 与产物目录 research/060-companies/<TICKER>-<中文名>/<YYYY-MM-DD>/
- 决策与置信度（来自 06-collision.json：decision / confidence / position_pct）
- fengcheck 审计结果（x/42 与判定 PASS/CONDITIONAL/FAIL）
- fengstate verify + 五门闸门输出（原文粘贴）
- raw↔layer 对拍证据（见第 8 条）
- 数据降级与失败点清单（哪些源没用上、哪些字段标了未验证）
- **若要提前收束**（只做了部分层）：如实报告做到哪层、哪些层没开始、为什么收束。
  严禁把未做的层写成"已分析"。

【11. 边界】
不要碰持仓登记（/fengholding）、不写买入建议、不改本标的以外的任何标的。
````

---

## 四、给接力调度者的验收口径（主代理用，不给子代理看）

子代理自述**不算**完成。逐只跑：

```bash
python tools/fengstate.py status <T>          # 必须 completed 且八层全 [x]
python tools/fengstate.py verify <T>          # 必须 exit 0 且 "8 通过, 0 失败"
python tools/fengverify_gate.py <T> --json    # 必须 all_passed=true 且 gates 长度=5
```

机器门之外还要**人工**看四项（审计已证明这是唯一能区分"跑了"和"编了"的检查）：
1. **溯源四件套**都在且时间戳字段非空 —— 缺一即"工具没真跑过"。
2. **raw↔layer 对拍**逐键相等（注意 CST/UTC 差 8 小时）。
3. **报告抽数**：从 07-report.md 抽 2-3 个核心数字回查 02-market.json 与 sources/，
   报告里有而源头没有的数字 = 打回。
4. **占位符排查**：rules 八条 / factors / 05、07 正文不得出现 TBD/待补/重复粘贴。

四项有任何一项不过 → 标「需返工」，**不计入完成数**，在汇报里点名。
