"""同年多国宏观剖面：保留原值、全球中秩位置和严格端点变化。"""

from __future__ import annotations

import math

import pandas as pd

from .catalog import INDICATOR_BY_CODE


PROFILE_INDICATORS = (
    "NY.GDP.MKTP.KD.ZG",   # 实际增长
    "FP.CPI.TOTL.ZG",      # 消费者价格
    "BN.CAB.XOKA.GD.ZS",  # 经常账户/GDP
    "NE.GDI.TOTL.ZS",     # 资本形成/GDP
    "BX.KLT.DINV.WD.GD.ZS",  # FDI净流入/GDP
    "NV.IND.MANF.ZS",     # 制造业/GDP
    "SL.UEM.TOTL.ZS",     # 失业率
    "FR.INR.RINR",        # 实际利率
    "GC.DOD.TOTL.GD.ZS", # 中央政府债务/GDP
)
DEFAULT_PROFILE_INDICATORS = PROFILE_INDICATORS[:5]
PROFILE_SHORT_NAMES = {
    "NY.GDP.MKTP.KD.ZG": "实际GDP增速",
    "FP.CPI.TOTL.ZG": "消费者价格涨幅",
    "BN.CAB.XOKA.GD.ZS": "经常账户/GDP",
    "NE.GDI.TOTL.ZS": "资本形成/GDP",
    "BX.KLT.DINV.WD.GD.ZS": "FDI 净流入/GDP",
    "NV.IND.MANF.ZS": "制造业/GDP",
    "SL.UEM.TOTL.ZS": "失业率",
    "FR.INR.RINR": "实际利率",
    "GC.DOD.TOTL.GD.ZS": "中央政府债务/GDP",
}


def build_macro_profile(macro: pd.DataFrame, countries: list[str], year: int,
                        indicators: list[str], lookback: int = 5) -> pd.DataFrame:
    """逐国逐指标返回所选年份原值；历史变化只使用精确的 year-lookback 端点。"""
    if not countries or len(countries) > 6 or len(countries) != len(set(countries)):
        raise ValueError("请选择 1—6 个不重复的经济体")
    if not indicators or len(indicators) > 7 or len(indicators) != len(set(indicators)):
        raise ValueError("请选择 1—7 个不重复的指标")
    if any(code not in PROFILE_INDICATORS or INDICATOR_BY_CODE[code].unit != "%"
           for code in indicators):
        raise ValueError("多维剖面只支持预设的百分比指标")
    if lookback < 1:
        raise ValueError("历史端点间隔须为正数")
    population = macro.loc[macro.year == year, ["country_code", "country_name"]].drop_duplicates("country_code")
    if population.empty:
        raise ValueError(f"{year} 年没有 WDI 经济体记录")
    current = macro.loc[
        (macro.year == year) & macro.indicator_code.isin(indicators),
        ["country_code", "indicator_code", "value"],
    ].copy()
    past = macro.loc[
        (macro.year == year - lookback) & macro.country_code.isin(countries)
        & macro.indicator_code.isin(indicators),
        ["country_code", "indicator_code", "value"],
    ].rename(columns={"value": "past_value"})
    keys = ["country_code", "indicator_code"]
    if current.duplicated(keys).any() or past.duplicated(keys).any():
        raise ValueError("宏观快照存在重复的经济体、年份、指标组合")
    for frame, column in ((current, "value"), (past, "past_value")):
        numeric = pd.to_numeric(frame[column], errors="coerce")
        valid_numeric = numeric.map(
            lambda value: pd.notna(value) and math.isfinite(float(value))).astype(bool)
        invalid = frame[column].notna() & ~valid_numeric
        if invalid.any():
            raise ValueError("宏观快照包含无法比较的非有限数值")
        frame[column] = numeric
    population_size = len(population)
    observed = current.dropna(subset=["value"]).copy()
    observed["global_percentile"] = (
        (observed.groupby("indicator_code").value.rank(method="average") - 0.5)
        / observed.groupby("indicator_code").value.transform("count") * 100
    )
    counts = observed.groupby("indicator_code").value.count().to_dict()
    grid = pd.MultiIndex.from_product([countries, indicators], names=keys).to_frame(index=False)
    result = grid.merge(population, on="country_code", how="left", validate="many_to_one")
    result = result.merge(observed[keys + ["value", "global_percentile"]],
                          on=keys, how="left", validate="one_to_one")
    result = result.merge(past, on=keys, how="left", validate="one_to_one")
    result.insert(1, "year", year)
    result["past_year"] = year - lookback
    result["delta_pp"] = result.value - result.past_value
    result["global_observed"] = result.indicator_code.map(counts).fillna(0).astype(int)
    result["global_total"] = population_size
    result["indicator_name_zh"] = result.indicator_code.map(
        lambda code: INDICATOR_BY_CODE[code].name)
    result["unit"] = "%"
    return result[["country_code", "country_name", "year", "indicator_code", "indicator_name_zh",
                   "unit", "value", "global_percentile", "global_observed", "global_total",
                   "past_year", "past_value", "delta_pp"]]
