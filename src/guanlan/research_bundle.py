"""生成可离线阅读、可核验来源的确定性宏观研究包。"""

from __future__ import annotations

import hashlib
import html
import io
import json
import math
from dataclasses import dataclass
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import mistune
import pandas as pd

from .analytics import GROWTH, INFLATION, trade_partner_table
from .catalog import INDICATORS, country_label
from .financial import financial_report_table
from .research import REPORT_FORMAT_VERSION, build_research_report, peer_sample


@dataclass(frozen=True)
class ResearchBundle:
    report_id: str
    markdown: str
    html: str
    manifest: dict
    archive: bytes


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source(meta: dict) -> dict:
    return {key: meta.get(key) for key in (
        "provider", "source_url", "downloaded_at_utc", "source_last_updated",
        "parquet_sha256", "source_archive_sha256", "methodology_url",
        "build_id", "release", "vintage", "frequency",
    ) if meta.get(key) is not None}


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8-sig")


def _history(macro: pd.DataFrame, country: str, year: int) -> pd.DataFrame:
    frame = macro.loc[
        (macro.country_code == country) & macro.year.between(year - 14, year)
        & macro.indicator_code.isin([GROWTH, INFLATION]),
        ["year", "indicator_code", "value"],
    ].copy()
    frame["指标"] = frame.indicator_code.map({GROWTH: "实际GDP增速", INFLATION: "消费者价格涨幅"})
    return frame.sort_values(["indicator_code", "year"]).reset_index(drop=True)


