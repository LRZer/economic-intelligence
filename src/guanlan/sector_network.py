"""Build country/HS2/partner networks from a verified official BACI archive."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import duckdb
import numpy as np
import pandas as pd

from .baci import RAW_COLUMNS, YEARS, _archive_members, _country_codes, _sha256
from .panel_ai import INPUTS, TARGET

OWN_NAMES = {'NY.GDP.MKTP.KD.ZG':'own_gdp', 'FP.CPI.TOTL.ZG':'own_inflation',
             'SL.UEM.TOTL.ZS':'own_unemployment', 'NE.GDI.TOTL.ZS':'own_investment',
             'BN.CAB.XOKA.GD.ZS':'own_current_account'}


def build_network(zip_path: Path, destination: Path, temporary_root: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    temporary_root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination).free < 8*1024**3:
        raise OSError('贸易网络构建要求目标盘至少8GiB可用空间')
    raw_hash = _sha256(zip_path)
    audit=[]
    with ZipFile(zip_path) as archive:
        annual, country_member = _archive_members(archive)
        if set(annual)!=set(YEARS):
            raise ValueError('协议要求完整2017—2024数据，不静默缩小范围')
        countries = _country_codes(archive, country_member)
        countries.to_csv(destination/'country_codes.csv',index=False,encoding='utf-8-sig')
        for year in YEARS:
            target=destination/f'sector_partner_{year}.parquet'
            meta_path=target.with_suffix('.json')
            if target.exists() and meta_path.exists():
                old=json.loads(meta_path.read_text(encoding='utf-8'))
                if old['raw_zip_sha256']==raw_hash and old['sha256']==_sha256(target):
                    audit.append(old)
                    print(f'{year}: 使用已校验的网络分区',flush=True)
                    continue
            with tempfile.TemporaryDirectory(prefix='sector-network-',dir=temporary_root) as temporary:
                safe=Path(temporary).resolve()
                if not safe.is_relative_to(temporary_root.resolve()):
                    raise ValueError('临时目录越界')
                csv_path=safe/f'baci-{year}.csv'
                member=annual[year]
                with archive.open(member) as source,csv_path.open('wb') as output:
                    shutil.copyfileobj(source,output,length=8*1024*1024)
                if csv_path.stat().st_size!=archive.getinfo(member).file_size:
                    raise IOError('年度CSV解压不完整')
                connection=duckdb.connect()
                connection.execute("SET memory_limit='1GB'")
                connection.execute('SET threads=4')
                connection.execute('SET temp_directory=?',[str(safe)])
                connection.register('countries',countries)
                connection.read_csv(str(csv_path),header=True,columns=RAW_COLUMNS).create_view('flows')
                checks=connection.sql("""SELECT count(*) AS rows,sum(v)*1000 AS total_usd,
                  count(*) FILTER(WHERE t<>$year OR v IS NULL OR NOT isfinite(v) OR v<0
                    OR NOT regexp_full_match(k,'[0-9]{6}')) AS invalid,
                  count(*) FILTER(WHERE e.iso3 IS NULL OR m.iso3 IS NULL) AS unmapped
                  FROM flows f LEFT JOIN countries e ON f.i=e.numeric_code
                  LEFT JOIN countries m ON f.j=m.numeric_code""",params={'year':year}).df().iloc[0]
                if checks['invalid'] or checks['unmapped']:
                    raise ValueError('BACI原始流存在无效或未映射数据')
                network=connection.sql("""SELECT t AS year,e.iso3 AS country_code,
                  m.iso3 AS partner_code,left(k,2) AS hs2,sum(v)*1000 AS trade_usd
                  FROM flows f JOIN countries e ON f.i=e.numeric_code
                  JOIN countries m ON f.j=m.numeric_code
                  WHERE try_cast(left(k,2) AS INTEGER) BETWEEN 1 AND 97
                  GROUP BY 1,2,3,4 ORDER BY 2,4,3""").df()
                connection.close()
                if network.duplicated(['year','country_code','partner_code','hs2']).any():
                    raise ValueError('网络聚合有重复键')
                network.to_parquet(target,index=False)
                info={'year':year,'rows':len(network),'raw_rows':int(checks['rows']),
                      'raw_total_usd':float(checks['total_usd']),'included_total_usd':float(network.trade_usd.sum()),
                      'excluded_nonstandard_hs_usd':float(checks['total_usd']-network.trade_usd.sum()),
                      'sha256':_sha256(target),'raw_zip_sha256':raw_hash,'file':target.name}
                meta_path.write_text(json.dumps(info,indent=2,allow_nan=False),encoding='utf-8')
                audit.append(info)
                print(f'{year}: 原始{info["raw_rows"]:,}行 → 行业伙伴{len(network):,}行',flush=True)
    result={'version':'baci-sector-network-v1','provider':'CEPII BACI','release':'HS17 V202601',
            'source_url':'https://www.cepii.fr/DATA_DOWNLOAD/baci/data/BACI_HS17_V202601.zip',
            'license_url':'https://www.cepii.fr/CEPII/fr/bdd_modele/bdd_modele_item.asp?id=37',
            'license':'Etalab 2.0','citation':'Gaulier and Zignago (2010), CEPII Working Paper 2010-23',
            'raw_zip_sha256':raw_hash,'partitions':audit,'built_at_utc':datetime.now(timezone.utc).isoformat(),
            'original_archive_download_date':'原始本地官方包未提供下载日',
            'method':'HS6金额按出口国、进口国、HS2、年聚合；v×1000转换美元；未做因果推断'}
    (destination/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return result


def prepare_features(network_directory: Path, macro: pd.DataFrame) -> tuple[pd.DataFrame,dict]:
    manifest=json.loads((network_directory/'manifest.json').read_text(encoding='utf-8'))
    expected={p['file']:p for p in manifest['partitions']}
    actual={p.name for p in network_directory.glob('sector_partner_*.parquet')}
    if actual != set(expected):
        raise ValueError('网络分区与来源清单不一致')
    selected=macro.loc[macro.indicator_code.isin(INPUTS)]
    if selected.duplicated(['country_code','year','indicator_code']).any():
        raise ValueError('WDI重复键，拒绝联合建模')
    if np.isinf(selected.value.dropna().to_numpy(dtype=float)).any():
        raise ValueError('WDI包含非有限数值')
    wide=selected.pivot(index=['country_code','year'],columns='indicator_code',values='value').reset_index()
    for code in INPUTS:
        if code not in wide: wide[code]=np.nan
    gdp=wide[['country_code','year',TARGET]].rename(columns={'country_code':'partner_code',TARGET:'partner_gdp'})
    annual=[]
    for path in sorted(network_directory.glob('sector_partner_*.parquet')):
        if _sha256(path)!=expected[path.name]['sha256']:
            raise ValueError('网络分区SHA256校验失败')
        network=pd.read_parquet(path)
        if network.duplicated(['year','country_code','partner_code','hs2']).any():
            raise ValueError('网络重复键')
        totals=network.groupby(['year','country_code','hs2']).trade_usd.sum().rename('export_usd').reset_index()
        network=network.merge(totals,on=['year','country_code','hs2'],validate='many_to_one')
        network['share']=network.trade_usd/network.export_usd.replace(0,np.nan)
        network=network.merge(gdp,on=['partner_code','year'],how='left',validate='many_to_one')
        network['known_weight']=network['share'].where(network.partner_gdp.notna(),0)
        network['gdp_weighted']=network['share']*network.partner_gdp
        network['squared_share']=network['share']**2
        keys=['year','country_code','hs2']
        top5=network.sort_values('share',ascending=False).groupby(keys).head(5).groupby(keys)['share'].sum().rename('top5_share')
        features=network.groupby(keys).agg(export_usd=('export_usd','first'),
          partner_hhi=('squared_share','sum'),
          partner_gdp_coverage=('known_weight','sum'),weighted_gdp_sum=('gdp_weighted','sum'),
          partner_count=('partner_code','nunique')).reset_index()
        features=features.merge(top5,on=keys,validate='one_to_one')
        features['partner_gdp']=features.weighted_gdp_sum/features.partner_gdp_coverage.replace(0,np.nan)
        annual.append(features.drop(columns='weighted_gdp_sum'))
    all_years=pd.concat(annual,ignore_index=True).sort_values(['year','country_code','hs2'])
    own=wide.rename(columns=OWN_NAMES)
    prior=all_years.merge(own[['country_code','year',*OWN_NAMES.values()]],on=['country_code','year'],how='left',validate='many_to_one')
    prev=all_years[['year','country_code','hs2','export_usd']].copy()
    prev['year']+=1
    prev=prev.rename(columns={'export_usd':'previous_export_usd'})
    prior=prior.merge(prev,on=['year','country_code','hs2'],how='left',validate='one_to_one')
    prior['previous_growth']=100*(prior.export_usd/prior.previous_export_usd.replace(0,np.nan)-1)
    prior['feature_year']=prior['year']
    prior['weight_year']=prior['year']
    prior['macro_year']=prior['year']
    prior['year']+=1
    prior=prior.rename(columns={'export_usd':'lag_export_usd'})
    targets=all_years[['year','country_code','hs2','export_usd']]
    joined=prior.merge(targets,on=['year','country_code','hs2'],how='left',validate='one_to_one')
    reported=set(zip(all_years.year,all_years.country_code))
    joined['target_country_reported']=[(y,c) in reported for y,c in zip(joined.year,joined.country_code)]
    joined['target_sector_unreported']=joined.target_country_reported&joined.export_usd.isna()
    joined.loc[joined.target_sector_unreported,'export_usd']=0.
    joined['outcome']=np.where(joined.target_country_reported,(joined.export_usd<=joined.lag_export_usd*.9).astype(float),np.nan)
    eligible=(joined.lag_export_usd>=10_000_000)&joined.previous_export_usd.notna()&(joined.partner_gdp_coverage>=.8)
    data=joined.loc[eligible].copy()
    data['log_export']=np.log1p(data.lag_export_usd)
    data['missing_own_features']=data[list(OWN_NAMES.values())].isna().sum(axis=1)
    data=data.sort_values(['year','country_code','hs2']).reset_index(drop=True)
    if data.duplicated(['year','country_code','hs2']).any(): raise ValueError('模型样本键重复')
    if not ((data.feature_year<data.year)&(data.weight_year<data.year)&(data.macro_year<data.year)).all():
        raise ValueError('联合特征发生时间泄漏')
    quality={'candidate_rows':len(joined),'eligible_rows':len(data),'excluded_rows':int((~eligible).sum()),
             'exclusion_rules':'上年出口≥1000万美元；前两年有该行业观测；伙伴GDP覆盖≥80%',
             'target_sector_unreported_rows':int(data.target_sector_unreported.sum()),
             'own_macro_missing_rows':int((data.missing_own_features>0).sum()),
             'year_counts':{str(y):len(p) for y,p in data.groupby('year')},
             'countries':int(data.country_code.nunique()),'hs2_count':int(data.hs2.nunique()),
             'weighted_partner_gdp_mean_coverage':float(data.partner_gdp_coverage.mean())}
    return data,quality
