from pathlib import Path
import json
import pandas as pd
from guanlan.data import load_snapshot
from guanlan.panel_benchmark import evaluate_references

root=Path(__file__).resolve().parents[1]
frame,meta=load_snapshot('macro')
result=evaluate_references(frame)
result['source_metadata']=meta
(root/'reports'/'wdi-reference-benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
pd.DataFrame(result.get('backtest',[])).to_csv(root/'reports'/'wdi-reference-backtest.csv',index=False,encoding='utf-8-sig')
print(json.dumps({k:v for k,v in result.items() if k not in ['backtest','source_metadata']},ensure_ascii=False))