def _chart_svg(history: pd.DataFrame) -> str:
    valid = history.loc[history.value.map(
        lambda value: pd.notna(value) and math.isfinite(float(value))
    )]
    if valid.empty or valid.year.nunique() < 2:
        return ""
    years = sorted(int(value) for value in history.year.unique())
    first, last = min(years), max(years)
    if first == last:
        return ""
    minimum = min(0.0, float(valid.value.min()))
    maximum = max(0.0, float(valid.value.max()))
    spread = max(maximum - minimum, 1.0)
    minimum -= spread * 0.12
    maximum += spread * 0.12
    width, height = 920, 288
    left, right, top, bottom = 54, 22, 18, 38
    chart_width = width - left - right
    chart_height = height - top - bottom

    def x_pos(year: int) -> float:
        return left + (year - first) / (last - first) * chart_width

    def y_pos(value: float) -> float:
        return top + (maximum - value) / (maximum - minimum) * chart_height

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="近十五年实际GDP增速与消费者价格涨幅的年度轨迹" '
        'xmlns="http://www.w3.org/2000/svg">',
        '<rect width="920" height="288" fill="#ffffff"/>',
    ]
    for index in range(5):
        tick = minimum + index * (maximum - minimum) / 4
        y = y_pos(tick)
        parts.append(f'<line x1="{left}" x2="{width-right}" y1="{y:.1f}" y2="{y:.1f}" '
                     'stroke="#e3eaed" stroke-width="1"/>')
        parts.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" '
                     f'fill="#526672" font-size="12">{tick:.1f}</text>')
    x_ticks = sorted({first, first + (last - first) // 2, last})
    for tick in x_ticks:
        parts.append(f'<text x="{x_pos(tick):.1f}" y="{height-13}" text-anchor="middle" '
                     f'fill="#526672" font-size="12">{tick}</text>')
    for code, color, label in (
        (GROWTH, "#146f7c", "实际GDP增速"),
        (INFLATION, "#b95d42", "消费者价格涨幅"),
    ):
        rows = valid.loc[valid.indicator_code == code].sort_values("year")
        run: list[tuple[int, float]] = []
        runs: list[list[tuple[int, float]]] = []
        for row in rows.itertuples():
            point = (int(row.year), float(row.value))
            if run and point[0] != run[-1][0] + 1:
                runs.append(run)
                run = []
            run.append(point)
        if run:
            runs.append(run)
        for segment in runs:
            if len(segment) >= 2:
                points = " ".join(f"{x_pos(y):.1f},{y_pos(v):.1f}" for y, v in segment)
                parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" '
                             'stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round"/>')
            for point_year, value in segment:
                parts.append(f'<circle cx="{x_pos(point_year):.1f}" cy="{y_pos(value):.1f}" '
                             f'r="3.2" fill="{color}"><title>{point_year} 年{label}：{value:.2f}%</title></circle>')
    parts.append('</svg>')
    return "".join(parts)


def _html_report(markdown: str, history: pd.DataFrame, title: str, report_id: str) -> str:
    rendered = mistune.create_markdown(escape=True, plugins=["table"])(markdown)
    chart = _chart_svg(history)
    if chart:
        figure = (
            '<figure><div class="figure-heading">近十五年增长与通胀轨迹 <span>年度变化率 · %</span></div>'
            '<div class="legend"><span class="growth-line"></span>实际GDP增速'
            '<span class="inflation-line"></span>消费者价格涨幅</div>'
            + chart + '<figcaption>来源：世界银行 WDI，所选经济体的同一数据快照。缺失年份断线；'
            '图中不含 IMF 未来预测。</figcaption></figure>'
        )
        rendered = rendered.replace("</h1>", "</h1>" + figure, 1)
    css = """
    @page { size: A4; margin: 17mm; }
    * { box-sizing: border-box; }
    body { margin: 0; color: #18303d; background: #edf2f4;
      font-family: "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif;
      font-size: 14px; line-height: 1.65; }
    .brand { padding: 20px max(30px, calc((100vw - 1050px)/2)); background: #153b48;
      color: #fff; letter-spacing: .08em; font-size: 13px; font-weight: 700; }
    main { max-width: 1050px; margin: 26px auto 50px; padding: 42px 54px;
      background: white; box-shadow: 0 12px 35px #173b4814; }
    h1 { color: #143745; font-size: 27px; line-height: 1.3; margin: 0 0 23px; }
    h2 { color: #175963; font-size: 19px; border-bottom: 1px solid #d6e2e5;
      padding-bottom: 7px; margin-top: 36px; }
    ul { padding-left: 20px; color: #425866; }
    li { margin: 4px 0; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; margin: 17px 0 26px; }
    thead { background: #e9f2f3; color: #214553; }
    th, td { border-bottom: 1px solid #dce6e9; padding: 7px 9px; vertical-align: top; }
    td:nth-child(2) { font-variant-numeric: tabular-nums; }
    tr:nth-child(even) td { background: #f7fafb; }
    a { color: #146f7c; text-decoration: none; }
    code { font-size: 11px; overflow-wrap: anywhere; color: #355766; }
    figure { margin: 23px 0 28px; border: 1px solid #dbe7e9; padding: 18px 20px 10px;
      break-inside: avoid; }
    svg { display: block; width: 100%; height: auto; }
    .figure-heading { font-size: 15px; font-weight: 700; color: #234451; }
    .figure-heading span { float: right; font-size: 12px; font-weight: 400; color: #667b85; }
    .legend { display: flex; align-items: center; gap: 8px; color: #526672; font-size: 11px;
      margin: 8px 0 0; }
    .growth-line, .inflation-line { width: 21px; height: 3px; display: inline-block;
      margin-left: 12px; border-radius: 2px; }
    .growth-line { background: #146f7c; } .inflation-line { background: #b95d42; }
    figcaption { font-size: 11px; color: #607480; margin-top: 5px; }
    .foot { max-width: 1050px; margin: 0 auto 30px; color: #70818b; font-size: 11px; }
    @media print { body { background: white; } .brand { padding: 10px 0; background: white;
      color: #175963; } main { margin: 0; padding: 0; box-shadow: none; }
      .foot { display: none; } a { color: #175963; } }
    """
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{html.escape(title)}</title><style>{css}</style></head><body>'
        '<div class="brand">观澜 GUANLAN　/　GLOBAL MACRO RESEARCH</div>'
        f'<main>{rendered}</main><div class="foot">报告编号 {html.escape(report_id)} · '
        '离线阅读版，可在浏览器中打印或另存为 PDF。</div></body></html>'
    )


