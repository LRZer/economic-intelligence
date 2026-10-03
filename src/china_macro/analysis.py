"""Reproducible descriptive statistics from reported observations only.

These are comparisons of published rates or index levels, not reconstructed
month-on-month growth or causal conclusions.
"""

from __future__ import annotations

from .quality import month_number, period_from_number


RESEARCH_KEYS = (
    "industrial_yoy", "retail_yoy", "fai_ytd_yoy", "real_estate_fai_ytd_yoy",
    "cpi_yoy", "cpi_mom", "ppi_yoy", "ppi_mom", "manufacturing_pmi",
    "fiscal_revenue_ytd_yoy", "fiscal_spending_ytd_yoy", "land_revenue_ytd_yoy",
)
PMI_KEYS = ("manufacturing_pmi", "manufacturing_new_orders_pmi", "nonmanufacturing_pmi")
SHORT_NAMES = {
    "industrial_yoy": "工业", "retail_yoy": "零售", "fai_ytd_yoy": "投资",
    "cpi_yoy": "CPI", "ppi_yoy": "PPI", "unemployment": "失业率",
    "manufacturing_pmi": "制造业PMI", "manufacturing_new_orders_pmi": "新订单指数",
    "nonmanufacturing_pmi": "非制造业指数", "m2_yoy": "M2", "tsf_stock_yoy": "社融存量",
    "fiscal_revenue_ytd_yoy": "财政收入", "fiscal_spending_ytd_yoy": "财政支出",
    "real_estate_fai_ytd_yoy": "房地产投资", "housing_sales_area_ytd_yoy": "商品房销售面积",
    "export_usd_yoy": "美元出口", "import_usd_yoy": "美元进口",
}
OBSERVATION_TOPICS = (
    ("生产与需求", ("industrial_yoy", "retail_yoy", "fai_ytd_yoy"), "同比及累计同比读数的变化，不能直接当作当月产出或消费的环比增长。"),
    ("景气", PMI_KEYS, "PMI反映调查景气；高于或低于50不等同于实际产出增速。"),
    ("价格与就业", ("cpi_yoy", "ppi_yoy", "unemployment"), "价格与失业率的数值方向不直接代表经济好坏，也不能据此判断因果关系。"),
    ("货币与融资", ("m2_yoy", "tsf_stock_yoy"), "存量同比变化不能单独说明新增融资规模或资金实际流向。"),
    ("房地产", ("real_estate_fai_ytd_yoy", "housing_sales_area_ytd_yoy"), "年内累计同比变化不能直接代表当月成交或投资变化。"),
    ("财政", ("fiscal_revenue_ytd_yoy", "fiscal_spending_ytd_yoy"), "累计收入与支出属于不同预算科目，二者差额不能作为完整财政赤字。"),
    ("外贸", ("export_usd_yoy", "import_usd_yoy"), "本组为美元单月同比，不与人民币口径拼接；金额受汇率等因素影响。"),
)


def reader_summary(series: dict[str, list[dict]], catalog: list[dict], latest_period: str | None) -> dict:
    """Exact previous-calendar-month comparisons, with evidence and boundaries."""
    changes = {}
    for spec in catalog:
        key = spec["key"]
        points = sorted(series.get(key, []), key=lambda row: row["period"])
        if not points:
            continue
        current = points[-1]
        prior_period = period_from_number(month_number(current["period"]) - 1)
        previous = next((row for row in points if row["period"] == prior_period), None)
        reason = ""
        if spec["basis"] == "年内累计":
            reason = "累计金额不在此处计算较上期变化"
        elif "年内累计" in spec["basis"] and current["period"][:4] != prior_period[:4]:
            reason = "跨年累计口径不直接比较"
        elif previous is None:
            reason = "未收录上个自然月的同口径读数"
        delta = round(current["value"] - previous["value"], 4) if previous and not reason else None
        changes[key] = {"key": key, "name": spec["name"], "short_name": SHORT_NAMES.get(key, spec["name"]),
                        "basis": spec["basis"], "unit": spec["unit"], "current": current,
                        "previous": previous, "comparison_period": prior_period,
                        "delta": delta, "direction": ("上升" if delta > 0 else "下降" if delta < 0 else "持平") if delta is not None else None,
                        "reason": reason}
    observations = []
    for topic, keys, boundary in OBSERVATION_TOPICS:
        entries = [changes[key] for key in keys if key in changes and changes[key]["delta"] is not None
                   and latest_period and month_number(latest_period) - month_number(changes[key]["current"]["period"]) <= 2]
        if not entries:
            continue
        # Do not combine readings from different months into a single statement.
        newest = max(item["current"]["period"] for item in entries)
        entries = [item for item in entries if item["current"]["period"] == newest]
        title = "，".join(f'{item["short_name"]}读数{item["direction"]}' for item in entries[:2])
        observations.append({"topic": topic, "period": newest, "title": title,
                             "keys": [item["key"] for item in entries], "boundary": boundary})
    lead = next((item for item in observations if item["topic"] == "生产与需求"),
                observations[0] if observations else None)
    return {"version": "2.0", "changes": changes, "observations": observations,
            "headline": lead["title"] if lead else "暂缺连续月份的比较依据",
            "headline_period": lead["period"] if lead else None}


