"""Targeted replay and raw-source snapshots for selected NBS historical gaps."""

from __future__ import annotations

from .paths import DATA_ROOT

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from .collector import parse_nbs, parse_nbs_special


SNAPSHOT_ROOT = DATA_ROOT / "source_snapshots"
TARGETS = {
    "infrastructure_ex_utilities_ytd_yoy": ("infrastructure_ex_utilities_ytd_yoy", "investment"),
    "private_fai_ytd_yoy": ("manufacturing_fai_ytd_yoy", "investment"),
    "housing_sales_area_ytd_yoy": ("real_estate_fai_ytd_yoy", "estate"),
    "cpi_mom": ("cpi_yoy", "cpi"),
    "ppi_mom": ("ppi_yoy", "ppi"),
    "cpi_yoy": ("cpi_yoy", "cpi"),
    "ppi_yoy": ("ppi_yoy", "ppi"),
    "export_yoy": ("export_yoy", "overview"),
    "import_yoy": ("import_yoy", "overview"),
    "unemployment": ("unemployment", "overview"),
    "manufacturing_pmi": ("manufacturing_pmi", "pmi"),
    "manufacturing_new_orders_pmi": ("manufacturing_new_orders_pmi", "pmi"),
    "nonmanufacturing_pmi": ("nonmanufacturing_pmi", "pmi"),
    "retail_yoy": ("retail_yoy", "retail"),
}
# The stored同比 reading sometimes came from the later monthly overview. These
# are the corresponding earlier price releases with an explicit环比 reading.
PRICE_SOURCE_OVERRIDES = {
    ("cpi_mom", "2021-09"): ("https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901237.html", "2021年9月份居民消费价格同比上涨0.7% 环比持平", "2021-10-14"),
    ("cpi_mom", "2024-03"): ("https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202404/t20240411_1948448.html", "2024年3月份居民消费价格同比上涨0.1%", "2024-04-11"),
    ("cpi_mom", "2024-09"): ("https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202410/t20241013_1956899.html", "2024年9月份居民消费价格同比上涨0.4%", "2024-10-13"),
    ("cpi_mom", "2025-03"): ("https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202504/t20250410_1959261.html", "2025年3月份居民消费价格同比下降0.1%", "2025-04-10"),
    ("cpi_mom", "2026-06"): ("https://www.stats.gov.cn/zwfwck/sjfb/202607/t20260709_1964084.html", "2026年6月份居民消费价格同比上涨1.0%", "2026-07-09"),
    ("ppi_mom", "2024-03"): ("https://www.stats.gov.cn/sj/zxfb/202404/t20240411_1948465.html", "2024年3月份工业生产者出厂价格同比下降2.8%", "2024-04-11"),
    ("ppi_mom", "2025-03"): ("https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202504/t20250410_1959260.html", "2025年3月份工业生产者出厂价格同比下降2.5%", "2025-04-10"),
    ("ppi_mom", "2025-07"): ("https://www.stats.gov.cn/sj/zxfb/202508/t20250809_1960634.html", "2025年7月份工业生产者出厂价格环比降幅收窄", "2025-08-09"),
    ("ppi_mom", "2026-06"): ("https://www.stats.gov.cn/sj/zxfb/202607/t20260709_1964083.html", "2026年6月份工业生产者出厂价格同比上涨4.1% 环比下降0.3%", "2026-07-09"),
}

# These specialist releases supply periods missing from the original price
#同比 series. Both national同比 and环比 readings are replayed from each report.
PRICE_MISSING_REPORTS = (
    ("cpi", "2024-01", "https://www.stats.gov.cn/sj/zxfb/202402/t20240208_1947623.html", "2024年1月份居民消费价格环比上涨0.3%", "2024-02-08"),
    ("ppi", "2021-09", "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901238.html", "2021年9月份工业生产者出厂价格同比上涨10.7% 环比上涨1.2%", "2021-10-14"),
    ("ppi", "2024-01", "https://www.stats.gov.cn/sj/zxfb/202402/t20240208_1947624.html", "2024年1月份工业生产者出厂价格降幅收窄", "2024-02-08"),
    ("ppi", "2024-12", "https://www.stats.gov.cn/sj/zxfb/202501/t20250109_1958169.html", "2024年12月份工业生产者出厂价格同比降幅收窄", "2025-01-09"),
    ("ppi", "2025-01", "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202502/t20250209_1958645.html", "2025年1月份工业生产者出厂价格同比下降2.3%", "2025-02-09"),
    ("ppi", "2026-03", "https://www.stats.gov.cn/sj/zxfb/202604/t20260410_1963263.html", "2026年3月份工业生产者出厂价格同比由降转涨 环比涨幅扩大", "2026-04-10"),
)