def build_research_bundle(
    macro: pd.DataFrame, trade: pd.DataFrame, macro_meta: dict, trade_meta: dict,
    country: str, year: int, indicator_code: str, cohort: str,
    weo: pd.DataFrame | None = None, weo_meta: dict | None = None,
    bis_policy: pd.DataFrame | None = None, bis_credit: pd.DataFrame | None = None,
    bis_policy_meta: dict | None = None, bis_credit_meta: dict | None = None,
) -> ResearchBundle:
    """Markdown、HTML、图表底稿和来源清单来自同一组筛选与快照。"""
    for label, frame, metadata in (("政策利率", bis_policy, bis_policy_meta),
                                   ("信贷/GDP", bis_credit, bis_credit_meta)):
        if bool(metadata) != (frame is not None and not frame.empty):
            raise ValueError(f"BIS {label} 数据与元数据不一致")
    sources = {"wdi": _source(macro_meta)}
    if trade_meta:
        sources["trade"] = _source(trade_meta)
    if weo is not None and not weo.empty and weo_meta:
        sources["weo"] = _source(weo_meta)
    if bis_policy_meta:
        sources["bis_policy"] = _source(bis_policy_meta)
    if bis_credit_meta:
        sources["bis_credit"] = _source(bis_credit_meta)
    selection = {"country_code": country, "year": int(year),
                 "peer_indicator": indicator_code, "cohort": cohort}
    draft = build_research_report(
        macro, trade, macro_meta, trade_meta, country, year, indicator_code, cohort,
        weo=weo, weo_meta=weo_meta,
        bis_policy=bis_policy, bis_credit=bis_credit,
        bis_policy_meta=bis_policy_meta, bis_credit_meta=bis_credit_meta,
    )
    identity = {"format_version": REPORT_FORMAT_VERSION, "selection": selection,
                "sources": sources, "draft_sha256": _sha256(draft.encode("utf-8"))}
    report_id = _sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8"))[:16]
    markdown = build_research_report(
        macro, trade, macro_meta, trade_meta, country, year, indicator_code, cohort,
        weo=weo, weo_meta=weo_meta, report_id=report_id,
        bis_policy=bis_policy, bis_credit=bis_credit,
        bis_policy_meta=bis_policy_meta, bis_credit_meta=bis_credit_meta,
    )
    selected = macro.loc[(macro.country_code == country) & (macro.year == year)]
    name = country_label(country, str(selected.iloc[0].country_name))
    history = _history(macro, country, year)
    html_text = _html_report(markdown, history, f"观澜研究报告 · {name} · {year} 年", report_id)

    values = selected.set_index("indicator_code").value
    annual = pd.DataFrame([{
        "country_code": country, "year": year, "indicator_code": item.code,
        "indicator_name_zh": item.name, "unit": item.unit,
        "value": values.get(item.code), "source_url": item.source_url,
    } for item in INDICATORS])
    peer, group_name = peer_sample(macro, country, year, indicator_code, cohort)
    peer = peer.sort_values("country_code").reset_index(drop=True)
    peer.insert(0, "year", year)
    peer.insert(1, "indicator_code", indicator_code)
    peer["cohort"] = cohort
    peer["group_name"] = group_name
    partners = trade_partner_table(trade, country, year, "X") if not trade.empty else pd.DataFrame(
        columns=["partner_code", "partner_name", "trade_usd", "share"])
    if partners.empty:
        partners["partner_name_zh"] = pd.Series(dtype="str")
    else:
        partners["partner_name_zh"] = partners.apply(
            lambda row: country_label(row.partner_code, row.partner_name), axis=1)
    forecast = pd.DataFrame(columns=["country_code", "indicator_code", "year", "value", "vintage", "status"])
    if weo is not None and not weo.empty and weo_meta:
        forecast = weo.loc[
            (weo.country_code == country) & weo.indicator_code.isin(["NGDP_RPCH", "PCPIPCH", "GGXWDG_NGDP"])
            & weo.year.isin([2026, 2027, 2031]),
            ["country_code", "indicator_code", "year", "value"],
        ].sort_values(["indicator_code", "year"]).reset_index(drop=True)
        forecast["vintage"] = weo_meta.get("vintage")
        forecast["status"] = "IMF staff projection"
    finance = financial_report_table(bis_policy, bis_credit, country, year)
    files = {
        "report.md": markdown.encode("utf-8"),
        "report.html": html_text.encode("utf-8"),
        "data/annual_indicators.csv": _csv_bytes(annual),
        "data/peer_sample.csv": _csv_bytes(peer),
        "data/growth_inflation_history.csv": _csv_bytes(history),
        "data/export_partners.csv": _csv_bytes(partners),
        "data/imf_forecast.csv": _csv_bytes(forecast),
        "data/bis_financial.csv": _csv_bytes(finance),
    }
    manifest = {
        **identity, "report_id": report_id,
        "snapshot_checksums_complete": all("parquet_sha256" in item for item in sources.values()),
        "coverage": {
            "selected_wdi_indicators": int(annual.value.count()),
            "total_wdi_indicators": len(annual),
            "peer_economies": len(peer), "peer_observed": int(peer.value.count()),
            "export_partners": len(partners),
            "bis_observed_measures": int(finance.value.count()),
        },
        "files_sha256": {path: _sha256(contents) for path, contents in sorted(files.items())},
        "note": "快照校验值验证输入版本；CSV 保留缺失值为空；BIS 观察月季与 WDI 年度及 IMF 预测分开。",
    }
    files["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                        indent=2) + "\n").encode("utf-8")
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        for path, contents in sorted(files.items()):
            info = ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, contents)
    return ResearchBundle(report_id, markdown, html_text, manifest, stream.getvalue())
