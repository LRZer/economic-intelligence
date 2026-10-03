"""Verify published research boundaries and future-feature independence, without refitting."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from guanlan.data import load_snapshot
from guanlan.sector_network import prepare_features
from guanlan.sector_risk import METHODS,validate


def main():
    data,meta=load_snapshot('sector_features')
    backtest,back_meta=load_snapshot('sector_backtest')
    latest,_=load_snapshot('sector_latest')
    macro,_=load_snapshot('macro')
    research=back_meta['research']
    validate(data)
    assert (backtest.train_end<backtest.year).all()
    assert (backtest[['feature_year','weight_year','macro_year']].lt(backtest.year,axis=0)).all().all()
    assert not backtest.duplicated(['year','country_code','hs2']).any()
    assert np.isfinite(backtest[METHODS]).all().all()
    assert backtest[METHODS].ge(0).all().all() and backtest[METHODS].le(1).all().all()
    assert research['test']['joint_hgb']['n']==research['test']['logistic']['n']==16538
    assert latest.outcome.isna().all() and set(latest.year)=={2025}
    assert research['protocol_sha256']==hashlib.sha256((ROOT/'docs/SECTOR_RISK_PROTOCOL.md').read_bytes()).hexdigest()
    rebuilt,quality=prepare_features(ROOT/'data/network',macro)
    pd.testing.assert_frame_equal(data,rebuilt,check_dtype=False)
    future=macro.copy();future.loc[future.year>=2023,'value']=99999.
    changed,_=prepare_features(ROOT/'data/network',future)
    pd.testing.assert_frame_equal(rebuilt.loc[rebuilt.year<=2023],changed.loc[changed.year<=2023])
    training=[]
    known=data.loc[data.outcome.notna()&data.year.between(2019,2024)]
    for year,part in backtest.groupby('year'):
        train=known.loc[known.year<year]
        assert set(part.train_n)=={len(train)} and set(part.train_end)=={int(train.year.max())}
        training.append({'target_year':int(year),'train_first_label_year':int(train.year.min()),
                         'train_last_label_year':int(train.year.max()),'train_n':len(train),'evaluation_n':len(part)})
    result={'status':'passed','raw_trade_rows':sum(p['raw_rows'] for p in research['network_source']['partitions']),
            'country_sector_candidates':quality['candidate_rows'],'eligible_rows':len(data),'year_counts':quality['year_counts'],
            'train_boundaries':training,'protocol_sha256':research['protocol_sha256'],
            'dataset_hash':research['dataset_hash'],'raw_zip_sha256':research['network_source']['raw_zip_sha256'],
            'same_comparison_rows':True,'future_macro_perturbation_early_features_unchanged':True,
            'label_unreported_sector_rows':quality['target_sector_unreported_rows'],
            'limits':'统计年度边界检查通过；当前修订版本仍不能证明首次发布日期可用性；没有重新拟合或调整留出。'}
    (ROOT/'reports/sector-leakage-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
