"""严格按同一年观测值构建同组参照与可复现的中文研究报告。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .analytics import (
    GROWTH,
    classify_regime,
    format_value,
    trade_concentration,
    trade_partner_table,
)
from .catalog import INDICATORS, INDICATOR_BY_CODE, country_label, group_label
from .financial import financial_report_table

COHORTS = {"全球": None, "同地区": "region", "同收入组": "income_level"}
REPORT_FORMAT_VERSION = "3"


@dataclass(frozen=True)
class PeerSummary:
    year: int
    indicator_code: str
    cohort: str
    group_value: str
    total_economies: int
    observed_economies: int
    selected_value: float | None
    percentile: float | None
    rank_descending: int | None
    median: float | None
    q1: float | None
    q3: float | None


def peer_sample(macro: pd.DataFrame, country: str, year: int,
                indicator_code: str, cohort: str) -> tuple[pd.DataFrame, str]:
    """返回同年参照组的全部经济体与原值，包括没有该指标的经济体。"""
    if indicator_code not in INDICATOR_BY_CODE:
        raise ValueError(f"未知指标：{indicator_code}")
    if cohort not in COHORTS:
        raise ValueError(f"未知同组方式：{cohort}")
    selected = macro.loc[(macro.country_code == country) & (macro.year == year)]
    if selected.empty:
        raise ValueError(f"{country} 在 {year} 年没有数据记录")
    selected_meta = selected.iloc[0]
    population = macro.loc[macro.year == year, ["country_code", "country_name", "region", "income_level"]].drop_duplicates("country_code")
    group_column = COHORTS[cohort]
    group_value = group_label(str(selected_meta[group_column]), group_column) if group_column else "所有经济体"
    if group_column is not None:
        population = population.loc[population[group_column] == selected_meta[group_column]]
    values = macro.loc[
        (macro.year == year) & (macro.indicator_code == indicator_code),
        ["country_code", "value"],
    ]
    distribution = population.merge(values, on="country_code", how="left", validate="one_to_one")
    return distribution, group_value


def peer_context(
    macro: pd.DataFrame, country: str, year: int, indicator_code: str, cohort: str
) -> tuple[pd.DataFrame, PeerSummary]:
    """只使用指定年份；百分位为中秩，数值越高仅表示位置越靠上。"""
    distribution, group_value = peer_sample(macro, country, year, indicator_code, cohort)
    observed = distribution.dropna(subset=["value"]).copy()
    observed = observed.sort_values("value", ascending=False).reset_index(drop=True)
    selected_series = distribution.loc[distribution.country_code == country, "value"]
    selected_value = float(selected_series.iloc[0]) if not selected_series.empty and pd.notna(selected_series.iloc[0]) else None
    percentile = rank = None
    if selected_value is not None and not observed.empty:
        lower = int((observed.value < selected_value).sum())
        tied = int((observed.value == selected_value).sum())
        percentile = 100 * (lower + 0.5 * tied) / len(observed)
        rank = 1 + int((observed.value > selected_value).sum())
    summary = PeerSummary(
        year=year,
        indicator_code=indicator_code,
        cohort=cohort,
        group_value=group_value,
        total_economies=len(distribution),
        observed_economies=len(observed),
        selected_value=selected_value,
        percentile=percentile,
        rank_descending=rank,
        median=float(observed.value.median()) if not observed.empty else None,
        q1=float(observed.value.quantile(0.25)) if not observed.empty else None,
        q3=float(observed.value.quantile(0.75)) if not observed.empty else None,
    )
    return observed, summary


def build_research_report(
    macro: pd.DataFrame,
    trade: pd.DataFrame,
    macro_meta: dict,
    trade_meta: dict,
    country: str,
    year: int,
    indicator_code: str = GROWTH,
    cohort: str = "同收入组",
    weo: pd.DataFrame | None = None,
    weo_meta: dict | None = None,
    report_id: str | None = None,
    bis_policy: pd.DataFrame | None = None,
    bis_credit: pd.DataFrame | None = None,
    bis_policy_meta: dict | None = None,
    bis_credit_meta: dict | None = None,
) -> str:
    """报告只引用快照内的同年事实，保持确定性并明确样本边界。"""
    selected = macro.loc[(macro.country_code == country) & (macro.year == year)]
    if selected.empty:
        raise ValueError(f"{country} 在 {year} 年没有数据记录")
    name = country_label(country, str(selected.iloc[0].country_name))
    values = selected.set_index("indicator_code").value
    observed_count = sum(pd.notna(values.get(item.code)) for item in INDICATORS)
    _, peer = peer_context(macro, country, year, indicator_code, cohort)
    indicator = INDICATOR_BY_CODE[indicator_code]
    lines = [
        f"# 观澜研究快照：{name} · {year} 年",
        "",
        "- 文档性质：基于固定数据快照的描述性宏观研究，不是实时交易信号。",
        *([f"- 报告编号：`{report_id}`；格式版本：{REPORT_FORMAT_VERSION}。"] if report_id else []),
        f"- 本国该年有效 WDI 指标：{observed_count}/{len(INDICATORS)}。缺失值未填补。",
        f"- 数据快照下载时间（UTC）：{macro_meta.get('downloaded_at_utc', '未知')}",
        f"- WDI 来源更新日期：{macro_meta.get('source_last_updated') or '未提供'}",
        "- 缺失值：保留为空；WDI 数值对应所标年份的当前发布版本，可能包含估计和后续修订，不跨年填补。",
        "",
        "## 年度宏观指标",
        "",
        "| 指标 | 数值 | 单位 | 来源 |",
        "| --- | ---: | --- | --- |",
    ]
    for item in INDICATORS:
        value = values.get(item.code)
        display = f"{float(value):.2f}%" if item.format_kind == "percent" and pd.notna(value) else format_value(value, item.format_kind)
        lines.append(
            f"| {item.name} | {display} | {item.unit} | "
            f"[WDI {item.code}]({item.source_url}) |"
        )
    lines += ["", "## 同组参照", ""]
    lines.append(
        f"{indicator.name}（{year} 年，{cohort}：{peer.group_value}）："
        f"{peer.observed_economies}/{peer.total_economies} 个经济体有观测值。"
    )
    if peer.total_economies and peer.observed_economies / peer.total_economies < 0.5:
        lines.append("本组该指标有效覆盖不足一半，相对位置可能有明显选择偏差。")
    if peer.selected_value is None:
        lines.append("所选经济体在该年缺少此指标，不能计算相对位置。")
    else:
        lines.append(
            f"本国数值 {format_value(peer.selected_value, indicator.format_kind)}；"
            f"同组中位数 {format_value(peer.median, indicator.format_kind)}；"
            f"从高到低第 {peer.rank_descending}/{peer.observed_economies} 位，"
            f"中秩百分位 {peer.percentile:.1f}。"
        )
    lines.append(f"口径提醒：{indicator.comparison_note} 百分位仅描述数值位置，不是经济质量或投资评分。")
    lines.append("分组采用本次 WDI 快照提供的地区与收入分类；快照未提供分类生效年度，不能将其当作所选数据年度的历史分类。")
    lines += ["", "## 相对历史位置", ""]
    regime = classify_regime(macro, country, year)
    if regime is None:
        lines.append("当前年份或历史窗口有效观测不足，无法计算描述性状态。")
    else:
        lines.append(
            f"{regime.label}。{year} 年实际增长率 {regime.growth:.2f}%"
            f"（{regime.reference_start}—{regime.reference_end} 年中位数 {regime.growth_reference:.2f}%），"
            f"消费者价格涨幅 {regime.inflation:.2f}%"
            f"（同期中位数 {regime.inflation_reference:.2f}%）。"
        )
    is_baci = trade_meta.get("provider") == "CEPII BACI"
    lines += ["", "## 双边贸易结构" if is_baci else "## 双边贸易样本", ""]
    partners = trade_partner_table(trade, country, year, "X") if not trade.empty else pd.DataFrame()
    concentration = trade_concentration(partners)
    if concentration is None:
        lines.append("该经济体、该年份没有本项目已下载的出口伙伴样本。")
    else:
        source_label = "CEPII BACI 调和双边贸易" if is_baci else "联合国 Comtrade 公开预览样本"
        lines.append(
            f"{source_label}含 {concentration['partner_count']} 个出口伙伴；"
            f"前五伙伴占比 {concentration['top5_share']:.1%}，伙伴集中度 HHI {concentration['hhi']:.3f}。"
        )
        scope = (f"BACI {trade_meta.get('revision')} V{trade_meta.get('release')}，原始数据为 HS6 商品级；"
                 "此处按伙伴聚合，进口是相同双边流的反向视角。" if is_baci else
                 "此数据仅为全部商品的指定报告国伙伴国汇总，不能替代全球商品级贸易网络。")
        lines.append(f"贸易快照下载时间（UTC）：{trade_meta.get('downloaded_at_utc', '未知')}。{scope}")
    lines += ["", "## 金融条件（BIS）", ""]
    finance = financial_report_table(bis_policy, bis_credit, country, year)
    if not bis_policy_meta and not bis_credit_meta:
        lines.append("本研究包未提供 BIS 金融数据快照，因此不推断该经济体的政策利率或信贷状态。")
    else:
        lines.append(f"以下分别选取 {year} 年内 BIS 有记录的最后一个月和季度；"
                     "若该年没有记录或来源标记缺失，则保留空值，不沿用上一年。")
        lines += ["", "| 指标 | 观察期 | 数值 | 单位 | 来源状态 |",
                  "| --- | --- | ---: | --- | --- |"]
        for row in finance.itertuples(index=False):
            value = f"{float(row.value):,.2f}" if pd.notna(row.value) else "—"
            status = ("BIS 标记缺失" if row.obs_status == "M" else
                      "有值" if pd.notna(row.value) else
                      "该期无有效值" if row.period else "该年无记录")
            lines.append(f"| {row.indicator_name_zh} | {row.period or '—'} | "
                         f"{value} | {row.unit} | {status} |")
        lines.append("")
        lines.append("政策利率工具因国而异，部分欧元区成员的国家序列已终止；"
                     "信贷缺口是实际比率减 BIS 单边趋势的百分点差，不是资产收益预测。")
    if weo is not None and not weo.empty and weo_meta:
        lines += ["", "## IMF 中期预测附录（独立数据版次）", ""]
        lines.append(
            f"来源：[IMF WEO DataMapper]({weo_meta.get('source_url', 'https://data.imf.org/Datasets/WEO')})，"
            f"{weo_meta.get('vintage', '未知版次')}。以下是该版次的 IMF 工作人员预测，"
            "不属于上文 WDI 所选年份的历史发布值。"
        )
        lines += ["", "| 指标 | 2026 年预测 | 2027 年预测 | 2031 年预测 |", "| --- | ---: | ---: | ---: |"]
        for code, name in (
            ("NGDP_RPCH", "实际GDP增速（%）"),
            ("PCPIPCH", "平均消费者价格涨幅（%）"),
            ("GGXWDG_NGDP", "广义政府总债务占 GDP（%）"),
        ):
            rows = weo.loc[(weo.country_code == country) & (weo.indicator_code == code)]
            values_by_year = rows.set_index("year").value if not rows.empty else pd.Series(dtype=float)
            cells = [f"{float(values_by_year[target]):.2f}" if target in values_by_year and pd.notna(values_by_year[target])
                     else "暂无预测" for target in (2026, 2027, 2031)]
            lines.append(f"| {name} | {' | '.join(cells)} |")
        lines.append("")
        lines.append("2026 年 7 月 WEO Update 仅为部分指标与经济体更新，未混入本 4 月完整数据库快照。预测随版次变化，不能解释为资产收益。")
    lines += [
        "",
        "## 来源、方法与限制",
        "",
        f"- 年度指标：[世界银行 WDI](https://data.worldbank.org/)；本报告使用 {year} 年原值。历史数据可能修订，各指标发布时间不同。",
        ("- 贸易数据：[CEPII BACI](https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37)；"
         "仅在国家和年份均有已导入记录时计算。" if is_baci else
         "- 贸易样本：[联合国 Comtrade](https://uncomtrade.org/docs/un-comtrade-api/)；仅在报告国和年份均有样本时计算。"),
        "- 增长与通胀状态仅与本国前十年有效观测的中位数比较，不预测资产回报。",
        "- 跨国同组位置不控制经济规模、汇率、人口结构或统计定义差异；不构成投资建议。",
        f"- WDI 快照 SHA-256：`{macro_meta.get('parquet_sha256', '未提供')}`。",
    ]
    if trade_meta:
        lines.append(f"- 贸易快照 SHA-256：`{trade_meta.get('parquet_sha256', '未提供')}`。")
    if weo is not None and not weo.empty and weo_meta:
        lines.append(f"- IMF 预测快照 SHA-256：`{weo_meta.get('parquet_sha256', '未提供')}`。")
    if bis_policy_meta:
        lines.append(f"- 月度政策利率：[BIS 官方方法](https://data.bis.org/topics/CBPOL)；"
                     f"快照 SHA-256：`{bis_policy_meta.get('parquet_sha256', '未提供')}`。")
    if bis_credit_meta:
        lines.append(f"- 季度信贷/GDP：[BIS 官方方法](https://data.bis.org/topics/CREDIT_GAPS)；"
                     f"快照 SHA-256：`{bis_credit_meta.get('parquet_sha256', '未提供')}`。")
    if bis_policy_meta or bis_credit_meta:
        lines.append("- BIS 中文说明为观澜项目翻译，非官方译文；使用数据不表示 BIS 认可本报告。"
                     "快照含历史修订，不能当作所选年份当时已经可获得的数据。")
    return "\n".join(lines) + "\n"
