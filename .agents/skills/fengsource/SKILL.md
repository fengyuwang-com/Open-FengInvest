---
name: fengsource
description: "[FengInvest] 自主选股 — thesis-first 的标的发现：五条发现路径 → 三道闸门 → 候选卡 → 排队七层。不从 ETF/指数成分出发，也不从量化筛子出发。"
when_to_use: "主动找标的（而不是分析给定标的）时使用。当用户要求'找找有什么好公司''自主选股''有什么值得研究的''帮我发现标的''不限于红利股去找有护城河的''AI 自己去找股票'时使用。触发词：自主选股、找股票、发现标的、有什么好公司、值得研究的公司、ideation、选股源"
allowed-tools:
  - Bash
  - Read
  - Write
  - Skill
  - Agent
triggers:
  - fengsource
  - 自主选股
  - 找股票
  - 发现标的
  - 有什么好公司
---

# FengSource — 自主选股（thesis-first 标的发现）

> **机制说明书（先读）**：`research/120-idea-sourcing/README.md` —— 本 skill 是它的可执行版。
> **一句话**：不问"哪个筛子能筛出好股票"，先问"什么样的事业值得拥有"，再去找它。

---

## 铁律

1. **入口禁止跑量化筛子**。`fengscreen` 的 7 硬指标是**闸门 3**，不是入口。先有生意判断，再谈财务排除。
   （根因：红利/价值类筛子的输入全是"当期结果指标"，周期股在景气高点长得和高股息优质股一模一样 —— 实测 24 只红利幸存者里 15+ 只是纯周期股。）
2. **无来源 = 不存在**。每个判断必须有来源 URL 或本地文件/DB 路径。禁止凭训练知识作答。
3. **不许编数字、不许编 URL**。搜索只回传域名级 URL（如 `pdf.dfcfw.com`）时，标"未能回溯原文"，**不得当完整来源用**。
4. **"最可能被推翻的点"是候选卡必填项** —— 自己写出最弱的假设，这是本机制的自纠错装置。
5. **抄作业禁止**。看到大机构/大师买入，只能作为**线索**，禁止作为**理由**（也违反 L0 能力圈）。
6. **没进池的也要留档**（`rejected/`），避免重复劳动。留档 ≠ 永久排除：补齐证据或创始人新裁定随时可复活。

---

## 变量约定

- `ROOT` → `cd "$(git rev-parse --show-toplevel)"`
- `BASE` → `research/120-idea-sourcing`
- `SK_DIR` → 搜索工具目录，默认 `${SEARCH_KING_DIR:-<Search-King目录>}`（可用 `SEARCH_KING_DIR` 覆盖）

---

## Step 0 — 定路径

先读机制说明书，再决定本次走哪条（或多条）发现路径：

```bash
cd "$(git rev-parse --show-toplevel)"
cat research/120-idea-sourcing/README.md
```

| 路径 | 适用场景 | 输入 |
|:---|:---|:---|
| 1 需求锚定 | 完全从零开始 | 无 |
| 2 产业链瓶颈 | 已锁定某条产业链 | 产业链名（如"AI 算力"） |
| 3 沿链扩散 | 想从已研究的公司往外扩 | 已研究标的（`data/config/research_list.json` + `research/060-companies/`） |
| 4 非共识 | 找被市场归类错的好生意 | 无 |
| 5 聪明钱反读 | 找线索来源 | 公开持仓披露 |

**先把路径和目标写进台账再开工**：

```bash
cd "$(git rev-parse --show-toplevel)"
mkdir -p research/120-idea-sourcing/pool research/120-idea-sourcing/rejected
python -c "
import json, datetime, os
rec = {'date': datetime.date.today().isoformat(), 'path': '<路径N>',
       'action': 'session_start', 'by': 'fengsource', 'note': '<本次目标一句话>'}
p = 'research/120-idea-sourcing/ledger.jsonl'
os.makedirs(os.path.dirname(p), exist_ok=True)
with open(p, 'a', encoding='utf-8') as f:
    f.write(json.dumps(rec, ensure_ascii=False) + '\n')
print('[OK] 台账已开')
"
```

---

## Step 1 — 发现（走选中的路径）

按机制说明书 §3 的执行细节做。每条路径共同的纪律：

- **先有线索 → 先查证 → 再立卡**。禁止"想到一个名字就写进候选池"。
- 搜索命令：
  ```bash
  python "$SK_DIR/scraper.py" --search "关键词" --limit 5
  python "$SK_DIR/scraper.py" --read <URL>          # 取正文
  ```
  失败换 `--backend cloak`，再失败标"未能联网，置信度降级"。
