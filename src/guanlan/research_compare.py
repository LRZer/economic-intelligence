"""核验研究包并比较同一研究选择在不同快照下的数据差异。"""

from __future__ import annotations

import hashlib
import html
import io
import json
import math
import re
from difflib import unified_diff
from dataclasses import dataclass
from zipfile import BadZipFile, ZipFile

import pandas as pd

from .catalog import INDICATOR_BY_CODE
from .financial import FINANCIAL_REPORT_COLUMNS
from .research import COHORTS
from .research_bundle import ResearchBundle


MAX_ARCHIVE_BYTES = 12 * 1024 * 1024
MAX_EXPANDED_BYTES = 32 * 1024 * 1024
TABLES = {
    "年度 WDI 指标": ("data/annual_indicators.csv", ["indicator_code"], "value"),
    "同组样本": ("data/peer_sample.csv", ["country_code"], "value"),
    "增长通胀历史": ("data/growth_inflation_history.csv", ["indicator_code", "year"], "value"),
    "出口伙伴": ("data/export_partners.csv", ["partner_code"], "trade_usd"),
    "IMF 预测": ("data/imf_forecast.csv", ["indicator_code", "year"], "value"),
    "BIS 金融条件": ("data/bis_financial.csv", ["indicator_code"], "value"),
}
REQUIRED_V2 = {"report.md", "report.html", *(entry[0] for label, entry in TABLES.items()
                                             if label != "BIS 金融条件")}
REQUIRED_V3 = REQUIRED_V2 | {"data/bis_financial.csv"}


@dataclass(frozen=True)
class VerifiedResearchPackage:
    manifest: dict
    tables: dict[str, pd.DataFrame]
    report_markdown: str


@dataclass(frozen=True)
class ResearchComparison:
    earlier_id: str
    current_id: str
    source_changes: pd.DataFrame
    peer_summary: pd.DataFrame
    tables: dict[str, pd.DataFrame]
    markdown: str
    report_diff: str


def _report_id(manifest: dict) -> str:
    identity = {key: manifest[key] for key in ("format_version", "selection", "sources")}
    if "draft_sha256" in manifest:
        identity["draft_sha256"] = manifest["draft_sha256"]
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _markdown_cell(value: object) -> str:
    escaped = html.escape(str(value if value is not None else "无"))
    return escaped.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("[", "\\[").replace("!", "\\!")


def comparison_csv_bytes(frame: pd.DataFrame) -> bytes:
    """转义来自上传研究包的文本，避免电子表格把它当公式执行。"""
    safe = frame.copy()
    for column in safe.select_dtypes(include=["object", "string"]).columns:
        safe[column] = safe[column].map(
            lambda value: "'" + value if isinstance(value, str)
            and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value)
    return safe.to_csv(index=False).encode("utf-8-sig")


