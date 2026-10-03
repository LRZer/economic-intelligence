import json
import math
import pandas as pd
import pytest
from guanlan.panel_ai import INPUTS, TARGET, prepare, evaluate


def sample():
    rows=[]
    for country in range(50):
        for year in range(2000,2025):
            values=[2+country*.03+math.sin((year-2000)/3), 2+math.cos(year), 4+country*.01, 20+country*.1, country*.02]
            for code,value in zip(INPUTS,values):
                if code==INPUTS[2] and country%7==0 and year%3==0:
                    continue
                rows.append({'country_code':f'T{country:02d}','year':year,'indicator_code':code,'value':value})
    return pd.DataFrame(rows)


def test_panel_calendar_alignment_and_training_boundaries():
    data=sample()
    result=evaluate(data)
    assert result['status']=='evaluated'
    for row in result['backtest']:
        assert row['train_end'] < row['year']
        assert row['feature_year'] == row['year']-1
        assert row['split']==('validation' if row['year']<2020 else 'test')
    assert result['test_countries']==50
    # Export contains JSON null for missing features, not non-standard NaN.
    json.dumps(result,allow_nan=False)
    sparse=data.loc[~((data.country_code=='T00') & (data.year==2010))]
    aligned=prepare(sparse)
    assert aligned.loc[(aligned.country_code=='T00') & (aligned.year==2011)].empty


def test_future_labels_do_not_change_earlier_predictions_or_calibration():
    data=sample()
    first=evaluate(data)
    data.loc[(data.year==2024) & (data.indicator_code==TARGET),'value']=100
    second=evaluate(data)
    for a,b in zip(first['backtest'],second['backtest']):
        if a['year']<2024:
            assert a['prediction']==b['prediction']
    assert first['validation']==second['validation']
    assert first['interval_radius']==second['interval_radius']
    assert first['development_feature_importance']==second['development_feature_importance']
    assert first['snapshot_hash']!=second['snapshot_hash']


def test_panel_duplicate_and_insufficient_data():
    data=sample()
    with pytest.raises(ValueError,match='重复'):
        prepare(pd.concat([data,data.iloc[:1]]))
    assert evaluate(data.loc[data.country_code=='T00'])['status']=='insufficient'
