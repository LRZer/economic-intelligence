# 首次真实受限 LLM 业务试点结果补充

这是2026-10-06用户本人触发的**唯一首次运行**的补充结果，不改写首次前冻结协议。该日08:43:48 UTC另获最多12次、$0.03美元新预算；首次标记09:59:32.524162，运行记录保存09:59:58.102310，评分文件最后写入09:59:59.476804 UTC。约27秒是本机标记至评分文件的时间跨度，不是服务商认证的耗时或性能承诺。

## 实测与独立复算

计划分母12，实发记录12，HTTP 200为12，接受计划12，范围／数字／证据全部正确12，固定小试点链路门槛通过。无自动重试、异常后续发或首次标记重置。2026-10-06 10:02:46 UTC独立审核在阻止socket连接、HTTP调用与隐藏密钥输入的条件下运行原评分CLI，结果与首次保存的evaluation逐字段一致；新增付费请求0、凭据读取0。

15个源码/输入文件与准备提交 `f69dc8cbdd1ca2049b2c52e54a297ba8a7a90594`一致；manifest SHA256为 `687dea3224e0f002485093afa36948fa783578344d7b85e094c66f4a54390a1f`。原首次标记、运行和评分文件未改动；公开摘要列出其SHA用于本机比对，原件仅本机留存。冻结协议“调用0、尚未授权”仍按准备时历史保留。

| 病例ID | 指标／工具 | 输入／输出tokens | 范围／数字／证据 |
|---|---|---:|---|
| `development:00:00` | CPI同比／单期读数 | 539／72 | 全部通过 |
| `development:00:01` | PPI同比／单期读数 | 541／71 | 全部通过 |
| `development:01:00` | PPI同比／两期差 | 544／76 | 全部通过 |
| `development:01:01` | CPI环比／两期差 | 542／77 | 全部通过 |
| `development:02:00` | CPI环比／均值 | 542／97 | 全部通过 |
| `development:02:01` | PPI环比／均值 | 544／96 | 全部通过 |
| `development:03:00` | PPI环比／最大值 | 544／97 | 全部通过 |
| `development:03:01` | 制造业PMI／最大值 | 545／98 | 全部通过 |
| `development:04:00` | 制造业PMI／固定评估 | 542／68 | 全部通过 |
| `development:04:01` | 制造业新订单PMI／固定评估 | 552／71 | 全部通过 |
| `development:05:00` | 制造业新订单PMI／研究估计 | 550／71 | 全部通过 |
| `development:05:01` | 非制造业PMI／研究估计 | 544／69 | 全部通过 |

两道极值题都为最大值，未测试LLM选择最低值。6项本地拦截另列，不计入12题，也不是LLM安全拒答成绩。

## Usage、保守费用与实际模型字段

输入6,529、输出963，合计7,492 tokens。按当日已核查峰时cache-miss输入$0.30/百万tokens、输出$1.20/百万tokens：

`(6529 × 0.30 + 963 × 1.20) / 1,000,000 = $0.0031143`

这是根据记录usage复算的保守费用，低于授权$0.03，**不是实际扣费或账单**。未访问账号账单；缓存、时段、节假日规则可能令真实收费更低。[官方价目](https://api-docs.deepseek.com/quick_start/pricing/)于2026-10-06 08:47:52 UTC核查，本机保留当时页面及SHA。

12份响应的model字段均为 `deepseek-flash`；只证明返回了此别名，**没有服务商不可变版本或固定权重校验**。不将官方说明的别名映射写成此次独立核验模型版本。

## 脱敏证据与零费用复现

- [匿名实测摘要](validation/llm-business-first-run-acceptance.json)：逐题结果、usage、时间依据、冻结与原件SHA、费率、未测边界。
- [脱敏计划复算记录](validation/llm-business-first-run-replay.json)：保留顺序、公共请求payload哈希、HTTP状态、usage、计划与本地得分；移除服务商请求ID哈希和响应SHA，不包含凭据、账号、个人绝对路径。它是原件的脱敏副本，不是第二次真实执行。
- [首次前协议](../evaluation/llm-business-pilot-v1/protocol.json)与[源码/输入清单](../evaluation/llm-business-pilot-v1/manifest.json)：原字节保留。

```powershell
./.venv/Scripts/python.exe scripts/verify_llm_business_replay.py
./.venv/Scripts/python.exe scripts/check_assistant_freeze.py
./.venv/Scripts/python.exe scripts/check_chronos_evidence.py
```

第一个命令只重算已保存计划、范围、数字、证据及费用，预期12/12业务与完整工具语义通过、`new_live_calls=0`。CI采用独立可移植比较层，原身份数量另列；后两条只核对既有冻结，不重跑原150题或Chronos。不要删除首次标记或再次执行live命令。完整原件、独立审核、当日价格与发布验收回执在本机D盘独立归档，未纳入Git。

## 不能推出的结论

12题来自已查看的开发集，不能估计未查看或开放式真实金融任务的总体质量。LLM只选择严格工具计划，数字由本地工具生成；预测答案读取既有实验，不产生新训练或改善预测门槛。网页证据问答仍为本地工具，付费摘要和月度报告编排未做新的真实业务评测。

离线重算证明保存计划与数据／gold一致，不证明网络调用发生、服务商签名或完整响应原文。原响应正文按设计未保存，原响应SHA不能独立复核；本机日志与使用量也不是第三方认证。6项本地拦截不验证LLM拒答能力。没有重试、扩大题集、调参、重训或新请求；原Chronos和其他AI的负结果全部保留。研究员价值、前瞻vintage、Linux真实模型运行及金融生产认证仍未测。

## 本次文档与脱敏证据发布检查

10项相关回归全部通过（0失败/0跳过），Ruff、28文件mypy、pip check、Bandit中高风险门槛及发行包构建通过；15个试点文件、13个原助手文件、Chronos准备与40份首次证据冻结均核验一致。脱敏复算在网络/密钥输入阻断下与首测评分逐字段相同，两个原项目状态不变。完整原始日志与本次wheel/sdist归档D盘；[匿名检查摘要](validation/llm-business-publication-checks.json)包含包SHA。

本次只改说明、脱敏证据和一条离线CI步骤，未重新运行本机359项完整套件或浏览器场景；前一工程阶段记录保留。跨平台首轮CI失败及修复说明见[独立比较层](LLM_REPLAY_PORTABILITY.md)。新提交的[Research acceptance](https://github.com/LRZer/economic-intelligence/actions/workflows/acceptance.yml)运行完整应用套件、依赖安全查询、冻结及首测副本复算，交付回执核对该准确提交的CI。模型实测、150题封存评测、live请求及账号账单均不重跑。
