# 阶段二：证据问答与受限工具实测验收

这次交付可用的中国月度证据问答工作区。它解析问题范围，检索国家统计局来源行，调用六种确定性工具，提供数字、原文链接、计算轨迹和可离线复核的导出。它不是生成式大模型，也不代表整个长期路线完成。

## 实际能力与输入边界

七个既有指标：CPI同比/环比、PPI同比/环比、制造业PMI、新订单PMI、非制造业PMI。当前批准快照包含423条源行；指标、口径、单位、有限数值、有效自然月、重复键及NBS HTTPS出处均检查。国家仅中国；GDP、境外指标、任意外部URL、文件或代码执行不进入此工具。

支持单期/最新读数、两期百分点差、2—24个完整连续自然月的算术均值、最大/最小值及并列月份、当前固定回测/基线比较、下一统计期研究估计。同比读数差不是价格水平增长率；平均读数不是累计指标。缺月不插值。模型回测与预测沿用原固定协议；七项Ridge门槛失败和验证期默认基线结论保持，没有新训练或追分。

因果、盈利/交易判断、历史实时版本、缺数据、范围/口径歧义、越权及过长问题明确拒绝或要求澄清。敏感请求在答案、截图与导出中仅显示已删减提示；不会打开本机凭据文件。页面不提供新的付费入口。

## 首轮封存应用评测

60开发病例（10族）和150封存病例（25个不同族），问题无重复。原始公共经济数据已查看；隔离的是问题表述族与gold，不是预测训练数据。oracle独立从源行计算数值/证据；模型审计gold复用原固定模型结果。工作进程只收到批准数据和问题，审计钩子禁止gold/题库文件、凭据、网络和外部进程访问。

协议在生成/运行前固定；开发初始TF-IDF为54/60，六项差值表述失败，经开发修正至60/60。随后冻结13个实现、数据与协议文件及阈值0.08，唯一首轮封存标记和结果完整保留。没有依据封存结果修改源码、词表、参数或答案，也没有重新跑首轮。

| 首轮指标 | TF-IDF＋显式范围/运算约束 | 关键词路由对照 |
|---|---:|---:|
| 任务正确且有据 | 144/150，96.0% | 102/150，68.0% |
| 应答任务覆盖 | 72/78，92.3% | 42/78，53.8% |
| 已答应答病例数值全部正确 | 72/72，100% | 30/42，71.4% |
| 已答应答病例引用真正支持 | 72/72，100% | 36/42，85.7% |
| 按预定理由拒答/澄清 | 72/72，100% | 72/72，100% |
| 问答调用中位/P95延迟 | 2.290/4.769 ms | 0.296/3.056 ms |

TF-IDF任务正确Wilson95%区间[91.55%,98.15%]；覆盖区间[84.22%,96.43%]；数值/引用/拒答比例区间均[94.93%,100%]。按25个表述族整组抽样2,000次的任务正确描述性区间[88%,100%]。所有预定点估计门槛通过，但区间不能当作真实用户总体保证；延迟是本机单进程工具调用，不含浏览器/服务/API/初始化开销。

六个失败全部属于`sealed-wording-family-10`的“谷值/哪些月并列”表述。助手要求澄清（`ambiguous_period`），未输出数字；这是应答覆盖不足，不能算正确拒答。该表述族保留0/6，所有首次失败问句、答案、路由、gold和逐病例评分公开在本私有仓库中。原型仅有少量能力描述，词法路由会误判；关键词对照也很有限。模型和应用由同一开发者编写，分进程独立oracle不等于独立机构审核。

**程序构造任务、同一固定快照、有限表述族、已知任务模板，不是随机真实用户调查、无污染训练验证、LLM质量评测或生产认证。** 所有封存问题/gold在首轮结束后发布；后续复算仅是已公开审计集重检。

## 工程、界面与安全

- 最终全量pytest：269项＋10 subtests通过，182.34秒；其中31项问答/界面回归。Ruff、mypy 15文件、pip check、JS语法与图表日历/状态测试（Node报告1个文件测试）通过。
- 最终真实Edge浏览器：13场景通过；六工具、因果/越权拒答、口径歧义、重复提问、未提交编辑不改写已完成答复、窄屏下载、离线HTML。实际下载三种文件，每份JSON重建源库并重算验证；1440/390px溢出0、页面错误0、付费API请求0。空/非法数据导航由AppTest覆盖，浏览器截图不是全部用户/设备覆盖。
- 完整Bandit只有两项既有低风险subprocess提示（B404/B603）；中高风险0。依赖审计当次无已知漏洞；不会承诺未来永久安全。默认ENABLE_PAID_AI=0、AUTO_REFRESH=0。
- JSON包含批准源行、数值、依赖、方法和指纹。重写数字后重新算SHA仍不能通过离线工具重算；HTML转义且无脚本，CSV防公式注入。指纹不是数字签名，恶意同步替换源数据不由此防御；跨版本浮点差异需显式核查。
- wheel/sdist、原始数据802文件不变、源项目状态、Git历史扫描和实际commit CI另列最终构建/发布收据；不能以本机测试替代远端验证。

## 验收证据与复现

[冻结协议](ASSISTANT_EVAL_PROTOCOL.md)；[完整首轮结果](validation/assistant-sealed-evaluation.json)；[逐问题、gold、源码冻结与最初开发记录](../evaluation/assistant-v1/)；[浏览器记录](validation/assistant-browser-acceptance.json)；[完整测试XML](validation/assistant-full-tests.xml)。

实际截图：[桌面差值](../assets/screenshots/assistant-difference-desktop.png)、[拒答](../assets/screenshots/assistant-cause-desktop.png)、[390px页面](../assets/screenshots/assistant-mobile.png)、[离线报告](../assets/screenshots/assistant-offline-mobile.png)。下载演示：[HTML](../assets/demo/assistant-cpi/cpi-difference.html)、[JSON](../assets/demo/assistant-cpi/cpi-difference.json)、[CSV](../assets/demo/assistant-cpi/cpi-difference.csv)。

```powershell
# 已发布病例重算，不能再称未触及封存验证。使用新目录，不覆盖首次记录。
New-Item -ItemType Directory reports/assistant-reproduction
Copy-Item evaluation/assistant-v1/manifest.json,evaluation/assistant-v1/source-freeze.json,evaluation/assistant-v1/sealed-questions.json,evaluation/assistant-v1/sealed-gold.json reports/assistant-reproduction
python scripts/evaluate_assistant.py reports/assistant-reproduction --split sealed
python scripts/verify_assistant_report.py assets/demo/assistant-cpi/cpi-difference.json
```

Windows首次实验采用CRLF/LF混合源码，`.gitattributes`对13个冻结文件保留原字节，确保跨平台Git checkout与原SHA一致。请使用requirements.lock.txt的Python3.11环境；延迟不要求一致。

LLM仅有严格计划适配/mock及12项离线试点请求准备，真实调用为0，业务质量未测。[独立运行交接与预算提案](ASSISTANT_LLM_PILOT.md)不构成收费批准，先前10元授权已结束。贸易图及基础模型挑战者继续为后续阶段。
