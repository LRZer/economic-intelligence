# CEPII BACI 全球贸易数据：方法与边界

贸易模块使用 [CEPII BACI HS17 V202601](https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37) 官方包。原始观察单位为年 × 出口地 × 进口地 × HS6 商品，字段 `v` 为千美元、`q` 为吨。系统按 `v × 1000` 转为现价美元，以官方数字国别代码表映射 ISO3；HS6 代码按文本读取，保留前导零。当前版本处理 2017—2024 年的 89,207,221 行，产出伙伴和 HS2 商品章两个研究快照。原始包留在本地 `data/raw/`，不提交到 Git。

每年导入时检查年份、金额非负、HS6 长度、国家映射和原始总额。伙伴聚合的出口总额、商品章聚合的出口与进口总额须分别与原始金额勾稽；导出快照记录原始 ZIP 的 SHA-256、处理批次、逐年行数与金额。伙伴和商品章快照必须来自同一批次，否则应用退回已有的 Comtrade 预览样本。

**定义**：伙伴份额 = 指定经济体与伙伴的贸易额 / 该经济体同向总额；HHI = 各伙伴份额平方和；前五占比 = 最大五个伙伴份额之和。商品章份额以该国同向总额为分母。Balassa 显性比较优势 RCA =（某国某 HS2 章出口额 / 该国出口总额）/（全球该章出口额 / 全球出口总额），只对出口计算。RCA 大于 1 表示相对专门化，不代表产品利润、产业竞争力或资产回报。

商品章中文短名称按[世界海关组织 HS 2017 章目录](https://www.wcoomd.org/en/topics/nomenclature/instrument-and-tools/hs_nomenclature_previous_editions/hs-nomenclature-2017-edition/hs-nomenclature-2017-edition.aspx)编写，图表同时保留 HS2 代码，便于回查官方定义。

**口径边界**：BACI 对申报与镜像流做调和，表中的“进口”是同一条出口地→进口地流从进口地观察的视角；两者不应相加为全球总额，也不能据此检验原始申报镜像差异。贸易差额基于 BACI 调和值，是描述性的现价美元差额。HS17 分类在本版覆盖 2017—2024 年，不能直接外推为 2025 年事实。应用所带聚合快照无法下钻到 HS6；需要原始官方包重新构建。跨来源与 WDI 经济体数量可能不同，且 BACI 国别代码表包括部分非主权经济体。官方方法和版本修订见 [BACI 数据页](https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37) 与 [202601 发布说明](https://www.cepii.fr/DATA_DOWNLOAD/baci/doc/release_notes_202601.pdf)。
