"""Fixed-protocol macro/trade-network one-year export downside experiment."""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TRADE_FEATURES=['log_export','previous_growth','partner_hhi','top5_share','partner_gdp_coverage']
MACRO_FEATURES=['partner_gdp','own_gdp','own_inflation','own_unemployment','own_investment','own_current_account']
NUMERIC=TRADE_FEATURES+MACRO_FEATURES
FEATURES=NUMERIC+['hs2']
METHODS=['global_rate','sector_rate','logistic','joint_hgb','trade_only_hgb']
PARAMS=dict(max_iter=100,max_leaf_nodes=15,learning_rate=.05,l2_regularization=10.,random_state=42)
LABELS={'log_export':'上期行业出口规模（对数）','previous_growth':'上期行业出口增速',
        'partner_hhi':'伙伴集中度HHI','top5_share':'前五伙伴份额','partner_gdp_coverage':'伙伴GDP覆盖权重',
        'partner_gdp':'伙伴加权GDP增速','own_gdp':'本国GDP增速','own_inflation':'本国通胀',
        'own_unemployment':'本国失业率','own_investment':'本国资本形成占GDP','own_current_account':'本国经常账户占GDP','hs2':'HS2行业类别'}


def array(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    result=frame[columns].copy()
    result['hs2']=result.hs2.astype(int)
    return result.to_numpy(dtype=float)


def new_tree(columns: list[str]):
    return HistGradientBoostingClassifier(**PARAMS,categorical_features=[len(columns)-1])


def new_logistic():
    numeric=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),StandardScaler())
    transformer=ColumnTransformer([('numeric',numeric,NUMERIC),
       ('industry',OneHotEncoder(categories=[[f'{i:02d}' for i in range(1,98)]],handle_unknown='ignore',sparse_output=False),['hs2'])])
    return make_pipeline(transformer,LogisticRegression(C=1.,max_iter=1000))


def predict_all(train: pd.DataFrame,current: pd.DataFrame):
    if train.empty or current.empty or train.year.max()>=current.year.min():
        raise ValueError('训练标签时点不得进入预测年度')
    y=train.outcome.astype(int)
    if y.nunique()!=2: raise ValueError('训练标签没有两种类别')
    output=current.copy()
    overall=float((y.sum()+1)/(len(y)+2))
    rates=train.groupby('hs2').outcome.agg(['sum','count'])
    rates=(rates['sum']+2)/(rates['count']+4)
    output['global_rate']=overall
    output['sector_rate']=output.hs2.map(rates).fillna(overall)
    logistic=new_logistic().fit(train[FEATURES],y)
    output['logistic']=logistic.predict_proba(current[FEATURES])[:,1]
    main=new_tree(FEATURES).fit(array(train,FEATURES),y)
    output['joint_hgb']=main.predict_proba(array(current,FEATURES))[:,1]
    reduced=TRADE_FEATURES+['hs2']
    ablation=new_tree(reduced).fit(array(train,reduced),y)
    output['trade_only_hgb']=ablation.predict_proba(array(current,reduced))[:,1]
    output['train_end']=int(train.year.max())
    output['train_n']=len(train)
    return output,main


def metric(frame: pd.DataFrame,method: str) -> dict:
    if frame.empty: return {'n':0}
    y=frame.outcome.astype(int).to_numpy()
    p=frame[method].to_numpy(dtype=float)
    if not np.isfinite(p).all() or ((p<0)|(p>1)).any(): raise ValueError('模型概率无效')
    return {'n':len(frame),'events':int(y.sum()),'event_rate':float(y.mean()),
            'brier':float(brier_score_loss(y,p)),'log_loss':float(log_loss(y,p,labels=[0,1])),
            'roc_auc':float(roc_auc_score(y,p)) if len(frame)>=30 and len(set(y))==2 else None,
            'average_precision':float(average_precision_score(y,p)) if y.sum()>0 else None}


def calibration(frame: pd.DataFrame,method: str) -> list[dict]:
    bins=np.minimum((frame[method]*10).astype(int),9)
    result=[]
    for index in range(10):
        part=frame.loc[bins==index]
        result.append({'bin':index,'lower':index/10,'upper':(index+1)/10,'n':len(part),
                       'mean_prediction':float(part[method].mean()) if len(part) else None,
                       'event_rate':float(part.outcome.mean()) if len(part) else None})
    return result


def grouped_interval(test: pd.DataFrame) -> list[float]:
    losses=(test.joint_hgb-test.outcome)**2-(test.sector_rate-test.outcome)**2
    grouped=test.assign(loss=losses).groupby('country_code').loss.agg(['sum','count'])
    rng=np.random.default_rng(42)
    idx=rng.integers(0,len(grouped),size=(2000,len(grouped)))
    delta=grouped['sum'].to_numpy()[idx].sum(axis=1)/grouped['count'].to_numpy()[idx].sum(axis=1)
    return np.quantile(delta,[.025,.975]).tolist()


