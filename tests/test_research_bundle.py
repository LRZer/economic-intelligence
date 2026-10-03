import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest

from guanlan.analytics import GROWTH, INFLATION
from guanlan.data import load_snapshot
from guanlan.research_bundle import _chart_svg, build_research_bundle
from guanlan.research_compare import compare_research_packages, verify_research_package


def _data():
    rows = []
    for code, name, growth in (
        ("AAA", "<script>alert(1)</script>", 4.0),
        ("BBB", "乙国", 2.0),
        ("DDD", "丁国", None),
    ):
        rows.append({"country_code": code, "country_name": name, "region": "东区",
                     "income_level": "中收入", "year": 2024,
                     "indicator_code": GROWTH, "value": growth})
    for year, code, value in ((2022, GROWTH, 3.0), (2023, GROWTH, 3.5),
                              (2022, INFLATION, 2.0), (2023, INFLATION, 2.5),
                              (2024, INFLATION, 3.0)):
        rows.append({"country_code": "AAA", "country_name": "<script>alert(1)</script>",
                     "region": "东区", "income_level": "中收入", "year": year,
                     "indicator_code": code, "value": value})
    rows.append({**rows[0], "year": 2025, "value": 100.0})
    return pd.DataFrame(rows)


def test_research_package_is_reproducible_and_checks_every_file():
    macro_meta = {"provider": "World Bank WDI", "parquet_sha256": "a" * 64,
                  "downloaded_at_utc": "2026-09-01T00:00:00+00:00"}
    trade_meta = {"provider": "CEPII BACI", "parquet_sha256": "b" * 64,
                  "downloaded_at_utc": "2026-09-01T00:00:00+00:00"}
    trade = pd.DataFrame([{"reporter_code": "AAA", "partner_code": "BBB", "partner_name": "乙国",
                           "year": 2023, "flow": "X", "trade_usd": 100.0}])
    weo = pd.DataFrame([{"country_code": "AAA", "indicator_code": "NGDP_RPCH",
                         "year": 2026, "value": 4.4}])
    weo_meta = {"provider": "IMF WEO DataMapper", "vintage": "April 2026",
                "parquet_sha256": "c" * 64}
    args = (_data(), trade, macro_meta, trade_meta, "AAA", 2024, GROWTH, "同收入组")
    first = build_research_bundle(*args, weo=weo, weo_meta=weo_meta)
    second = build_research_bundle(*args, weo=weo, weo_meta=weo_meta)
    assert first.report_id == second.report_id
    assert first.archive == second.archive
    changed_macro = _data()
    changed_macro.loc[(changed_macro.country_code == "AAA") & (changed_macro.year == 2024)
                      & (changed_macro.indicator_code == GROWTH), "value"] = 5.0
    changed = build_research_bundle(changed_macro, trade, macro_meta, trade_meta,
                                    "AAA", 2024, GROWTH, "同收入组", weo=weo, weo_meta=weo_meta)
    assert changed.report_id != first.report_id
    assert first.manifest["snapshot_checksums_complete"] is True
    assert first.report_id in first.markdown and first.report_id in first.html
    assert "<script>alert(1)</script>" not in first.html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in first.html
    assert "<svg" in first.html and "<table>" in first.html
    with ZipFile(io.BytesIO(first.archive)) as archive:
        paths = set(archive.namelist())
        assert {"report.html", "report.md", "manifest.json", "data/peer_sample.csv",
                "data/growth_inflation_history.csv", "data/imf_forecast.csv"} <= paths
        manifest = json.loads(archive.read("manifest.json"))
        for path, expected in manifest["files_sha256"].items():
            assert hashlib.sha256(archive.read(path)).hexdigest() == expected
        peer = pd.read_csv(io.BytesIO(archive.read("data/peer_sample.csv")))
        assert len(peer) == 3
        assert pd.isna(peer.loc[peer.country_code == "DDD", "value"]).all()
        assert 100.0 not in peer.value.values
        partners = pd.read_csv(io.BytesIO(archive.read("data/export_partners.csv")))
        assert partners.empty
        forecast = pd.read_csv(io.BytesIO(archive.read("data/imf_forecast.csv")))
        assert forecast.status.iloc[0] == "IMF staff projection"


def test_history_chart_keeps_missing_year_as_a_gap():
    history = pd.DataFrame([
        {"year": 2021, "indicator_code": GROWTH, "value": 1.0},
        {"year": 2022, "indicator_code": GROWTH, "value": 2.0},
        {"year": 2023, "indicator_code": GROWTH, "value": None},
        {"year": 2024, "indicator_code": GROWTH, "value": 3.0},
    ])
    svg = _chart_svg(history)
    assert svg.count("<polyline") == 1
    assert svg.count("<circle") == 3


