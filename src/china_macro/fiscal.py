"""Selected national fiscal series from Ministry of Finance budget releases."""

from __future__ import annotations

from .paths import DATA_ROOT

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .catalog import INDICATORS
from .collector import HEADERS, LIMITS


ARCHIVE = "https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/quanguocaizhengshouzhiqingkuang/"
SNAPSHOT_ROOT = DATA_ROOT / "source_snapshots"
ARTICLE_HOST = "gks.mof.gov.cn"
# These national reports are present on the ministry's own article host
# but omitted from the shorter thematic archive pagination.
SUPPLEMENTAL_REPORTS = (
    ("https://gks.mof.gov.cn/tongjishuju/202112/t20211217_3775786.htm", "2021年11月财政收支情况", "2021-11", "2021-12-17"),
    ("https://gks.mof.gov.cn/tongjishuju/202201/t20220128_3785692.htm", "2021年财政收支情况", "2021-12", "2022-01-28"),
    ("https://gks.mof.gov.cn/tongjishuju/202203/t20220318_3796233.htm", "2022年1-2月财政收支情况", "2022-02", "2022-03-18"),
    ("https://gks.mof.gov.cn/tongjishuju/202310/t20231024_3912883.htm", "2023年前三季度财政收支情况", "2023-09", "2023-10-24"),
)
SERIES = {
    "fiscal_revenue_ytd": "全国一般公共预算收入",
    "fiscal_spending_ytd": "全国一般公共预算支出",
    "tax_revenue_ytd": "税收收入",
    "fund_revenue_ytd": "全国政府性基金预算收入",
    "land_revenue_ytd": "国有土地使用权出让收入",
}


def period_from_title(title: str) -> str | None:
    match = re.fullmatch(r"(20\d{2})年(.*?)财政收支情况", title.strip())
    if not match:
        return None
    year, span = match.groups()
    if span == "":
        month = 12
    elif span == "一季度":
        month = 3
    elif span == "上半年":
        month = 6
    elif span == "前三季度":
        month = 9
    else:
        numbered = re.fullmatch(r"(?:1[-—－至])?(\d{1,2})月", span)
        if not numbered:
            return None
        month = int(numbered.group(1))
    return f"{year}-{month:02d}" if 2 <= month <= 12 else None


def fiscal_links(session: requests.Session, pages: int = 1) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    found: dict[str, tuple[str, str, str]] = {}
    errors: list[str] = []
    if not 1 <= pages <= 9:
        raise ValueError("Fiscal archive page count outside supported bounds")
    for index in range(pages):
        listing = ARCHIVE if index == 0 else urljoin(ARCHIVE, f"index_{index}.html")
        try:
            response = session.get(listing, headers=HEADERS, timeout=(5, 18))
            response.raise_for_status()
            if len(response.content) > 2_000_000:
                raise ValueError("Fiscal directory unexpectedly large")
            soup = BeautifulSoup(response.content.decode("utf-8"), "html.parser")
            candidates = 0
            for a in soup.find_all("a", href=True):
                title = a.get_text(" ", strip=True)
                period = period_from_title(title)
                url = urljoin(listing, a["href"]).replace("http://gks.mof.gov.cn/", "https://gks.mof.gov.cn/")
                parsed = urlparse(url)
                if (period and parsed.scheme == "https" and parsed.hostname == ARTICLE_HOST
                        and re.fullmatch(r"/tongjishuju/20\d{4}/t20\d{6}_\d+\.htm", parsed.path)):
                    published_match = re.search(r"/t(20\d{2})(\d{2})(\d{2})_", parsed.path)
                    published = "-".join(published_match.groups()) if published_match else ""
                    found[url] = (title, period, published)
                    candidates += 1
            if not candidates:
                errors.append(f"财政部：目录第 {index + 1} 页未发现符合筛选条件的报告")
        except (requests.RequestException, UnicodeError, ValueError) as exc:
            errors.append(f"财政部：目录第 {index + 1} 页访问失败（{type(exc).__name__}）")
            break
        if index + 1 < pages:
            time.sleep(0.3)
    for url, title, period, published in SUPPLEMENTAL_REPORTS:
        found.setdefault(url, (title, period, published))
    links = [(url, title, period, published) for url, (title, period, published) in found.items()]
    return sorted(links, key=lambda row: row[2], reverse=True), errors


