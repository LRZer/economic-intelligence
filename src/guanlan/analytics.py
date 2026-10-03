"""可复核的描述性统计与宏观状态分析。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .catalog import INDICATORS, INDICATOR_BY_CODE

GDP = "NY.GDP.MKTP.CD"
GROWTH = "NY.GDP.MKTP.KD.ZG"
INFLATION = "FP.CPI.TOTL.ZG"


@dataclass(frozen=True)
class RegimeResult:
    label: str
    growth: float
    growth_reference: float
    inflation: float
    inflation_reference: float
    reference_start: int
    reference_end: int
    observations_growth: int
    observations_inflation: int


def macro_pivot(macro: pd.DataFrame, year: int) -> pd.DataFrame:
    current = macro.loc[macro.year == year]
    if current.empty:
        return pd.DataFrame()
    wide = current.pivot(
        index=["country_code", "country_name", "region", "income_level"],
        columns="indicator_code",
        values="value",
    ).reset_index()
    wide.columns.name = None
    return wide


def indicator_series(macro: pd.DataFrame, countries: list[str], indicator: str) -> pd.DataFrame:
    return macro.loc[
        macro.country_code.isin(countries) & (macro.indicator_code == indicator) & macro.value.notna(),
        ["country_code", "country_name", "year", "value"],
    ].sort_values(["country_code", "year"])


def classify_regime(macro: pd.DataFrame, country: str, year: int, lookback: int = 10) -> RegimeResult | None:
    if lookback < 5:
        raise ValueError("历史参照窗口至少为五年")
    subset = macro.loc[
        (macro.country_code == country)
        & macro.indicator_code.isin([GROWTH, INFLATION])
        & macro.year.between(year - lookback, year)
    ]
    if subset.empty:
        return None
    current = subset.loc[subset.year == year].set_index("indicator_code").value
    if GROWTH not in current or INFLATION not in current:
        return None
    if pd.isna(current[GROWTH]) or pd.isna(current[INFLATION]):
        return None
    past = subset.loc[subset.year < year]
    growth_past = past.loc[(past.indicator_code == GROWTH) & past.value.notna(), "value"]
    inflation_past = past.loc[(past.indicator_code == INFLATION) & past.value.notna(), "value"]
    if len(growth_past) < 5 or len(inflation_past) < 5:
        return None
    growth = float(current[GROWTH])
    inflation = float(current[INFLATION])
    growth_reference = float(growth_past.median())
    inflation_reference = float(inflation_past.median())
    growth_label = "增长高于历史中位" if growth >= growth_reference else "增长低于历史中位"
    inflation_label = "通胀高于历史中位" if inflation >= inflation_reference else "通胀低于历史中位"
    return RegimeResult(
        label=f"{growth_label} · {inflation_label}",
        growth=growth,
        growth_reference=growth_reference,
        inflation=inflation,
        inflation_reference=inflation_reference,
        reference_start=year - lookback,
        reference_end=year - 1,
        observations_growth=len(growth_past),
        observations_inflation=len(inflation_past),
    )


def trade_partner_table(trade: pd.DataFrame, reporter: str, year: int, flow: str = "X") -> pd.DataFrame:
    subset = trade.loc[
        (trade.reporter_code == reporter) & (trade.year == year) & (trade.flow == flow),
        ["partner_code", "partner_name", "trade_usd"],
    ].copy()
    if subset.empty:
        return subset
    total = subset.trade_usd.sum()
    if total <= 0:
        return subset.assign(share=0.0)
    subset["share"] = subset.trade_usd / total
    return subset.sort_values("trade_usd", ascending=False).reset_index(drop=True)


def trade_concentration(partners: pd.DataFrame) -> dict | None:
    if partners.empty:
        return None
    positive = partners.loc[partners.trade_usd > 0, "trade_usd"]
    if positive.empty:
        return None
    shares = positive / positive.sum()
    return {
        "hhi": float((shares**2).sum()),
        "top5_share": float(shares.sort_values(ascending=False).head(5).sum()),
        "partner_count": int(len(positive)),
    }


def observation_summary(macro: pd.DataFrame, year: int) -> pd.DataFrame:
    current = macro.loc[macro.year == year]
    total = current.country_code.nunique()
    coverage = (
        current.groupby("indicator_code", as_index=False)
        .agg(observed=("value", "count"), median=("value", "median"))
    )
    coverage["indicator"] = coverage.indicator_code.map(
        lambda code: INDICATOR_BY_CODE[code].name if code in INDICATOR_BY_CODE else code
    )
    coverage["coverage_pct"] = 100 * coverage.observed / total if total else 0
    return coverage[["indicator", "observed", "coverage_pct", "median", "indicator_code"]]


def country_observation_status(macro: pd.DataFrame, country: str, year: int) -> pd.DataFrame:
    """逐指标说明指定年份是否有值及此前最近观测年；不推断缺失原因。"""
    subset = macro.loc[
        (macro.country_code == country) & (macro.year <= year),
        ["indicator_code", "year", "value"],
    ]
    rows = []
    for indicator in INDICATORS:
        series = subset.loc[subset.indicator_code == indicator.code]
        current = series.loc[series.year == year, "value"]
        observed = series.loc[series.value.notna(), "year"]
        latest = int(observed.max()) if not observed.empty else None
        has_value = not current.empty and pd.notna(current.iloc[0])
        rows.append({
            "indicator_code": indicator.code,
            "indicator": indicator.name,
            "selected_year": year,
            "has_observation": has_value,
            "latest_observed_year_through_selection": latest,
            "years_since_last_observation": year - latest if latest is not None else None,
        })
    return pd.DataFrame(rows)


def format_value(value: float | None, kind: str) -> str:
    if value is None or pd.isna(value):
        return "暂无数据"
    if kind == "percent":
        return f"{value:,.1f}%"
    if kind == "usd":
        if abs(value) >= 1e12:
            return f"{value / 1e12:,.1f}万亿"
        if abs(value) >= 1e8:
            return f"{value / 1e8:,.1f}亿"
        return f"{value:,.0f} 美元"
    if kind == "count":
        if abs(value) >= 1e8:
            return f"{value / 1e8:,.2f} 亿人"
        if abs(value) >= 1e4:
            return f"{value / 1e4:,.1f} 万人"
    return f"{value:,.2f}"


def research_facts(macro: pd.DataFrame, trade: pd.DataFrame, country: str, year: int,
                   trade_meta: dict | None = None, weo: pd.DataFrame | None = None,
                   weo_meta: dict | None = None) -> dict:
    current = macro.loc[(macro.country_code == country) & (macro.year == year) & macro.value.notna()]
    values = {row.indicator_code: float(row.value) for row in current.itertuples()}
    regime = classify_regime(macro, country, year)
    partners = trade_partner_table(trade, country, year, "X") if not trade.empty else pd.DataFrame()
    concentration = trade_concentration(partners)
    outlook = None
    if weo is not None and not weo.empty and weo_meta:
        selected = weo.loc[
            (weo.country_code == country) & weo.indicator_code.isin(["NGDP_RPCH", "PCPIPCH", "GGXWDG_NGDP"])
            & weo.year.isin([2026, 2027, 2031]) & weo.value.notna()
        ]
        outlook = {
            "provider": "IMF WEO DataMapper", "vintage": weo_meta.get("vintage"),
            "status": "IMF staff projections; separate from WDI observations",
            "values": [
                {"indicator_code": row.indicator_code,
                 "name": {"NGDP_RPCH": "实际GDP增速", "PCPIPCH": "平均消费者价格涨幅",
                          "GGXWDG_NGDP": "广义政府总债务占 GDP"}[row.indicator_code],
                 "unit": "%", "year": int(row.year), "value": float(row.value)}
                for row in selected.itertuples()
            ],
        }
    return {
        "country_code": country,
        "year": year,
        "indicators": {
            code: {"name": INDICATOR_BY_CODE[code].name, "value": value, "unit": INDICATOR_BY_CODE[code].unit}
            for code, value in values.items()
            if code in INDICATOR_BY_CODE
        },
        "regime": regime.__dict__ if regime else None,
        "trade_sample": concentration,
        "trade_provider": (trade_meta or {}).get("provider"),
        "trade_release": (trade_meta or {}).get("release"),
        "imf_outlook": outlook,
        "trade_scope_note": (
            "贸易伙伴指标来自 CEPII BACI 调和后的全球 HS17 商品级双边流在伙伴层面的聚合；"
            "进口为同一流的反向视角，年份最新至 2024。"
            if (trade_meta or {}).get("provider") == "CEPII BACI" else
            "贸易数据仅覆盖指定报告国与全部商品汇总；不能代表完整全球商品网络。"
        ),
    }
