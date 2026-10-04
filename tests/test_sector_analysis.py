import copy
import json

import numpy as np
import pandas as pd
import pytest

from guanlan.sector_analysis import (cohort_for_year, comparison_frame, feature_peer_profile,
    historical_event_context, validate_context, validate_partner_evidence)
from guanlan.sector_report import export_bundle, scenario
from guanlan.sector_risk import METHODS, NUMERIC


def inputs():
    rows=[]
    for year in [2019,2020,2021,2022,2023,2024,2025]:
        for country in ['AAA','BBB','CCC']:
            for hs in ['01','85']:
                rows.append({**{k:1. for k in NUMERIC},'country_code':country,'hs2':hs,'year':year,
                             'feature_year':year-1,'weight_year':year-1,'macro_year':year-1,
                             'outcome':float(country=='AAA') if year<2025 else np.nan,
                             'lag_export_usd':100.,'partner_gdp_coverage':.8,'partner_gdp':2.})
    features=pd.DataFrame(rows)
    scores=features.loc[features.year>=2021].copy()
    for method in METHODS:scores[method]=.3
    scores['train_end']=scores.year-1
    scores['train_n']=10
    for year in scores.year.unique():
        incidence=historical_event_context(features,'85',int(year))
        scores.loc[scores.year==year,'sector_rate']=incidence['smoothed_sector_rate']
    return features,scores.loc[scores.year<2025],scores.loc[scores.year==2025]


def test_year_scoped_cohort_comparisons_and_input_midrank():
    _,back,latest=inputs()
    cohort=cohort_for_year(latest,back,2023)
    assert set(cohort.year)=={2023} and len(cohort)==6
    country=comparison_frame(cohort,'AAA','85','country')
    industry=comparison_frame(cohort,'AAA','85','industry')
    assert len(country)==2 and set(country.country_code)=={'AAA'}
    assert len(industry)==3 and set(industry.hs2)=={'85'}
    assert country.selected.sum()==1 and country.covered_export_share.sum()==pytest.approx(1.)
    row=country.loc[country.selected].iloc[0].to_dict()
    profile=feature_peer_profile(row,country)
    assert profile.midrank_percentile.eq(.5).all()
    assert profile.peer_constant.all()
    with pytest.raises(ValueError,match='开发期'):cohort_for_year(latest,back,2022)
    with pytest.raises(ValueError,match='没有'):cohort_for_year(latest,back,2026)
    with pytest.raises(ValueError,match='重复'):cohort_for_year(latest,pd.concat([back,back]),2023)
    changed=back.copy();changed.loc[changed.year==2023,'train_end']=2023
    with pytest.raises(ValueError,match='时点'):cohort_for_year(latest,changed,2023)


def test_prior_event_interval_is_reproducible_and_ignores_future_labels():
    features,_,_=inputs()
    original=historical_event_context(features,'85',2023)
    changed=features.copy();changed.loc[changed.year>=2023,'outcome']=999.
    assert historical_event_context(changed,'85',2023)==original
    assert original['last_label_year']==2022 and original['n']==12
    assert original['countries']==3 and original['event_rate']==pytest.approx(1/3)
    assert original['historical_event_rate_cluster_interval_95'][0]<=original['event_rate']
    with pytest.raises(ValueError,match='重复'):historical_event_context(pd.concat([features,features]),'85',2023)


def test_partner_evidence_rejects_mixed_macro_versions_and_coverage():
    row={'lag_export_usd':100.,'partner_gdp_coverage':.8,'partner_gdp':2.}
    partners=pd.DataFrame({'partner_code':['AAA','BBB'],'trade_usd':[80.,20.],'gdp_growth':[2.,np.nan]})
    validate_partner_evidence(row,partners)
    with pytest.raises(ValueError,match='GDP与'):validate_partner_evidence(row,partners.assign(gdp_growth=[3.,np.nan]))
    with pytest.raises(ValueError,match='覆盖'):validate_partner_evidence(row,partners.assign(gdp_growth=[2.,0.]))
    with pytest.raises(ValueError,match='规模'):validate_partner_evidence(row,partners.assign(trade_usd=[80.,30.]))


def test_report_preserves_year_peer_scope_interval_and_refuses_future_history():
    features,back,latest=inputs()
    cohort=cohort_for_year(latest,back,2023)
    peers=comparison_frame(cohort,'AAA','85','industry')
    row=peers.loc[peers.selected].iloc[0].to_dict()
    context={'country_code':'AAA','hs2':'85','target_year':2023,'lens':'industry','peer_count':3,
             'peers':peers.to_dict('records'),'training_event_context':historical_event_context(features,'85',2023)}
    partners=pd.DataFrame({'partner_code':['AAA','BBB'],'trade_usd':[80.,20.],'gdp_growth':[2.,np.nan]})
    history=back.loc[(back.country_code=='AAA')&(back.hs2=='85')&(back.year<=2023)]
    output=export_bundle(row,partners,history,{},scenario(partners,{'AAA':-2.}),context)
    exported=json.loads(output['json'])
    assert exported['scope']['target_year']==2023
    assert exported['comparison_context']['training_event_context']['last_label_year']==2022
    assert exported['comparison_context']['peer_count']==3
    assert b'2023' in output['html'] and b'<script>' not in output['html']
    changed=copy.deepcopy(context);changed['peers'][0]['macro_year']=2023
    with pytest.raises(ValueError,match='泄漏'):validate_context(changed,row)
    changed=copy.deepcopy(context);changed['target_year']=2025
    with pytest.raises(ValueError,match='范围'):validate_context(changed,row)
    changed=copy.deepcopy(context);changed['training_event_context']['last_label_year']=2023
    with pytest.raises(ValueError,match='时点'):validate_context(changed,row)
    with pytest.raises(ValueError,match='超出'):export_bundle(row,partners,history.assign(year=2024),{},scenario(partners,{}),context)
