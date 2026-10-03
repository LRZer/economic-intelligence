"""Reproduce the predeclared BACI × WDI country/sector downside experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from guanlan.data import DEFAULT_DATA_DIR, load_snapshot, publish_snapshots, record_refresh_failure
from guanlan.sector_network import build_network, prepare_features
from guanlan.sector_risk import evaluate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip',type=Path,required=True,help='完整CEPII BACI HS17 V202601官方ZIP')
    parser.add_argument('--network',type=Path,default=ROOT/'data/network')
    parser.add_argument('--temporary',type=Path,required=True,help='有至少8GiB空间的专用临时目录')
    parser.add_argument('--directory',type=Path,default=DEFAULT_DATA_DIR)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/sector-risk.json')
    args=parser.parse_args()
    protocol=ROOT/'docs/SECTOR_RISK_PROTOCOL.md'
    protocol_hash=hashlib.sha256(protocol.read_bytes()).hexdigest()
    macro,macro_meta=load_snapshot('macro',args.directory)
    try:
        network=build_network(args.zip,args.network,args.temporary)
        features,quality=prepare_features(args.network,macro)
        print('联合特征已校验：'+json.dumps(quality,ensure_ascii=False),flush=True)
        backtest,latest,summary=evaluate(features)
        summary.update(protocol_sha256=protocol_hash,quality=quality,network_source=network,
                       macro_source=macro_meta,python=platform.python_version(),
                       packages={k:version(k) for k in ['scikit-learn','pandas','numpy','duckdb']},
                       computed_at_utc=datetime.now(timezone.utc).isoformat())
        source={'provider':'CEPII BACI × World Bank WDI','source_url':network['source_url'],
                'source_last_updated':'BACI V202601 / 固定WDI快照','protocol_sha256':protocol_hash,
                'raw_zip_sha256':network['raw_zip_sha256'],'dataset_hash':summary['dataset_hash']}
        snapshots={'sector_features':(features,{**source,'rows':len(features),'quality':quality}),
                   'sector_backtest':(backtest,{**source,'rows':len(backtest),'research':summary})}
        if not latest.empty:
            snapshots['sector_latest']=(latest,{**source,'rows':len(latest),'research':summary,
                                               'status':'2025待标签核验的历史研究估计，不是实时未来预测'})
        summary['batch_id']=publish_snapshots(snapshots,args.directory,'macro-sector-research-v1')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        backtest.to_csv(args.output.with_suffix('.csv'),index=False)
        print(json.dumps({k:summary[k] for k in ['validation','test','yearly_metrics',
              'paired_country_brier_difference_95','passes_research_gate','unseen_country_development_2022'] if k in summary},ensure_ascii=False),flush=True)
    except Exception as exc:
        record_refresh_failure('macro-sector-research-v1',['sector_features','sector_backtest','sector_latest'],exc,args.directory)
        raise


if __name__=='__main__':
    main()
