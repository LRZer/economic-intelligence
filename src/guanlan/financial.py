"""BIS 金融条件页面使用的严格年份截面与历史筛选。"""

from __future__ import annotations

import pandas as pd

from .bis import BIS_CREDIT_PAGE, BIS_POLICY_PAGE

FINANCIAL_REPORT_COLUMNS = (
    "country_code", "year", "indicator_code", "indicator_name_zh",
    "period", "frequency", "unit", "value", "obs_status", "source_url",
)


def period_comparison(frame: pd.DataFrame, countries: list[str], cutoff: pd.Timestamp,
                      mode: str = "common") -> pd.DataFrame:
    """共同期严格匹配；各自最新可得值只在截止期之前选择非缺失记录。

    返回实际观察期和末条记录期，避免把陈旧的有效值误认为共同期值。
    调用方先选定一个 measure，禁止把不同信贷量的最新季度混合。
    """
    if mode not in ("common", "latest"):
        raise ValueError("未知金融比较模式")
    rows = []
    for country in countries:
        eligible = frame.loc[(frame.country_code == country) & (frame.date <= cutoff)].sort_values("date")
        last_record = eligible.iloc[-1] if not eligible.empty else None
        selected = eligible.loc[eligible.date == cutoff] if mode == "common" else eligible.loc[eligible.value.notna()]
        record = selected.iloc[-1] if not selected.empty else None
        rows.append({"country_code": country, "date": record.date if record is not None else pd.NaT,
                     "value": record.value if record is not None else float("nan"),
                     "obs_status": record.get("obs_status", "") if record is not None else "",
                     "last_record_date": last_record.date if last_record is not None else pd.NaT})
    return pd.DataFrame(rows)


def policy_history(frame: pd.DataFrame, countries: list[str], year: int,
                   lookback_years: int = 10) -> pd.DataFrame:
    return frame.loc[
        frame.country_code.isin(countries) & frame.date.dt.year.between(
            year - lookback_years + 1, year),
    ].sort_values(["country_code", "date"]).copy()


def policy_latest_in_year(frame: pd.DataFrame, countries: list[str], year: int) -> pd.DataFrame:
    """只取指定年份内来源报告的最后一个月份；缺失状态不向前填补。"""
    current = frame.loc[frame.country_code.isin(countries) & (frame.date.dt.year == year)]
    latest = current.sort_values("date").drop_duplicates("country_code", keep="last")
    grid = pd.DataFrame({"country_code": countries})
    return grid.merge(latest[["country_code", "date", "value", "obs_status"]],
                      on="country_code", how="left", validate="one_to_one")


def credit_history(frame: pd.DataFrame, countries: list[str], year: int,
                   measure: str = "gap", lookback_years: int = 20) -> pd.DataFrame:
    if measure not in ("ratio", "trend", "gap"):
        raise ValueError("未知 BIS 信贷指标")
    return frame.loc[
        frame.country_code.isin(countries) & (frame.measure == measure)
        & frame.date.dt.year.between(year - lookback_years + 1, year),
    ].sort_values(["country_code", "date"]).copy()


def credit_latest_in_year(frame: pd.DataFrame, countries: list[str], year: int) -> pd.DataFrame:
    """每国只取所选年份内最后一个季度，三种量必须来自同一季度。"""
    current = frame.loc[frame.country_code.isin(countries) & (frame.date.dt.year == year)]
    if current.empty:
        latest = pd.DataFrame(columns=["country_code", "date", "period", "ratio", "trend", "gap"])
    else:
        latest_period = current.groupby("country_code").date.transform("max")
        selected = current.loc[current.date.eq(latest_period)]
        latest = selected.pivot(index=["country_code", "date", "period"],
                                columns="measure", values="value").reset_index()
        latest.columns.name = None
    for measure in ("ratio", "trend", "gap"):
        if measure not in latest:
            latest[measure] = pd.Series(dtype=float)
    grid = pd.DataFrame({"country_code": countries})
    return grid.merge(latest[["country_code", "date", "period", "ratio", "trend", "gap"]],
                      on="country_code", how="left", validate="one_to_one")


