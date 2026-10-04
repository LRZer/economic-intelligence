# 数据许可与发布处置

核查日期：2026-10-03／04 UTC。目标是 LRZer 的新私有研究仓库。代码与每个来源的数据条件分别适用；私有仓库不改变第三方权利。本项目没有个人明细、账户数据或非公开商业材料。

| 来源 | 已查证的官方证据 | 发布内容与条件 |
|---|---|---|
| World Bank WDI | [数据许可](https://datacatalog.worldbank.org/public-licenses)，14 个实际指标的官方页面均显示 CC BY-4.0，见 `license-evidence.json` | 14 指标数值、指标代码、来源、日期和 SHA；保留各原始机构归属、缺失；注明聚合／中文标签等修改，不把第三方机构数据声称为本项目原创 |
| CEPII BACI | [CEPII 法文官方数据页](https://www.cepii.fr/CEPII/fr/bdd_modele/bdd_modele_item.asp?id=37) 链接 [Etalab 2.0](https://www.etalab.gouv.fr/wp-content/uploads/2017/04/ETALAB-Licence-Ouverte-v2.0.pdf) | 完整 HS17 V202601 原包字节分块及派生网络、伙伴、HS2 聚合。引用 Gaulier and Zignago (2010), CEPII Working Paper 2010-23；标明版本、v×1000 单位转换、聚合与分类筛选；不暗示 CEPII 认可 |
| BIS | [官方数据使用条件](https://data.bis.org/help/legal) | 三个统计原始 ZIP 与派生数值快照；标明 BIS，中文为非官方译文，不暗示认可，不对统计数据额外收费 |
| IMF WEO | [官方现行版权与使用条件：统计数据专门条款](https://www.imf.org/en/about/copyright-and-terms) | 归属 IMF 的固定 2026 年 4 月 WEO 数值快照，准确注明预测与版次，传达来源条件。统计数据条款允许复制、派生与分发；潜在商业复用需另向 IMF 申请，不能将其条款写成通用开放许可证。未用于 LLM 训练 |
| BLS | [官方版权说明](https://www.bls.gov/bls/linksite.htm)、[API 条款](https://www.bls.gov/developers/termsOfService.htm) | BLS 数值与直接 API JSON，注明 BLS；统计材料属公有领域，原有版权照片／插图除外；不发布 BLS 标志、不暗示认可 |
| 美联储理事会 | [官方免责声明](https://www.federalreserve.gov/disclaimer.htm) | 直接 G.17 与 H.15 数值和文档；除另行注明内容外属公有领域，注明 Board 来源；排除标志、印章与第三方图像 |
| 国家统计局 | [服务条款](https://www.stats.gov.cn/wzgl/202302/t20230217_1912857.html) | 免费资料性研究所需的官方统计数值与可重放统计摘录，显著标注国家统计局网站和 URL；排除网站特有标志、版式和程序，也不扩展署名文章或第三方材料的许可 |
| 人民银行／财政部／商务部 | 各观测和摘录记录官方统计来源 URL；没有声称整站或完整文章开放许可 | 只发布官方数值事实、必要的统计段落／表格重放材料及出处。移除整站程序、CSS、图像、标志、导航；完整原始网页只保存在本机审计目录。若拟发布完整文章或用于其他用途，应先核查对应权利 |
| UN Comtrade | [许可入口](https://comtrade.un.org/licenseagreement.html) 的再分发限制尚未取得覆盖本项目的书面许可 | 原件本机保留；`trade.parquet/json` 排除发布。默认刷新不会获取，显式 `--trade-only` 返回说明；所有现有贸易功能使用许可明确的完整 BACI |
| FRED | [FRED 条款](https://fred.stlouisfed.org/legal/) 对机器学习、归档和再提供内容有限制 | 原项目原件与旧衍生物保留本机；整合发布不含 FRED 缓存、旧模型回测或适配器。美国数据独立直接来自 BLS 与 Fed，不用旧缓存换来源标签 |

上述是具体发布处置及来源证据记录，不是对其他商业用途、未来条款或第三方材料的一揽子授权。

## 完整数据和修改说明

- BACI 官方 ZIP：794,583,540 字节，17 块，逐块 SHA 与整体 SHA 都保留；已实际重建并核对。分块只改变存储形式，重建字节不变。
- 原项目独立 2024 CSV：已完整包含于同一官方 ZIP，避免重复存储 363,762,242 字节；不是丢弃该年数据。
- BIS 三个 ZIP：全部包含，合计 10,998,317 字节。
- WDI、WEO、BIS、BACI、美国与行业派生：12 个发布数值快照均经过同值核验。旧批次历史、运行数据库、失败日志与本机迁移清单保留在发布目录之外。
- 中国 HTML：342 份生成的中性统计摘录，原始 SHA 和摘录 SHA 都记录；逐份比较全部解析行完全一致，不改变统计原意。数值 JSON 继续保留。
- 本机路径、密钥、认证材料、缓存、`.venv`、源项目未提交修改与原件不进入 Git。

逐项清单：[data-disposition.json](data-disposition.json)。逐份中国统计摘录：[source-excerpt-manifest.json](source-excerpt-manifest.json)。官方逐指标许可：[license-evidence.json](license-evidence.json)。完整数据文件清单及 SHA 由发布验收脚本生成于 `data-file-manifest.json`。

## 归属声明

数值来源包括 World Bank WDI（及其官方逐指标列出的原机构）、CEPII BACI、BIS、IMF WEO、BLS、美联储理事会、国家统计局、人民银行、财政部、商务部。项目中文标签、聚合、模型和情景是本项目研究处理，均非官方预测或官方解释。

本项目不对统计资料单独收费，不使用官方标志，不声称上述机构赞助、合作或认可。原始统计可能修订，接口可访问不自动代表其他素材可再分发。


## 阶段二问答与应用评测

检索库复用既有许可内国家统计局七指标423条数值事实与官方URL，不添加网页完整文章、标志、商业私密数据或外部问答语料。题目模板、gold算术、计算轨迹和应用评测文件为本项目程序构造；不是外部版权问答集或真实用户日志。来源归属及当前修订限制随导出保留。

60开发/150首轮封存问题和gold在唯一首轮完成后加入本私有仓库用于复现，此后不再称未查看。已有802项数据的物理字节与许可处置未变；评测副本/演示报告在evaluation/assets目录明确列出，不冒充新增原始官方数据。没有LLM训练、真实新API请求或钥匙传输；12项离线请求只含项目自写问题、能力schema及可用期别，不含IMF内容或私密材料。
