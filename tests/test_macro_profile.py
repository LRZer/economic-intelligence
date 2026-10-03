import pandas as pd
import pytest

from guanlan.analytics import GROWTH, INFLATION
from guanlan.macro_profile import build_macro_profile


def _sample():
    current = {
        "AAA": {GROWTH: 2.0, INFLATION: 1.0},
        "BBB": {GROWTH: 2.0, INFLATION: None},
        "CCC": {GROWTH: 4.0, INFLATION: 3.0},
        "DDD": {GROWTH: None, INFLATION: 2.0},
    }
    rows = [{"country_code": country, "country_name": country, "year": 2024,
             "indicator_code": code, "value": value}
            for country, indicators in current.items() for code, value in indicators.items()]
    rows.extend([
        {"country_code": "AAA", "country_name": "AAA", "year": 2019,
         "indicator_code": GROWTH, "value": 1.0},
        {"country_code": "BBB", "country_name": "BBB", "year": 2023,
         "indicator_code": GROWTH, "value": 99.0},
        {"country_code": "AAA", "country_name": "AAA", "year": 2025,
         "indicator_code": GROWTH, "value": 100.0},
    ])
    return pd.DataFrame(rows)


def test_profile_keeps_global_ties_missing_and_exact_five_year_endpoints():
    profile = build_macro_profile(_sample(), ["AAA", "BBB", "DDD"], 2024,
                                  [GROWTH, INFLATION])
    assert list(profile[["country_code", "indicator_code"]].itertuples(index=False, name=None)) == [
        ("AAA", GROWTH), ("AAA", INFLATION),
        ("BBB", GROWTH), ("BBB", INFLATION),
        ("DDD", GROWTH), ("DDD", INFLATION),
    ]
    growth = profile.loc[profile.indicator_code == GROWTH].set_index("country_code")
    assert growth.loc["AAA", "global_percentile"] == pytest.approx(100 / 3)
    assert growth.loc["BBB", "global_percentile"] == pytest.approx(100 / 3)
    assert growth.loc["AAA", "global_observed"] == 3
    assert growth.loc["AAA", "global_total"] == 4
    assert growth.loc["AAA", "delta_pp"] == 1.0
    assert pd.isna(growth.loc["BBB", "past_value"])
    assert pd.isna(growth.loc["BBB", "delta_pp"])
    assert pd.isna(growth.loc["DDD", "value"])
    assert pd.isna(growth.loc["DDD", "global_percentile"])
    inflation = profile.loc[profile.indicator_code == INFLATION].set_index("country_code")
    assert pd.isna(inflation.loc["BBB", "value"])
    assert inflation.loc["DDD", "global_percentile"] == 50.0
    no_past = build_macro_profile(_sample(), ["AAA"], 2024, [GROWTH], lookback=30)
    assert pd.isna(no_past.delta_pp.iloc[0])


def test_profile_rejects_duplicate_observations_and_unsupported_indicators():
    sample = _sample()
    duplicate = pd.concat([sample, sample.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="重复"):
        build_macro_profile(duplicate, ["AAA"], 2024, [GROWTH])
    with pytest.raises(ValueError, match="百分比"):
        build_macro_profile(sample, ["AAA"], 2024, ["NY.GDP.MKTP.CD"])
    nonfinite = sample.copy()
    nonfinite.loc[(nonfinite.country_code == "AAA") & (nonfinite.year == 2024)
                  & (nonfinite.indicator_code == GROWTH), "value"] = float("inf")
    with pytest.raises(ValueError, match="非有限"):
        build_macro_profile(nonfinite, ["AAA"], 2024, [GROWTH])
