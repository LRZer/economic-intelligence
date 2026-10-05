# Chronos-2-Synth：批准前固定的回顾审计协议

此目录是独立准备材料，未发布到主仓库、未改README。真实模型尚未下载、安装或执行。`protocol.json`与`protocol-lock.json`在fixture测试前生成；`real-data-plan.json`只列时间边界与输入指纹，没有拟合或预测结果。最终代码冻结记录在测试后生成，均不叫盲评/sealed。

## 数据、一步预测与信息边界

固定已发布提交10981d934329e9d3ed68febbacbb9657f1a63c63的`src/china_macro/demo_data.json`，SHA256为90e4e0d4237d2c414578c29786c9585bddbc27192cdd7c65c937f563326bb6c2，捕获于2026-10-03。七指标：CPI同比/PPI同比、CPI环比/PPI环比、制造业PMI、制造业新订单PMI、非制造业商务活动。共423条已见观察。

为同月配对，主范围固定2021-09—2026-08，七条序列各60个月（共420）。额外2026-09三项PMI不进入这次审计，原快照不删除。开发比较期2024-09—2025-08，共12个月/指标；审计期2025-09—2026-08，共12个月/指标。所有168个开发/审计起点的时间契约先检查，Chronos仅跑84个审计起点，开发期不运行或调Chronos。

一步指下一个统计月，不是下一工作日、资产价格或交易收益。每次输入只含该指标2021-09起到目标上月的完整前缀，长度36—59；没有目标实际值、未来观察、其他指标、外部协变量或跨指标联合分组。预测时点定义为目标统计月20日，所有输入来源标注发布日期必须严格早于此日，目标来源标注发布日期严格晚于此日；零冲突已在计划生成时核对。日期只有日精度，不把当日披露视为已知。

这是当前修订快照的**已见历史回顾审计**。标注发布日期检查不能证明那些修订值当时已公开，缺少真实vintage；提供者的synthetic-only声明也未独立审计。不称实时回测、全污染排除、未见样本或盲评。2026价格基期/统计变化以预定2025年9—12月、2026年1—8月切片描述，不按成绩移除年份。

## 固定模型与强对照

唯一候选`autogluon/chronos-2-synth`，revision3607918a9fd027d5c465d8213e46b98e2c041cea；权重SHA920a3344726a8026c9335d38ae1a2bfa9b7d659c1b8fe0b0af8d5f775863422e。提供者声明仅合成训练、Apache2，非独立污染审计。CPU float32，batch1、horizon1，点估计p50，原生p10/p50/p90；关闭训练/dropout/远程自定义代码，不fine-tune、不设数据驱动超参数、不变换为别的模型。实际API适配与完整CPU依赖哈希/许可/审计必须批准后通过compatibility smoke，否则停止，不用另一输出口径替代。

四强对照每个起点同样输入边界：上一月；去年同月；全前缀端点drift；既有冻结StandardScaler+Ridge(alpha10)，滞后1/2/3/12及已知月份sin/cos，至少24个先前完整标签样本、至多120。缩放与拟合仅用此前标签；不读审计目标。Ridge实现直接复用冻结代码，不调参、不改原模型或原失败研究结论。

新的**审计参考**由四项在开发12个月的MAE选最小，平局按上述顺序，称audit_reference；与线上/现有默认参考分开。现有默认及UI一律保持，即使回顾审计良好也不能替换。Chronos不根据开发成绩选context、任务组、模型、概率点或样本。

## 指标、局限与保留负结果

逐指标MAE、RMSE、季节MASE。每起点MASE分母是该训练前缀内12个月差值的平均绝对值；<=1e-12为undefined，不加epsilon、不删该指标。主宏观量为七指标MASE等权平均，不混合价格百分点与PMI指数百分点的raw MAE。

所有四项的逐指标配对MASE差、同月七指标等权对开发参考差，以circular时间块长度3、2000重采样、seed42报描述性95%区间。仅12个月且指标相关，不能当显著性检验或真实用户/市场推广证据。模型原生80%区间报覆盖、平均宽度、p10/p50/p90 pinball，不事后校准，不把基线点预测伪造为对照概率带。

预定描述性screen要求全部84个模型输出完整、有限且分位顺序正确、MASE定义；宏观MASE比全部四对照低；对开发参考的宏观配对区间上界<0；至少5/7指标优于各自开发参考（1e-8容差）。screen仅支持未来独立vintage验证，不构成模型有效性认证。失败、持平、负结果均保留完整模型身份、源/代码SHA、逐起点预测/错误/运行成本；不删失败起点、不换时间窗、不再次追分，不改变现有默认。

## 明确资源预算与硬停止

- CPU4个intra-op线程、interop1、BLAS1；batch1、CPU float32，无GPU回退；最大context60、预测步长1。
- 离线整次运行最多1800秒（30分钟），包括加载、强对照与84模型预测；加载最多120秒，单起点计算最多45秒。监视每0.25秒，终止只针对本次创建的子进程；调度/终止开销另记录，不能承诺精确到毫秒。
- 开始前系统可用RAM至少4GiB；运行中最低1.5GiB；自有模型进程当前/峰值working set上限2.5GiB、private committed bytes上限3GiB。内存读取失败也停止；峰值working set由Windows内核计数，private峰值为采样值。当前fixture不认证真实Chronos内存/速度。
- 独立D研究目录总逻辑文件预算5GiB，D盘启动空闲至少8GiB、过程中至少3GiB。env、pip/HF缓存与TEMP/TMP均在D；不修改主应用.venv/锁，不在C下载新文件。完整传递依赖尚未解析，超过预算必须重新交接，不能自行增加。
- 先决审批未到、依赖/许可/hash/CPU适配未通过、源SHA/日期/缺口/输入边界不符、OOM/超时/崩溃、分位无效、任一起点失败均停止，写partial_stopped。部分结果不得报为84完成，不自动重跑、补值、改变dtype/线程/context或转GPU。

## 当前可运行的范围

`chronos_fixture_cli.py`只允许三种本地假模型，输入强制合成fixture；没有真实Chronos入口或下载代码。`chronos_audit_core.py`提供generic输入契约/强对照/评价实现供批准后受控适配使用。fixture会在**人工合成数据**上拟合现有Ridge以检查对照实现，但没有对真实快照拟合或预测。产物始终标注`not_economic_evidence`/`fixture_only`。

已有依赖下验证：时间/发布界限、未来目标污染不影响预测及训练尺度、Ridge训练仅先前标签、独立linear金值、零MASE明确undefined、分位非法拒绝、负fixture结果保留、四对照开发选择、同月配对、窗口/资源硬停止与自有子进程终止。资源探测使用Windows原生只读API，没有安装psutil。

```powershell
# 使用主应用已有环境，不安装包；真实模型没有该入口。
D:\Documents\ChatGPT\guanlan-economic-intelligence\.venv\Scripts\python.exe -m pytest -q test_chronos_preparation.py
D:\Documents\ChatGPT\guanlan-economic-intelligence\.venv\Scripts\python.exe chronos_fixture_cli.py --output-name fixture-smoke
```

等待用户批准官方权重/CPU依赖下载与独立环境安装。等待经过多久、协议锁定或fixture通过均不意味着授权。
