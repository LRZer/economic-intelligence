"""Fetch only selected NBS releases and PBC financial statistical reports."""

from __future__ import annotations

import re
import time
from datetime import date
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .catalog import INDICATORS

# The NBS information-disclosure archive republishes the same official releases
# and has stable static pagination. The main /sj/zxfb/ directory intermittently
# responds with an HTTP-200 JavaScript verification page.
NBS_LISTS = {
    "disclosure": "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/",
    "main": "https://www.stats.gov.cn/sj/zxfb/",
}
NBS_LIST = NBS_LISTS["disclosure"]
PBC_LIST = "https://www.pbc.gov.cn/diaochatongjisi/116219/116225/index.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ChinaMacroObservatory/1.0; curated public data)"}
LIMITS = {
    "industrial_yoy": (-50, 80), "retail_yoy": (-50, 80), "fai_ytd_yoy": (-50, 80),
    "private_fai_ytd_yoy": (-80, 150), "manufacturing_fai_ytd_yoy": (-80, 150),
    "infrastructure_fai_ytd_yoy": (-80, 150), "infrastructure_ex_utilities_ytd_yoy": (-80, 150),
    "real_estate_fai_ytd_yoy": (-80, 150),
    "housing_sales_area_ytd_yoy": (-80, 150), "industrial_profit_ytd_yoy": (-100, 300),
    "export_yoy": (-70, 150), "import_yoy": (-70, 150), "unemployment": (0, 30),
    "export_usd": (0, 10000), "import_usd": (0, 10000),
    "export_usd_yoy": (-80, 200), "import_usd_yoy": (-80, 200),
    "cpi_yoy": (-20, 30), "cpi_mom": (-10, 10),
    "ppi_yoy": (-50, 80), "ppi_mom": (-15, 15), "manufacturing_pmi": (20, 80),
    "manufacturing_new_orders_pmi": (20, 80), "nonmanufacturing_pmi": (20, 80),
    "m1_yoy": (-50, 100), "m1_legacy_yoy": (-50, 100), "m2_yoy": (-50, 100), "tsf_stock_yoy": (-50, 100),
    "loans_ytd": (0, 100),
    "fiscal_revenue_ytd": (0, 300000), "fiscal_revenue_ytd_yoy": (-60, 80),
    "fiscal_spending_ytd": (0, 400000), "fiscal_spending_ytd_yoy": (-60, 80),
    "tax_revenue_ytd": (0, 250000), "tax_revenue_ytd_yoy": (-60, 80),
    "fund_revenue_ytd": (0, 150000), "fund_revenue_ytd_yoy": (-80, 100),
    "land_revenue_ytd": (0, 120000), "land_revenue_ytd_yoy": (-80, 100),
}
MONTH_WORDS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}


class SourceAccessBlocked(ValueError):
    """An official source returned an access-verification page."""


def fetch(session: requests.Session, url: str, *, include_raw: bool = False) -> BeautifulSoup | tuple[BeautifulSoup, bytes]:
    host = urlparse(url).hostname
    if host not in {"www.stats.gov.cn", "www.pbc.gov.cn"} or not url.startswith("https://"):
        raise ValueError("Source host is not allowlisted")
    response = session.get(url, headers=HEADERS, timeout=(5, 18))
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise ValueError("Source page is unexpectedly large")
    html = response.content.decode("utf-8")
    if ("Please enable JavaScript" in html or "__jsl_clearance" in html
            or "acw_sc__v2" in html or "document.cookie" in html[:3000]):
        raise SourceAccessBlocked("Official source returned an access verification page")
    soup = BeautifulSoup(html, "html.parser")
    if not soup.find("a") and not soup.select_one(".trs_editor_view, .TRS_Editor, .content"):
        raise ValueError("Official source did not return an article or directory")
    return (soup, response.content) if include_raw else soup


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text).replace("−", "-").replace("－", "-")


