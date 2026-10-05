"""Independently rescore stored live pilot plans; no network or key lookup."""
import argparse
import json
from pathlib import Path

from guanlan.llm_business import evaluate_saved

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    if args.run.stat().st_size>2*1024*1024:raise ValueError('Run file exceeds bound')
    result=evaluate_saved(ROOT,json.loads(args.run.read_text(encoding='utf-8')))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['pipeline_gate_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
