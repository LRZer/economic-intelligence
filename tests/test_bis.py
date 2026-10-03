import csv
import io
from zipfile import ZipFile

import pandas as pd
import pytest

from guanlan.bis import (
    AREA, BORROWERS, BORROWERS_AREA, EER_BASKET, EER_TYPE, FREQ, GAP_TYPE, LENDERS,
    MULTIPLIER, PERIOD, STATUS, UNIT, VALUE,
    normalize_bis_credit_zip, normalize_bis_eer_zip, normalize_bis_policy_zip,
)
from guanlan.financial import (
    credit_latest_in_year, eer_latest_in_year, eer_with_12m_change, policy_latest_in_year,
)


def _archive(filename, rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    archive = io.BytesIO()
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr(filename, output.getvalue().encode("utf-8"))
    return archive.getvalue()


def _policy_row(area="CN: China", frequency="M: Monthly", period="2024-12",
                value="3.1", status="A: Normal value"):
    return {FREQ: frequency, AREA: area, PERIOD: period, VALUE: value,
            UNIT: "368: Per cent per year", MULTIPLIER: "0: Units", STATUS: status,
            "COMPILATION:Compilation": "Policy instrument spliced by BIS",
            "SOURCE_REF:Publication Source": "Central bank"}


def test_bis_policy_import_keeps_monthly_missing_and_excludes_euro_area():
    rows = [
        _policy_row(frequency="D: Daily", period="2024-12-30", value="9"),
        _policy_row(),
        _policy_row(area="US: United States", value="4.5"),
        _policy_row(area="CN: China", period="2025-01", value="NaN",
                    status="M: Missing value; data cannot exist"),
        _policy_row(area="XM: Euro area", value="3.0"),
    ]
    frame, meta = normalize_bis_policy_zip(_archive("WS_CBPOL_csv_flat.csv", rows))
    assert len(frame) == 3
    assert set(frame.country_code) == {"CHN", "USA"}
    assert frame.loc[(frame.country_code == "CHN") & (frame.date.dt.year == 2025), "value"].isna().all()
    assert meta["missing_observations"] == 1
    assert meta["excluded_euro_area_rows"] == 1
    duplicate = rows + [rows[1]]
    with pytest.raises(ValueError, match="重复"):
        normalize_bis_policy_zip(_archive("WS_CBPOL_csv_flat.csv", duplicate))


def _credit_row(kind, value, area="CN: China"):
    return {FREQ: "Q: Quarterly", BORROWERS_AREA: area,
            BORROWERS: "P: Private non-financial sector", LENDERS: "A: All sectors",
            GAP_TYPE: kind, PERIOD: "2024-Q4", VALUE: str(value),
            UNIT: "770: Percentage of GDP", MULTIPLIER: "0: Units",
            STATUS: "A: Normal value"}


def test_bis_credit_import_reconciles_gap_and_detects_wrong_source_values():
    rows = [_credit_row("A: Credit-to-GDP ratios (actual data)", 100.001),
            _credit_row("B: Credit-to-GDP trend (HP filter)", 90.0),
            _credit_row("C: Credit-to-GDP gaps (actual-trend)", 10.001)]
    frame, meta = normalize_bis_credit_zip(_archive("WS_CREDIT_GAP_csv_flat.csv", rows))
    assert len(frame) == 3
    assert set(frame.measure) == {"ratio", "trend", "gap"}
    assert frame.date.iloc[0] == pd.Timestamp("2024-12-31")
    assert meta["reconciled_country_quarters"] == 1
    broken = [*rows[:-1], _credit_row("C: Credit-to-GDP gaps (actual-trend)", 11)]
    with pytest.raises(ValueError, match="勾稽"):
        normalize_bis_credit_zip(_archive("WS_CREDIT_GAP_csv_flat.csv", broken))
    bad_unit = [dict(row) for row in rows]
    bad_unit[0][UNIT] = "999: Changed"
    with pytest.raises(ValueError, match="口径"):
        normalize_bis_credit_zip(_archive("WS_CREDIT_GAP_csv_flat.csv", bad_unit))


def test_financial_year_end_does_not_borrow_other_years_or_fill_missing():
    policy = pd.DataFrame([
        {"country_code": "CHN", "date": pd.Timestamp("2023-12-01"), "value": 3.0, "obs_status": "A"},
        {"country_code": "CHN", "date": pd.Timestamp("2024-11-01"), "value": 2.8, "obs_status": "A"},
        {"country_code": "CHN", "date": pd.Timestamp("2024-12-01"), "value": None, "obs_status": "M"},
        {"country_code": "USA", "date": pd.Timestamp("2025-01-01"), "value": 4.3, "obs_status": "A"},
    ])
    selected = policy_latest_in_year(policy, ["CHN", "USA"], 2024).set_index("country_code")
    assert pd.isna(selected.loc["CHN", "value"])
    assert selected.loc["CHN", "obs_status"] == "M"
    assert pd.isna(selected.loc["USA", "date"])

    credit = pd.DataFrame([
        {"country_code": "CHN", "date": pd.Timestamp("2024-09-30"), "period": "2024-Q3",
         "measure": "gap", "value": 2.0},
        {"country_code": "CHN", "date": pd.Timestamp("2024-12-31"), "period": "2024-Q4",
         "measure": "ratio", "value": 100.0},
        {"country_code": "USA", "date": pd.Timestamp("2025-03-31"), "period": "2025-Q1",
         "measure": "gap", "value": 3.0},
    ])
    credit_selected = credit_latest_in_year(credit, ["CHN", "USA"], 2024).set_index("country_code")
    assert credit_selected.loc["CHN", "period"] == "2024-Q4"
    assert pd.isna(credit_selected.loc["CHN", "gap"])
    assert pd.isna(credit_selected.loc["USA", "date"])


def test_financial_comparison_modes_preserve_actual_period_and_missing_values():
    from guanlan.financial import period_comparison
    frame = pd.DataFrame([
        {"country_code": "CHN", "date": pd.Timestamp("2024-11-01"), "value": 3.0, "obs_status": "A"},
        {"country_code": "CHN", "date": pd.Timestamp("2024-12-01"), "value": None, "obs_status": "M"},
        {"country_code": "USA", "date": pd.Timestamp("2024-12-01"), "value": 4.5, "obs_status": "A"},
        {"country_code": "USA", "date": pd.Timestamp("2025-01-01"), "value": 9.0, "obs_status": "A"},
    ])
    cutoff = pd.Timestamp("2024-12-01")
    common = period_comparison(frame, ["CHN", "USA", "DEU"], cutoff).set_index("country_code")
    latest = period_comparison(frame, ["CHN", "USA", "DEU"], cutoff, "latest").set_index("country_code")
    assert pd.isna(common.loc["CHN", "value"])
    assert common.loc["CHN", "obs_status"] == "M"
    assert latest.loc["CHN", "date"] == pd.Timestamp("2024-11-01")
    assert latest.loc["CHN", "last_record_date"] == cutoff
    assert latest.loc["USA", "value"] == 4.5
    assert pd.isna(latest.loc["DEU", "date"])


def _eer_row(area="CN: China", kind="N: Nominal", basket="B: Broad",
             frequency="", period="", value="", unit="882: Index, 2020 = 100",
             status=""):
    return {AREA: area, EER_TYPE: kind, EER_BASKET: basket, FREQ: frequency,
            PERIOD: period, VALUE: value, UNIT: unit, STATUS: status}


def test_bis_eer_import_keeps_monthly_broad_and_marks_euro_area_aggregate():
    rows = [
        _eer_row(), _eer_row(kind="R: Real"), _eer_row(area="XM: Euro area"),
        _eer_row(frequency="M: Monthly", period="2024-12", value="109.21",
                 unit="", status="A: Normal value"),
        _eer_row(kind="R: Real", frequency="M: Monthly", period="2024-12",
                 value="92.26", unit="", status="A: Normal value"),
        _eer_row(area="XM: Euro area", frequency="M: Monthly", period="2024-12",
                 value="100.2", unit="", status="A: Normal value"),
        _eer_row(frequency="D: Daily", period="2024-12-31", value="999", unit="",
                 status="A: Normal value"),
    ]
    frame, meta = normalize_bis_eer_zip(_archive("WS_EER_csv_flat.csv", rows))
    assert len(frame) == 3
    assert set(frame.measure) == {"nominal", "real"}
    assert set(frame.country_code) == {"CHN", "XEA"}
    assert frame.loc[frame.country_code == "XEA", "area_type"].eq("aggregate").all()
    assert meta["countries"] == 1 and meta["aggregate_areas"] == 1
    assert meta["base"] == "2020 = 100"
    bad = [dict(row) for row in rows]
    bad[0][UNIT] = "999: Changed"
    with pytest.raises(ValueError, match="基期"):
        normalize_bis_eer_zip(_archive("WS_EER_csv_flat.csv", bad))


def test_eer_change_requires_exact_prior_calendar_month_and_year():
    frame = pd.DataFrame([
        {"country_code": "CHN", "measure": "nominal", "date": pd.Timestamp("2023-12-01"), "value": 100.0},
        {"country_code": "CHN", "measure": "nominal", "date": pd.Timestamp("2024-11-01"), "value": 105.0},
        {"country_code": "CHN", "measure": "nominal", "date": pd.Timestamp("2024-12-01"), "value": 110.0},
        {"country_code": "CHN", "measure": "real", "date": pd.Timestamp("2023-12-01"), "value": 100.0},
        {"country_code": "CHN", "measure": "real", "date": pd.Timestamp("2024-12-01"), "value": 90.0},
    ])
    changed = eer_with_12m_change(frame, ["CHN"])
    november = changed.loc[changed.date == pd.Timestamp("2024-11-01")]
    assert november.change_12m_pct.isna().all()
    latest = eer_latest_in_year(frame, ["CHN", "XEA"], 2024)
    chn = latest.loc[latest.country_code == "CHN"].set_index("measure")
    assert chn.loc["nominal", "change_12m_pct"] == pytest.approx(10.0)
    assert chn.loc["real", "change_12m_pct"] == pytest.approx(-10.0)
    assert latest.loc[latest.country_code == "XEA", "date"].isna().all()
