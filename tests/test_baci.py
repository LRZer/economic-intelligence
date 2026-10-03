from zipfile import ZipFile

import pandas as pd
import pytest

from guanlan.baci import build_baci_snapshots
from guanlan.data import load_snapshot
from guanlan.trade import HS_CHAPTERS, annual_trade_totals, chapter_profile, compact_usd


def _fixture_zip(tmp_path, destination_code="156"):
    archive = tmp_path / "BACI_HS17_V202601.zip"
    with ZipFile(archive, "w") as handle:
        handle.writestr("country_codes_V202601.csv",
                        "country_code,country_name,country_iso2,country_iso3\n"
                        "156,China,CN,CHN\n842,United States,US,USA\n276,Germany,DE,DEU\n")
        handle.writestr("product_codes_HS17_V202601.csv", "code,description\n010121,Live horses\n850110,Electric motors\n")
        handle.writestr("BACI_HS17_Y2024_V202601.csv",
                        "t,i,j,k,v,q\n"
                        f"2024,842,{destination_code},010121,2.5,1\n"
                        "2024,842,276,850110,7.5,2\n"
                        "2024,156,276,850110,10,3\n")
    return archive


def test_baci_import_preserves_hs_leading_zero_and_direction(tmp_path):
    archive = _fixture_zip(tmp_path)
    meta = build_baci_snapshots(archive, (2024,), tmp_path / "processed")
    partners, partner_meta = load_snapshot("baci_partner", tmp_path / "processed")
    chapters, chapter_meta = load_snapshot("baci_chapter", tmp_path / "processed")
    assert meta["raw_rows"] == 3
    assert meta["audit_by_year"][0]["total_usd"] == 20_000
    assert partner_meta["build_id"] == chapter_meta["build_id"]
    us_to_china = partners.loc[
        (partners.reporter_code == "USA") & (partners.partner_code == "CHN") & (partners.flow == "X")
    ]
    china_from_us = partners.loc[
        (partners.reporter_code == "CHN") & (partners.partner_code == "USA") & (partners.flow == "M")
    ]
    assert us_to_china.trade_usd.iloc[0] == china_from_us.trade_usd.iloc[0] == 2500
    assert chapters.loc[(chapters.reporter_code == "USA") & (chapters.hs2 == "01"), "trade_usd"].iloc[0] == 2500
    assert partners.loc[partners.flow == "X", "trade_usd"].sum() == 20_000
    assert chapters.loc[chapters.flow == "M", "trade_usd"].sum() == 20_000
    totals = annual_trade_totals(partners, "USA")
    assert totals.exports_usd.iloc[0] == 10_000
    assert totals.imports_usd.iloc[0] == 0
    profile = chapter_profile(chapters, "USA", 2024)
    assert profile.loc[profile.hs2 == "01", "rca"].iloc[0] == pytest.approx(2.0)
    assert profile.loc[profile.hs2 == "01", "chapter"].iloc[0] == "活动物"
    assert pd.isna(chapter_profile(chapters, "USA", 2024, "M").rca).all()
    assert compact_usd(3_592_205_537_980) == "3.59万亿"


def test_hs_chapter_names_cover_real_snapshot():
    chapters, _ = load_snapshot("baci_chapter")
    assert set(chapters.hs2).issubset(HS_CHAPTERS)


def test_baci_import_rejects_unmapped_country(tmp_path):
    archive = _fixture_zip(tmp_path, destination_code="999")
    with pytest.raises(ValueError, match="未映射"):
        build_baci_snapshots(archive, (2024,), tmp_path / "processed")
