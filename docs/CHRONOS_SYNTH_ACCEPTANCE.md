# Chronos-2-Synth 固定回顾审计：结果与复现

真实模型审计已执行，84/84 单步预测完整。**未通过预先固定的描述性研究门槛，生产默认参考保持不变。** 模型的七项等权 MASE 为 0.478350，四项基线中最低的固定 Ridge 为 0.570978，但与开发期预选参考的描述性配对区间为 [-0.182745, 0.011344]，上界仍为正。不是盲测、实时版本回测、生产认证或交易信号。本页先记录不可修改的科学结果；工程验收状态由下方验证记录补充。

## 目的与实际功能

检验一个固定时序基础模型在中国官方月度数据上的零样本能力，形成可复核的研究工作流。系统新增“研究与风险分析 → 时序基础模型审计”，提供实际预测曲线、四项强基线、原生分位数带、开发参考、训练边界、年度切片及全量 HTML/JSON/CSV。界面只读已执行结果，不自动下载或加载模型，普通应用环境无 PyTorch 依赖。

## 模型、数据与冻结

- 官方模型：`autogluon/chronos-2-synth`；revision `3607918a9fd027d5c465d8213e46b98e2c041cea`；118,985,888 个参数，CPU float32。模型提供方声明仅用合成数据预训练，**未独立核验训练语料**。没有本地训练或微调。
- 权重：475,963,368 字节的固定 safetensors；SHA-256 `920a3344726a8026c9335d38ae1a2bfa9b7d659c1b8fe0b0af8d5f775863422e`。只加载已验证本地文件，`use_safetensors=True`、`local_files_only=True`、`trust_remote_code=False`；模型进程禁止 socket 连接。
- 模型库：`chronos-forecasting==2.3.2`；独立 CPU 环境使用 `torch==2.14.1+cpu`、`transformers==5.18.0` 等共44个锁定依赖。所有 wheel SHA-256 核对，许可信息及完整依赖安全查询保留。模型不装入应用 `.venv`，共享 Conda 从未升级或卸载。
- 来源是已经获准发布的国家统计局真实快照 `src/china_macro/demo_data.json`，采集时间2026-10-03T19:08:02+00:00；SHA-256 `33338fc490dd5cbba6142b73555318e936007fd3fb05c904ab81fd8a08e2bf2a` 是**首个审计历史前缀**指纹，完整源文件 SHA-256 为 `90e4e0d4237d2c414578c29786c9585bddbc27192cdd7c65c937f563326bb6c2`。原文件2225行，七项423行；共同区间2021-09—2026-08，共420行。三条2026-09 PMI仅排除在本审计外，原始记录保留。
- 原冻结科学协议、算法、测试与计划在 `research/chronos/`；协议物理 SHA-256 `cd1abcfa04b3d3183cfbd4cb0a365f62aca3d90503b85d09136a4ae21d712261`，2026-10-04锁定；用户于2026-10-05明确授权下载、独立安装和离线实验。原协议“待授权/未运行”状态是预执行历史记录，未据事后结果改写；实际授权与运行另存。

## 时间顺序、基线与泄漏控制

开发期2024-09—2025-08，每指标12个月，仅比较四项基线并选该指标开发 MAE 最低者，平局按协议顺序。**开发期 Chronos 预测数为0**。审计期2025-09—2026-08，每指标12个月、合计84预测；只有这一轮经济审计，未以结果调参或重跑。

每次模型只收到目标统计月之前的全部固定快照历史前缀；审计前缀48—59个月，开发前缀36—47个月；无插值、缺期替代、外部协变量或跨指标共享。目标月20日是固定发布时间边界：全部输入行的记录发布日期在此前，目标记录在此后。只有日期级 metadata，没有首次发布逐期版本；**当前修订值可能在历史当时不可得，历史标签也已被查看**。代码顺序和输入隔离不能解决修订值或模型预训练审查缺口。

四项对照为上期值、去年同月值、按历史端点斜率外推的 drift、原冻结 StandardScaler+Ridge(alpha=10，滞后1/2/3/12、月份sin/cos)。固定 Ridge 使用原应用的 NumPy2.4.6、scikit-learn1.9.1，逐期仅拟合此前24—120个完整滞后标签。新审计参考允许开发期选择这四种方法；**它不替换现有系统的生产默认研究参考**。

后端 IPC 仅接受历史数字，不接受目标实际值；目标实际值在预测返回后加入评分。全部context指纹、输入边界、训练截止、84次请求与返回在 `evaluation/chronos-synth-v1/events.jsonl`。原证据助手首测144/150、六个失败和13项源码冻结，以及原7项Ridge研究门槛均保持。

## 指标与真实结果

点预测固定为原生p50；逐指标MAE/RMSE保留原单位。每次MASE分母是该历史前缀中12月差值的平均绝对值；接近零则明确未定义，不加epsilon或删样本。先逐指标平均MASE，再对七项等权，禁止把百分点和指数点的原始MAE混合平均。

