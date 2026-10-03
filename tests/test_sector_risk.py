import numpy as np
import pandas as pd
import pytest

from guanlan.sector_risk import FEATURES,METHODS,NUMERIC,evaluate,predict_all,validate
from guanlan.sector_report import export_bundle,scenario


def synthetic():
    rng=np.random.default_rng(17)
    rows=[]
    for year in range(2019,2026):
        for country in range(20):
            for hs in range(1,31):
                values={feature:float(rng.normal()) for feature in NUMERIC}
                rows.append({**values,'country_code':f'X{country:02d}','hs2':f'{hs:02d}','year':year,
                             'feature_year':year-1,'weight_year':year-1,'macro_year':year-1,
                             'outcome':float(values['previous_growth']<-.3) if year<2025 else np.nan})
    return pd.DataFrame(rows)


def test_walk_forward_cohorts_default_reference_calibration_and_geography():
    data=synthetic()
    backtest,latest,result=evaluate(data)
    assert len(backtest)==2400 and len(latest)==600
    assert (backtest.train_end<backtest.year).all()
    assert result['default_reference']==min(('global_rate','sector_rate','logistic'),key=lambda m:result['validation'][m]['brier'])
    assert len({result['test'][m]['n'] for m in METHODS})==1
    assert all(sum(b['n'] for b in result['calibration'][m])==1200 for m in METHODS)
    assert result['unseen_country_development_2022']['overlap_count']==0
    assert latest.outcome.isna().all() and set(latest.train_end)=={2024}
    assert latest[METHODS].ge(0).all().all() and latest[METHODS].le(1).all().all()


def test_future_observations_cannot_change_earlier_predictions():
    data=synthetic()
    train=data.loc[data.year<2021];current=data.loc[data.year==2021]
    first,_=predict_all(train,current)
    changed=data.copy();changed.loc[changed.year>=2023,NUMERIC]=999.
    changed.loc[changed.year>=2023,'outcome']=1.
    second,_=predict_all(changed.loc[changed.year<2021],changed.loc[changed.year==2021])
    np.testing.assert_allclose(first[METHODS],second[METHODS],rtol=0,atol=0)


def test_leakage_duplicate_invalid_category_and_infinite_inputs_fail():
    data=synthetic()
    with pytest.raises(ValueError,match='训练标签时点'):
        predict_all(data.loc[data.year<=2021],data.loc[data.year==2021])
    changed=data.copy();changed.loc[0,'macro_year']=changed.loc[0,'year']
    with pytest.raises(ValueError,match='泄漏'):validate(changed)
    with pytest.raises(ValueError,match='重复'):validate(pd.concat([data,data.iloc[[0]]]))
    changed=data.copy();changed.loc[0,'hs2']='00'
    with pytest.raises(ValueError,match='HS2'):validate(changed)
    changed=data.copy();changed.loc[0,NUMERIC[0]]=np.inf
    with pytest.raises(ValueError,match='无限'):validate(changed)


def test_exposure_scenario_report_escape_and_scope_boundary():
    partners=pd.DataFrame({'partner_code':['AAA','BBB'],'trade_usd':[80.,20.],'name':['<script>unsafe</script>','B']})
    shock=scenario(partners,{'AAA':-2.})
    assert shock['weighted_gdp_shock_pp']==pytest.approx(-1.6)
    assert scenario(partners,{})['weighted_gdp_shock_pp']==0
    for invalid in [{'ZZZ':-2.},{'AAA':np.nan},{'AAA':11.}]:
        with pytest.raises(ValueError):scenario(partners,invalid)
    row={'country_code':'AAA','hs2':'85','year':2025,'feature_year':2024,'weight_year':2024,'macro_year':2024,
         'train_end':2024,**{m:.2 for m in METHODS}}
    history=pd.DataFrame({'country_code':['AAA'],'hs2':['85'],'year':[2024],'outcome':[1]})
    bundle=export_bundle(row,partners,history,{'limits':'<script>bad</script>'},shock)
    assert b'<script>' not in bundle['html']
    assert b'&lt;script&gt;' in bundle['html']
    import json
    assert json.loads(bundle['json'])['scope']=={'country_code':'AAA','hs2':'85','target_year':2025}
    with pytest.raises(ValueError,match='范围'):
        export_bundle(row,partners,history.assign(country_code='BBB'),{},shock)
    with pytest.raises(ValueError,match='泄漏'):
        export_bundle({**row,'train_end':2025},partners,history,{},shock)
