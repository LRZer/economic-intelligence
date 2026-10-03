import hashlib
import json
from collections import namedtuple
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from guanlan.panel_ai import INPUTS,TARGET
from guanlan.sector_network import build_network,prepare_features


def archive_fixture(root,unmapped=False,incomplete=False):
    path=root/'baci.zip'
    with ZipFile(path,'w') as z:
        z.writestr('country_codes_V202601.csv','country_code,country_name,country_iso3\n1,A,AAA\n2,B,BBB\n3,C,CCC\n')
        z.writestr('product_codes_HS17_V202601.csv','code,description\n010100,A\n850100,B\n')
        for year in range(2017,2025-int(incomplete)):
            other=99 if unmapped else 3
            amount=9000 if year==2019 else 10000
            z.writestr(f'BACI_HS17_Y{year}_V202601.csv',
                       f't,i,j,k,v,q\n{year},1,2,010100,{amount*8},1\n{year},1,{other},010100,{amount*2},1\n'
                       f'{year},1,2,850100,12000,1\n')
    return path


@pytest.fixture
def network(tmp_path,monkeypatch):
    Usage=namedtuple('Usage','total used free')
    monkeypatch.setattr('guanlan.sector_network.shutil.disk_usage',lambda p:Usage(30*1024**3,0,30*1024**3))
    archive=archive_fixture(tmp_path)
    folder=tmp_path/'network'
    meta=build_network(archive,folder,tmp_path/'temp')
    macro=pd.DataFrame([{'country_code':c,'year':y,'indicator_code':code,
                         'value':2. if code==TARGET else 3.}
                        for c in ['AAA','BBB'] for y in range(2017,2025) for code in INPUTS])
    return folder,macro,meta


def test_full_archive_units_calendar_weights_and_unknown_labels(network):
    folder,macro,meta=network
    features,quality=prepare_features(folder,macro)
    row=features.loc[(features.year==2019)&(features.hs2=='01')].iloc[0]
    assert row.lag_export_usd==100_000_000
    assert row.export_usd==90_000_000 and row.outcome==1 # Exact -10% boundary.
    assert row.partner_gdp_coverage==pytest.approx(.8)
    assert row.partner_gdp==pytest.approx(2.) # Matched weights normalized, missing GDP is not zero.
    assert row.partner_hhi==pytest.approx(.68)
    assert row.previous_growth==0
    assert row.feature_year==row.weight_year==row.macro_year==2018
    assert features.loc[features.year==2025,'outcome'].isna().all()
    assert quality['year_counts']['2019']==2
    assert sum(p['raw_rows'] for p in meta['partitions'])==24


def test_future_macro_perturbation_does_not_change_earlier_features(network):
    folder,macro,_=network
    first,_=prepare_features(folder,macro)
    changed=macro.copy()
    changed.loc[changed.year>=2020,'value']=999.
    second,_=prepare_features(folder,changed)
    pd.testing.assert_frame_equal(first.loc[first.year<=2020],second.loc[second.year<=2020])
    missing=macro.loc[~((macro.year==2018)&(macro.country_code=='BBB')&(macro.indicator_code==TARGET))]
    excluded,_=prepare_features(folder,missing)
    assert 2019 not in set(excluded.year) # No adjacent-year GDP substitution.


def test_source_tampering_duplicate_macro_and_incomplete_archive_are_rejected(network,tmp_path):
    folder,macro,_=network
    with pytest.raises(ValueError,match='重复'):
        prepare_features(folder,pd.concat([macro,macro.iloc[[0]]]))
    path=folder/'sector_partner_2017.parquet'
    path.write_bytes(path.read_bytes()+b'tampered')
    with pytest.raises(ValueError,match='SHA256'):
        prepare_features(folder,macro)
    with pytest.raises(ValueError,match='完整'):
        build_network(archive_fixture(tmp_path,incomplete=True),tmp_path/'other',tmp_path/'temp')


def test_source_country_mapping_is_required(tmp_path,monkeypatch):
    Usage=namedtuple('Usage','total used free')
    monkeypatch.setattr('guanlan.sector_network.shutil.disk_usage',lambda p:Usage(30*1024**3,0,30*1024**3))
    with pytest.raises(ValueError,match='未映射'):
        build_network(archive_fixture(tmp_path,unmapped=True),tmp_path/'network',tmp_path/'temp')