# Period, official article, original release date, report type, expected keys.
# Every value must be present in the report; the backfill rejects the batch if
# a source is unavailable or an expected monthly reading cannot be confirmed.
SELECTED_NBS_REPORTS = (
    ("2024-02", "https://www.stats.gov.cn/sj/zxfb/202403/t20240322_1948131.html", "2024-03-18", "investment", ("infrastructure_ex_utilities_ytd_yoy",)),
    ("2024-03", "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202404/t20240416_1948569.html", "2024-04-16", "investment", ("infrastructure_ex_utilities_ytd_yoy",)),
    ("2021-09", "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901240.html", "2021-10-18", "overview", ("export_yoy", "import_yoy")),
    ("2022-03", "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901427.html", "2022-04-18", "overview", ("export_yoy", "import_yoy")),
    ("2022-05", "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901486.html", "2022-06-15", "overview", ("export_yoy", "import_yoy")),
    ("2023-06", "https://www.stats.gov.cn/sj/zxfb/202307/t20230715_1941271.html", "2023-07-17", "overview", ("export_yoy", "import_yoy")),
    ("2023-09", "https://www.stats.gov.cn/sj/zxfb/202310/t20231018_1943654.html", "2023-10-18", "overview", ("export_yoy", "import_yoy")),
    ("2024-03", "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202404/t20240416_1948561.html", "2024-04-16", "overview", ("export_yoy", "import_yoy")),
    ("2024-06", "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202407/t20240715_1955618.html", "2024-07-15", "overview", ("export_yoy", "import_yoy")),
    ("2024-09", "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202410/t20241018_1957044.html", "2024-10-18", "overview", ("export_yoy", "import_yoy")),
    ("2025-03", "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202504/t20250416_1959321.html", "2025-04-16", "overview", ("export_yoy", "import_yoy")),
    ("2025-06", "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202507/t20250715_1960414.html", "2025-07-15", "overview", ("export_yoy", "import_yoy")),
    ("2026-06", "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202607/t20260715_1964121.html", "2026-07-15", "overview", ("export_yoy", "import_yoy")),
    ("2021-10", "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901278.html", "2021-11-15", "overview", ("export_yoy", "import_yoy", "unemployment")),
    ("2021-12", "https://www.stats.gov.cn/sj/xwfbh/fbhwd/202302/t20230203_1901336.html", "2022-01-17", "overview", ("export_yoy", "import_yoy", "unemployment")),
    ("2022-04", "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901460.html", "2022-05-16", "overview", ("unemployment",)),
    ("2022-06", "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901513.html", "2022-07-15", "overview", ("export_yoy", "import_yoy", "unemployment")),
    ("2022-12", "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202301/t20230117_1892123.html", "2023-01-17", "overview", ("export_yoy", "import_yoy", "unemployment")),
    ("2023-03", "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202304/t20230418_1938732.html", "2023-04-18", "overview", ("export_yoy", "import_yoy", "unemployment")),
    ("2023-12", "https://www.stats.gov.cn/sj/zxfb/202401/t20240117_1946624.html", "2024-01-17", "overview", ("export_yoy", "import_yoy", "unemployment")),
    ("2024-12", "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202501/t20250117_1958332.html", "2025-01-17", "overview", ("export_yoy", "import_yoy", "unemployment")),
    ("2025-09", "https://www.stats.gov.cn/zwfwck/sjfb/202510/t20251020_1961612.html", "2025-10-20", "overview", ("export_yoy", "import_yoy", "unemployment")),
    ("2025-12", "https://www.stats.gov.cn/sj/zxfb/202601/t20260119_1962330.html", "2026-01-19", "overview", ("export_yoy", "import_yoy", "unemployment")),
    ("2026-03", "https://www.stats.gov.cn/sj/zxfb/202604/t20260416_1963330.html", "2026-04-16", "overview", ("unemployment",)),
    ("2021-09", "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901233.html", "2021-09-30", "pmi", ("manufacturing_pmi", "manufacturing_new_orders_pmi", "nonmanufacturing_pmi")),
    ("2021-10", "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901269.html", "2021-10-31", "pmi", ("manufacturing_pmi",)),
    ("2021-12", "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901325.html", "2021-12-31", "pmi", ("manufacturing_pmi",)),
    ("2022-01", "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901362.html", "2022-01-30", "pmi", ("manufacturing_pmi",)),
    ("2024-01", "https://www.stats.gov.cn/sj/zxfb/202401/t20240131_1947009.html", "2024-01-31", "pmi", ("manufacturing_pmi", "manufacturing_new_orders_pmi", "nonmanufacturing_pmi")),
    ("2021-12", "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901341.html", "2022-01-17", "retail", ("retail_yoy",)),
)


def parse_target(soup: BeautifulSoup, source: dict, target_key: str) -> dict | None:
    if target_key not in TARGETS:
        raise ValueError("Unknown targeted NBS series")
    if not source["source_url"].startswith("https://www.stats.gov.cn/"):
        raise ValueError("Target source is not the official NBS host")
    kind = TARGETS[target_key][1]
    parser = parse_nbs if kind == "overview" else parse_nbs_special
    args = (soup, source["source_url"], source["source_title"])
    if kind == "overview":
        rows = parser(*args, period_override=source["period"], published_hint=source["published"])
    else:
        rows = parser(*args, kind, period_override=source["period"], published_hint=source["published"])
    matches = [row for row in rows if row["key"] == target_key and row["period"] == source["period"]]
    return matches[0] if len(matches) == 1 else None


def save_snapshot(content: bytes, source: dict, row: dict,
                  root: Path = SNAPSHOT_ROOT) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"nbs-gap-{digest}.html"
    if not path.exists():
        temporary = root / f".{path.name}.{os.getpid()}.tmp"
        temporary.write_bytes(content)
        os.replace(temporary, path)
    manifest = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": digest, "key": row["key"], "period": row["period"],
        "value": row["value"], "source_url": source["source_url"],
        "source_title": source["source_title"], "published": source["published"],
    }
    # A single article can legitimately supply more than one targeted series.
    meta = root / f"nbs-gap-{digest}-{row['key']}.meta.json"
    meta.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