def empirical_percentile(values: list[float], value: float) -> float:
    """Mid-rank empirical percentile, retaining ties as half a rank."""
    below = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    return round(100 * (below + equal / 2) / len(values), 1)


def computed_analysis(series: dict[str, list[dict]], catalog: list[dict],
                      quality_60m: dict, latest_period: str | None,
                      min_points: int = 24) -> dict:
    if not latest_period:
        return {"version": "1.0", "findings": [], "pmi_breadth": None}
    end = month_number(latest_period)
    names = {item["key"]: item for item in catalog}
    quality = {item["key"]: item for item in quality_60m["metrics"]}
    findings = []
    for key in RESEARCH_KEYS:
        observations = sorted(series.get(key, []), key=lambda row: row["period"])
        if not observations or key not in names:
            continue
        current = observations[-1]
        current_month = month_number(current["period"])
        if end - current_month > 2:
            continue
        prior_period = period_from_number(current_month - 12)
        prior = next((row for row in observations if row["period"] == prior_period), None)
        sample = [row["value"] for row in observations
                  if end - 59 <= month_number(row["period"]) <= end]
        # A sparse sample can produce a precise-looking but misleading rank.
        eligible_rank = (len(sample) >= min_points and
                         quality.get(key, {}).get("coverage_pct", 0) >= 70)
        rank = empirical_percentile(sample, current["value"]) if eligible_rank else None
        if prior is None and rank is None:
            continue
        findings.append({
            "key": key, "name": names[key]["name"], "basis": names[key]["basis"],
            "unit": names[key]["unit"],
            "latest": {field: current[field] for field in ("period", "value", "source_url")},
            "year_ago": ({field: prior[field] for field in ("period", "value", "source_url")}
                         if prior else None),
            "year_ago_delta_pp": round(current["value"] - prior["value"], 3) if prior else None,
            "percentile_60m": rank, "sample_size": len(sample),
            "coverage_60m_pct": quality.get(key, {}).get("coverage_pct", 0),
        })
    pmi_points = [series.get(key, [])[-1] for key in PMI_KEYS if series.get(key)]
    pmi_breadth = None
    if len(pmi_points) == len(PMI_KEYS) and all(row["period"] == latest_period for row in pmi_points):
        pmi_breadth = {
            "period": latest_period, "above_50": sum(row["value"] > 50 for row in pmi_points),
            "equal_50": sum(row["value"] == 50 for row in pmi_points),
            "total": len(PMI_KEYS),
            "inputs": [{"key": key, "value": row["value"], "source_url": row["source_url"]}
                       for key, row in zip(PMI_KEYS, pmi_points)],
        }
    return {"version": "1.0", "findings": findings, "pmi_breadth": pmi_breadth,
            "methodology": "同期差=本期已发布读数减去12个月前同指标读数，单位为百分点；历史分位采用近60个自然月已收录值的中秩，至少24期且窗口覆盖率不低于70%；未插值。"}
