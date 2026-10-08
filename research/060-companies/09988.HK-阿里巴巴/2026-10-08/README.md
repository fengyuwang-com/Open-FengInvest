> ⚠️ **本文件是影子演示数据**（AGENTS.md §一.3 影子替代原则）：真实持仓为腾讯 0700.HK，本文件用阿里巴巴 09988.HK 虚构替代，数字全为编造。非投资建议。

# 影子七层分析（演示）

本目录是**影子替代**的示例：真实个股七层分析（`research/060-companies/` 真实内容）不入库，
此处用 09988.HK 阿里巴巴的虚构走法占位，让开源版能看出七层产物长什么样。

## 状态机八层顺序

`01-capability → 02-market → 03-discipline → (04-quantitative ∥ 05-qualitative) → 06-collision → 07-report → 08-portfolio`

每层产物必须由对应工具产生（L1→fengrule.py / L2b→fengquant.py / M→fengdata.py），AI 不得冒充。

## 本目录当前只有首层示例

`01-capability.md` —— L0 能力圈三问判定（懂 / 半懂 / 不懂）。完整七层需要真实数据源，
开源者 clone 后自行取数跑出其余各层。
