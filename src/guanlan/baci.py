"""CEPII BACI HS17：从官方年度商品流构建可审计的研究聚合。"""

from __future__ import annotations

import hashlib
import io
import shutil
import zlib
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import duckdb
import pandas as pd
import requests

from .data import DEFAULT_DATA_DIR, publish_snapshots

BACI_RELEASE = "202601"
BACI_REVISION = "HS17"
BACI_URL = f"https://www.cepii.fr/DATA_DOWNLOAD/baci/data/BACI_{BACI_REVISION}_V{BACI_RELEASE}.zip"
YEARS = tuple(range(2017, 2025))
RAW_COLUMNS = {"t": "INTEGER", "i": "INTEGER", "j": "INTEGER", "k": "VARCHAR", "v": "DOUBLE", "q": "DOUBLE"}


def download_baci_zip(destination: Path) -> Path:
    """从 CEPII 官方地址下载压缩包，完成后才替换目标文件。"""
    destination = Path(destination)
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    with requests.get(BACI_URL, headers={"User-Agent": "GuanlanMacro/0.1 (educational research)"},
                      stream=True, timeout=(15, 120)) as response:
        response.raise_for_status()
        expected = int(response.headers.get("Content-Length", "0"))
        received = 0
        with part.open("wb") as output:
            for block in response.iter_content(chunk_size=8 * 1024 * 1024):
                if block:
                    output.write(block)
                    received += len(block)
                    print(f"\rBACI 官方包：{received / 1e6:,.0f} MB", end="", flush=True)
        print(flush=True)
        if expected and received != expected:
            raise IOError(f"BACI 下载不完整：{received}/{expected} 字节")
    part.replace(destination)
    return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive_members(archive: ZipFile) -> tuple[dict[int, str], str]:
    annual: dict[int, str] = {}
    country_name = f"country_codes_V{BACI_RELEASE}.csv"
    product_name = f"product_codes_{BACI_REVISION}_V{BACI_RELEASE}.csv"
    names = set(archive.namelist())
    if country_name not in names or product_name not in names:
        raise ValueError("BACI 压缩包缺少匹配版本的国家或商品代码表")
    for year in YEARS:
        name = f"BACI_{BACI_REVISION}_Y{year}_V{BACI_RELEASE}.csv"
        if name in names:
            annual[year] = name
    if not annual:
        raise ValueError("BACI 压缩包没有匹配版本的年度数据")
    return annual, country_name


def _country_codes(archive: ZipFile, member: str) -> pd.DataFrame:
    with archive.open(member) as handle:
        countries = pd.read_csv(io.BytesIO(handle.read()), dtype={"country_iso3": str})
    required = {"country_code", "country_name", "country_iso3"}
    if not required.issubset(countries.columns):
        raise ValueError("BACI 国家映射缺少必要字段")
    if countries.country_code.duplicated().any() or countries.country_iso3.isna().any():
        raise ValueError("BACI 国家映射存在重复代码或空 ISO3")
    countries = countries.rename(columns={"country_code": "numeric_code", "country_iso3": "iso3", "country_name": "name"})
    return countries[["numeric_code", "iso3", "name"]]


def _extract_member(archive: ZipFile, member: str, raw_dir: Path) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / Path(member).name
    member_info = archive.getinfo(member)
    if target.exists() and target.stat().st_size == member_info.file_size:
        checksum = 0
        with target.open("rb") as existing:
            for block in iter(lambda: existing.read(8 * 1024 * 1024), b""):
                checksum = zlib.crc32(block, checksum)
        if checksum == member_info.CRC:
            return target
    part = raw_dir / f"{target.name}.part"
    with archive.open(member) as source, part.open("wb") as destination:
        shutil.copyfileobj(source, destination, length=8 * 1024 * 1024)
    if part.stat().st_size != member_info.file_size:
        raise IOError(f"解压不完整：{member}")
    part.replace(target)
    return target


