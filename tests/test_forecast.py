import math
import pytest
from guanlan.forecast import analyze_series, anomaly, observations, period_label, month_id


def series(n=84):
    start = month_id('2018-01')
    return [{'period': period_label(start+i), 'value': 2 + math.sin(i/5) + .01*i} for i in range(n)]


def test_training_and_features_precede_every_target_and_missing_months_are_not_filled():
    rows = series()
    result = analyze_series(rows)
    assert result['status'] == 'evaluated'
    for point in result['backtest']:
        assert point['train_end'] < point['period']
        assert point['latest_feature_period'] < point['period']
        assert point['train_n'] >= 24
    missing = rows[45]['period']
    sparse = analyze_series([r for r in rows if r['period'] != missing])
    periods = {r['period'] for r in sparse['backtest']}
    assert missing not in periods
    assert period_label(month_id(missing)+1) not in periods


def test_future_value_cannot_change_prior_predictions_or_validation_baseline_selection():
    rows = series()
    first = analyze_series(rows)
    modified = [{**r, 'value': 9999} if i == len(rows)-1 else r for i, r in enumerate(rows)]
    second = analyze_series(modified)
    assert first['baseline'] == second['baseline']
    assert [r['ridge'] for r in first['backtest'][:-1]] == [r['ridge'] for r in second['backtest'][:-1]]
    assert first['metrics']['validation'] == second['metrics']['validation']
    assert first['interval_radius'] == second['interval_radius']
    assert first['snapshot_hash'] != second['snapshot_hash']


def test_forecast_contribution_identity_and_deterministic_results():
    first = analyze_series(series())
    second = analyze_series(series())
    assert first == second
    forecast = first['forecast']
    assert forecast['ridge'] == pytest.approx(forecast['intercept']+sum(forecast['contributions'].values()))
    assert forecast['lower'] <= forecast['ridge'] <= forecast['upper']
    scored = anomaly(series())
    assert scored['train_end'] < scored['period']
    assert scored == anomaly(series())


def test_invalid_and_insufficient_inputs_fail_explicitly():
    assert analyze_series([])['status'] == 'insufficient'
    assert analyze_series(series(20))['status'] == 'insufficient'
    with pytest.raises(ValueError, match='重复'):
        observations([{'period':'2024-01','value':1}]*2)
    for value in [float('nan'),float('inf')]:
        with pytest.raises(ValueError, match='非有限'):
            observations([{'period':'2024-01','value':value}])
    with pytest.raises(ValueError):
        month_id('2024-13')
