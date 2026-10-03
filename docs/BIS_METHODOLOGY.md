# BIS 金融条件数据：口径、重建与解释边界

观澜使用国际清算银行（BIS）的[央行政策利率](https://data.bis.org/topics/CBPOL)、[信贷/GDP 缺口](https://data.bis.org/topics/CREDIT_GAPS)和[有效汇率](https://data.bis.org/topics/EER)官方批量 CSV。有效汇率的月度指数口径及跨国比较方法单独见[有效汇率方法](EER_METHODOLOGY.md)。页面中文说明由本项目翻译，**不是 BIS 官方译文**；使用这些数据不表示 BIS 认可本项目或其分析。原始数据及使用条件见 [BIS 统计数据使用说明](https://data.bis.org/help/legal)。

## 当前随仓库提供的快照

| 序列 | 频率与单位 | 纳入范围 | 当前快照观察期 |
| --- | --- | --- | --- |
| 政策利率 | 月度、年利率 %；当月最后营业日 | 48 个经济体，24,764 行 | 1945-01 至 2026-08 |
| 私人非金融部门信贷/GDP | 季度；实际比率与趋势为 GDP 的 %，缺口为百分点 | 43 个经济体，24,373 行（三种指标合计） | 1947Q4 至 2026Q1；缺口从 1957Q4 起 |

政策利率和信贷两份原始包都含欧元区区域汇总 `XM`，导入时将其排除，避免与成员经济体重复计数。国家系列仍保留；一些国家的独立政策利率系列在加入欧元区后终止。政策利率快照保留 BIS 的 `A` 正常、`M` 缺失状态，不以前一期补值。页面提供各国 BIS 原始编制说明，因为政策工具及其历史接续口径并不相同，利率水平不能直接当作等价的货币政策立场或跨国收益率预测。

信贷序列限定为**私人非金融部门借款人、所有放贷部门**。`ratio` 是 BIS 信贷/GDP 实际比率，`trend` 是 BIS 发布的单边 HP 滤波长期趋势，`gap = ratio − trend`。导入器要求每个完整的国家与季度记录在 0.001 个百分点内勾稽。BIS 将缺口用于金融稳定监测，但也明确反对机械地用它确定政策或危机概率；观澜仅展示原值和时间路径。

页面的“观察年份”截面取**所选年份内**该国最新月或季度，并列出实际观察期；若该年没有数据，保持空值。图表显示当前下载版次的历史记录。两项数据均可能发生历史修订，快照没有逐次公布日期和历史实时版本，因此不支持无未来信息的历史投资回测。

## 重建与核验

```powershell
python scripts/refresh_bis.py
python scripts/refresh_bis.py --policy-zip data/raw/WS_CBPOL_csv_flat.zip --credit-zip data/raw/WS_CREDIT_GAP_csv_flat.zip --eer-zip data/raw/WS_EER_csv_flat.zip
```

脚本从 [BIS 官方批量下载](https://data.bis.org/bulkdownload)获取压缩包；也可指定已下载的原始 ZIP。下载的 ZIP 存放在 `data/raw/` 并由 Git 忽略；随仓库提供的是 Parquet 基础快照及同名 JSON 元数据。元数据记录原始包 SHA-256、下载时间、来源、覆盖范围及 Parquet SHA-256。刷新先校验压缩结构、必要字段、单位、频率、状态、唯一主键和信贷勾稽，再将三份快照作为同一不可变批次发布；失败写入审计，活动版本保持不变。`--policy-only`、`--credit-only` 或 `--eer-only` 可单独刷新，但联合研究时建议一次整批刷新。

CSV 下载附来源 URL、原始包与快照校验值，可与 [快照发布与回退操作](SNAPSHOT_OPERATIONS.md)共同复核。BIS 官方会更新历史值；比较不同研究时，应固定快照批次、来源包 SHA-256 与观察期。
