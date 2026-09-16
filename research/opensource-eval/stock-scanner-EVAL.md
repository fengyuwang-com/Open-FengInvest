# stock-scanner Evaluation

> Repo: https://github.com/DR-lin-eng/stock-scanner（原版，1,129 stars，MIT）
> 调研日期: 2026-09-11（网络调研，未 clone）
> 判定: **用不上（边缘可借鉴）——不进 fengscreen/fengbatch，不集成**

## 先澄清"哪个 stock-scanner"

GitHub 同名项目交叉确认，最活跃正身 = **DR-lin-eng/stock-scanner**（1,129 stars / 435 forks，Python，MIT，2026-03-02 最后 push，学生式间歇维护）。生态：

| 仓库 | 定位 |
|---|---|
| DR-lin-eng/stock-scanner | 原版，AI 增强 A 股单股分析系统（Flask） |
| lanzhihong6/stock-scanner | Vue3+Docker 二改版（672 stars，**无 License，不可复制代码**） |
| wbsu2003/stock-scanner-mcp | 系项目的 FastAPI-MCP 封装（244 stars） |

## 是什么

**不是量化筛选器，是"单只股票 AI 深度分析器"**：输入一只 A 股代码 → 产出综合报告：

- 25 项财务指标（ROE/毛利率/流动比率/周转率/增速/PE/PB/PEG…）
- 技术面打分（MA 多周期、MACD、RSI、布林带、量价，0-100 综合分）
- 新闻/公告/研报情绪分析（100+ 条新闻）喂 LLM（GPT-4/Claude/智谱/DeepSeek 主备切换、SSE 流式）给买卖建议；**AI 不可用时降级为规则打分**
- 批量并发、PDF 报告下载、密码鉴权、Docker 部署；**无回测、无因子验证、无组合层**
- 数据源 akshare（A 股为主；3.0 版自述支持港美股但"受限缓慢优化中"，成熟度低）

## FengInvest 增益评估

- **与 fengscreen/fengbatch 零互补**：它没有全市场扫描/筛选能力——25 项指标是单股取数，不是多因子流水线；fengscreen（7 硬指标+3 豁免）、fengquant、fengtechnicals 全部更强且有 PIT/验证纪律。拿它的筛选思路 = 降级。
- **与 fenginvest 七层重叠且我们更严**：它"AI 直接给买卖建议"恰与我们"AI 不得冒充工具结果 + 来源铁律 + 状态机强制"相悖。
- **唯一可借鉴点**：L2a 定性层的**新闻情绪聚合**（100+ 条新闻/公告/研报打分喂 LLM）+ **AI 失效降级规则打分**的 fallback 设计——留作 L2a 新闻情绪自动化演进的参考思路；代码本身（Flask 单股分析器）不可直接集成。

## 未验证项

demo 站（stockscanner.linzefeng.top）实际可用性未测；港美股 3.0 覆盖深度仅基于 README 自述。

## 来源

- api.github.com/repos/DR-lin-eng/stock-scanner（及 /readme、/contents）
- api.github.com/repos/lanzhihong6/stock-scanner
- Search King 检索结果（github.com/m-turnergane/stock-screener 等均为小项目，不构成增益）