def month_from_title(title: str, publication_url: str, published_hint: str = "") -> str | None:
    year_match = re.search(r"(20\d{2})年", title)
    url_month = re.search(r"/(20\d{2})(\d{2})/", publication_url)
    pub_match = re.match(r"(20\d{2})-(\d{2})-\d{2}$", published_hint)
    year = (int(year_match.group(1)) if year_match else
            int(pub_match.group(1)) if pub_match else
            int(url_month.group(1)) if url_month else date.today().year)
    number_match = re.search(r"(?:\d+[—－-])?(\d{1,2})月份?", title)
    if number_match:
        month = int(number_match.group(1))
    elif "上半年" in title:
        month = 6
    elif "一季度" in title:
        month = 3
    elif "前三季度" in title:
        month = 9
    elif re.match(r"20\d{2}年(?:全国)?(?:固定资产投资|房地产市场|房地产开发投资|规模以上工业企业利润|金融统计数据报告)", title):
        # Year-end cumulative reports are released in the following January.
        month = 12
    else:
        return None
    publication_month = int(pub_match.group(2)) if pub_match else (int(url_month.group(2)) if url_month else None)
    if not year_match and publication_month is not None and month > publication_month:
        year -= 1
    return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None


def signed_change(direction: str, number: str) -> float:
    value = float(number)
    return -value if direction in {"下降", "下跌", "减少"} else value


def find_change(text: str, pattern: str) -> float | None:
    match = re.search(pattern + r"同比(增长|上涨|下降|下跌|减少)(\d+(?:\.\d+)?)%", text)
    return signed_change(*match.groups()) if match else None


def record(key: str, value: float | None, period: str, url: str, title: str, published: str = "") -> dict | None:
    if value is None or key not in INDICATORS:
        return None
    low, high = LIMITS[key]
    if not low <= value <= high:
        return None
    return {"key": key, "value": round(value, 3), "period": period, "source_url": url,
            "source_title": title, "published": published}


def nbs_publication_date(soup: BeautifulSoup) -> str:
    meta = soup.find("meta", attrs={"name": re.compile(r"^PubDate$", re.I)})
    raw = meta.get("content", "") if meta else ""
    match = re.search(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})", raw)
    return f"{match[1]}-{int(match[2]):02d}-{int(match[3]):02d}" if match else ""


NBS_REPORT_TYPES = {
    "overview": lambda title: ("国民经济" in title or "上半年经济运行" in title) and ("月份" in title or "上半年" in title or "一季度" in title or "前三季度" in title) and "公报" not in title,
    "industry": lambda title: "规模以上工业增加值" in title,
    "retail": lambda title: "社会消费品零售总额" in title,
    "investment": lambda title: "全国固定资产投资" in title and ("基本情况" in title or "增长" in title or "下降" in title),
    "estate": lambda title: "全国房地产市场基本情况" in title or "全国房地产开发投资" in title,
    "cpi": lambda title: "居民消费价格" in title and "月份" in title,
    "ppi": lambda title: "工业生产者出厂价格" in title and "月份" in title,
    "pmi": lambda title: "中国采购经理指数运行情况" in title,
    "profit": lambda title: "规模以上工业企业利润" in title,
}


def report_type(title: str) -> str | None:
    return next((name for name, matches in NBS_REPORT_TYPES.items() if matches(title)), None)


def directory_publication_date(text: str) -> str:
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?", text)
    return f"{match[1]}-{int(match[2]):02d}-{int(match[3]):02d}" if match else ""


def nbs_links(session: requests.Session, pages: int = 4, start_year: int | None = None,
              through_year: int | None = None, archive: str = "disclosure",
              errors: list[str] | None = None) -> list[tuple[str, str, str, str, str]]:
    found = {}
    errors = errors if errors is not None else []
    if archive not in NBS_LISTS:
        raise ValueError("Unknown NBS archive")
    listing = NBS_LISTS[archive]
    article_path = (r"/xxgk/sjfb/zxfb2020/" if archive == "disclosure"
                    else r"/sj/zxfb/")
    # The archive is filtered by named national releases before article requests.
    for page in range(pages):
        url = listing if page == 0 else urljoin(listing, f"index_{page}.html")
        try:
            soup = fetch(session, url)
        except (requests.RequestException, UnicodeError, ValueError) as exc:
            errors.append(f"国家统计局：目录第 {page + 1} 页访问失败（{type(exc).__name__}）；后续目录未读取")
            break
        for a in soup.find_all("a", href=True):
            title = a.get_text(" ", strip=True)
            href = urljoin(url, a["href"])
            kind = report_type(title)
            context = a.parent.get_text(" ", strip=True) if a.parent else ""
            published = directory_publication_date(context)
            period = month_from_title(title, href, published) if kind else None
            if (kind and period and (start_year is None or int(period[:4]) >= start_year)
                    and (through_year is None or int(period[:4]) <= through_year)
                    and re.search(article_path + r"20\d{4}/t\d+_\d+\.html$", href)):
                if len(title) > len(found.get(href, ("", ""))[0]):
                    found[href] = (title, kind, period, published)
        time.sleep(0.4)
    # Overview first; specialist releases take priority for overlapping values.
    return [(url, title, kind, period, published) for url, (title, kind, period, published) in sorted(
        found.items(), key=lambda pair: (pair[1][1] != "overview", pair[0]))]


