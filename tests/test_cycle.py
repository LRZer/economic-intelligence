import numpy as np
import pandas as pd
import pytest

from guanlan.cycle import FEATURES, build_cycle_features, evaluate_cycle, training_window
from guanlan.data import load_snapshot
def test_future_label_is_missing_when_horizon_not_observed():
    dates = pd.date_range("2020-01-01", periods=30, freq="MS")
    values = {
        "UNEMP_SA": [4.0] * 30,
        "CPI_SA": np.linspace(100, 110, 30),
        "IP_SA": np.linspace(100, 95, 30),
        "EFFR": [2.0] * 30,
    }
    monthly = pd.DataFrame(
        [
            {"date": date, "series_code": code, "value": value}
            for code, series in values.items()
            for date, value in zip(dates, series)
        ]
    )
    features = build_cycle_features(monthly, horizon=6)
    assert np.isnan(features.loc[dates[11], "ip_yoy"])
    assert np.isfinite(features.loc[dates[12], "ip_yoy"])
    assert features.loc[dates[20], "contraction_at_horizon"] == 1
    assert np.isnan(features.loc[dates[-6]:, "contraction_at_horizon"]).all()


def test_training_window_purges_unfinished_future_outcomes():
    dates = pd.date_range("2000-01-01", periods=180, freq="MS")
    frame = pd.DataFrame({feature: np.arange(180) / 180 for feature in FEATURES}, index=dates)
    frame["contraction_at_horizon"] = 0.0
    current_position = 150
    train = training_window(frame, current_position, horizon=6, lookback=120, min_train=100)
    assert len(train) == 120
    assert train.index.max() == dates[current_position - 7]
    assert train.index.max() < dates[current_position - 6]


def test_snapshot_backtest_has_chronological_training_and_bounded_probabilities():
    monthly, _ = load_snapshot("us_monthly")
    backtest, signal, metrics = evaluate_cycle(build_cycle_features(monthly))
    assert len(backtest) == metrics["months"] > 100
    assert backtest.risk.between(0, 1).all()
    assert backtest.baseline.between(0, 1).all()
    assert (backtest.training_last_month < backtest.date - pd.DateOffset(months=6)).all()
    assert 0 <= signal.risk <= 1
    assert metrics["model_brier"] >= 0
    assert metrics["baseline_brier"] >= 0


def test_backtest_handles_missing_feature_month_without_lag_leakage():
    monthly, _ = load_snapshot("us_monthly")
    features = build_cycle_features(monthly)
    features = features.drop(pd.Timestamp("2015-06-01"))
    backtest, _, _ = evaluate_cycle(features)
    assert (backtest.training_last_month < backtest.date - pd.DateOffset(months=6)).all()