| 方法 | 七项等权 MASE |
| --- | ---: |
| 上期值 | 0.600270 |
| 去年同月值 | 0.759436 |
| 历史端点漂移 | 0.614972 |
| 固定 Ridge | 0.570978 |
| Chronos-2-Synth | 0.478350 |

| 指标 | 开发期预选参考 | 模型 MAE | 参考 MAE | 模型 MASE | 原生80%带实际覆盖 |
| --- | --- | ---: | ---: | ---: | ---: |
| CPI 同比 | 上期值 | 0.329993 | 0.366667 | 0.312377 | 58.3% |
| PPI 同比 | 上期值 | 0.416627 | 0.675000 | 0.100733 | 83.3% |
| CPI 环比 | 固定 Ridge | 0.227694 | 0.304329 | 0.639099 | 66.7% |
| PPI 环比 | 固定 Ridge | 0.486450 | 0.538140 | 0.866386 | 33.3% |
| 制造业 PMI | 固定 Ridge | 0.560582 | 0.503849 | 0.628368 | 91.7% |
| 制造业新订单 PMI | 上期值 | 1.061267 | 1.341667 | 0.639425 | 66.7% |
| 非制造业商务活动指数 | 上期值 | 0.472925 | 0.491667 | 0.162063 | 91.7% |

CPI/PPI误差单位是百分点，PMI是指数点。6/7项优于开发期预选参考，制造业PMI不如其固定Ridge参考；PPI环比也不如上期值，但该项的开发参考是Ridge，不能把“6/7”写成逐项优于全部基线。

固定门槛同时要求全84完整、有序有限分位数、定义的MASE，模型宏观MASE低于四项基线，至少5/7项胜过开发参考，且宏观配对描述性95%区间上界<0。本轮最后一项未满足，门槛为false，默认保持不变。三月循环块、2000次、seed42，对同月七项差值先等权再按月份抽样；仅描述12个月小样本，不作总体显著性或未来稳定优势推断。

原生p10—p90没有用这批经济数据事后校准；各项覆盖33.3%—91.7%，不是可靠经济置信带。平均带宽、0.1/0.5/0.9 pinball loss及2025-09—12/2026-01—08切片全保留，尤其不能把2026口径变化静默拼成同质历史。

## 实际资源与操作性勘误

有效审计监督记录：21.735秒，模型加载15.078秒，单次模型调用范围0.031—0.079秒。机器缓存和本地环境影响时间；不是通用性能benchmark。监督时长不含初始资源预检和记录后的末次目录统计。

实际模型进程与Windows venv启动器已通过原生父子关系校验；持有进程句柄，避免PID复用并确保只停止自有进程。合计应用评估宿主与模型进程的峰值工作集0.963GiB、抽样私有内存0.983GiB，最低系统可用3.183GiB；80次内存采样，名义间隔0.25秒，实测最大间隔0.516秒（受OS调度影响）。整个D研究目录约1.484GiB。加载<=120秒、单origin<=45秒、整轮<=1800秒；合计WS<=2.5GiB、private<=3GiB、启动可用>=4GiB、运行可用>=1.5GiB、目录<=5GiB。真实运行没有触发停止阈值。

安装前44依赖审计无当时已知漏洞；这不是永久无漏洞或全部原生代码漏洞审计。现有Conda Torch2.6有公开漏洞记录，未使用或修改。官方高危pickle公告的加载路径与本实验固定safetensors不同，没有证据表明遭到攻击。

首轮许可ZIP目录归档错误、官方权重HTTP中断、Anaconda14.27/14.29运行库与新Torch的DLL冲突，以及磁盘扫描阻塞内存轮询/Windows venv PID只代表启动器的问题，全部保留操作性勘误与原记录。DLL修复仅在自有进程显式加载已有、已签名Microsoft14.51系统运行库，没有安装系统软件。早期两轮成功人工序列的资源记录不作为容量证明；最后pid-repair人工序列检查才通过容量验收。以上修正均在首次经济预测前完成，**未使用审计指标调参**；原科学协议、窗口、权重及评估算法不变。检查人工序列不算经济评测。

## 普通应用使用与离线复核

按主README安装应用依赖并启动，选择“研究与风险分析 → 时序基础模型审计”。七指标切换、曲线与原生区间、开发参考、训练边界、年份切片、HTML/JSON/CSV均可离线使用，无需Torch或网络。

```powershell
.\.venv\Scripts\python.exe scripts/verify_chronos_report.py assets/demo/chronos-synth-v1/chronos-synth-audit.json
.\.venv\Scripts\python.exe scripts/check_chronos_evidence.py
.\.venv\Scripts\python.exe -m pytest tests/test_chronos_protocol.py tests/test_chronos_report.py tests/test_chronos_ui.py tests/test_chronos_runtime.py -q
```

JSON核验器重算历史边界、固定基线、所有指标和门槛，但只回放已存的模型分位数；**不重跑模型，也不独立证明预测曾由该权重产生**。模型执行来源另有本机日志、进程、模型文件哈希、依赖锁及审计前代码冻结。HTML无脚本/远程资源，CSV含全部168开发/审计记录，开发期模型列为空。打包wheel也包含同一结果与源快照。