def _annual_aggregates(csv_path: Path, countries: pd.DataFrame, year: int) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    connection = duckdb.connect()
    connection.register("countries", countries)
    raw = connection.read_csv(str(csv_path), header=True, columns=RAW_COLUMNS)
    raw.create_view("raw_flows")
    audit = connection.sql("""
        SELECT count(*) AS rows, sum(v) AS total_thousand_usd,
               count(*) FILTER (WHERE t <> $year OR v IS NULL OR NOT isfinite(v) OR v < 0
                                OR NOT regexp_full_match(k, '[0-9]{6}')) AS invalid_rows,
               count(*) FILTER (WHERE e.iso3 IS NULL OR m.iso3 IS NULL) AS unmapped_rows,
               count(*) FILTER (WHERE q IS NULL) AS missing_quantity_rows
        FROM raw_flows r
        LEFT JOIN countries e ON r.i = e.numeric_code
        LEFT JOIN countries m ON r.j = m.numeric_code
    """, params={"year": year}).df().iloc[0].to_dict()
    if audit["invalid_rows"] or audit["unmapped_rows"]:
        raise ValueError(f"BACI {year} 年存在无效或未映射记录：{audit}")
    base = """
        FROM raw_flows r
        JOIN countries e ON r.i = e.numeric_code
        JOIN countries m ON r.j = m.numeric_code
    """
    pairs = connection.sql(f"""
        SELECT r.t AS year, e.iso3 AS exporter_code, e.name AS exporter_name,
               m.iso3 AS importer_code, m.name AS importer_name,
               sum(r.v) * 1000 AS trade_usd
        {base}
        GROUP BY 1, 2, 3, 4, 5
    """).df()
    chapters = connection.sql(f"""
        SELECT r.t AS year, e.iso3 AS reporter_code, e.name AS reporter_name,
               'X' AS flow, left(r.k, 2) AS hs2, sum(r.v) * 1000 AS trade_usd
        {base}
        GROUP BY 1, 2, 3, 4, 5
        UNION ALL
        SELECT r.t AS year, m.iso3 AS reporter_code, m.name AS reporter_name,
               'M' AS flow, left(r.k, 2) AS hs2, sum(r.v) * 1000 AS trade_usd
        {base}
        GROUP BY 1, 2, 3, 4, 5
    """).df()
    connection.close()
    expected = float(audit["total_thousand_usd"]) * 1000
    for name, frame, multiple in (("伙伴", pairs, 1), ("HS2", chapters, 2)):
        if abs(frame.trade_usd.sum() - expected * multiple) > max(1, expected * multiple * 1e-9):
            raise ValueError(f"BACI {year} 年{name}聚合未通过总量勾稽")
    return pairs, chapters, {
        "year": year, "raw_rows": int(audit["rows"]),
        "total_usd": expected, "missing_quantity_rows": int(audit["missing_quantity_rows"]),
        "partner_pairs": len(pairs), "country_chapters": len(chapters),
    }


def _with_flows(frame: pd.DataFrame) -> pd.DataFrame:
    exports = frame.rename(columns={
        "exporter_code": "reporter_code", "exporter_name": "reporter_name",
        "importer_code": "partner_code", "importer_name": "partner_name",
    }).assign(flow="X")
    imports = frame.rename(columns={
        "importer_code": "reporter_code", "importer_name": "reporter_name",
        "exporter_code": "partner_code", "exporter_name": "partner_name",
    }).assign(flow="M")
    return pd.concat([exports, imports], ignore_index=True)


def build_baci_snapshots(zip_path: Path, years: tuple[int, ...] = YEARS,
                         directory: Path = DEFAULT_DATA_DIR) -> dict:
    """按年份解压并聚合，不将 8 年、约八千万条 HS6 原始行同时载入内存。"""
    zip_path = Path(zip_path).resolve()
    if not zip_path.is_file():
        raise ValueError("请输入 BACI HS17 官方压缩包路径")
    selected = tuple(sorted(set(years)))
    if not selected or any(year not in YEARS for year in selected):
        raise ValueError("年份必须位于 BACI HS17 2017—2024 范围内")
    archive_hash = _sha256(zip_path)
    partner_parts, chapter_parts, audit_years = [], [], []
    with ZipFile(zip_path) as archive:
        annual, country_member = _archive_members(archive)
        missing = set(selected) - set(annual)
        if missing:
            raise ValueError(f"BACI 压缩包缺少年份：{sorted(missing)}")
        countries = _country_codes(archive, country_member)
        raw_dir = zip_path.parent / "extracted"
        for year in selected:
            print(f"BACI {year}：解压与聚合……", flush=True)
            csv_path = _extract_member(archive, annual[year], raw_dir)
            pairs, chapters, audit = _annual_aggregates(csv_path, countries, year)
            partner_parts.append(_with_flows(pairs))
            chapter_parts.append(chapters)
            audit_years.append(audit)
            print(f"  {audit['raw_rows']:,} 条商品流；{audit['partner_pairs']:,} 个双边伙伴组合", flush=True)
    partner = pd.concat(partner_parts, ignore_index=True)
    chapter = pd.concat(chapter_parts, ignore_index=True)
    for name, frame, keys in (
        ("伙伴", partner, ["year", "reporter_code", "partner_code", "flow"]),
        ("商品章", chapter, ["year", "reporter_code", "flow", "hs2"]),
    ):
        if frame.duplicated(keys).any():
            raise ValueError(f"BACI {name}聚合存在重复键")
    build_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    common = {
        "provider": "CEPII BACI", "source_url": BACI_URL,
        "release": BACI_RELEASE, "revision": BACI_REVISION,
        "raw_zip_sha256": archive_hash, "build_id": build_id,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "years": list(selected), "raw_rows": sum(item["raw_rows"] for item in audit_years),
        "audit_by_year": audit_years, "value_unit": "USD, current (BACI v × 1000)",
        "method": "BACI reconciled directional flows; imports are the reverse view of the same flows",
        "scope": "HS17 商品级全球双边流；应用快照聚合至伙伴与 HS2 商品章",
        "citation": "Gaulier, G. and Zignago, S. (2010), CEPII Working Paper 2010-23",
    }
    publish_snapshots({
        "baci_partner": (partner, {**common, "granularity": "year × reporter × partner × flow", "rows": len(partner)}),
        "baci_chapter": (chapter, {**common, "granularity": "year × reporter × flow × HS2", "rows": len(chapter)}),
    }, directory, operation="import_baci")
    return {**common, "partner_rows": len(partner), "chapter_rows": len(chapter)}
