"""Load only an approved year/HS partition, verifying physical source bytes."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pandas as pd
from .trade_graph import TradeGraph


def load_trade_graph(directory: Path,year: int,hs2: str) -> TradeGraph:
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version')!='baci-sector-network-v1' or manifest.get('release')!='HS17 V202601':raise ValueError('来源版本无效')
    parts=[p for p in manifest['partitions'] if p['year']==year]
    if len(parts)!=1:raise ValueError('所选年缺少唯一批准分区')
    part=parts[0];path=directory/part['file']
    if path.name!=f'sector_partner_{year}.parquet' or not path.resolve().is_relative_to(directory.resolve()):raise ValueError('来源路径无效')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=part['sha256']:raise ValueError('贸易分区SHA校验失败')
    frame=pd.read_parquet(path)
    if len(frame)!=part['rows'] or not (frame.year==year).all():raise ValueError('贸易分区行数/年份不一致')
    provenance={k:manifest[k] for k in ['provider','release','source_url','license','license_url','citation','raw_zip_sha256']}
    provenance.update(kind='BACI_official_aggregate',partition_sha256=part['sha256'],partition_rows=part['rows'])
    return TradeGraph(frame.loc[frame.hs2==hs2],year,hs2,provenance)
