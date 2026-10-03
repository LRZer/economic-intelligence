import numpy as np
import pandas as pd
import pytest

from guanlan.cycle_diagnostics import cycle_period_breakdown, paired_block_brier_interval
from guanlan.data import load_snapshot


def test_paired_block_interval_is_reproducible_and_preserves_paired_comparison():
    dates = pd.date_range("2017-01-01", periods=72, freq="MS")
    events = np.tile([0, 0, 1, 0, 1, 0], 12)
    frame = pd.DataFrame({"date": dates, "outcome": events,
                          "risk": np.where(events, 0.7, 0.3),
                          "baseline": np.full(72, 0.5)})
    first = paired_block_brier_interval(frame, replications=1000, seed=42)
    assert first == paired_block_brier_interval(frame, replications=1000, seed=42)
    assert first["ci_95_upper"] < 0
    assert first["missing_calendar_months"] == 0

    equal = frame.copy()
    equal["baseline"] = equal["risk"]
    equal_interval = paired_block_brier_interval(equal, replications=1000)
    assert equal_interval["brier_difference_model_minus_baseline"] == 0
    assert equal_interval["ci_95_lower"] == equal_interval["ci_95_upper"] == 0


def test_diagnostics_reject_invalid_backtests_and_show_fixed_periods():
    dates = pd.date_range("2018-01-01", periods=36, freq="MS")
    frame = pd.DataFrame({"date": dates, "outcome": [0, 1] * 18,
                          "risk": [0.3, 0.7] * 18,
                          "baseline": [0.5] * 36})
    split = cycle_period_breakdown(frame)
    assert split.months.tolist() == [12, 24]
    assert split.months.sum() == len(frame)
    assert split.events.tolist() == [6, 12]
    assert (split.difference < 0).all()
    earlier = pd.concat([pd.DataFrame({"date": [pd.Timestamp("2000-12-01")],
                                       "outcome": [0], "risk": [0.3], "baseline": [0.5]}),
                         frame], ignore_index=True)
    assert cycle_period_breakdown(earlier).months.sum() == len(earlier)
    bad = frame.copy()
    bad.loc[2, "risk"] = 1.2
    with pytest.raises(ValueError, match="概率"):
        paired_block_brier_interval(bad, replications=1000)
    bad = frame.copy()
    bad.loc[2, "date"] = bad.loc[1, "date"]
    with pytest.raises(ValueError, match="日期"):
        cycle_period_breakdown(bad)


def test_saved_cycle_uncertainty_matches_saved_backtest():
    backtest, metadata = load_snapshot("us_cycle_backtest")
    assert metadata["uncertainty"] == paired_block_brier_interval(backtest)
