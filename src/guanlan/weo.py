"""IMF WEO DataMapper 官方接口的固定版本中期预测快照。"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd
import requests

API_BASE = "https://www.imf.org/external/datamapper/api/v2"
SOURCE_URL = "https://data.imf.org/Datasets/WEO"
VINTAGE = "April 2026"
EXPECTED_SOURCE = f"World Economic Outlook ({VINTAGE})"
FORECAST_YEARS = tuple(range(2026, 2032))

# WEO DataMapper 所提供的全部 15 项指标，名称为项目中文短名称，原始定义与单位由接口保留。
WEO_INDICATORS = {
    "NGDP_RPCH": "实际GDP增速",
    "NGDPD": "现价 GDP（美元）",
    "NGDPDPC": "人均现价 GDP（美元）",
    "PPPGDP": "购买力平价 GDP",
    "PPPPC": "人均购买力平价 GDP",
    "PPPSH": "全球购买力平价 GDP 份额",
    "PPPEX": "购买力平价换算率",
    "PCPIPCH": "平均消费者价格涨幅",
    "PCPIEPCH": "期末消费者价格涨幅",
    "LP": "人口",
    "BCA": "经常账户余额（美元）",
    "BCA_NGDPD": "经常账户余额占 GDP",
    "LUR": "失业率",
    "GGXCNL_NGDP": "广义政府净借贷占 GDP",
    "GGXWDG_NGDP": "广义政府总债务占 GDP",
}
WEO_UNITS_ZH = {
    "NGDP_RPCH": "%（年度变化）", "NGDPD": "十亿美元", "NGDPDPC": "美元/人",
    "PPPGDP": "十亿国际元", "PPPPC": "国际元/人", "PPPSH": "全球份额（%）",
    "PPPEX": "本币/国际元", "PCPIPCH": "%（年度平均）", "PCPIEPCH": "%（期末同比）",
    "LP": "百万人", "BCA": "十亿美元", "BCA_NGDPD": "占 GDP（%）",
    "LUR": "%", "GGXCNL_NGDP": "占 GDP（%）", "GGXWDG_NGDP": "占 GDP（%）",
}
PERCENT_INDICATORS = {
    "NGDP_RPCH", "PPPSH", "PCPIPCH", "PCPIEPCH", "BCA_NGDPD", "LUR",
    "GGXCNL_NGDP", "GGXWDG_NGDP",
}


def format_forecast_value(value: float | None, indicator: str) -> str:
    if value is None or pd.isna(value):
        return "暂无数据"
    if indicator in PERCENT_INDICATORS:
        return f"{value:,.1f}%"
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.2f}"


def _get_json(url: str) -> dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=(12, 50))
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(f"IMF 返回格式异常：{url}")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"IMF 数据接口失败：{url}") from last_error


def normalize_weo_forecasts(indicators: dict, countries: dict,
                            payloads: dict[str, dict]) -> tuple[pd.DataFrame, dict]:
    """只接收同一 WEO 版本的未来年份，明确保留缺失而不混入历史观测。"""
    labels = countries.get("countries")
    catalog = indicators.get("indicators")
    if not isinstance(labels, dict) or not isinstance(catalog, dict):
        raise ValueError("IMF 国家或指标目录格式异常")
    if set(payloads) != set(WEO_INDICATORS):
        raise ValueError("IMF 预测指标不完整")
    series_data: dict[str, dict] = {}
    catalog_summary: dict[str, dict] = {}
    observed_countries: set[str] = set()
    for code in WEO_INDICATORS:
        item = catalog.get(code, {})
        payload = payloads[code]
        returned = payload.get("indicators", {}).get(code, {})
        for source in (item.get("source"), returned.get("source")):
            if source != EXPECTED_SOURCE:
                raise ValueError(f"IMF {code} 版本不是 {EXPECTED_SOURCE}：{source}")
        if item.get("unit") != returned.get("unit"):
            raise ValueError(f"IMF {code} 单位与指标目录不一致")
        values = payload.get("values", {}).get(code)
        if not isinstance(values, dict):
            raise ValueError(f"IMF {code} 没有国家时间序列")
        series_data[code] = values
        observed_countries.update(set(values) & set(labels))
        catalog_summary[code] = {
            "name_zh": WEO_INDICATORS[code],
            "label_en": item.get("label", ""),
            "unit": item.get("unit", ""),
            "source": EXPECTED_SOURCE,
        }
    records = []
    for country in sorted(observed_countries):
        name = labels[country].get("label", country)
        for code in WEO_INDICATORS:
            values = series_data[code].get(country) or {}
            if not isinstance(values, dict):
                raise ValueError(f"IMF {code}/{country} 时间序列格式异常")
            for year in FORECAST_YEARS:
                raw = values.get(str(year))
                value = None if raw in (None, "", "n/a") else float(raw)
                if value is not None and not math.isfinite(value):
                    raise ValueError(f"IMF {code}/{country}/{year} 非有限数值")
                records.append({
                    "country_code": country, "country_name": name,
                    "indicator_code": code, "year": year, "value": value,
                })
    frame = pd.DataFrame.from_records(records, columns=["country_code", "country_name", "indicator_code", "year", "value"])
    if frame.empty or frame.value.notna().sum() == 0:
        raise ValueError("IMF 未返回可用预测")
    forecast_countries = set(frame.loc[frame.value.notna(), "country_code"])
    frame = frame.loc[frame.country_code.isin(forecast_countries)].reset_index(drop=True)
    if frame.duplicated(["country_code", "indicator_code", "year"]).any():
        raise ValueError("IMF 预测存在重复的国家、指标和年份组合")
    return frame, catalog_summary


def fetch_weo_forecasts() -> tuple[pd.DataFrame, dict]:
    indicators = _get_json(f"{API_BASE}/indicators")
    countries = _get_json(f"{API_BASE}/countries")
    payloads: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_get_json, f"{API_BASE}/{code}"): code for code in WEO_INDICATORS}
        for future in as_completed(futures):
            code = futures[future]
            payloads[code] = future.result()
            print(f"IMF WEO：{code} 已获取", flush=True)
    frame, catalog = normalize_weo_forecasts(indicators, countries, payloads)
    return frame, {
        "provider": "IMF WEO DataMapper", "source_url": SOURCE_URL,
        "api_url": API_BASE, "vintage": VINTAGE,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "years": list(FORECAST_YEARS), "countries": int(frame.country_code.nunique()),
        "indicators": len(WEO_INDICATORS), "rows": len(frame),
        "available_values": int(frame.value.notna().sum()),
        "indicator_catalog": catalog,
        "status": "IMF staff projection; not observed WDI data",
        "coverage_note": "DataMapper WEO subset, not the full WEO database; July 2026 partial WEO Update is not included",
    }


def forecast_cross_section(frame: pd.DataFrame, indicator: str, year: int) -> pd.DataFrame:
    if indicator not in WEO_INDICATORS or year not in FORECAST_YEARS:
        raise ValueError("IMF 预测指标或年份无效")
    return frame.loc[
        (frame.indicator_code == indicator) & (frame.year == year) & frame.value.notna(),
        ["country_code", "country_name", "value"],
    ].sort_values("value", ascending=False).reset_index(drop=True)


def growth_inflation_map(frame: pd.DataFrame, year: int, highlight: str | None = None,
                         top_n: int = 30) -> pd.DataFrame:
    """按同版现价 GDP 选取前 N 大经济体，并可额外包含所选经济体。"""
    if year not in FORECAST_YEARS or top_n < 1:
        raise ValueError("IMF 预测年份或样本数无效")
    rows = frame.loc[(frame.year == year) & frame.indicator_code.isin(["NGDP_RPCH", "PCPIPCH", "NGDPD"])]
    wide = rows.pivot(index=["country_code", "country_name"], columns="indicator_code", values="value")
    wide = wide.dropna(subset=["NGDP_RPCH", "PCPIPCH", "NGDPD"]).reset_index()
    wide = wide.loc[wide.NGDPD > 0].sort_values("NGDPD", ascending=False)
    selected = wide.head(top_n)
    if highlight and highlight not in set(selected.country_code):
        selected = pd.concat([selected, wide.loc[wide.country_code == highlight]], ignore_index=True)
    return selected.rename(columns={"NGDP_RPCH": "growth", "PCPIPCH": "inflation", "NGDPD": "gdp_billion_usd"})[
        ["country_code", "country_name", "growth", "inflation", "gdp_billion_usd"]
    ].reset_index(drop=True)
