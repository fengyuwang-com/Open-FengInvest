# FengInvest — 数据管理规范（data/market_data.db）

> 董事长两条硬需求（2026-08-23 定稿，适用于本库一切批量写入与对外同步）：
>
> 1. **任何写入必须可回滚** —— 绝不允许乱写毁库
> 2. **多 GB 库只传增量** —— 首次全量上传后，每次只传改动量

## 一、机制：SQLite session 扩展（官方增量 + 官方撤销）

写入前对目标表开 session 盯守 → 写完提取 **changeset**（紧凑二进制，只含本批真正改动的行）→ 上传百度网盘。要撤销某批 → `Changeset.invert(cs)` 得到"撤销包"再 apply，精确还原该批、不动其他数据。

2026-08-24 起该机制由 `tools/fengdb.py` 统一封装：业务脚本一律经 `safe_batch()` 写库，不直接操作 apsw。

```
批量写入 ──► Session.attach(表) 记录 ──► cs_<日期>_<批次>.bin ──► BaiduPCS-Go ──► 百度网盘
                                        │
                                        └─ invert() ──► apply() = 精确撤销该批
整库回滚 = 基线快照 ⊕ 按序重放 changeset
```

前置条件（已验证满足）：被盯表须有声明 PRIMARY KEY（`cn_financials` 复合键 stkcd+accper+typrep ✅ / `daily_data` id ✅）；不支持虚拟表。

## 二、实测数字（2026-08-23，apsw 3.53.4）

| 项 | 值 |
|:---|:---|
| 撤销精度 | 烟雾测试坏 UPDATE+误删 → invert 后逐字节还原 PASS |
| 单行 changeset | ≈ 749 B（121 行 × 24 列实批 = 88.6 KB，提取 0.017s）|
| 常规一批（50 只×20期≈1000行）| ≈ 0.7 MB |
| 全市场一次性回填（5828只×20期）| ≈ 83 MB（仅一次）|
| 回滚演练（临时副本，2026-08-24） | 55 ops → cs 3,516 B → undo 后全表 sha256 与基线一致 PASS |
| 变更集存量 | `data/changesets/` 共 142 个可回滚（2026-08-24 回填总攻后）|

## 三、操作铁律

1. **批量写库一律走 `tools/fengdb.py safe_batch`**（自动盯表+提取变更集，禁止绕过它的裸批量写）；写前先 `fengdb snapshot <label>` 落文件快照（VACUUM INTO，WAL 安全），库内 bak 表（`<表>_bak_<日期>`）与分批事务按需叠加。
2. **每批一个 changeset 文件**：`safe_batch` 自动命名 `cs_<YYYYMMDD>_<HHMMSS>_<label>.bin` 并追加 `data/changesets/index.jsonl` 索引；单批反悔即 `fengdb undo <cs>`。
3. **精确撤销走 invert**：单批反悔 = 该批 changeset invert+apply；不重放历史、不动其他数据。整库回退才用 快照+重放。
4. **密钥不入仓**：API key 存仓库外 `%APPDATA%\<服务>\credentials.env`（现例：hithink-finance）。快照/bak/cs 文件均属 data 域，gitignored 不外发。
5. **时区**：fuyao 等毫秒时间戳按北京时间（UTC+8）解析，否则 accper 早一天产生重复期。
6. **工具崩溃修依赖，不手工填坑**（同全局铁律）。
7. **DDL 不入变更集**（session 扩展固有边界）：建表/建索引必须在 `safe_batch` 之外完成。

## 四、工具链现状

| 组件 | 位置 | 状态 |
|:-----|:-----|:-----|
| apsw（session 绑定） | Python 包（清华镜像 cp314 wheel） | ✅ 3.53.4 已装 |
| fengdb.py（统一安全写库入口） | `tools/fengdb.py` | ✅ safe_batch/undo/snapshot/status；临时副本回滚演练 PASS |
| fengfuyao.py（A股财报回填） | `tools/fengfuyao.py`（原 `~/fuyao_backfill.py` 转正，写库改走 safe_batch） | ✅ 全市场 5,828 只完成：done 5,129 + failed 699（全部 code=1002 退市/无码）；已知缺陷见 todo S 条 |
| fengstockdb.py（日线构建） | 改造完成 | ✅ download_one 只取数不落库；build_market 统一走 safe_batch；HK 走新浪源、TW 走 FinMind、baostock 串行 |
| fengstockintl.py（国际四源补数） | `tools/fengstockintl.py` | ✅ probe/fetch/fill；默认 `--dry-run`，真写需 `FENG_INTL_FILL_CONFIRM=YES` 且走 safe_batch |
| 本地双份备份+定时复制（替代 BaiduPCS-Go 直连方案） | tools/fengbackup.py（待建） | ⏳ todo K |
| 安全网快照 | `data/market_data.db.snap_*` 系列 + 库内 `cn_financials_bak_20260823` | ✅ 在位 |

