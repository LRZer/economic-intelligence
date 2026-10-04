# Chronos-2-Synth 下一阶段只读可行性

本阶段没有下载权重/轮子、安装软件或运行预测。仅查本机CIM/磁盘、已装包元数据、官方HF/PyPI JSON与CPU轮子HTTP HEAD，不读凭据、不沿用10元预算。资源是2026-10-04 UTC检查时快照，会变化；不包含个人主机名或序列号。

## 来源、具体版本与许可

官方[Chronos项目](https://github.com/amazon-science/chronos-forecasting)列出`autogluon/chronos-2-synth`。[该模型卡](https://huggingface.co/autogluon/chronos-2-synth)声明仅合成单变量/多变量数据训练，Apache-2.0；不是普通Chronos-T5的真实+合成混训模型。此为提供者声明，训练语料未独立审计；不能证明所有污染不存在，也不能把已查看中国历史标签重新叫盲评。

固定候选revision `3607918a9fd027d5c465d8213e46b98e2c041cea`；118,985,888个F32参数。`model.safetensors`475,963,368字节（约453.9MiB），LFS SHA256 `920a3344726a8026c9335d38ae1a2bfa9b7d659c1b8fe0b0af8d5f775863422e`；config.json 971字节。[文件页](https://huggingface.co/autogluon/chronos-2-synth/tree/3607918a9fd027d5c465d8213e46b98e2c041cea)与[元数据记录](validation/chronos-metadata-feasibility.json)保存明确来源。

代码候选为PyPI `chronos-forecasting==2.3.2`，轮子80,769字节，SHA `0f0d9a1972f252d6cf584b9fa749bd1b389b3c1cf05a889c4130cb10652c2117`。Python≥3.10；[官方依赖](https://raw.githubusercontent.com/amazon-science/chronos-forecasting/main/pyproject.toml)包括torch≥2.2,<3、transformers≥4.41,<6、accelerate≥1.1,<2、einops≥.7,<1、numpy、pandas。五项新增核心包在当前项目.venv均未安装；不改原锁文件，不选择云部署或开发extras。

官方CPU PyTorch候选`2.14.1+cpu`、CPython3.11 Windows amd64，HTTP HEAD200、Content-Length123,978,347字节，未取轮子正文；[头记录](validation/chronos-cpu-header-check.json)保留URL。不可用普通PyPI的可能GPU依赖推断CPU总安装量。权重＋config＋CPU torch＋Chronos最小传输600,023,455字节（约572.2MiB），**尚不含**transformers/accelerate/HF hub/tokenizers/sympy等传递依赖；未进行解析、软件安全扫描或安装兼容测试。后续须固定完整锁与哈希，不能把此最低值当全部下载费用/大小。

## 本机容量与可行性推断

实测i9-13900HX，24核/32逻辑线程，约15.8GiB可见RAM，检查时空闲约4.57GiB。C空闲4.49GiB、D37.92GiB、F98.20GiB；[只读资源记录](validation/chronos-local-resource-check.json)。不使用GPU结论，未做显存检查或推理测速。

F32权重约454MiB，短中国月度序列、batch=1的CPU试验在此机**可能可行**；这是容量推断，不是实测内存/速度承诺。依赖解压、缓存、激活和其他进程会额外占用内存；建议在D预留3—5GiB并单独建研究环境，临时/下载缓存仅在D，执行前重新测可用RAM，限制线程与批量，内存不足停止。不能把本项目.venv跨盘搬移或直接升级它。

## 执行前必须授权和固定的事项

1. 明确批准下载该revision的safetensors/config、官方CPU轮子及已审查传递依赖，安装到独立D研究环境；本阶段没有该执行授权，不能自动开始。公共权重不需要访问令牌，禁止读取密钥文件；保持trust_remote_code关闭，不下载pickle模型或运行远程自定义代码。
2. 事先锁定七指标的一步零样本审计、来源SHA、origin输入边界、无调参规则、CPU线程/内存/时长与停止条件。模型未胜出保留，不能换掉默认验证期基线。
3. 同样本强对照至少上期、季节朴素、drift、Ridge；固定MAE/RMSE/MASE（训练内缩放）、逐指标/时间切片、配对时间块描述区间及分位带覆盖。已查看历史仅称回顾审计；真正未查看的新统计期及vintage需另立协议/数据许可，不从输入时间切分推断没有预训练污染。
4. 下载后核对文件SHA，离线加载小fixture并记录实际包/模型版本、峰值RAM与耗时；联网下载和离线评估分开。完成软件/依赖审计与可复现锁后才跑预定评估；不反复追原2023—2024或月度已见留出成绩。

此文件给出可审查候选和步骤，不等于安装批准或模型优势结论。当前图阶段原AI负面结论、默认基线及冻结应用评测保持。