def validate(data: pd.DataFrame):
    if data.duplicated(['year','country_code','hs2']).any(): raise ValueError('国家行业年度重复键')
    if not data.hs2.isin([f'{i:02d}' for i in range(1,98)]).all(): raise ValueError('HS2类别无效')
    if not ((data.feature_year==data.year-1)&(data.weight_year==data.year-1)&(data.macro_year==data.year-1)).all():
        raise ValueError('特征时点泄漏')
    if not data.outcome.dropna().isin([0,1]).all(): raise ValueError('下行标签无效')
    if np.isinf(data[NUMERIC].to_numpy(dtype=float)).any(): raise ValueError('特征含无限值')


def evaluate(data: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame,dict]:
    validate(data)
    known=data.loc[data.outcome.notna() & data.year.between(2019,2024)].copy()
    if len(known.loc[known.year<2021])<1000: raise ValueError('初始训练少于1000个国家行业年度样本')
    version=hashlib.sha256(pd.util.hash_pandas_object(data,index=True).values.tobytes()).hexdigest()
    backtests=[];development_model=None
    for year in (2021,2022,2023,2024):
        train=known.loc[known.year<year]
        current=known.loc[known.year==year]
        if current.empty: raise ValueError(f'协议评估年{year}无样本，拒绝缩小留出')
        part,model=predict_all(train,current)
        part['split']='validation' if year<2023 else 'test'
        backtests.append(part)
        if year==2022: development_model=model
    backtest=pd.concat(backtests,ignore_index=True)
    validation=backtest.loc[backtest.split=='validation']
    test=backtest.loc[backtest.split=='test']
    validation_metrics={m:metric(validation,m) for m in METHODS}
    selected_reference=min(('global_rate','sector_rate','logistic'),key=lambda m:validation_metrics[m]['brier'])
    test_metrics={m:metric(test,m) for m in METHODS}
    years: list[dict]=[{'year':int(year),'metrics':{m:metric(part,m) for m in METHODS}} for year,part in test.groupby('year')]
    interval=grouped_interval(test)
    passed=interval[1]<0 and all(r['metrics']['joint_hgb']['brier']<r['metrics']['sector_rate']['brier'] for r in years)
    explanation=permutation_importance(development_model,array(known.loc[known.year==2022],FEATURES),
       known.loc[known.year==2022].outcome.astype(int),scoring='neg_brier_score',n_repeats=3,random_state=42,n_jobs=1)
    result={'version':'macro-sector-downside-v1','dataset_hash':version,'protocol':'docs/SECTOR_RISK_PROTOCOL.md',
        'params':PARAMS,'features':FEATURES,'label':'下一年行业出口金额≤上年金额的90%',
        'validation':validation_metrics,'selected_reference_on_validation':selected_reference,'test':test_metrics,
        'yearly_metrics':years,'paired_country_brier_difference_95':interval,'passes_research_gate':passed,
        'default_reference':selected_reference,'identical_comparison_samples':True,'test_countries':int(test.country_code.nunique()),
        'test_hs2':int(test.hs2.nunique()),'calibration':{m:calibration(test,m) for m in METHODS},
        'country_slices':{str(c):{m:metric(part,m) for m in METHODS} for c,part in test.groupby('country_code')},
        'industry_slices':{str(c):{m:metric(part,m) for m in METHODS} for c,part in test.groupby('hs2')},
        'development_feature_importance':dict(zip(FEATURES,explanation.importances_mean.tolist())),
        'limits':'当前修订历史数据；没有首次发布日期或点时版本。概率为研究估计，GDP情景只描述暴露，不能推导因果出口损失或投资收益。'}
    held={c for c in known.country_code.unique() if int(hashlib.sha256(c.encode()).hexdigest(),16)%5==0}
    geographical_train=known.loc[(known.year<2022)&~known.country_code.isin(held)]
    geographical_test=known.loc[(known.year==2022)&known.country_code.isin(held)]
    if not geographical_test.empty:
        diagnostic=geographical_test.copy()
        model=new_tree(FEATURES).fit(array(geographical_train,FEATURES),geographical_train.outcome.astype(int))
        diagnostic['joint_hgb']=model.predict_proba(array(diagnostic,FEATURES))[:,1]
        rates=geographical_train.groupby('hs2').outcome.agg(['sum','count'])
        diagnostic['sector_rate']=diagnostic.hs2.map((rates['sum']+2)/(rates['count']+4)).fillna((geographical_train.outcome.sum()+1)/(len(geographical_train)+2))
        result['unseen_country_development_2022']={'overlap_count':len(set(geographical_train.country_code)&set(geographical_test.country_code)),
            'countries':int(geographical_test.country_code.nunique()),'joint_hgb':metric(diagnostic,'joint_hgb'),
            'sector_rate':metric(diagnostic,'sector_rate')}
    latest=data.loc[(data.year==2025)&data.outcome.isna()].copy()
    if not latest.empty:
        latest,_=predict_all(known,latest)
    return backtest,latest,result