## 独立研究环境复现（Windows CPython3.11 x64）

此步骤需要下载官方模型和CPU包，占用约1.5GiB以上、预留3—5GiB；与只读界面分开。不要在共享Conda或应用`.venv`安装这些包。仓库不包含权重、wheel或研究环境；安装锁固定WindowsCPU wheel，不适用于Linux或其他PythonABI。已有完整审计目录不允许覆盖或重跑；独立复现使用新空目录，不把复现次数改称首次审计。

```powershell
$research = 'D:\economic-research-reproduction-v1'
New-Item -ItemType Directory -Path $research
New-Item -ItemType Directory -Path "$research\temp", "$research\hf-cache", "$research\model", "$research\scripts", "$research\reports", "$research\metadata"
$env:TEMP = "$research\temp"
$env:TMP = "$research\temp"
$env:HF_HOME = "$research\hf-cache"
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '4'
$env:MKL_NUM_THREADS = '1'
$env:ENABLE_PAID_AI = '0'
$env:AUTO_REFRESH = '0'
.\.venv\Scripts\python.exe -m venv --without-pip "$research\.venv"
.\.venv\Scripts\python.exe -m pip --python "$research\.venv\Scripts\python.exe" install --require-hashes -r research/chronos/requirements-cpu.lock.txt
Copy-Item research/chronos/chronos_cpu_backend.py, research/chronos/chronos_owned_process.py, research/chronos/chronos_runtime_resources.py, research/chronos/run_chronos_frozen_audit.py "$research\scripts"
```

先对整个依赖锁执行当前安全审计；旧锁未来可能需要新的安全版本，**不要静默替换并声称精确复现**。模型仅取官方revision的config.json/README.md/model.safetensors并核对上述全SHA；下载与标记校验的便携脚本及具体后续命令见 `research/chronos/REPRODUCE.md`。新数据、vintage或不同环境的未来实验必须另立版本与协议；不复用已查看标签称未查看。

## 工程验证记录

本地完整Python回归 **345 passed、10 subtests passed，296.87秒**。最后离线HTML表格可读性、历史边界文案与异常重试验收补充后，相关 **17 tests passed，19.37秒**；Ruff与23文件mypy再次通过。Node前端测试及语法检查、pip check、安全扫描也通过；Bandit扫描src/scripts/research未发现中高危，应用91项可查询依赖和模型44项锁当次查询均无已知漏洞。本地guanlan项目未发布到PyPI，注册库查询明确跳过，项目源码另由扫描和测试检查；不称全部代码无漏洞。

实际Microsoft Edge执行12项验收：七指标控件切换与URL状态、三种下载、重复下载、训练边界/年份展开、1440px桌面/390px移动曲线与下载、无脚本离线HTML。页面异常、付费接口请求及整体横向溢出均为0；离线数据表格使用局部横向滚动，数字保持完整。最初脚本误读input控件、长revision文本溢出、旧预览导出器未重载的失败与原截图保留，最终截图逐一目视检查，来源见 `docs/validation/chronos-browser-acceptance.json`。

发行包逐项校验69个Python库文件、342来源摘录和4个审计JSON；独立安装目标离线重算84条保存预测/168条固定基线并导出三格式，不导入Torch或运行模型。README最后完善后重新构建并核验发行包，文件SHA见 `docs/validation/chronos-build-artifact-audit.json`。两个原项目与原未提交修改的状态哈希完全保持；阶段二13文件与本阶段8科学准备文件/40份原始审计证据核验通过。未满足的科学门槛没有改写。

本地逐项记录见 `docs/validation/chronos-validation-status.json`；最终GitHub准确提交及其完整CI只在读取远端实际结果后记录到独立交付回执。此处不把先前阶段CI当成本阶段结果。新的首次发布vintage/独立时期、Linux模型执行和付费API未运行；便携下载器现有固定三文件校验已通过，新的空目录传输没有额外重演。

## 文件证据

- `evaluation/chronos-synth-v1/`：唯一原始报告、168完成事件、84请求/返回、资源样本、依赖/模型来源和全部预检失败/勘误；delivery-manifest固定物理字节。
- `research/chronos/`：原冻结科学算法和协议、实际CPU适配器、进程/磁盘监督、Windows完整依赖哈希锁；与应用依赖锁分离。
- `src/guanlan/resources/chronos-synth-v1/`：wheel内置报告、协议、运行来源与完整性清单。
- `assets/demo/chronos-synth-v1/`：可直接打开的离线HTML、JSON、CSV与原始报告。

官方来源：[模型固定revision](https://huggingface.co/autogluon/chronos-2-synth/tree/3607918a9fd027d5c465d8213e46b98e2c041cea)、[Chronos代码与许可](https://github.com/amazon-science/chronos-forecasting)、[官方CPU索引](https://download.pytorch.org/whl/cpu/torch/)、[PyTorch高危公告](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p)。数据许可与质量继续遵循 `docs/DATA_LICENSES.md` 和主README已有来源说明。
