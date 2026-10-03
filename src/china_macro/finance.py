"""Selected PBC reports and explicit rates in annual statistical tables.

Stocks are never converted into reported growth rates or loan flows. Old M1
and the revised M1, including the bank's 2024 backcast, are separate series.
"""
from __future__ import annotations

from .paths import DATA_ROOT

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .collector import (HEADERS, PBC_LIST, SourceAccessBlocked, compact,
                       directory_publication_date, fetch, find_change,
                       month_from_title, record)

TABLE_LIST = "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"
SNAPSHOT_ROOT = DATA_ROOT / "source_snapshots"
# This national report is absent from the statistics department directory but
# remains in the bank's news directory (original publication 2025-02-14).
SUPPLEMENTAL_REPORTS = (
    {"source_url": "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/2025092212554572702/index.html",
     "source_title": "2025年1月金融统计数据报告", "published": "2025-02-14"},
)


def parse_financial_report(soup: BeautifulSoup, url: str, title: str,
                           published_hint: str = "") -> list[dict]:
    if urlparse(url).scheme != "https" or urlparse(url).hostname != "www.pbc.gov.cn":
        raise ValueError("Not the national PBC source")
    period = month_from_title(title, url, published_hint)
    content = soup.select_one(".content")
    if not period or not content:
        return []
    text = compact(content.get_text())
    text = re.split(r"注1[:：]|注：", text, maxsplit=1)[0]
    # The same article can include the TSF loan component. The loan patterns
    # require an explicit reporting-period prefix and national loan wording.
    results = {
        "m1_yoy" if period >= "2025-01" else "m1_legacy_yoy": find_change(
            text, r"狭义货币[（(]M1[）)]余额\d+(?:\.\d+)?万亿元[，,。]?"),
        "m2_yoy": find_change(text, r"广义货币[（(]M2[）)]余额\d+(?:\.\d+)?万亿元[，,。]?"),
        "tsf_stock_yoy": find_change(text, r"社会融资规模存量为\d+(?:\.\d+)?万亿元[，,。]?"),
    }
    month = int(period[-2:])
    words = {2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十", 11: "十一", 12: "十二"}
    prefixes = [rf"(?:今年)?前(?:{month}|{words.get(month, '一')})个月",
                rf"1[—－-]{month}月"]
    if month == 2:
        prefixes.append(r"(?:今年)?前两个月")
    if month == 1:
        prefixes.append(r"(?<![\d—－-])1月份?")
    if month in (3, 6, 9, 12):
        prefixes.append({3: "一季度", 6: "上半年", 9: "前三季度", 12: "全年"}[month])
    values = set()
    for match in re.finditer("(?:" + "|".join(prefixes) + r")[，,]?人民币贷款(?:累计)?增加(\d+(?:\.\d+)?)(万亿元|亿元)", text):
        values.add(round(float(match[1]) / (10000 if match[2] == "亿元" else 1), 3))
    if len(values) > 1:
        raise ValueError("Conflicting explicitly stated cumulative loan values")
    results["loans_ytd"] = next(iter(values)) if values else None
    return [row for key, value in results.items()
            if (row := record(key, value, period, url, title, published_hint))]


def discover_reports(session: requests.Session, start_year: int = 2021,
                     through_year: int | None = None, pages: int = 1) -> list[dict]:
    found = {}
    url = PBC_LIST
    for _ in range(pages):
        soup = fetch(session, url)
        years = []
        for a in soup.find_all("a", href=True):
            title = a.get_text(" ", strip=True)
            if not re.fullmatch(r"20\d{2}年.*金融统计数据报告", title):
                continue
            year = int(title[:4])
            years.append(year)
            href = urljoin(url, a["href"])
            if year < start_year or (through_year and year > through_year):
                continue
            if urlparse(href).hostname != "www.pbc.gov.cn":
                continue
            context = a.parent.parent.get_text(" ", strip=True)
            published = directory_publication_date(context)
            found[href] = {"source_url": href, "source_title": title, "published": published}
        if years and min(years) < start_year:
            break
        # Follow only pagination emitted by the directory itself.
        next_link = next((a for a in soup.find_all("a")
                          if a.get_text(strip=True) == "下一页"), None)
        match = re.search(r"['\"](/diaochatongjisi/116219/116225/[^'\"]+\.html)['\"]",
                          next_link.get("onclick", "")) if next_link else None
        if not match:
            break
        url = urljoin(PBC_LIST, match[1])
        time.sleep(0.4)
    if pages > 1:
        for source in SUPPLEMENTAL_REPORTS:
            year = int(source["source_title"][:4])
            if start_year <= year and (through_year is None or year <= through_year):
                found[source["source_url"]] = source
    return sorted(found.values(), key=lambda item: (item["published"], item["source_url"]))


def table_grid(table: BeautifulSoup) -> list[list[str]]:
    """Expand actual table spans; keep the header and value columns aligned."""
    grid = []
    carry: dict[int, tuple[str, int]] = {}
    for tr in table.find_all("tr"):
        current = {col: text for col, (text, _) in carry.items()}
        upcoming = {col: (text, remaining - 1) for col, (text, remaining) in carry.items()
                    if remaining > 1}
        col = 0
        for cell in tr.find_all(["td", "th"], recursive=False):
            while col in current:
                col += 1
            text = compact(cell.get_text(" ", strip=True))
            width, height = int(cell.get("colspan", 1)), int(cell.get("rowspan", 1))
            if not (1 <= width <= 100 and 1 <= height <= 100):
                raise ValueError("Invalid table span")
            for offset in range(width):
                current[col + offset] = text
                if height > 1:
                    upcoming[col + offset] = (text, height - 1)
            col += width
        grid.append([current.get(i, "") for i in range(max(current, default=-1) + 1)])
        carry = upcoming
    return grid


def parse_tsf_table(soup: BeautifulSoup, source: dict) -> list[dict]:
    year = source["year"]
    text = compact(soup.get_text())
    if "社会融资规模存量统计表" not in text or "万亿元人民币" not in text:
        raise ValueError("Not an explicit TSF stock table")
    found = {}
    for table in soup.find_all("table"):
        months, rate_columns = {}, set()
        for cells in table_grid(table):
            for col, cell in enumerate(cells):
                match = re.fullmatch(rf"{year}[.](\d{{1,2}})", cell)
                if match and 1 <= int(match[1]) <= 12:
                    months[col] = f"{year}-{int(match[1]):02d}"
                if cell in {"增速（%）", "增速(%)"}:
                    rate_columns.add(col)
            if cells and re.match(r"^社会融资规模存量(?:AFRE\(stock\))?$", cells[0]):
                for col in rate_columns:
                    if col not in months or col >= len(cells):
                        raise ValueError("TSF growth column lacks a month header")
                    if not cells[col] or cells[col] in {"—", "-"}:
                        continue
                    if not re.fullmatch(r"-?\d+(?:\.\d+)?", cells[col]):
                        raise ValueError("Invalid reported TSF growth rate")
                    row = record("tsf_stock_yoy", float(cells[col]), months[col],
                                 source["source_url"], source["source_title"], source.get("published", ""))
                    if row is None or (row["period"] in found and found[row["period"]] != row):
                        raise ValueError("Conflicting or invalid TSF table value")
                    found[row["period"]] = row
    if not found:
        raise ValueError("TSF total growth row unavailable")
    return list(found.values())


def parse_m1_backcast(soup: BeautifulSoup, source: dict) -> list[dict]:
    text = compact(soup.get_text())
    if "2025年1月份" not in text or "按可比口径回溯" not in text or "2024年" not in text:
        raise ValueError("Official revised M1 backcast note missing")
    found = {}
    for table in soup.find_all("table"):
        months = {}
        for cells in table_grid(table):
            for col, cell in enumerate(cells):
                match = re.fullmatch(r"2024[.](\d{1,2})", cell)
                if match and 1 <= int(match[1]) <= 12:
                    months[col] = f"2024-{int(match[1]):02d}"
            if "同比增速" in cells and months:
                for col, period in months.items():
                    if col >= len(cells) or not re.fullmatch(r"-?\d+(?:\.\d+)?%", cells[col]):
                        raise ValueError("Invalid M1 backcast growth cell")
                    row = record("m1_yoy", float(cells[col].rstrip("%")), period,
                                 source["source_url"], source["source_title"], source.get("published", ""))
                    if row is None:
                        raise ValueError("M1 backcast outside guardrail")
                    if period in found and found[period] != row:
                        raise ValueError("Conflicting M1 backcast")
                    found[period] = row
    if len(found) != 12:
        raise ValueError("Incomplete official 2024 M1 backcast")
    return list(found.values())


def fetch_table(session: requests.Session, url: str) -> tuple[BeautifulSoup, bytes]:
    if not url.startswith("https://www.pbc.gov.cn/diaochatongjisi/") or not url.endswith(".htm"):
        raise ValueError("Not an allowlisted PBC statistical HTML table")
    response = session.get(url, headers=HEADERS, timeout=(5, 18))
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise ValueError("Table unexpectedly large")
    html = response.content.decode("latin1")  # Verification markers are ASCII.
    if any(marker in html for marker in ("__jsl_clearance", "document.cookie", "Please enable JavaScript")):
        raise SourceAccessBlocked("PBC table returned access verification")
    soup = BeautifulSoup(response.content, "html.parser")
    if not soup.find("table"):
        raise ValueError("No official statistical table")
    return soup, response.content


def discover_tables(session: requests.Session, start_year: int, through_year: int) -> list[dict]:
    soup = fetch(session, TABLE_LIST)
    categories = {}
    year = None
    for a in soup.find_all("a", href=True):
        label = a.get_text(strip=True)
        match = re.fullmatch(r"(20\d{2})年统计数据", label)
        if match:
            year = int(match[1])
        if year and start_year <= year <= through_year and (
                label == "社会融资规模" or (year == 2025 and label == "货币统计概览")):
            categories[(year, label)] = urljoin(TABLE_LIST, a["href"])
    sources = []
    for (year, label), url in categories.items():
        page = fetch(session, url)
        # Each table's htm/xls/pdf links are in the same row as its label.
        target = "社会融资规模存量统计表" if label == "社会融资规模" else "货币供应量"
        matches = [a for a in page.find_all("a", href=True)
                   if a.get_text(strip=True).lower() == "htm"
                   and target in a.parent.parent.get_text()]
        if len(matches) != 1:
            raise ValueError(f"Ambiguous official {year} {target} HTML table")
        href = urljoin(url, matches[0]["href"])
        sources.append({"source_url": href, "source_title": f"{year}年{target}" + (
            "（含2024年M1新口径官方回溯）" if target == "货币供应量" else ""),
            "year": year, "published": "", "kind": "tsf_table" if label == "社会融资规模" else "m1_backcast"})
        time.sleep(0.4)
    return sources


def replay_snapshot(raw: bytes, source: dict) -> list[dict]:
    soup = BeautifulSoup(raw, "html.parser")
    parsers = {"tsf_table": parse_tsf_table, "m1_backcast": parse_m1_backcast}
    if source["kind"] == "financial_report":
        return parse_financial_report(soup, source["source_url"], source["source_title"], source.get("published", ""))
    if source["kind"] not in parsers:
        raise ValueError("Unknown financial source type")
    if not source["source_url"].startswith("https://www.pbc.gov.cn/"):
        raise ValueError("Not an official PBC source")
    return parsers[source["kind"]](soup, source)


def save_snapshot(raw: bytes, source: dict, rows: list[dict], root: Path = SNAPSHOT_ROOT) -> dict:
    digest = hashlib.sha256(raw).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    stem = f"pbc-{digest}-{source['kind']}"
    (root / f"{stem}.html").write_bytes(raw)
    manifest = {**{key: source[key] for key in ("source_url", "source_title", "year", "published", "kind") if key in source},
                "sha256": digest, "file": f"{stem}.html", "record_count": len(rows),
                "fetched_at": source.get("fetched_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "rows": [{key: row[key] for key in ("key", "period", "value")} for row in rows]}
    (root / f"{stem}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def collect_finance(session: requests.Session | None = None) -> tuple[list[dict], list[str]]:
    session = session or requests.Session()
    rows, errors = [], []
    try:
        sources = discover_reports(session)
        if not sources:
            raise ValueError("No selected financial reports")
        for source in sources:
            try:
                _, raw = fetch(session, source["source_url"], include_raw=True)
                source = {**source, "kind": "financial_report"}
                parsed = replay_snapshot(raw, source)
                if not parsed:
                    raise ValueError("Report did not contain selected readings")
                save_snapshot(raw, source, parsed)
                rows.extend(parsed)
            except SourceAccessBlocked:
                errors.append("中国人民银行：遇到访问验证，暂停本批剩余报告")
                break
            except (requests.RequestException, ValueError, UnicodeError) as exc:
                errors.append(f"中国人民银行：{source['source_title']} 获取或核验失败（{type(exc).__name__}）")
            time.sleep(0.4)
        # Use the current annual stock table after monthly reports so routine
        # refreshes retain the bank's table revisions instead of restoring old
        # report values or repeatedly switching provenance.
        years = [int(source["source_title"][:4]) for source in sources]
        try:
            for source in discover_tables(session, min(years), max(years)):
                if source["kind"] != "tsf_table":
                    continue
                _, raw = fetch_table(session, source["source_url"])
                parsed = replay_snapshot(raw, source)
                save_snapshot(raw, source, parsed)
                rows.extend(parsed)
                time.sleep(0.4)
        except (requests.RequestException, ValueError, UnicodeError) as exc:
            errors.append(f"中国人民银行：年度社融存量表获取或核验失败（{type(exc).__name__}）")
    except (requests.RequestException, ValueError, UnicodeError) as exc:
        errors.append(f"中国人民银行：目录获取失败（{type(exc).__name__}）")
    return rows, errors