def verify_research_package(payload: bytes) -> VerifiedResearchPackage:
    """验证结构、文件散列和报告编号后才读取 CSV；散列不构成数字签名。"""
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError("研究包超过 12 MB 上限")
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or any(
                info.is_dir() or name.startswith("/") or "\\" in name
                or any(part in (".", "..") for part in name.split("/"))
                for info, name in zip(infos, names)
            ):
                raise ValueError("研究包含重复或无效路径")
            if "manifest.json" not in names:
                raise ValueError("研究包缺少 manifest.json")
            if sum(info.file_size for info in infos) > MAX_EXPANDED_BYTES:
                raise ValueError("研究包解压内容超过 32 MB 上限")
            with archive.open("manifest.json") as source:
                raw_manifest = source.read(1_000_001)
            if len(raw_manifest) > 1_000_000:
                raise ValueError("研究包清单过大")
            manifest = json.loads(raw_manifest)
            if not isinstance(manifest, dict):
                raise ValueError("研究包清单不是 JSON 对象")
            version = manifest.get("format_version")
            if version not in ("2", "3"):
                raise ValueError("只支持格式版本 2 或 3 的研究包")
            if not isinstance(manifest.get("selection"), dict) or not isinstance(manifest.get("sources"), dict):
                raise ValueError("研究包缺少筛选条件或来源信息")
            selection = manifest["selection"]
            if (not re.fullmatch(r"[A-Z]{3}", str(selection.get("country_code", "")))
                    or type(selection.get("year")) is not int
                    or selection["year"] < 1900 or selection["year"] > 2200
                    or not isinstance(selection.get("peer_indicator"), str)
                    or selection.get("peer_indicator") not in INDICATOR_BY_CODE
                    or not isinstance(selection.get("cohort"), str)
                    or selection.get("cohort") not in COHORTS):
                raise ValueError("研究包筛选条件无效")
            if ("wdi" not in manifest["sources"] or not all(
                    isinstance(name, str) and isinstance(source, dict)
                    for name, source in manifest["sources"].items())):
                raise ValueError("研究包来源信息无效")
            if "draft_sha256" in manifest and not re.fullmatch(
                r"[0-9a-f]{64}", str(manifest["draft_sha256"])):
                raise ValueError("研究包正文散列无效")
            if manifest.get("report_id") != _report_id(manifest):
                raise ValueError("研究包编号与清单不符")
            hashes = manifest.get("files_sha256")
            required = REQUIRED_V3 if version == "3" else REQUIRED_V2
            if not isinstance(hashes, dict) or set(hashes) | {"manifest.json"} != set(names) or not required <= set(hashes):
                raise ValueError("研究包文件清单不完整")
            contents = {}
            expanded = 0
            for name, expected in hashes.items():
                if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                    raise ValueError(f"{name} 的 SHA-256 无效")
                with archive.open(name) as source:
                    contents[name] = source.read(MAX_EXPANDED_BYTES + 1)
                expanded += len(contents[name])
                if expanded > MAX_EXPANDED_BYTES:
                    raise ValueError("研究包实际解压内容超过 32 MB 上限")
                if hashlib.sha256(contents[name]).hexdigest() != expected:
                    raise ValueError(f"{name} 的 SHA-256 校验失败")
    except (BadZipFile, KeyError, json.JSONDecodeError, UnicodeDecodeError, TypeError,
            OSError, RuntimeError) as exc:
        raise ValueError("研究包格式无效或内容损坏") from exc

    tables = {}
    selection = manifest["selection"]
    for label, (path, keys, value) in TABLES.items():
        if label == "BIS 金融条件" and version == "2":
            tables[label] = pd.DataFrame(columns=FINANCIAL_REPORT_COLUMNS)
            continue
        try:
            frame = pd.read_csv(io.BytesIO(contents[path]), dtype={key: "str" for key in keys})
        except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"{path} 无法读取为 CSV") from exc
        required_columns = set(keys + [value])
        if label == "年度 WDI 指标":
            required_columns |= {"country_code", "year", "unit"}
        if label == "同组样本":
            required_columns |= {"indicator_code", "year"}
        if label == "BIS 金融条件":
            required_columns |= set(FINANCIAL_REPORT_COLUMNS)
        if (not required_columns <= set(frame.columns) or frame.duplicated(keys).any()
                or frame[keys].isna().any().any()):
            raise ValueError(f"{path} 缺少必要字段或存在重复主键")
        parsed = pd.to_numeric(frame[value], errors="coerce")
        if (frame[value].notna() & parsed.isna()).any() or not parsed.dropna().map(math.isfinite).all():
            raise ValueError(f"{path} 包含无效数值")
        frame[value] = parsed
        tables[label] = frame
    annual = tables["年度 WDI 指标"]
    if (annual.empty or annual.country_code.nunique() != 1
            or annual.country_code.iloc[0] != selection.get("country_code")
            or annual.year.nunique() != 1 or str(annual.year.iloc[0]) != str(selection.get("year"))):
        raise ValueError("年度指标与清单筛选条件不一致")
    peer = tables["同组样本"]
    if (peer.empty or selection["country_code"] not in peer.country_code.values
            or peer.indicator_code.nunique() != 1
            or peer.indicator_code.iloc[0] != selection.get("peer_indicator")
            or peer.year.nunique() != 1 or str(peer.year.iloc[0]) != str(selection.get("year"))):
        raise ValueError("同组样本与清单筛选条件不一致")
    if version == "3":
        finance = tables["BIS 金融条件"]
        expected_codes = {"BIS.CBPOL", "BIS.CREDIT_RATIO", "BIS.CREDIT_TREND", "BIS.CREDIT_GAP"}
        expected_units = {"BIS.CBPOL": "年利率 %", "BIS.CREDIT_RATIO": "GDP 的 %",
                          "BIS.CREDIT_TREND": "GDP 的 %", "BIS.CREDIT_GAP": "百分点"}
        if (len(finance) != 4 or set(finance.indicator_code) != expected_codes
                or finance.country_code.nunique() != 1
                or finance.country_code.iloc[0] != selection["country_code"]
                or finance.year.nunique() != 1 or str(finance.year.iloc[0]) != str(selection["year"])):
            raise ValueError("BIS 金融条件与清单筛选条件不一致")
        for row in finance.itertuples(index=False):
            period = "" if pd.isna(row.period) else str(row.period)
            status = "" if pd.isna(row.obs_status) else str(row.obs_status)
            expected_frequency = "月度" if row.indicator_code == "BIS.CBPOL" else "季度"
            pattern = r"\d{4}-(0[1-9]|1[0-2])" if expected_frequency == "月度" else r"\d{4}-Q[1-4]"
            if (row.frequency != expected_frequency or row.unit != expected_units[row.indicator_code]
                    or (period and (not re.fullmatch(pattern, period)
                                       or int(period[:4]) != selection["year"]))):
                raise ValueError("BIS 金融条件的频率、单位或观察期无效")
            if (status not in ("", "A", "M") or (status == "A") != pd.notna(row.value)
                    or (status == "M" and (not period or pd.notna(row.value)))
                    or (pd.notna(row.value) and not period)):
                raise ValueError("BIS 金融条件的数值与来源状态不一致")
        credit_periods = finance.loc[finance.indicator_code != "BIS.CBPOL", "period"].dropna().unique()
        if len(credit_periods) > 1:
            raise ValueError("BIS 信贷指标观察季度不一致")
        credit_values = finance.set_index("indicator_code").value
        if all(pd.notna(credit_values[code]) for code in
               ("BIS.CREDIT_RATIO", "BIS.CREDIT_TREND", "BIS.CREDIT_GAP")):
            residual = (credit_values["BIS.CREDIT_RATIO"] - credit_values["BIS.CREDIT_TREND"]
                        - credit_values["BIS.CREDIT_GAP"])
            if abs(residual) > 0.001:
                raise ValueError("BIS 信贷缺口与比率减趋势无法勾稽")
    try:
        report_markdown = contents["report.md"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("report.md 不是 UTF-8 文本") from exc
    if f"报告编号：`{manifest['report_id']}`" not in report_markdown:
        raise ValueError("报告正文编号与清单不符")
    return VerifiedResearchPackage(manifest, tables, report_markdown)


def _changed_values(earlier: pd.DataFrame, current: pd.DataFrame,
                    keys: list[str], value: str) -> pd.DataFrame:
    old = earlier[keys + [value]].rename(columns={value: "原值"})
    new = current[keys + [value]].rename(columns={value: "新值"})
    merged = old.merge(new, on=keys, how="outer", indicator=True, validate="one_to_one")

    def status(row) -> str:
        if row["_merge"] == "left_only":
            return "移出样本"
        if row["_merge"] == "right_only":
            return "加入样本"
        if pd.isna(row["原值"]) and pd.isna(row["新值"]):
            return "未变化"
        if pd.isna(row["原值"]):
            return "新增数值"
        if pd.isna(row["新值"]):
            return "变为空值"
        return "未变化" if row["原值"] == row["新值"] else "数值修订"

    merged["变化类型"] = merged.apply(status, axis=1)
    merged["差值"] = merged["新值"] - merged["原值"]
    merged.loc[merged["变化类型"] != "数值修订", "差值"] = float("nan")
    return merged.drop(columns="_merge").sort_values(keys).reset_index(drop=True)


def _peer_summary(package: VerifiedResearchPackage) -> dict:
    peer = package.tables["同组样本"]
    country = package.manifest["selection"]["country_code"]
    observed = peer.dropna(subset=["value"])
    selected = peer.loc[peer.country_code == country, "value"]
    value = float(selected.iloc[0]) if len(selected) and pd.notna(selected.iloc[0]) else None
    return {
        "样本经济体": len(peer), "有值经济体": len(observed),
        "本国值": value,
        "名次（降序）": 1 + int((observed.value > value).sum()) if value is not None else None,
        "中秩百分位": 100 * (int((observed.value < value).sum())
                         + 0.5 * int((observed.value == value).sum())) / len(observed)
        if value is not None and len(observed) else None,
    }


def compare_research_packages(earlier: VerifiedResearchPackage,
                              current: VerifiedResearchPackage) -> ResearchComparison:
    """只比较相同国家、年份、参照指标和同组方式的研究包。"""
    left, right = earlier.manifest, current.manifest
    if left["selection"] != right["selection"]:
        raise ValueError("两个研究包的经济体、年份、参照指标或同组方式不同")
    sources = []
    for name in sorted(set(left["sources"]) | set(right["sources"])):
        old, new = left["sources"].get(name, {}), right["sources"].get(name, {})
        old_identity = tuple(old.get(key) for key in
                             ("provider", "parquet_sha256", "source_archive_sha256", "vintage", "release"))
        new_identity = tuple(new.get(key) for key in
                             ("provider", "parquet_sha256", "source_archive_sha256", "vintage", "release"))
        sources.append({"来源": name, "原提供方": old.get("provider"), "新提供方": new.get("provider"),
                        "原版次": old.get("vintage") or old.get("release"),
                        "新版次": new.get("vintage") or new.get("release"),
                        "原快照 SHA-256": old.get("parquet_sha256"),
                        "新快照 SHA-256": new.get("parquet_sha256"),
                        "来源版次或文件已变化": old_identity != new_identity})
    source_changes = pd.DataFrame(sources)
    tables = {}
    for label, (_, keys, value) in TABLES.items():
        tables[label] = _changed_values(earlier.tables[label], current.tables[label], keys, value)
    old_units = earlier.tables["年度 WDI 指标"][["indicator_code", "unit"]].rename(columns={"unit": "原单位"})
    new_units = current.tables["年度 WDI 指标"][["indicator_code", "unit"]].rename(columns={"unit": "新单位"})
    annual_units = old_units.merge(new_units, on="indicator_code", how="outer", validate="one_to_one")
    annual = tables["年度 WDI 指标"].merge(annual_units, on="indicator_code", how="left", validate="one_to_one")
    unit_changed = annual["原单位"].fillna("") != annual["新单位"].fillna("")
    annual.loc[unit_changed, "变化类型"] = "单位或口径变化"
    annual.loc[unit_changed, "差值"] = float("nan")
    tables["年度 WDI 指标"] = annual
    old_finance = earlier.tables["BIS 金融条件"][["indicator_code", "unit", "period"]].rename(
        columns={"unit": "原单位", "period": "原观察期"})
    new_finance = current.tables["BIS 金融条件"][["indicator_code", "unit", "period"]].rename(
        columns={"unit": "新单位", "period": "新观察期"})
    finance_scope = old_finance.merge(new_finance, on="indicator_code", how="outer", validate="one_to_one")
    finance = tables["BIS 金融条件"].merge(finance_scope, on="indicator_code", how="left",
                                             validate="one_to_one")
    scope_changed = ((finance["原单位"].fillna("") != finance["新单位"].fillna(""))
                     | (finance["原观察期"].fillna("") != finance["新观察期"].fillna("")))
    finance.loc[scope_changed & ~finance["变化类型"].isin(["加入样本", "移出样本"]),
                "变化类型"] = "观察期或单位变化"
    finance.loc[finance["变化类型"] == "观察期或单位变化", "差值"] = float("nan")
    if left["format_version"] == "2" and right["format_version"] == "3":
        finance["变化类型"] = "新版新增资料"
        finance["差值"] = float("nan")
    elif left["format_version"] == "3" and right["format_version"] == "2":
        finance["变化类型"] = "新版未包含资料"
        finance["差值"] = float("nan")
    tables["BIS 金融条件"] = finance
    old_peer, new_peer = _peer_summary(earlier), _peer_summary(current)
    peer_summary = pd.DataFrame([{"指标": key, "旧报告": old_peer[key], "新报告": new_peer[key]}
                                 for key in old_peer])
    country = right["selection"]["country_code"]
    year = right["selection"]["year"]
    lines = [f"# 观澜研究包版次比较：{country} · {year} 年", "",
             f"- 旧报告：`{left['report_id']}`；新报告：`{right['report_id']}`。",
             "- 两份研究包均已通过包内 SHA-256 校验；校验值证明文件一致性，不证明外部来源真实性。",
             "- 差值 = 新报告原值 − 旧报告原值；增长率、通胀率、利率和占比的差值单位是百分点。",
             "- BIS 指标只在观察期和单位相同时计算数值差；观察期变化单独标记。",
             "- 快照或提供方变化可能反映数据修订、覆盖变化或方法变化；不能直接解释为经济实际变动。", "",
             "## 来源与数据变化", "",
             "| 来源 | 旧提供方 | 新提供方 | 版次或文件变化 |", "| --- | --- | --- | --- |"]
    body_changed = left["files_sha256"].get("report.md") != right["files_sha256"].get("report.md")
    html_changed = left["files_sha256"].get("report.html") != right["files_sha256"].get("report.html")
    report_diff = "".join(unified_diff(
        earlier.report_markdown.splitlines(keepends=True),
        current.report_markdown.splitlines(keepends=True),
        fromfile=f"旧报告 {left['report_id']}", tofile=f"新报告 {right['report_id']}",
    ))
    lines.insert(6, f"- 报告正文{'已变化' if body_changed else '未变化'}；HTML 阅读版{'已变化' if html_changed else '未变化'}。")
    for row in source_changes.itertuples(index=False):
        lines.append(f"| {_markdown_cell(row.来源)} | {_markdown_cell(row.原提供方)} | "
                     f"{_markdown_cell(row.新提供方)} | "
                     f"{'是' if row.来源版次或文件已变化 else '否'} |")
    lines.extend(["", "## 差异摘要", "", "| 数据范围 | 加入/移出记录 | 数值变化或缺失变化 |",
                  "| --- | ---: | ---: |"])
    for label, table in tables.items():
        membership = int(table["变化类型"].isin(["加入样本", "移出样本",
                                                "新版新增资料", "新版未包含资料"]).sum())
        revised = int(table["变化类型"].isin(["数值修订", "新增数值", "变为空值",
                                             "单位或口径变化", "观察期或单位变化"]).sum())
        lines.append(f"| {label} | {membership} | {revised} |")
    if all((table["变化类型"] == "未变化").all() for table in tables.values()) and body_changed:
        lines.extend(["", "数据底稿未变化；本次报告差异来自文字、格式或报告生成逻辑，"
                      "可查看 `report_text.diff` 定位正文修改。"])
    lines.extend(["", "## 同组位置", "", "| 指标 | 旧报告 | 新报告 |", "| --- | ---: | ---: |"])
    for row in peer_summary.itertuples(index=False):
        integer_metric = row.指标 in ("样本经济体", "有值经济体", "名次（降序）")
        old = "—" if pd.isna(row.旧报告) else str(int(row.旧报告)) if integer_metric else f"{row.旧报告:.2f}"
        new = "—" if pd.isna(row.新报告) else str(int(row.新报告)) if integer_metric else f"{row.新报告:.2f}"
        lines.append(f"| {row.指标} | {old} | {new} |")
    annual = tables["年度 WDI 指标"]
    revised = annual.loc[annual["变化类型"] != "未变化"]
    lines.extend(["", "## 已变化的 WDI 指标原值", "",
                  "| 指标代码 | 单位 | 旧值 | 新值 | 差值 | 类型 |",
                  "| --- | --- | ---: | ---: | ---: | --- |"])
    for row in revised.itertuples(index=False):
        def value_text(value):
            return "—" if pd.isna(value) else f"{value:,.6g}"
        unit = row.原单位 if row.原单位 == row.新单位 else f"{row.原单位} → {row.新单位}"
        lines.append(f"| {_markdown_cell(row.indicator_code)} | {_markdown_cell(unit)} | "
                     f"{value_text(row.原值)} | {value_text(row.新值)} | "
                     f"{value_text(row.差值)} | {row.变化类型} |")
    if revised.empty:
        lines.append("| 无 | — | — | — | — | — |")
    if left["sources"].get("trade", {}).get("provider") != right["sources"].get("trade", {}).get("provider"):
        lines.extend(["", "贸易提供方不同，出口伙伴差值仅供定位数据来源变化，不作可比的贸易增减解释。"])
    lines.extend(["", "完整逐项差异可在系统表格中查看并下载 CSV。"])
    return ResearchComparison(left["report_id"], right["report_id"], source_changes,
                              peer_summary, tables, "\n".join(lines) + "\n", report_diff)


def compare_with_current(previous_archive: bytes, current: ResearchBundle) -> ResearchComparison:
    return compare_research_packages(verify_research_package(previous_archive),
                                     verify_research_package(current.archive))