- **多语言搜索**：目标市场的语言必须搜（韩股用韩文、日股用日文、A/H 股中英都搜）。英文偏好是本机制明令杜绝的偏见。
- 沿链扩散（路径 3）先读已研究标的：
  ```bash
  cd "$(git rev-parse --show-toplevel)"
  python -c "
  import json,io
  d=json.load(io.open('data/config/research_list.json',encoding='utf-8'))
  items = d if isinstance(d,list) else d.get('items',d.get('companies',[]))
  for it in items: print(it.get('ticker'), it.get('name'), it.get('status'))
  "
  ```
- 聪明钱反读（路径 5）：
  ```bash
  cd "$(git rev-parse --show-toplevel)"
  python tools/fengsec.py ownership <TICKER> 2>&1 | head -40
  ```
  **软柿子公式（DK 逆向判据，2026-09-30 接入；knowledge/奇衡思想总纲.md §5）**：路径 5 候选进闸门前必须逐条核对，三条全中才进——
  ① **跌幅足够**：距 52 周高点回撤 ≥40%（市场先生压价收货）；
  ② **拐点证据**：基本面出现可指认的改善证据（订单/毛利率/现金流/政策，≥1 条带 URL）；
  ③ **共识仍空**：主流评级/舆论仍以看空或冷落为主（买分歧——有分歧说明行情还在展开）。
  三缺一 → 记 rejected 并写明缺哪条；中二条 → 放观察池（watching）不进闸门。

**产出**：候选线索清单（未验证），每条写明"是从哪条路径、什么线索发现的"。

---

## Step 2 — 过闸门（顺序不可换）

### 闸门 0 — 证据闸（硬性，无豁免）

凑齐 **≥3 条带 URL 的客观事实**：① 主营与收入结构 ② 竞争格局 ③ 定价权证据。
**达不到 3 条 → 暂缓进池**，写 `rejected/<TICKER>.md` 标"证据不足"（补齐即复活）。**暂缓不是否决**——闸门不排除任何公司（2026-09-20 创始人裁定）。

### 闸门 1 — 周期标记闸

> 2026-09-20 创始人裁定：**闸门只能标记与排序，不能排除任何公司**。「周期性公司如果现在在周期底部是可以研究的」——命中判据 = 打周期属性标记，不构成淘汰。

逐条判（判据定义见说明书 §4）：

```
A. 价格接受者还是价格制定者？
B. 近 10 年毛利率极差与标准差（>15pp 且与商品价格同向 → 强周期）
C. 谷底年份赚钱吗？ROE 正吗？
D. 成本没涨时提过价并保住份额吗？
```

- 本地库能算的部分优先用本地数据（不许心算）：
  ```bash
  cd "$(git rev-parse --show-toplevel)"
  python tools/fengdata.py <TICKER> --financials 2>&1 | head -60
  python tools/fengdata.py <TICKER> --sina-financials 2>&1 | head -60   # A 股
  ```
- **标记规则**：命中条数 = 周期强度标记（0 条非周期 / 1 条疑似 / ≥2 条强周期）。**无论命中多少，一律进池参与排序**——是否研究、何时研究由七层与创始人综合判断定。
- **强周期标记者的七层第一题**：当前周期位置——底部/底部区域 → 正常研究；景气高位 → 挂起等回落。
- **"周期之上有结构"论证**：确有周期性但存在结构性壁垒（如存储三巨头 HBM 寡头）→ 照常进池，七层必须单独立"周期之上"的论证说明壁垒如何穿越周期。判不清就标 BORDERLINE 交创始人。

### 闸门 2 — 护城河闸

必须命中 ≥1 条**且有证据**：品牌溢价 / 转换成本 / 网络效应 / 规模成本优势 / 牌照特许 / 技术代差。

**伪护城河（明确不算，本次分级反复出现）**：
- "渠道规模大" ≠ 护城河
- "公司自述市占率第一"（无第三方 = 无来源）
- "成本领先"但产品同质（只是成本壁垒，不排他）
- "行业第一但份额仅 5%"（行业极度分散本身说明无壁垒）

### 闸门 3 — 去劣闸

通过前两闸**才**跑：

```bash
cd "$(git rev-parse --show-toplevel)" && Skill("fengscreen")
```

---