def first_change(text: str, pattern: str) -> float | None:
    match = re.search(pattern + r"(?:同比|比上年同期)(?:实际)?(增长|上涨|下降|下跌|减少)(\d+(?:\.\d+)?)%", text)
    if match:
        return signed_change(*match.groups())
    return 0.0 if re.search(pattern + r"(?:同比|与上年同期)持平", text) else None


def contextual_change(text: str, pattern: str) -> float | None:
    """For a subseries inside an explicitly year-to-date同比 paragraph."""
    match = re.search(pattern + r"(?:同比)?(增长|上涨|下降|下跌|减少)(\d+(?:\.\d+)?)%", text)
    return signed_change(*match.groups()) if match else None


def direct_change(text: str, pattern: str) -> float | None:
    """Read a directly stated rate, including an explicit flat reading."""
    match = re.search(pattern + r"(增长|上涨|下降|下跌|减少)(\d+(?:\.\d+)?)%", text)
    if match:
        return signed_change(*match.groups())
    return 0.0 if re.search(pattern + r"(?:基本)?持平", text) else None


def ppi_month_change(text: str) -> float | None:
    """Read the producer output-price month rate, never the purchasing-price rate."""
    intro = text.split("一、", 1)[0]
    mentions = list(re.finditer(r"工业生产者出厂价格", intro))
    for mention in mentions:
        next_output = intro.find("工业生产者出厂价格", mention.end())
        next_input = intro.find("工业生产者购进价格", mention.end())
        stops = [position for position in (next_output, next_input) if position >= 0]
        segment = intro[mention.end():min(stops) if stops else len(intro)]
        rate = re.search(r"环比(.{0,45})", segment)
        if rate is None:
            continue
        phrase = re.split(r"[；。]", rate.group(1), maxsplit=1)[0]
        # "由上月下降转为上涨" reports the current month after 转为.
        if "转为" in phrase:
            phrase = phrase.split("转为", 1)[1]
        value = direct_change(phrase, r"(?:分别|均|继续)?")
        if value is not None:
            return value
    return None