def financial_report_table(policy: pd.DataFrame | None, credit: pd.DataFrame | None,
                           country: str, year: int) -> pd.DataFrame:
    """固定四项 BIS 指标，严格保留所选年份内的观察期与缺失。"""
    rate = None
    if policy is not None and not policy.empty:
        rate = policy_latest_in_year(policy, [country], year).iloc[0]
    rate_date = rate["date"] if rate is not None else pd.NaT
    rows = [{
        "country_code": country, "year": year, "indicator_code": "BIS.CBPOL",
        "indicator_name_zh": "央行政策利率", "period": rate_date.strftime("%Y-%m") if pd.notna(rate_date) else "",
        "frequency": "月度", "unit": "年利率 %",
        "value": rate["value"] if rate is not None else float("nan"),
        "obs_status": rate["obs_status"] if rate is not None and pd.notna(rate["obs_status"]) else "",
        "source_url": BIS_POLICY_PAGE,
    }]
    selected_credit = None
    credit_status: dict[str, str] = {}
    if credit is not None and not credit.empty:
        selected_credit = credit_latest_in_year(credit, [country], year).iloc[0]
        if pd.notna(selected_credit["date"]):
            source_rows = credit.loc[(credit.country_code == country)
                                     & (credit.date == selected_credit["date"])]
            credit_status = source_rows.set_index("measure").obs_status.to_dict()
    for measure, code, name, unit in (
        ("ratio", "BIS.CREDIT_RATIO", "私人部门信贷/GDP 实际比率", "GDP 的 %"),
        ("trend", "BIS.CREDIT_TREND", "BIS 单边长期趋势", "GDP 的 %"),
        ("gap", "BIS.CREDIT_GAP", "信贷/GDP 缺口", "百分点"),
    ):
        rows.append({
            "country_code": country, "year": year, "indicator_code": code,
            "indicator_name_zh": name,
            "period": (selected_credit["period"] if selected_credit is not None
                       and pd.notna(selected_credit["period"]) else ""),
            "frequency": "季度", "unit": unit,
            "value": selected_credit[measure] if selected_credit is not None else float("nan"),
            "obs_status": credit_status.get(measure, ""), "source_url": BIS_CREDIT_PAGE,
        })
    return pd.DataFrame(rows, columns=FINANCIAL_REPORT_COLUMNS)


def eer_with_12m_change(frame: pd.DataFrame, areas: list[str]) -> pd.DataFrame:
    """只用同一地区与类型恰好 12 个日历月前的指数计算变化率。"""
    current = frame.loc[frame.country_code.isin(areas)].copy()
    prior = current[["country_code", "measure", "date", "value"]].copy()
    prior["date"] = prior.date + pd.DateOffset(months=12)
    prior = prior.rename(columns={"value": "value_12m_ago"})
    joined = current.merge(prior, on=["country_code", "measure", "date"],
                           how="left", validate="one_to_one")
    joined["change_12m_pct"] = 100 * (joined.value / joined.value_12m_ago - 1)
    return joined.sort_values(["country_code", "measure", "date"]).reset_index(drop=True)


def eer_history(frame: pd.DataFrame, areas: list[str], year: int,
                lookback_years: int = 6) -> pd.DataFrame:
    changed = eer_with_12m_change(frame, areas)
    return changed.loc[changed.date.dt.year.between(year - lookback_years + 1, year)].copy()


def eer_latest_in_year(frame: pd.DataFrame, areas: list[str], year: int) -> pd.DataFrame:
    changed = eer_with_12m_change(frame, areas)
    current = changed.loc[changed.date.dt.year == year]
    latest = current.sort_values("date").drop_duplicates(["country_code", "measure"], keep="last")
    grid = pd.MultiIndex.from_product([areas, ["nominal", "real"]],
                                      names=["country_code", "measure"]).to_frame(index=False)
    return grid.merge(latest[["country_code", "measure", "date", "value", "change_12m_pct"]],
                      on=["country_code", "measure"], how="left", validate="one_to_one")
