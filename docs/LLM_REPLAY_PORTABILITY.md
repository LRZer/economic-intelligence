# 首测复算的跨平台差异与独立语义核验

首测Windows原件与独立复算均12/12通过。提交 `2451e33f7f240edd176b91a948ca556477d7f255` 的[首次Linux CI](https://github.com/LRZer/economic-intelligence/actions/runs/37449892804)在冻结评分器完整字典比较处失败；当次355项、10子测试通过，4项Windows专用检查跳过，后续步骤因失败未运行。这个失败记录保留，不能用后来的新比较层回填为原评分器通过。

## 精确定位

独立诊断逐题显示：12题的范围、业务数字、证据ID与评分布尔值一致；只有4道模型题的 `answer_id`不同。原完整工具输出哈希还包含全部固定模型回测、区间、贡献值等派生浮点数。

两端相同NumPy2.4.6、SciPy1.17.1、scikit-learn1.9.1、pandas2.3.3、requests2.34.2；本机Windows/CPython3.11.7，Linux/CPython3.11.16。进一步检查发现**16个派生浮点叶子变化**，最大绝对差 `7.105427357601002e-15`，最多43 ULP；涉及个别Ridge回测值、RMSE、配对区间端点及预测贡献。全部业务数字逐位相同；非数值决策、默认基线、时间边界、来源、结构与类型均一致。

诊断只向GitHub日志输出字段路径、类型及SHA，完整121KB本地参照没有上传，也没有输出完整工具答案。参照在本机由冻结代码/数据离线重建，12个完整payload的SHA精确匹配首次记录 `answer_id`；对远端差异浮点查找邻值，仅接受SHA完全匹配的候选，重建整个Linuxpayload的根SHA也匹配。完整值与私有诊断留D盘；[脱敏字段摘要](validation/llm-replay-portability-diagnosis.json)保留路径、类型及差值，不包含完整模型输出。

## 单独定义的可移植检查

冻结评分器、15个源码/输入、首测3原件及公开首测副本均不改写。新层 `llm_replay_verify.py` 是**独立工程比较层**，原逐位身份与完整工具语义分开报告。

1. 固定核对原首测副本SHA、15文件manifest、12题顺序/分母、HTTP200、别名、实际usage、原费率及上限；预算仍用Decimal，既有授权不延续。
2. 范围与证据ID精确一致；原分数与重算分数均须支持原gold。业务数字沿用冻结 `score_plan` 的 `rel_tol=abs_tol=1e-9`；整数计数、布尔值和数值类型精确检查，不接受NaN/Infinity。
3. 每份完整工具输出使用[小型语义指纹契约](validation/llm-business-portable-semantics.json)。契约在首个可移植验收前生成，以本机原完整payload哈希匹配首次指纹为锚；只发布12组原身份与语义SHA，不上传完整参照。
4. 只对源码中明确列出的模型派生浮点路径使用 `Decimal.from_float`、half-even、`1e-9`网格；同格原数距离严格小于 `1e-9`。这比业务相对容差更严格，越过网格边界时即使很接近也会拒绝。其他浮点保留精确IEEE十六进制；官方观测、数据基线值、检索分数、类型、来源、日期、方法、研究门槛、文本和完整结构均精确进入SHA。
5. 原 `answer_id`不覆盖，新输出也核对自身完整payload哈希；报告原身份匹配数量。Linux应保留**8/12逐位相同、原严格身份门槛false**，同时独立检查12/12业务及完整工具语义。不能将它写成冻结评分器在Linux逐位通过。

新层规则不按模型质量或业务成绩选优；1e-9来源于原冻结数值规则，不为16项差异扩大。语义指纹SHA不是数字签名，不证明服务商响应或真实网络执行。

## 负例与复现

工程负例覆盖：派生数值越界、官方观察微小篡改、基线/门槛/训练截止改动、范围/证据/计数类型/检索分数/额外字段/指纹篡改、原分数数字与引用改动、整数伪装布尔、完整性/顺序/预算/容差配置改动、重复JSON键与非有限数。即使重新计算篡改内容的普通SHA，语义契约及首次锚仍拒绝；这些合成负例不计作LLM业务或安全成绩。

```powershell
# 跨平台：完整工具语义与原身份分别报告，零网络/零凭据/零写入原件。
./.venv/Scripts/python.exe scripts/verify_llm_business_replay.py
# 原Windows首测环境：保留原冻结严格评分CLI，不删除标记或改分数。
./.venv/Scripts/python.exe scripts/evaluate_llm_business_pilot.py docs/validation/llm-business-first-run-replay.json
# 仅诊断；打印字段路径/类型/SHA，不打印完整工具输出。
./.venv/Scripts/python.exe scripts/diagnose_llm_business_replay.py docs/validation/llm-business-first-run-replay.json --tool-fingerprints
./.venv/Scripts/python.exe -m pytest -q tests/test_llm_replay_verify.py tests/test_llm_replay.py tests/test_llm_business.py
```

CI使用明确命名的完整语义检查，失败仍阻断构建；原严格CLI继续保留用于原环境身份复算。前一失败、诊断日志、私有完整参照和最终准确提交CI回执各自保留。没有重跑真实试点、删除首次标记、读取密钥、扩大LLM题集、重训Chronos或改变研究结论。

## 本机最终检查

本机全量 **398项测试＋10子测试**通过，0失败、0跳过，pytest报告302.47秒；49项相关回归含35项新保护/集成检查。Ruff、32文件mypy、Node、pip check通过；Bandit中高风险0、219项LOW保留。91项可查询应用依赖和44项CPU锁依赖无当次已知漏洞；1个本地未注册包明确跳过。原Windows严格身份12/12与新完整语义12/12均在网络/密钥输入阻断下实跑；原项目、15冻结文件及3首次原件一致。

[脱敏完整检查摘要](validation/llm-replay-portability-validation.json)保留检查范围与未运行项，完整日志和发行包在D盘。最终Linux真实比较层、全套冻结、模型锁安全及构建须由准确提交CI核对，不能借用原提交或诊断工作流的绿灯。