## Step 3 — 立候选卡

写入 `research/120-idea-sourcing/pool/<TICKER>.md`，格式**照机制说明书 §5**，字段固定、缺项留空不编。
**「最可能被推翻的点」必填。**

台账追加：

```bash
cd "$(git rev-parse --show-toplevel)"
python -c "
import json, datetime
rec = {'date': datetime.date.today().isoformat(), 'ticker': '<TICKER>', 'path': '<路径N>',
       'action': 'admitted', 'by': 'fengsource', 'note': '<闸门结论 + 护城河类型>'}
with open('research/120-idea-sourcing/ledger.jsonl','a',encoding='utf-8') as f:
    f.write(json.dumps(rec, ensure_ascii=False)+'\n')
"
```

---

## Step 4 — 登记与排队

通过闸门的标的写 `data/config/research_list.json`（**只写"研究谁"，禁止写仓位/成本等交易字段**），`status` 取 `candidate`（可买候选）或 `watching`（观察）。

> `status` 合法枚举（改别的值会被清单脚本当脏数据）：`researching` 在研 / `candidate` 可买候选 / `watching` 观察 / `parked` 已停放（含七层前被否） / `holding` 已持有。**没有 `observing`**。

```bash
cd "$(git rev-parse --show-toplevel)"
python -c "
import json, io, datetime
p='data/config/research_list.json'
d=json.load(io.open(p,encoding='utf-8'))
items = d if isinstance(d,list) else d.get('items', d.get('companies'))
new={'ticker':'<TICKER>','name':'<中文名>','status':'candidate',
     'note':'fengsource 路径N 发现，闸门0/1/2 通过（<护城河类型>）','added':datetime.date.today().isoformat()}
have={i.get('ticker') for i in items}
if new['ticker'] in have:
    print('[SKIP] 已在清单:', new['ticker'])
else:
    items.append(new)
    json.dump(d, io.open(p,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
    print('[OK] 已登记:', new['ticker'])
"
```

然后**向创始人汇报并等排队**，不要自己直接开跑七层（七层很贵，一次两只，见 §节奏）。

---

## Step 5 — 淘汰也要留档

未通过的写 `research/120-idea-sourcing/rejected/<TICKER>.md`，含：
- 卡在哪个闸门、判据是什么、来源是什么
- **最没底气的地方**（哪一条是"没搜到反证"而不是"搜到了反证"）
- 复活条件（拿到什么证据就该翻案）

台账记 `action: rejected`。

---

## 节奏与输出

- **一次最多两只**进入七层（独立失败域，一只一个子代理）。发现阶段可以宽，分析阶段要窄。
- **汇报格式**：发现路径 → 线索数 → 过闸门情况（进了几只/否掉几只/各为什么）→ 候选卡路径 → 建议排队的顺序与理由。
- 发现阶段的产出**不是**投资建议，只是"值得看"的线索，最终判断一律由 `/fenginvest` 七层给出。

---

## 已知数据通道约束（会直接影响执行）

| 市场 | 行情通道 | 注意 |
|:---|:---|:---|
| A 股 | `fengdata.py` / 本地库 | 年线口径 = **MA250**，MA200 不得冒充年线 |
| 港股 | `fengdata.py` | — |
| 美股 | `fengdata.py`（腾讯源）+ `fengsec.py`（SEC 一手） | 美股优先 EDGAR 原文，二手源只降级用 |
| 韩股 | ⚠️ **yfinance `.KS` 已死**（实测 `possibly delisted; no price data found`）→ 走 `python tools/fengstockintl.py fetch <TICKER> --keep-data`（naver 源，3000 根 ≈ 12 年） | naver 复权口径**未定**，标 `unverified(疑似拆股复权)`，不许当复权价直接用 |
| 日股 | `fengstockintl.py`（`jp7203` 格式） | — |

**搜索通道退化**：`Search-King` 对相当一部分结果只回传域名级 URL；searx 多引擎超时，Bing 回退也可能空。拿不到原文必须标"未能回溯原文"。

---

## 与现有 skill 的边界

| Skill | 职责 | 与本 skill 的关系 |
|:---|:---|:---|
| `fengsource`（本 skill） | **找**标的 | 上游 |
| `fengscreen` | 去劣（7 硬指标） | 本 skill 的**闸门 3** |
| `fengbatch` | 给定名单的批量执行 | **降级**为执行器，不再是发现入口 |
| `fenginvest` | 单只七层深度分析 | 下游 |