def test_version_comparison_separates_value_revisions_membership_and_forecasts():
    old_macro = _data()
    new_macro = old_macro.copy()
    new_macro.loc[(new_macro.country_code == "AAA") & (new_macro.year == 2024)
                  & (new_macro.indicator_code == GROWTH), "value"] = 5.0
    new_macro = pd.concat([new_macro, pd.DataFrame([{
        "country_code": "CCC", "country_name": "丙国", "region": "东区", "income_level": "中收入",
        "year": 2024, "indicator_code": GROWTH, "value": 1.0,
    }])], ignore_index=True)
    old_trade = pd.DataFrame([{"reporter_code": "AAA", "partner_code": "BBB", "partner_name": "乙国",
                               "year": 2024, "flow": "X", "trade_usd": 100.0}])
    new_trade = old_trade.copy()
    new_trade.loc[0, "trade_usd"] = 125.0
    old_weo = pd.DataFrame([{"country_code": "AAA", "indicator_code": "NGDP_RPCH",
                             "year": 2026, "value": 4.4}])
    new_weo = old_weo.copy()
    new_weo.loc[0, "value"] = 4.1
    old = build_research_bundle(old_macro, old_trade, {"parquet_sha256": "a" * 64},
                                {"provider": "CEPII BACI", "parquet_sha256": "b" * 64},
                                "AAA", 2024, GROWTH, "同收入组", weo=old_weo,
                                weo_meta={"parquet_sha256": "c" * 64, "vintage": "April 2026"})
    new = build_research_bundle(new_macro, new_trade, {"parquet_sha256": "d" * 64},
                                {"provider": "CEPII BACI", "parquet_sha256": "e" * 64},
                                "AAA", 2024, GROWTH, "同收入组", weo=new_weo,
                                weo_meta={"parquet_sha256": "f" * 64, "vintage": "October 2026"})
    comparison = compare_research_packages(verify_research_package(old.archive),
                                           verify_research_package(new.archive))
    annual = comparison.tables["年度 WDI 指标"]
    assert annual.loc[annual.indicator_code == GROWTH, "差值"].iloc[0] == 1.0
    peer = comparison.tables["同组样本"]
    assert peer.loc[peer.country_code == "CCC", "变化类型"].iloc[0] == "加入样本"
    assert peer.loc[peer.country_code == "DDD", "变化类型"].iloc[0] == "未变化"
    assert comparison.tables["出口伙伴"].iloc[0]["差值"] == 25.0
    assert comparison.tables["IMF 预测"].iloc[0]["差值"] == pytest.approx(-0.3)
    assert "2024" in comparison.markdown and old.report_id in comparison.markdown


def test_research_package_rejects_tampering_and_different_selections():
    macro = _data()
    args = (macro, pd.DataFrame(), {"parquet_sha256": "a" * 64}, {},
            "AAA", 2024, GROWTH, "同收入组")
    old = build_research_bundle(*args)
    with ZipFile(io.BytesIO(old.archive)) as original:
        altered = io.BytesIO()
        with ZipFile(altered, "w") as rewritten:
            for name in original.namelist():
                content = original.read(name)
                if name == "data/annual_indicators.csv":
                    content += b"tampered"
                rewritten.writestr(name, content)
    with pytest.raises(ValueError, match="SHA-256"):
        verify_research_package(altered.getvalue())
    other = build_research_bundle(macro, pd.DataFrame(), {"parquet_sha256": "a" * 64}, {},
                                  "AAA", 2024, GROWTH, "全球")
    with pytest.raises(ValueError, match="不同"):
        compare_research_packages(verify_research_package(old.archive),
                                  verify_research_package(other.archive))


def test_unit_change_does_not_report_numeric_delta_as_comparable():
    bundle = build_research_bundle(_data(), pd.DataFrame(), {"parquet_sha256": "a" * 64}, {},
                                   "AAA", 2024, GROWTH, "同收入组")
    verified = verify_research_package(bundle.archive)
    annual = verified.tables["年度 WDI 指标"].copy()
    annual.loc[annual.indicator_code == GROWTH, "unit"] = "另一单位"
    changed = replace(verified, tables={**verified.tables, "年度 WDI 指标": annual})
    result = compare_research_packages(verified, changed)
    row = result.tables["年度 WDI 指标"].loc[
        result.tables["年度 WDI 指标"].indicator_code == GROWTH].iloc[0]
    assert row["变化类型"] == "单位或口径变化"
    assert pd.isna(row["差值"])


