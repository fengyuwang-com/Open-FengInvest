# 全站"有声失败"审计报告

> 2026-09-13 · 董事长立规："失败肯定要有声音……我很怕一再降级如果降级没说清楚就麻烦了。修复只加不减，不许砍功能，退役须显式标废。"
> 本报告 = 该立规的全站落地核查。扫描面：`tools/` 77 个 py + `fengweb/src` 9 个 ts/js，两遍脚本分级 + 重点链逐条人工复验（每条结论附 file:line 证据）。

## 一、总览

| 分级 | 数量 | 结论 |
|:-----|:-----|:-----|
| 静默点候选（except pass/return None、空 catch、suppress） | 131 | 脚本粗扫 |
| A 级 · 数据源链上的静默点 | 12+43（含疑漏复检） | 逐条人工定音 |
| ✅ **合规：降级链整体有声** | 9 条核心链 | 见第二节 |
| ⚠️ **真病灶：无声/半无声** | 4 处 | 见第三节，治理方案 |
| ⚪ 良性防御（缓存解析/格式转换/IO 容错） | ~120 | 不处置（非数据降级路径） |

## 二、合规样板链（中间静默是接力，链尾有声——不动）

这些链里 `except → pass/continue/return None` 只是"换下一个源"的接力，**最终输出带 source/live/as_of/_error/failed 标注**，符合"降级须说清楚"：

1. **fengrule 年线四源链**（`_series` tools/fengrule.py:155-167）：local_db→tencent_qfq→akshare_us→yahoo 逐级接力，输出 `series_source`+`series_as_of`（L337-338）；全灭时明示"源=全部失败，按弃权处理"（L316/355）。
2. **fengdata 汇率链**（`_fx_rates` tools/fengdata.py:480-540）：实时成功带 `live:true+source+date`；回退快照带 `live:false+source:"...(fallback)"`；全灭 `_cmd_fx` 直接 exit(1)。
3. **fengdata 持仓价格更新**（`_update_holdings_prices` L436-476）：免费源无价 → 列入 `failed[]` 输出 JSON（"免费源均无价"逐票明示）。
4. **fengmarketdata 指数快照**（`fetch_indices` L112-127）：双源皆空 → `_error:"腾讯/Yahoo 均无该代码快照"`。
5. **fengportfolio check**（L457-477）：输出 `fx:{live,date}` 明示汇率口径。
6. **fengweb 组合汇率三级链**（api.ts:952-963,1014）：`fengfx live → fx_latest.json → holdings meta 快照`，`fx_source` 透传进响应（db3ca0e 修复在位实证）。
7. **fengdata sina 财报缓存回退**（L763）：回退陈旧缓存时在 `warnings` 里追加"已回退本地陈旧缓存（注意数据时效）"——数据消费者可见。
8. **fengindexdb 回填**（L187-193）：备源失败 → `[WARN] {ticker}: 无数据`。
9. **fengastock 估值史**（L920-930）：缓存 miss 静默属正常，取不到数 `raise RuntimeError` 有声。

## 三、真病灶（4 处，按优先级）

### P1 · api.ts:43 — 行情采集器崩溃无声，页面永远 pending
```ts
runner.runTool('fengmarket.py', ['collect']).catch(() => {});
res.json({ _source: 'pending', message: 'Data collection in progress, try again in 30s' });
```
承诺"30 秒后再试"，但采集器若抛异常被空 catch 吞掉——**没人知道它死了、为什么死**，用户反复重试仍 pending。董事长点名的实证样例。
**治理**：catch 内 `console.error('[fengmarket] collect 后台采集失败:', e)` + 模块级 `lastCollectError` 记录；下一次 GET 若 `_source:'pending'` 且存在未失活的 lastCollectError，响应带 `collect_error` 字段让前端可见。（只加日志+透传，不砍任何回退。）

### P2 · fengwatch 基金份额三处 fetch — "失败"与"到底了"混淆
`_fund_http_get`（tools/fengwatch.py:88-96）异常时 `return None` 且捕获的 `e` 未使用；调用方 `if not data/text: break|return []`（L163-165, 229-231, 289-291）——**网络挂了被当成翻页结束**，份额数据静默截断，监控输出看不出缺了哪页。
**治理**：`_fund_http_get` 失败时把 `e` 记入返回值或模块级列表；调用处区分"HTTP 失败退出"与"正常翻页结束"，输出加 `fetch_errors:[...]`。

### P2 · fengportfolio risk/optimize — 汇率口径只在 check 透出
`fx_info()["FX"]`（L285、L511 附近）取数时丢弃 `live/date`；只有 `check` 输出带 `fx:{live,date}`。**用快照汇率算出的 risk 归因结论，读者无从知道汇率不是实时的。**
**治理**：risk/optimize 输出 JSON 同样加 `fx:{live,date}` 字段（对齐 check，一处两行的加法）。

### P3 · i18n.js:23 — 语言包加载失败静默退回内置词表
`load().catch(function(){})`：`/locales/en.json` 拉不到时界面静默变回中文兜底，用户切英文"没反应"无解释。影响小但同属"降级没说清楚"。
**治理**：catch 内 `console.warn('[i18n] locale fetch failed, using built-in dict')`。

（备忘级：fengstockdb `download_yf:397` 失败 return [] 与"无新数据"不可区分——该工具是旧入库链、已被 fengstockintl+探针覆盖，随旧链退役一并处理，不单独立项。）

## 四、制度化（防止新增无声降级）

- **探针已覆盖热链**：fengprobe 每日真跑 9 条核心链（159766+AAPL 冒烟），链死→🔴 exit(1) 上 /mission 看板；链"自报降级"→🟡（如 M 层 index_pe partial 实证）。
- **判据三条件**（本项目"有声"标准，写入本文件即基准）：①降级不隐瞒——输出含 source/live/as_of/_error/failed 任一标注；②声音可读——stderr/日志带异常上下文；③**链尾必须有声**——回退链中间接力可静默，但所有源落空时必须明确标注或 exit(1)。
- 可选提案（待拍板）：fengwebcheck 加静态规则——新增空 `.catch(() => {})` / `except Exception:\s*pass`（无紧邻标注注释）计 warn，病灶增量在 CI 可见。

## 五、结论

全站"一再降级"的主体是**带标注的合规回退**（9 条核心链全部有声，样板即 fengrule._series）；真正的无声点在 **web 端入口 JS 与监控外围工具**，共 4 处，全部适用"修复只加不减"（加日志、加透传、加区分，零砍功能）。治理清单 4 项，动工等董事长点头。
