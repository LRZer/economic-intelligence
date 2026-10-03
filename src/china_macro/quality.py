"""Coverage calculations for monthly releases; missing periods are never imputed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .catalog import INDICATORS


NO_JANUARY = {
    "industrial_yoy", "retail_yoy", "fai_ytd_yoy", "private_fai_ytd_yoy",
    "manufacturing_fai_ytd_yoy", "infrastructure_fai_ytd_yoy",
    "infrastructure_ex_utilities_ytd_yoy",
    "real_estate_fai_ytd_yoy", "housing_sales_area_ytd_yoy",
    "industrial_profit_ytd_yoy", "unemployment",
    "fiscal_revenue_ytd", "fiscal_revenue_ytd_yoy", "fiscal_spending_ytd",
    "fiscal_spending_ytd_yoy", "tax_revenue_ytd", "tax_revenue_ytd_yoy",
    "fund_revenue_ytd", "fund_revenue_ytd_yoy", "land_revenue_ytd", "land_revenue_ytd_yoy",
}
NO_JANUARY_FEBRUARY = {"industrial_yoy", "retail_yoy"}
ACTIVE_RANGES = {
    "infrastructure_fai_ytd_yoy": ("2026-02", None),
    "infrastructure_ex_utilities_ytd_yoy": (None, "2025-12"),
    "m1_yoy": ("2024-01", None),
    "m1_legacy_yoy": (None, "2024-12"),
}
CHINA_TIME = timezone(timedelta(hours=8))
CALENDAR_URL = "https://www.stats.gov.cn/xxgk/sjfb/fbrcb/202512/t20251224_1962137.html"
# Verified 2026 NBS plan. These are publication months, not data months.
# The plan can change; passing a scheduled time does not prove publication.
RELEASE_DAYS = {
    "overview": (19, None, 16, 16, 18, 16, 15, 17, 15, 19, 16, 15),
    "price": (9, 11, 9, 10, 11, 10, 9, 9, 9, 14, 9, 9),
    "profit": (27, None, 27, 27, 27, 27, 27, 27, 28, 27, 27, 27),
    "pmi": (31, None, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31),
}
PMI_KEYS = {"manufacturing_pmi", "manufacturing_new_orders_pmi", "nonmanufacturing_pmi"}
PRICE_KEYS = {"cpi_yoy", "cpi_mom", "ppi_yoy", "ppi_mom"}


def planned_release(key: str, period: str) -> datetime | None:
    number = month_number(period)
    category = ("pmi" if key in PMI_KEYS else "price" if key in PRICE_KEYS
                else "profit" if key == "industrial_profit_ytd_yoy"
                else "overview" if INDICATORS[key][4] in {"NBS", "NBS/GACC"} else None)
    if category is None:
        return None
    if category == "pmi" and period == "2026-02":
        return datetime(2026, 3, 4, 9, 30, tzinfo=CHINA_TIME)
    release_period = period if category == "pmi" else period_from_number(number + 1)
    year, month = map(int, release_period.split("-"))
    if year != 2026:
        return None
    day = RELEASE_DAYS[category][month - 1]
    if day is None:
        return None
    hour = 15 if category == "overview" and month == 8 else 10 if category == "overview" else 9
    minute = 0 if category == "overview" else 30
    return datetime(year, month, day, hour, minute, tzinfo=CHINA_TIME)


def period_status(key: str, period: str, available: set[str], as_of: datetime) -> dict:
    result = {"period": period, "scheduled_at": None, "source_url": None}
    if period in available:
        return {**result, "code": "recorded", "label": "已收录", "reason": "已收录官方读数"}
    active_start, active_end = ACTIVE_RANGES.get(key, (None, None))
    if (active_start and period < active_start) or (active_end and period > active_end):
        reason = ("M1新旧口径分列，新口径包含央行2024年官方回溯值"
                  if key in {"m1_yoy", "m1_legacy_yoy"}
                  else "基础设施投资新旧统计口径分列，按各自适用期展示")
        return {**result, "code": "inactive", "label": "口径未启用或已结束", "reason": reason}
    month = int(period[5:])
    if (key in NO_JANUARY and month == 1) or (key in NO_JANUARY_FEBRUARY and month in (1, 2)):
        return {**result, "code": "not_separate", "label": "不单列该月", "reason": "该序列不收录1—2月合并值为单月值，累计序列不单列1月"}
    release = planned_release(key, period)
    if release:
        result.update(scheduled_at=release.isoformat(timespec="minutes"), source_url=CALENDAR_URL)
        if as_of < release:
            return {**result, "code": "pending", "label": "待发布", "reason": "尚未到官方计划发布时间（计划可能调整）"}
    # No verified calendar for a recent period: do not invent a publication day
    # or count it as missing just because another indicator has a newer month.
    recent_start = month_number(as_of.strftime("%Y-%m")) - 1
    if release is None and month_number(period) >= recent_start:
        return {**result, "code": "unconfirmed", "label": "发布时间待确认", "reason": "本系统尚未核实该期的官方发布日期，暂不计入缺失"}
    detail = known_source_gap(key, period)
    return {**result, "code": "missing", "label": "待补录",
            "reason": detail["reason"] if detail else ("已到计划发布时间，未收录；是否已实际发布仍需核查" if release else "历史月度记录未收录；是否已实际发布仍需核查"),
            "source_url": detail["source_url"] if detail else result["source_url"]}

# These are source-specific findings, not a claim that customs never published
# the monthly data. The current NBS overview either combines January-February
# or omits separate monthly export/import rates; no value is inferred.
TRADE_COMBINED_REPORTS = {
    2022: "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901402.html",
    2023: "https://www.stats.gov.cn/sj/zxfb/202303/t20230315_1937190.html",
    2024: "https://www.stats.gov.cn/sj/zxfb/202403/t20240321_1948109.html",
    2025: "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202503/t20250317_1959010.html",
    2026: "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202603/t20260316_1962780.html",
}
TRADE_NO_BREAKDOWN = {
    "2022-04": "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901460.html",
    "2022-09": "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901627.html",
    "2026-03": "https://www.stats.gov.cn/sj/zxfb/202604/t20260416_1963330.html",
}
LOAN_MONTHLY_ONLY = {
    "2021-10": "49c49e1c0f3945a58821af20b1d49e7b",
    "2021-11": "28034b83163d40d2bf5aacb2112e2062",
    "2022-02": "f8157ada86814e82a99d8629e07e0cba",
    "2022-04": "356bd109230b48ae9013b790520a3425",
    "2023-02": "588b2401df5344f68b78d51b7396d743",
    "2023-04": "1bb8759c90de4353b2a93e00438375e3",
    "2023-05": "0755aafdab32428daa12f2cf682c81ba",
}


def known_source_gap(key: str, period: str) -> dict | None:
    if key == "loans_ytd" and period in LOAN_MONTHLY_ONLY:
        return {"period": period, "reason": "已核查该期央行金融统计报告：给出当月贷款增加额，未明确给出年内累计；不把单月值写入累计序列",
                "source_url": f"https://www.pbc.gov.cn/diaochatongjisi/116219/116225/{LOAN_MONTHLY_ONLY[period]}/index.html"}
    if key not in {"export_yoy", "import_yoy"}:
        return None
    year, month = (int(part) for part in period.split("-"))
    if month in (1, 2) and year in TRADE_COMBINED_REPORTS:
        return {"period": period, "reason": "统计局综述只给出1—2月累计，未列该月单独同比",
                "source_url": TRADE_COMBINED_REPORTS[year]}
    if period in TRADE_NO_BREAKDOWN:
        return {"period": period, "reason": "统计局综述未列当月出口、进口各自同比",
                "source_url": TRADE_NO_BREAKDOWN[period]}
    return None


def month_number(period: str) -> int:
    year, month = (int(part) for part in period.split("-"))
    return year * 12 + month - 1


def period_from_number(number: int) -> str:
    year, month = divmod(number, 12)
    return f"{year:04d}-{month + 1:02d}"


def coverage(series: dict[str, list[dict]], window: int = 24,
             as_of: datetime | None = None) -> dict:
    as_of = as_of or datetime.now(CHINA_TIME)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=CHINA_TIME)
    as_of = as_of.astimezone(CHINA_TIME)
    latest_global = max((row["period"] for points in series.values() for row in points), default=None)
    end = month_number(latest_global) if latest_global else None
    metrics = []
    for key, spec in INDICATORS.items():
        points = series.get(key, [])
        available = {row["period"] for row in points}
        states = ([period_status(key, period_from_number(i), available, as_of)
                   for i in range(end - window + 1, end + 1)] if end is not None else [])
        pending = [item["period"] for item in states if item["code"] == "pending"]
        unconfirmed = [item["period"] for item in states if item["code"] == "unconfirmed"]
        expected = [item["period"] for item in states if item["code"] in {"recorded", "missing"}]
        missing = [item["period"] for item in states if item["code"] == "missing"]
        missing_details = [detail for period in missing
                           if (detail := known_source_gap(key, period))]
        latest = max(available, default=None)
        metrics.append({
            "key": key, "name": spec[0], "source": spec[4], "latest": latest,
            "observed": len(expected) - len(missing), "expected": len(expected),
            "coverage_pct": round(100 * (len(expected) - len(missing)) / len(expected), 1) if expected else 0,
            "missing": missing, "missing_details": missing_details,
            "pending": pending, "unconfirmed": unconfirmed, "period_states": states,
            "inactive": bool(ACTIVE_RANGES.get(key, (None, None))[1]
                             and latest_global and latest_global > ACTIVE_RANGES[key][1]),
            "total_observations": len(points),
            "lag_months": end - month_number(latest) if latest and end is not None else None,
        })
    observed = sum(item["observed"] for item in metrics)
    expected_count = sum(item["expected"] for item in metrics)
    return {
        "window_months": window, "latest_period": latest_global,
        "indicator_count": len(metrics),
        "populated_indicators": sum(bool(item["total_observations"]) for item in metrics),
        "observation_count": sum(item["total_observations"] for item in metrics),
        "coverage_pct": round(100 * observed / expected_count, 1) if expected_count else 0,
        "observed": observed, "expected": expected_count, "metrics": metrics,
        "pending_count": sum(len(item["pending"]) for item in metrics),
        "unconfirmed_count": sum(len(item["unconfirmed"]) for item in metrics),
        "as_of": as_of.isoformat(timespec="seconds"), "calendar_url": CALENDAR_URL,
    }
