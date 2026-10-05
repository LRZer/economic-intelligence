# 固定 Chronos-2-Synth 研究环境复现

普通应用展示和 JSON 指标重算不需要模型、Torch 或网络。这里是单独的 **Windows CPython 3.11 x64、CPU** 实验流程，使用新空目录；不要覆盖 `audit-v1` 或原项目。原经济审计只执行一次，详见 [完整结果](../../docs/CHRONOS_SYNTH_ACCEPTANCE.md)。复现实验另存记录，不能改称首次审计或盲测。

科学协议、模型 revision、权重和原始快照固定；`preparation-freeze.json` 校验八个准备文件。运行代码单独冻结在 `evaluation/chronos-synth-v1/execution-source-freeze-actual-pid-erratum.json`，操作性修正保留原始失败记录。主应用的 NumPy/scikit-learn 依赖环境负责四个基线，新研究环境只负责模型。共享 Conda 不安装或修改。

## 1. 当前安全检查和空目录

在仓库根目录完成主 README 的应用安装后运行。以下 `$research` 必须是新的任务专用路径。完整 CPU 锁仅适用于本平台和 ABI；全部 44 项哈希/许可/来源另保存在 `evaluation/chronos-synth-v1/environment/`。先查询当前漏洞；若出现新问题，应中止并建立新版本协议，不静默替换冻结包。

```powershell
.\.venv\Scripts\python.exe -m pip_audit --disable-pip --no-deps -r research/chronos/requirements-audit.txt
$project = (Get-Location).Path
$research = 'D:\economic-research-reproduction-v1'
if (Test-Path -LiteralPath $research) { throw '请使用新空目录，保留已有实验' }
New-Item -ItemType Directory -Path $research
New-Item -ItemType Directory -Path "$research\temp", "$research\hf-cache", "$research\model", "$research\scripts", "$research\reports", "$research\metadata"
$env:TEMP = "$research\temp"
$env:TMP = "$research\temp"
$env:HF_HOME = "$research\hf-cache"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '4'
$env:MKL_NUM_THREADS = '1'
$env:ENABLE_PAID_AI = '0'
$env:AUTO_REFRESH = '0'
.\.venv\Scripts\python.exe -m venv --without-pip "$research\.venv"
.\.venv\Scripts\python.exe -m pip --python "$research\.venv\Scripts\python.exe" install --no-cache-dir --require-hashes -r research/chronos/requirements-cpu.lock.txt
.\.venv\Scripts\python.exe -m pip --python "$research\.venv\Scripts\python.exe" check
Copy-Item research/chronos/chronos_cpu_backend.py, research/chronos/chronos_owned_process.py, research/chronos/chronos_runtime_resources.py, research/chronos/run_chronos_frozen_audit.py "$research\scripts"
```

CPU wheel 使用 PyTorch 官方 CPU 索引；其他包取官方 PyPI 的固定哈希。安装下载和临时文件都放在此 D 目录，磁盘预留至少 8 GiB，整个研究目录限制 5 GiB。安装时也应观察可用空间；不要保留重复 wheel/cache。完整依赖锁和模型文件不进入应用运行环境。

## 2. 固定官方权重

```powershell
.\.venv\Scripts\python.exe research/chronos/download_model.py --root "$research"
.\.venv\Scripts\python.exe research/chronos/download_model.py --root "$research" --verify-only
```

下载脚本仅允许官方 Hugging Face HTTPS 域名及其官方 CDN，关闭环境代理/凭证继承；只取 revision `3607918a9fd027d5c465d8213e46b98e2c041cea` 的 config.json、README.md、model.safetensors。固定权重 475,963,368 bytes，SHA-256 `920a3344726a8026c9335d38ae1a2bfa9b7d659c1b8fe0b0af8d5f775863422e`。32 MiB HTTP 精确范围、完整长度和全文件哈希均校验；失败保留 `.part`，不加载、不自动重跑。已完成文件再次调用只复核，不重新下载、不覆盖原标记。下载器验证现有三个完整文件的路径已实际测试；新空目录网络传输流程未额外重演，原下载和续传日志保留。

权重 Apache-2.0，提供方宣称仅合成数据训练；该训练来源没有独立审计。固定安全 tensor 加载、不允许 pickle 或远程代码。模型执行阶段彻底断开 Python socket 网络访问，不传经济数据或使用 API key。

## 3. 两个人工序列预检和唯一新目录审计

```powershell
.\.venv\Scripts\python.exe research/chronos/run_chronos_frozen_audit.py --root "$research" --preparation "$project\research\chronos" --project "$project" --mode real-model-fixture --fixture-label pid-repair
.\.venv\Scripts\python.exe research/chronos/run_chronos_frozen_audit.py --root "$research" --preparation "$project\research\chronos" --project "$project" --mode audit --fixture-label pid-repair
.\.venv\Scripts\python.exe scripts/verify_chronos_report.py "$research\reports\audit-v1\report.json"
```

预检完成不表示科学效果。监督器要求启动可用 RAM ≥4 GiB、运行 ≥1.5 GiB；宿主与实际模型进程合计工作集 ≤2.5 GiB、私有内存 ≤3 GiB；4 CPU 线程/1 interop、BLAS=1、batch=1。加载 ≤120 秒、origin 含基线拟合 ≤45 秒、监督总时长 ≤1800 秒；磁盘 ≤5 GiB、运行剩余 ≥3 GiB。使用原生 Windows 父子关系和进程句柄，只终止自身子进程，内存监控独立于磁盘扫描。硬性输出排他创建，不允许覆盖、自动重试、挑选失败月份或调参。系统调度和磁盘扫描存在采样间隔，记录实测最大间隔，不将其描述为硬实时保障。

CPU backend 只在自身进程显式加载电脑已有的 System32 微软运行库；不会安装组件、修改全局 PATH 或共享环境。本机已签名 14.51 运行库通过实测。若其他电脑缺少兼容组件，保留错误并中止；系统软件安装不是该脚本的动作。

`run-status.json`、`report.json`、events、资源样本、backend 日志都是复现证据。报告核验器回放保存的分位数并重新拟合全部基线，不再次执行模型；原模型执行另由模型/依赖/代码哈希和运行日志支持。冻结经济数据没有逐期首次发布版本，历史标签已查看；需要独立的新时期与 vintage 才能验证前瞻能力。未通过的门槛和全部失败必须保留，生产默认参考不自动切换。