def test_bis_financial_report_preserves_periods_and_comparison_scope():
    policy = pd.DataFrame([
        {"country_code": "AAA", "date": pd.Timestamp("2023-12-01"), "value": 3.4, "obs_status": "A"},
        {"country_code": "AAA", "date": pd.Timestamp("2024-12-01"), "value": 3.1, "obs_status": "A"},
        {"country_code": "AAA", "date": pd.Timestamp("2025-01-01"), "value": 2.9, "obs_status": "A"},
    ])
    credit = pd.DataFrame([
        {"country_code": "AAA", "date": pd.Timestamp("2024-12-31"), "period": "2024-Q4",
         "measure": measure, "value": value, "obs_status": "A"}
        for measure, value in (("ratio", 100.0), ("trend", 95.0), ("gap", 5.0))
    ])
    args = (_data(), pd.DataFrame(), {"parquet_sha256": "a" * 64}, {},
            "AAA", 2024, GROWTH, "同收入组")
    meta_policy = {"provider": "BIS", "parquet_sha256": "b" * 64,
                   "source_archive_sha256": "1" * 64}
    meta_credit = {"provider": "BIS", "parquet_sha256": "c" * 64,
                   "source_archive_sha256": "2" * 64}
    old = build_research_bundle(*args, bis_policy=policy, bis_credit=credit,
                                bis_policy_meta=meta_policy, bis_credit_meta=meta_credit)
    verified = verify_research_package(old.archive)
    assert verified.manifest["format_version"] == "3"
    assert "<p>政策利率工具因国而异" in old.html
    assert set(verified.manifest["sources"]) == {"wdi", "bis_policy", "bis_credit"}
    finance = verified.tables["BIS 金融条件"].set_index("indicator_code")
    assert finance.loc["BIS.CBPOL", "period"] == "2024-12"
    assert finance.loc["BIS.CBPOL", "value"] == 3.1
    assert finance.loc["BIS.CREDIT_GAP", "period"] == "2024-Q4"
    assert "金融条件（BIS）" in old.markdown
    assert old.manifest["coverage"]["bis_observed_measures"] == 4

    revised_policy = policy.copy()
    revised_policy.loc[revised_policy.date == pd.Timestamp("2024-12-01"), "value"] = 3.0
    revised_credit = credit.copy()
    revised_credit["date"] = pd.Timestamp("2024-09-30")
    revised_credit["period"] = "2024-Q3"
    new = build_research_bundle(*args, bis_policy=revised_policy, bis_credit=revised_credit,
                                bis_policy_meta=meta_policy, bis_credit_meta=meta_credit)
    comparison = compare_research_packages(verified, verify_research_package(new.archive))
    changes = comparison.tables["BIS 金融条件"].set_index("indicator_code")
    assert changes.loc["BIS.CBPOL", "差值"] == pytest.approx(-0.1)
    assert changes.loc["BIS.CREDIT_GAP", "变化类型"] == "观察期或单位变化"
    assert pd.isna(changes.loc["BIS.CREDIT_GAP", "差值"])

    missing_policy = policy.copy()
    missing_policy.loc[missing_policy.date == pd.Timestamp("2024-12-01"), ["value", "obs_status"]] = [None, "M"]
    missing = build_research_bundle(*args, bis_policy=missing_policy, bis_credit=credit,
                                    bis_policy_meta=meta_policy, bis_credit_meta=meta_credit)
    missing_row = verify_research_package(missing.archive).tables["BIS 金融条件"].set_index(
        "indicator_code").loc["BIS.CBPOL"]
    assert missing_row["period"] == "2024-12"
    assert pd.isna(missing_row["value"])
    assert missing_row["obs_status"] == "M"


def test_saved_format_2_report_compares_with_current_bis_report():
    old_path = Path(__file__).parent / "fixtures" / "research_v2_china_2024.zip"
    earlier = verify_research_package(old_path.read_bytes())
    assert earlier.manifest["format_version"] == "2"
    macro, macro_meta = load_snapshot("macro")
    trade, trade_meta = load_snapshot("baci_partner")
    weo, weo_meta = load_snapshot("weo")
    policy, policy_meta = load_snapshot("bis_policy")
    credit, credit_meta = load_snapshot("bis_credit")
    current = build_research_bundle(
        macro, trade, macro_meta, trade_meta, "CHN", 2024, GROWTH, "同收入组",
        weo=weo, weo_meta=weo_meta, bis_policy=policy, bis_credit=credit,
        bis_policy_meta=policy_meta, bis_credit_meta=credit_meta,
    )
    result = compare_research_packages(earlier, verify_research_package(current.archive))
    assert result.tables["BIS 金融条件"]["变化类型"].eq("新版新增资料").all()
    assert result.tables["BIS 金融条件"]["差值"].isna().all()
