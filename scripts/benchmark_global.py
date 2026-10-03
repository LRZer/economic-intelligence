"""Reproduce global annual ML diagnostics using the installed WDI snapshot."""
import argparse
import json
import platform
import sys
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from guanlan.data import load_snapshot
from guanlan.panel_ai import evaluate
import pandas as pd


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('reports/wdi-panel-ai.json'))
    args=parser.parse_args()
    frame,meta=load_snapshot('macro')
    result=evaluate(frame)
    result['source_metadata']=meta
    result['python']=platform.python_version()
    result['packages']={k:version(k) for k in ['scikit-learn','pandas','numpy']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if result.get('backtest'):
        pd.DataFrame(result['backtest']).to_csv(args.output.with_suffix('.csv'),index=False)
    print(json.dumps({k:result.get(k) for k in ['status','validation','test','test_countries','yearly_metrics','test_interval_coverage','passes_research_gate']},ensure_ascii=False))


if __name__=='__main__':
    main()