def parse_fiscal_html(content: bytes, url: str, title: str, period: str, published: str) -> list[dict]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ARTICLE_HOST:
        raise ValueError("Fiscal article source host is not allowlisted")
    if period_from_title(title) != period:
        raise ValueError("Fiscal title and period disagree")
    if len(content) > 2_000_000:
        raise ValueError("Fiscal article unexpectedly large")
    soup = BeautifulSoup(content.decode("utf-8"), "html.parser")
    actual_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if period_from_title(actual_title) != period:
        raise ValueError("Fiscal article title and directory disagree")
    article_date = soup.select_one(".laiyuan")
    date_match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日",
                           article_date.get_text(" ", strip=True) if article_date else "")
    if date_match:
        published = f"{date_match[1]}-{int(date_match[2]):02d}-{int(date_match[3]):02d}"
    body = soup.select_one(".TRS_Editor")
    if body is None:
        raise ValueError("Fiscal article body not found")
    text = re.sub(r"\s+", "", body.get_text("", strip=False)).replace(",", "，")
    rows = []
    values: dict[str, float] = {}
    for key, phrase in SERIES.items():
        # Require both the national series name and 亿元 so provincial values,
        # subtotals and unrelated spending categories cannot be substituted.
        match = re.search(re.escape(phrase) + r"(\d+(?:\.\d+)?)亿元", text)
        if not match:
            continue
        amount = float(match.group(1))
        lo, hi = LIMITS[key]
        if not lo <= amount <= hi:
            raise ValueError(f"Fiscal {key} outside expected range")
        values[key] = amount
        row_base = {"period": period, "source_url": url,
                    "source_title": actual_title, "published": published}
        rows.append({**row_base, "key": key, "value": amount})
        clause = text[match.end():match.end() + 36]
        # In 2022 the ministry often published both a tax-refund-adjusted
        # growth rate and a natural-basis rate. Retain the latter only.
        natural = re.search(r"按自然口径计算(增长|下降)(\d+(?:\.\d+)?)%", clause)
        change = natural or re.match(r"[，；。]?\s*(?:同比|比上年同期|比上年)(增长|下降|微增)(\d+(?:\.\d+)?)%", clause)
        flat = re.match(r"[，；。]?\s*(?:同比|比上年同期|比上年|与去年同期|与上年同期)持平", clause)
        if change or flat:
            yoy_key = key + "_yoy"
            if yoy_key not in INDICATORS:
                continue
            yoy = (-1 if change and change.group(1) == "下降" else 1) * float(change.group(2)) if change else 0.0
            lo, hi = LIMITS[yoy_key]
            if not lo <= yoy <= hi:
                raise ValueError(f"Fiscal {yoy_key} outside expected range")
            rows.append({**row_base, "key": yoy_key, "value": yoy})
    if not {"fiscal_revenue_ytd", "fiscal_spending_ytd"}.issubset(values):
        raise ValueError("Fiscal report is missing core national revenue or spending")
    if values.get("tax_revenue_ytd", 0) > values["fiscal_revenue_ytd"]:
        raise ValueError("Tax receipts exceed general public budget revenue")
    if values.get("land_revenue_ytd", 0) > values.get("fund_revenue_ytd", float("inf")):
        raise ValueError("Land receipts exceed government fund revenue")
    return rows


def save_fiscal_snapshot(content: bytes, url: str, rows: list[dict], root: Path = SNAPSHOT_ROOT) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"mof-fiscal-{digest}.html"
    if not path.exists():
        temporary = root / f".{path.name}.{os.getpid()}.tmp"
        temporary.write_bytes(content)
        os.replace(temporary, path)
    manifest = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_url": url, "source_title": rows[0]["source_title"],
                "period": rows[0]["period"], "published": rows[0]["published"],
                "sha256": digest, "observation_count": len(rows)}
    path.with_suffix(".meta.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def collect_fiscal(session: requests.Session | None = None, pages: int = 1,
                   recent_limit: int | None = 3, skip_urls: set[str] | None = None,
                   start_year: int | None = None) -> tuple[list[dict], list[str]]:
    session = session or requests.Session()
    links, errors = fiscal_links(session, pages)
    if start_year is not None:
        links = [link for link in links if int(link[2][:4]) >= start_year]
    if recent_limit is not None:
        links = links[:recent_limit]
    rows: list[dict] = []
    for url, title, period, published in links:
        if skip_urls and url in skip_urls:
            continue
        try:
            response = session.get(url, headers=HEADERS, timeout=(5, 18))
            response.raise_for_status()
            parsed = parse_fiscal_html(response.content, url, title, period, published)
            save_fiscal_snapshot(response.content, url, parsed)
            rows.extend(parsed)
        except (requests.RequestException, UnicodeError, ValueError) as exc:
            errors.append(f"财政部：{title} 获取或核验失败（{type(exc).__name__}）")
        time.sleep(0.3)
    return rows, errors