接口备忘（apsw）：`sess = apsw.Session(con,"main"); sess.attach("cn_financials")`; `cs = sess.changeset()`（直接返回 bytes）; `apsw.Changeset.apply(apsw.Changeset.invert(cs), con)`。

## 五、安全写入与变更集流程（2026-08-24 落地）

### fengdb.py 用法

```python
from fengdb import safe_batch

with safe_batch(tables=["cn_financials"], label="fuyao_backfill"):
    ...  # 批量 UPSERT；上下文退出时自动提取 changeset 落盘
```

```
python tools/fengdb.py undo <cs文件>     # invert+apply 精确撤销该批，不动其他数据
python tools/fengdb.py snapshot <label>  # VACUUM INTO 只读导出整库快照（WAL 模式下安全）
python tools/fengdb.py status            # 变更集与索引一览
```

### 各管线接入方式

| 管线 | 写库通道 | 进度/断点机制 |
|:-----|:---------|:--------------|
| fengfuyao.py 财报回填 | safe_batch（每批一个 cs） | `data/cache/fuyao_progress.json` 断点续传；backfill 支持 `--tickers/--universe --limit --batch-size --force` |
| fengstockdb.py 日线构建 | safe_batch（update_log 与数据同 cs，可整体回滚） | update_log 表 |
| fengstockintl.py 国际补数 | safe_batch；默认 dry-run，真写需 `FENG_INTL_FILL_CONFIRM=YES` | probe/fetch/fill 三段分离 |

已知缺陷：fengfuyao `flush_batch` 整批全败时不落盘进度文件（todo S 条；已用锚点法 workaround 收尾，修复方向 = 存在 failed 记录也强制写进度）。

## 六、数据源清单（2026-08-24）

| 数据源 | 覆盖 | 接入工具 | 备注 |
|:-------|:-----|:---------|:-----|
| CSMAR 冷数据 | A股全历史三表（1990–2025Q1，含退市） | feng_import_csmar.py | 基础底座 |
| 同花顺 fuyao API | A股财报增量：34 原始科目 → 24 映射字段入 cn_financials | fengfuyao.py | 免费额度；key 存仓库外 `%APPDATA%\hithink-finance\credentials.env`；thscode 自动补交易所后缀（6→SH、0/3→SZ、4/8/92→BJ） |
| a-stock-data | A股 12 端点：quote 实时估值 / valuation-hist / ipo-date / sw-industry 行业变迁(as-of 消前视) / adj-factor(qfq/hfq) / macro 社融+PMI / lhb / lhb-market / limit-pool / unlock / margin / moneyflow | fengastock.py | 按需取用补缺口，不做批量回填、不入库（入库统一走 fengdb）；东财系端点必走内置 em_get() 限流防封 |
| 国际四源 | 海外个股/指数日线补数 | fengstockintl.py | yfinance 主源；腾讯(US)/东财(JP/KR/UK/指数)/naver(KR) 备源；stooq 已死弃用 |
| 腾讯/Yahoo/AKShare/baostock/yfinance | 实时行情与日线多源 | fengdata / fengstockdb 等 | HK 日线走新浪源 stock_hk_daily（东财 WAF 掐 Python TLS 指纹）；TW 走 FinMind；baostock 必须 workers=1 串行 |

## 七、待办

已完成：J（fengdb 新建 + fengfuyao 转正）/ K2（invert 回滚演练 PASS）/ L（全市场财报回填）。进行中见 [docs/todo.md](todo.md)：K（本地双备份+定时复制）、M（衍生列 ETL 重算）、Q（16 市场 unadj_close 补齐）、S（flush_batch 缺陷修复）。
