import pandas as pd

from guanlan.analytics import GROWTH, INFLATION, classify_regime, country_observation_status, trade_concentration, trade_partner_table


def _macro_series(future_growth=100):
    records = []
    for year in range(2014, 2025):
        records.append({"country_code": "AAA", "year": year, "indicator_code": GROWTH, "value": 2 if year < 2024 else 3})
        records.append({"country_code": "AAA", "year": year, "indicator_code": INFLATION, "value": 4 if year < 2024 else 3})
    records += [
        {"country_code": "AAA", "year": 2025, "indicator_code": GROWTH, "value": future_growth},
        {"country_code": "AAA", "year": 2025, "indicator_code": INFLATION, "value": future_growth},
    ]
    return pd.DataFrame(records)


def test_regime_uses_only_past_observations():
    result = classify_regime(_macro_series(), "AAA", 2024)
    changed_future = classify_regime(_macro_series(future_growth=-100), "AAA", 2024)
    assert result == changed_future
    assert result.label == "增长高于历史中位 · 通胀低于历史中位"
    assert result.growth_reference == 2
    assert result.inflation_reference == 4


def test_regime_requires_five_historical_values():
    short = _macro_series().query("year >= 2021")
    assert classify_regime(short, "AAA", 2024) is None


def test_trade_concentration_normalizes_partners():
    frame = pd.DataFrame(
        [
            {"reporter_code": "AAA", "partner_code": "BBB", "partner_name": "B", "year": 2024, "flow": "X", "trade_usd": 75},
            {"reporter_code": "AAA", "partner_code": "CCC", "partner_name": "C", "year": 2024, "flow": "X", "trade_usd": 25},
            {"reporter_code": "AAA", "partner_code": "DDD", "partner_name": "D", "year": 2023, "flow": "X", "trade_usd": 999},
        ]
    )
    partners = trade_partner_table(frame, "AAA", 2024)
    result = trade_concentration(partners)
    assert len(partners) == 2
    assert result["hhi"] == 0.625
    assert result["top5_share"] == 1.0


def test_observation_status_does_not_use_future_year_as_fallback():
    frame = pd.DataFrame([
        {"country_code": "AAA", "year": 2023, "indicator_code": GROWTH, "value": 2.0},
        {"country_code": "AAA", "year": 2024, "indicator_code": GROWTH, "value": None},
        {"country_code": "AAA", "year": 2025, "indicator_code": GROWTH, "value": 100.0},
    ])
    result = country_observation_status(frame, "AAA", 2024)
    row = result.loc[result.indicator_code == GROWTH].iloc[0]
    assert not row.has_observation
    assert row.latest_observed_year_through_selection == 2023
    assert row.years_since_last_observation == 1
