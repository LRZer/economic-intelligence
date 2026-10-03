import pandas as pd
import pytest

from guanlan.catalog import country_label
from guanlan.data import load_snapshot
from guanlan.weo import (
    EXPECTED_SOURCE,
    WEO_INDICATORS,
    forecast_cross_section,
    growth_inflation_map,
    normalize_weo_forecasts,
)


def _api_fixture():
    indicators = {"indicators": {
        code: {"label": name, "unit": "Annual percent change", "source": EXPECTED_SOURCE}
        for code, name in WEO_INDICATORS.items()
    }}
    countries = {"countries": {"USA": {"label": "United States"}, "CHN": {"label": "China"}}}
    payloads = {
        code: {
            "indicators": {code: {"unit": "Annual percent change", "source": EXPECTED_SOURCE}},
            "values": {code: {"USA": {"2026": 2.1, "2027": 2.0}, "CHN": {"2026": 4.4}}},
        }
        for code in WEO_INDICATORS
    }
    return indicators, countries, payloads


def test_weo_normalization_preserves_missing_forecast_and_vintage():
    frame, catalog = normalize_weo_forecasts(*_api_fixture())
    assert len(frame) == 2 * len(WEO_INDICATORS) * 6
    assert frame.loc[(frame.country_code == "CHN") & (frame.indicator_code == "NGDP_RPCH") &
                     (frame.year == 2026), "value"].iloc[0] == 4.4
    assert pd.isna(frame.loc[(frame.country_code == "CHN") & (frame.year == 2027), "value"]).all()
    assert catalog["NGDP_RPCH"]["source"] == EXPECTED_SOURCE
    assert len(forecast_cross_section(frame, "NGDP_RPCH", 2026)) == 2
    assert len(forecast_cross_section(frame, "NGDP_RPCH", 2027)) == 1


def test_weo_refuses_silent_new_vintage():
    indicators, countries, payloads = _api_fixture()
    payloads["NGDP_RPCH"]["indicators"]["NGDP_RPCH"]["source"] = "World Economic Outlook (October 2026)"
    with pytest.raises(ValueError, match="版本"):
        normalize_weo_forecasts(indicators, countries, payloads)


def test_weo_omits_country_without_future_values():
    indicators, countries, payloads = _api_fixture()
    countries["countries"]["AFG"] = {"label": "Afghanistan"}
    for payload in payloads.values():
        code = next(iter(payload["values"]))
        payload["values"][code]["AFG"] = {"2024": 1.0}
    frame, _ = normalize_weo_forecasts(indicators, countries, payloads)
    assert set(frame.country_code) == {"USA", "CHN"}


def test_forecast_country_names_are_localized():
    assert country_label("GUY", "Guyana") == "圭亚那（GUY）"
    assert country_label("UVK", "Kosovo") == "科索沃（UVK）"


def test_saved_weo_snapshot_counts_only_countries_with_forecasts():
    frame, metadata = load_snapshot("weo")
    assert metadata["vintage"] == "April 2026"
    assert metadata["countries"] == frame.country_code.nunique() == 191
    assert metadata["available_values"] == frame.value.notna().sum() == 16_455
    assert frame.groupby("country_code").value.count().gt(0).all()


def test_growth_inflation_map_uses_same_year_and_can_add_focus():
    rows = []
    for code, name, gdp, growth, inflation in [
        ("USA", "United States", 100, 2, 3),
        ("CHN", "China", 80, 4, 2),
        ("DEU", "Germany", 20, 1, 4),
    ]:
        for indicator, value in (("NGDPD", gdp), ("NGDP_RPCH", growth), ("PCPIPCH", inflation)):
            rows.append({"country_code": code, "country_name": name, "year": 2026,
                         "indicator_code": indicator, "value": value})
    frame = pd.DataFrame(rows)
    selected = growth_inflation_map(frame, 2026, highlight="DEU", top_n=2)
    assert set(selected.country_code) == {"USA", "CHN", "DEU"}
    assert selected.loc[selected.country_code == "DEU", "inflation"].iloc[0] == 4