def price_table_rates(content: BeautifulSoup, kind: str) -> tuple[float, float] | None:
    """Read the national headline row under explicit month/year columns."""
    target = r"居民消费价格" if kind == "cpi" else r"(?:一、)?工业生产者出厂价格"
    results: set[tuple[float, float]] = set()
    for table in content.find_all("table"):
        columns: tuple[int, int] | None = None
        for tr in table.find_all("tr"):
            cells = [compact(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"], recursive=False)]
            if not cells:
                continue
            monthly = next((i for i, cell in enumerate(cells) if "环比涨跌幅" in cell), None)
            yearly = next((i for i, cell in enumerate(cells) if "同比涨跌幅" in cell and "月" not in cell), None)
            if monthly is not None and yearly is not None:
                columns = (monthly, yearly)
                continue
            if columns and re.fullmatch(target, cells[0]) and max(columns) < len(cells):
                raw = (cells[columns[0]], cells[columns[1]])
                if all(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value) for value in raw):
                    results.add((float(raw[0]), float(raw[1])))
    if len(results) > 1:
        raise ValueError("Conflicting national price table rows")
    return next(iter(results)) if results else None


def annual_change(text: str, pattern: str, comparison_required: bool = True) -> float | None:
    comparison = r"(?:比上年|同比)" if comparison_required else r"(?:比上年|同比)?"
    match = re.search(pattern + comparison + r"(增长|上涨|下降|下跌|减少)(\d+(?:\.\d+)?)%", text)
    return signed_change(*match.groups()) if match else None


def parse_nbs_annual(soup: BeautifulSoup, url: str, title: str, kind: str,
                     period: str, published_hint: str = "") -> list[dict]:
    content = soup.select_one(".trs_editor_view, .TRS_Editor")
    if not content or kind not in {"investment", "estate", "profit"} or not period.endswith("-12"):
        return []
    text = compact(content.get_text("", strip=False))
    # Anchored narrative phrases avoid table columns and the annual report's
    # early parenthetical references to its own footnotes.
    values: dict[str, float | None] = {}
    if kind == "investment":
        values["fai_ytd_yoy"] = annual_change(text, r"全国固定资产投资（不含农户）\d+(?:\.\d+)?亿元[，,]")
        values["private_fai_ytd_yoy"] = annual_change(
            text, r"民间固定资产投资(?:\d+(?:\.\d+)?亿元[，,]?)?", False)
        values["manufacturing_fai_ytd_yoy"] = annual_change(text, r"制造业投资", False)
        values["infrastructure_ex_utilities_ytd_yoy"] = annual_change(
            text, r"基础设施投资（不含电力、热力、燃气及水生产和供应业）", False)
    elif kind == "estate":
        values["real_estate_fai_ytd_yoy"] = annual_change(
            text, r"全国房地产开发投资\d+(?:\.\d+)?亿元[，,]")
        values["housing_sales_area_ytd_yoy"] = annual_change(
            text, r"(?:新建)?商品房销售面积\d+(?:\.\d+)?万平方米[，,]")
    elif kind == "profit":
        values["industrial_profit_ytd_yoy"] = annual_change(
            text, r"全国规模以上工业企业实现利润总额\d+(?:\.\d+)?亿元[，,]")
    published = nbs_publication_date(soup) or published_hint
    return [row for key, value in values.items()
            if (row := record(key, value, period, url, title, published))]


def parse_nbs_special(soup: BeautifulSoup, url: str, title: str, kind: str,
                      period_override: str | None = None, published_hint: str = "") -> list[dict]:
    period = period_override or month_from_title(title, url, published_hint)
    if period and re.match(r"20\d{2}年(?:全国)?(?:固定资产投资|房地产市场|房地产开发投资|规模以上工业企业利润)", title):
        return parse_nbs_annual(soup, url, title, kind, period, published_hint)
    content = soup.select_one(".trs_editor_view, .TRS_Editor")
    if not period or not content:
        return []
    text = compact(content.get_text("", strip=False))
    # Patterns are anchored to narrative phrases. Splitting at "附注" would
    # truncate a first paragraph that merely references an appendix.
    month = int(period[-2:])
    prefix = rf"(?<![0-9—－-]){month}月份?"
    values: dict[str, float | None] = {}
    if kind == "industry":
        values["industrial_yoy"] = first_change(text, prefix + r"，?规模以上工业增加值")
    elif kind == "retail":
        values["retail_yoy"] = first_change(text, prefix + r"，?社会消费品零售总额\d+(?:\.\d+)?亿元[，,]")
    elif kind == "investment":
        values["fai_ytd_yoy"] = first_change(text, r"全国固定资产投资（不含农户）\d+(?:\.\d+)?亿元[，,]")
        private_pattern = r"民间固定资产投资(?:\d+(?:\.\d+)?亿元)?[，,]?"
        values["private_fai_ytd_yoy"] = contextual_change(text, private_pattern)
        if (values["private_fai_ytd_yoy"] is None
                and re.search(private_pattern + r"(?:总量)?与去年同期(?:基本)?持平", text)
                and re.search(r"(?:其中：)?民间投资0(?:\.0+)?(?:按构成分|分产业看)", text)):
            values["private_fai_ytd_yoy"] = 0.0
        values["manufacturing_fai_ytd_yoy"] = contextual_change(text, r"制造业投资")
        if "基础设施投资（口径详见附注" in text:
            values["infrastructure_fai_ytd_yoy"] = first_change(text, r"基础设施投资（口径详见附注\d+）")
        if "基础设施投资（不含电力、热力、燃气及水生产和供应业）" in text:
            values["infrastructure_ex_utilities_ytd_yoy"] = contextual_change(
                text, r"基础设施投资（不含电力、热力、燃气及水生产和供应业）")
    elif kind == "estate":
        values["real_estate_fai_ytd_yoy"] = first_change(text, r"全国房地产开发投资\d+(?:\.\d+)?亿元[，,]")
        values["housing_sales_area_ytd_yoy"] = contextual_change(
            text, r"(?:新建)?商品房销售面积\d+(?:\.\d+)?万平方米[，,]?")
    elif kind == "cpi":
        values["cpi_yoy"] = first_change(text, prefix + r"，?全国居民消费价格")
        values["cpi_mom"] = direct_change(text, prefix + r"，?全国居民消费价格环比")
    elif kind == "ppi":
        values["ppi_yoy"] = first_change(text, prefix + r"，?全国工业生产者出厂价格")
        values["ppi_mom"] = ppi_month_change(text)
    elif kind == "profit":
        values["industrial_profit_ytd_yoy"] = first_change(text, r"全国规模以上工业企业实现利润总额\d+(?:\.\d+)?亿元[，,]")
    elif kind == "pmi":
        headline = re.search(prefix + r"，?(?:中国)?制造业采购经理指数(?:（PMI）)?为(\d+(?:\.\d+)?)%", text)
        values["manufacturing_pmi"] = float(headline.group(1)) if headline else None
        orders = re.search(r"新订单指数为(\d+(?:\.\d+)?)%", text)
        values["manufacturing_new_orders_pmi"] = float(orders.group(1)) if orders else None
        nonmanufacturing = re.search(prefix + r"，?非制造业商务活动指数为(\d+(?:\.\d+)?)%", text)
        values["nonmanufacturing_pmi"] = float(nonmanufacturing.group(1)) if nonmanufacturing else None
    if kind in {"cpi", "ppi"}:
        table_rates = price_table_rates(content, kind)
        if table_rates:
            mom_key, yoy_key = ("cpi_mom", "cpi_yoy") if kind == "cpi" else ("ppi_mom", "ppi_yoy")
            for key, table_value in ((mom_key, table_rates[0]), (yoy_key, table_rates[1])):
                if values.get(key) is not None and values[key] != table_value:
                    raise ValueError(f"{key} narrative differs from national price table")
                values[key] = table_value
    published = nbs_publication_date(soup) or published_hint
    return [row for key, value in values.items() if (row := record(key, value, period, url, title, published))]


def parse_nbs(soup: BeautifulSoup, url: str, title: str,
              period_override: str | None = None, published_hint: str = "") -> list[dict]:
    period = period_override or month_from_title(title, url, published_hint)
    content = soup.select_one(".trs_editor_view, .TRS_Editor")
    if not period or not content:
        return []
    text = compact(content.get_text("", strip=False))
    # Exclude notes and tables; otherwise repeated numbers may be assigned to the wrong period.
    text = re.split(r"注[:：]|附表[:：]|\d{4}年\d+月份主要指标数据", text, maxsplit=1)[0]
    month = int(period[-2:])
    # A bare "8月份" must not match the cumulative "1—8月份" sentence.
    prefix = rf"(?<![0-9—－-]){month}月份"
    results = {
        "industrial_yoy": find_change(text, prefix + r"，?全国规模以上工业增加值"),
        "retail_yoy": find_change(text, prefix + r"，?社会消费品零售总额\d+(?:\.\d+)?亿元[，,]"),
        "cpi_yoy": find_change(text, prefix + r"，?全国居民消费价格(?:（CPI）)?"),
        "ppi_yoy": find_change(text, prefix + r"，?全国工业生产者出厂价格"),
    }
    # Annual and quarter reports often give a cumulative trade paragraph first,
    # followed by a separate monthly paragraph without the word "货物". Require
    # the current month's own total and both export/import amounts and rates.
    trade = re.search(
        prefix + r"[，,]?(?:货物)?进出口总额\d+(?:\.\d+)?亿元.{0,130}?其中[，,]?"
        r"出口\d+(?:\.\d+)?亿元[，,]?(?:同比)?(增长|下降|上涨|下跌|减少)(\d+(?:\.\d+)?)%"
        r"[^。]{0,80}?[；;，,]进口\d+(?:\.\d+)?亿元[，,]?(?:同比)?"
        r"(增长|下降|上涨|下跌|减少)(\d+(?:\.\d+)?)%", text)
    if trade:
        results["export_yoy"] = signed_change(trade.group(1), trade.group(2))
        results["import_yoy"] = signed_change(trade.group(3), trade.group(4))
    if results["ppi_yoy"] is None:
        # Some releases give cumulative PPI first, then the current month in an "其中" sentence.
        ppi_month = re.search(r"全国工业生产者出厂价格同比(?:增长|上涨|下降)\d+(?:\.\d+)?%。其中，" + prefix + r"同比(增长|上涨|下降)(\d+(?:\.\d+)?)%", text)
        results["ppi_yoy"] = signed_change(*ppi_month.groups()) if ppi_month else None
    investment = re.search(r"全国固定资产投资（不含农户）\d+(?:\.\d+)?亿元，同比(增长|下降)(\d+(?:\.\d+)?)%", text)
    results["fai_ytd_yoy"] = signed_change(*investment.groups()) if investment else None
    job = re.search(prefix + r"，?全国城镇调查失业率为(\d+(?:\.\d+)?)%", text)
    results["unemployment"] = float(job.group(1)) if job else None
    if results["unemployment"] is None:
        paired = re.search(
            r"全国城镇调查失业率为\d+(?:\.\d+)?%；\d+、" + prefix
            + r"(?:连续)?(?:回落|上升|下降)，分别为\d+(?:\.\d+)?%、(\d+(?:\.\d+)?)%", text)
        results["unemployment"] = float(paired.group(1)) if paired else None
    pmi = re.search(prefix + r"，?制造业采购经理指数为(\d+(?:\.\d+)?)%", text)
    results["manufacturing_pmi"] = float(pmi.group(1)) if pmi else None
    published = re.search(r"（(20\d{2})年(\d{1,2})月(\d{1,2})日）", text)
    published_date = nbs_publication_date(soup) or published_hint or (f"{published[1]}-{int(published[2]):02d}-{int(published[3]):02d}" if published else "")
    return [row for key, value in results.items() if (row := record(key, value, period, url, title, published_date))]


def pbc_links(session: requests.Session) -> list[tuple[str, str]]:
    soup = fetch(session, PBC_LIST)
    found = {}
    for a in soup.find_all("a", href=True):
        title = a.get_text(" ", strip=True)
        href = urljoin(PBC_LIST, a["href"])
        if "金融统计数据报告" in title and "年" in title and "/116225/" in href:
            found[href] = title
    return list(found.items())[:13]


def parse_pbc(soup: BeautifulSoup, url: str, title: str, published_hint: str = "") -> list[dict]:
    from .finance import parse_financial_report
    return parse_financial_report(soup, url, title, published_hint)


def collect(nbs_pages: int = 4, start_year: int | None = None, include_pbc: bool = True,
            skip_urls: set[str] | None = None, through_year: int | None = None,
            nbs_archive: str = "disclosure", include_trade: bool = True,
            include_fiscal: bool = True, include_cny: bool = True,
            known_cny_periods: set[tuple[str, str]] | None = None) -> tuple[list[dict], list[str]]:
    session = requests.Session()
    rows, errors = [], []
    try:
        links = nbs_links(session, pages=nbs_pages, start_year=start_year,
                          through_year=through_year, archive=nbs_archive, errors=errors)
        if not links:
            errors.append("国家统计局：未发现符合筛选条件的报告")
        for url, title, kind, period, published in links:
            if skip_urls and url in skip_urls:
                continue
            try:
                soup = fetch(session, url)
                parsed = (parse_nbs(soup, url, title, period, published) if kind == "overview"
                          else parse_nbs_special(soup, url, title, kind, period, published))
                rows.extend(parsed)
            except SourceAccessBlocked:
                errors.append(f"国家统计局：{title[:24]} 遇到访问验证；本批剩余报告暂停读取")
                break
            except (requests.RequestException, UnicodeError, ValueError) as exc:
                errors.append(f"国家统计局：{title[:24]} 获取失败（{type(exc).__name__}）")
            time.sleep(0.4)
    except (requests.RequestException, UnicodeError, ValueError) as exc:
        errors.append(f"国家统计局：目录获取失败（{type(exc).__name__}）")
    if include_pbc:
        from .finance import collect_finance
        finance_rows, finance_errors = collect_finance(session=session)
        rows.extend(finance_rows)
        errors.extend(finance_errors)
    if include_trade:
        from .trade import collect_trade
        try:
            trade_rows, _ = collect_trade()
            rows.extend(trade_rows)
        except (requests.RequestException, UnicodeError, ValueError, TypeError) as exc:
            errors.append(f"商务部货物进出口月度表：读取或核验失败（{type(exc).__name__}）")
    if include_fiscal:
        from .fiscal import collect_fiscal
        fiscal_rows, fiscal_errors = collect_fiscal(session=session, pages=1, recent_limit=3)
        rows.extend(fiscal_rows)
        errors.extend(fiscal_errors)
    if include_cny:
        from .cny_trade import collect_cny_trade
        cny_rows, cny_errors = collect_cny_trade(known_cny_periods)
        rows.extend(cny_rows)
        errors.extend(cny_errors)
    return rows, errors
