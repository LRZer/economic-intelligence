"""Finite, development-selected reference experiment; protocol lives in docs."""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .panel_ai import FEATURE_NAMES, PARAMS, TARGET, metrics, prepare, records

METHODS = ('persistence', 'median5', 'ridge10', 'hgb', 'residual_hgb')


def dataset(frame: pd.DataFrame) -> pd.DataFrame:
    data = prepare(frame)
    gdp = frame.loc[frame.indicator_code == TARGET].set_index(['country_code', 'year']).value.to_dict()
    centers = []
    for row in data.itertuples(index=False):
        values = [gdp.get((row.country_code, year), np.nan) for year in range(row.year-5, row.year)]
        values = [v for v in values if pd.notna(v)]
        centers.append(float(np.median(values)) if len(values) >= 3 else gdp[(row.country_code, row.year-1)])
    data['median5'] = centers
    return data


def predictions(train: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    result = current.copy()
    result['persistence'] = current[FEATURE_NAMES[0]]
    ridge = make_pipeline(SimpleImputer(strategy='median', add_indicator=True, keep_empty_features=True),
                          StandardScaler(), Ridge(alpha=10.0))
    ridge.fit(train[FEATURE_NAMES], train.actual)
    result['ridge10'] = ridge.predict(current[FEATURE_NAMES])
    raw = HistGradientBoostingRegressor(**PARAMS).fit(train[FEATURE_NAMES], train.actual)
    residual = HistGradientBoostingRegressor(**PARAMS).fit(train[FEATURE_NAMES], train.actual-train.median5)
    result['hgb'] = raw.predict(current[FEATURE_NAMES])
    result['residual_hgb'] = current.median5 + residual.predict(current[FEATURE_NAMES])
    result['train_end'] = int(train.year.max())
    result['feature_year'] = result.year - 1
    result['train_n'] = len(train)
    return result


def grouped_interval(test: pd.DataFrame, model: str, baseline: str) -> list[float]:
    delta = (test[model]-test.actual).abs() - (test[baseline]-test.actual).abs()
    grouped = test.assign(delta=delta).groupby('country_code').delta.agg(['sum','count'])
    rng = np.random.default_rng(42)
    indices = rng.integers(0, len(grouped), size=(2000,len(grouped)))
    differences = grouped['sum'].to_numpy()[indices].sum(axis=1) / grouped['count'].to_numpy()[indices].sum(axis=1)
    return np.quantile(differences,[.025,.975]).tolist()


def evaluate_references(frame: pd.DataFrame) -> dict:
    data = dataset(frame)
    known = data.loc[data.actual.notna()]
    signature = hashlib.sha256(pd.util.hash_pandas_object(data,index=True).values.tobytes()).hexdigest()
    result = {'version':'wdi-finite-reference-v1', 'snapshot_hash':signature,
              'protocol':'docs/EXPERIMENT_PROTOCOL.md', 'status':'insufficient',
              'test_interpretation':'2020—2024已在原实验查看，此补充比较为描述性复核，不是新的未接触测试。',
              'methods':list(METHODS), 'params':PARAMS}
    if len(known.loc[known.year<2015])<500:
        return result
    rows=[]
    for year in range(2015,2026):
        train=known.loc[known.year<year]
        current=known.loc[known.year==year]
        if current.empty:
            continue
        prediction=predictions(train,current)
        prediction['split']='validation' if year<2020 else 'test' if year<2025 else 'additional_2025'
        rows.append(prediction)
    backtest=pd.concat(rows,ignore_index=True)
    validation=backtest.loc[backtest.split=='validation']
    test=backtest.loc[backtest.split=='test']
    if validation.empty or test.empty:
        return result
    validation_metrics={m:metrics(validation,m) for m in METHODS}
    selected_model=min(('hgb','residual_hgb'),key=lambda m:validation_metrics[m]['mae'])
    selected_baseline=min(('persistence','median5','ridge10'),key=lambda m:validation_metrics[m]['mae'])
    test_metrics={m:metrics(test,m) for m in METHODS}
    interval=grouped_interval(test,selected_model,selected_baseline)
    years=[{'year':int(year),'metrics':{m:metrics(part,m) for m in METHODS}} for year,part in test.groupby('year')]
    improvement=1-test_metrics[selected_model]['mae']/test_metrics[selected_baseline]['mae']
    result.update(status='evaluated',selected_model=selected_model,selected_baseline=selected_baseline,
                  validation=validation_metrics,test=test_metrics,yearly_metrics=years,
                  paired_country_mae_difference_95=interval,relative_mae_improvement=improvement,
                  identical_comparison_samples=True,test_countries=int(test.country_code.nunique()),
                  passes_research_gate=interval[1]<0 and all(y['metrics'][selected_model]['mae']<y['metrics'][selected_baseline]['mae'] for y in years),
                  backtest=records(backtest))
    additional=backtest.loc[backtest.split=='additional_2025']
    result['additional_2025']={m:metrics(additional,m) for m in METHODS} if not additional.empty else {'status':'unavailable','reason':'固定快照没有符合滞后条件的2025实际GDP标签。'}
    # Development-only country group exclusion: no held-out country labels enter training.
    held={country for country in known.country_code.unique() if int(hashlib.sha256(country.encode()).hexdigest(),16)%5==0}
    train=known.loc[(known.year<2019)&~known.country_code.isin(held)]
    current=known.loc[(known.year==2019)&known.country_code.isin(held)]
    if not current.empty:
        diagnostic=predictions(train,current)
        result['unseen_country_development_2019']={'countries':int(current.country_code.nunique()),
            'train_countries':int(train.country_code.nunique()),'overlap_count':len(set(train.country_code)&set(current.country_code)),
            'metrics':{m:metrics(diagnostic,m) for m in METHODS}}
    return result
