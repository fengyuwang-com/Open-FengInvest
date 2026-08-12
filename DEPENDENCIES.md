# 依赖总览（DEPENDENCIES.md）

> 目的：**换电脑、换环境不再慌**。本文档回答三个问题：
> 1. 最小化运行需要什么（含一条命令装齐）
> 2. 哪些核心功能**零依赖**、哪些需要第三方库
> 3. 换电脑后如何一键重建环境

---

## 一、核心结论：日常链路已是纯标准库（零依赖）

持仓监控、行情、组合检查这些**日常高频功能**已经改为只用 Python 自带标准库（`urllib` / `json` / `sqlite3` / `http`），**不需要安装任何 pip 库**：

| 核心功能 | 脚本 | 数据源 | 依赖 |
|:---------|:-----|:--------|:-----|
| 持仓监控每日检查 | `fengwatch.py daily` | 腾讯行情 / Yahoo（urllib） | ✅ 零依赖 |
| 个股价/均线 | `fengdata.py` 价格模式 | 腾讯行情 / Yahoo（urllib） | ✅ 零依赖 |
| 组合分域检查 | `fengportfolio.py` | 读仓 JSON + 本地库 | ✅ 零依赖 |
| A股/港股/ETF 实时价 | 钱包行情接口 `qt.gtimg.cn` | urllib | ✅ 零依赖 |
| 美股/指数/汇率 | Yahoo chart API `query1.finance.yahoo.com` | urllib | ✅ 零依赖 |

**验证**：这些脚本在任何一台干净装好 Python 的机器上，直接 `python tools/fengwatch.py daily` 即可运行，不装任何东西。

---

## 二、需要第三方库的次要工具

以下**次要/增强工具**依赖第三方库。它们**不影响**上面的核心链路，仅在对应功能被调用时才需要：

| 库 | 用途 | 使用到的脚本 |
|:---|:-----|:-------------|
| `yfinance` | 美股财务/基本面增强、历史回退 | fengdata（financials 等次要模式）、fengfundamentals、fengportfolio（矩阵）、fengindexdb 系列等 |
| `pandas` | 数据框处理（跟随 yfinance） | fengdbrefine、fengportfolio、fengstockdb 等 |
| `futu-api` | 富途 OpenD 实时行情（需另开 OpenD） | fengdata、fengindexdb_verify、fengmarketdata |
| `akshare` | A股/港股/宏观增强 | fengindexdb_akshare、fill_hk_gaps 等 |
| `numpy` | 数值计算 | 多个工具 |
| `pyyaml` | YAML 配置 | 若干 |
| `scipy` | 统计 | 若干 |
| `cognee` | 知识图谱（可挂） | 独立图谱功能 |
| `playwright` | 浏览器抓取 | 独立爬虫 |

---

## 三、一键安装（换电脑后）

### 3.1 核心 + 次要工具全装（推荐，一条命令）

```bash
# 在项目根目录
pip install -r requirements.txt
```

### 3.2 只跑核心日常功能

核心链路零依赖，**什么都不用装**，直接：
```bash
python tools/fengwatch.py daily        # 持仓监控
python tools/fengportfolio.py check    # 组合检查
```

### 3.3 Web UI（fengweb）

需要 Node.js + npm：
```bash
cd fengweb
npm install
npm run build    # 编译 TypeScript
node dist/index.js   # 或 start-web.sh
```

---

## 四、requirements.txt 内容说明

`requirements.txt` 列出次要工具所需的全部第三方库（含主要传递依赖），版本已固定以保证可复现。**核心零依赖功能不在此列**。

> 注意：`futu-api` 需要额外启动富途 OpenD 客户端（`fengdata` 已自动探测并回退到 urllib/Yahoo，未开 OpenD 也不影响）。
> `numpy` 通常随 pandas 自动装，单独列出以防万一。

---

## 五、规避"换电脑崩"的最佳实践

1. **优先用标准库的 urllib 数据源**（已实现）：任何能跑 Python 的机器都有 urllib，不会缺。
2. **次要工具库用本文件 + requirements 固定版本**：换机器 `pip install -r requirements.txt` 一次性装齐。
3. **不要硬编码库**：代码内 `import yfinance` 只放在函数内（延迟加载），这样核心路径不触发，缺库也不崩主流程。
4. 环境建议：用一个独立 venv 固定 Python 版本，避免系统 Python 升级误伤。

---

*维护：新增第三方库时，请在本文档第 2 节第 5 节补记，并在 `requirements.txt` 固定版本。*
