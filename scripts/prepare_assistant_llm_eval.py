"""Prepare 12 development-case requests and token budget; never call an API."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from guanlan.evidence_assistant import EvidenceStore
from guanlan.assistant_plans import prepare_tool_plan_request

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('development_questions',type=Path)
    args=parser.parse_args()
    if 'sealed' in args.development_questions.name:raise SystemExit('Only development questions are allowed for the pilot.')
    questions=json.loads(args.development_questions.read_text(encoding='utf-8'))
    rows=json.loads((ROOT/'src/china_macro/demo_data.json').read_text(encoding='utf-8'))['rows']
    store=EvidenceStore(rows)
    chosen=[item for item in questions if int(item['id'].split(':')[1])<6 and int(item['id'].split(':')[2])<2]
    assert len(chosen)==12
    requests=[{'id':item['id'],'request':prepare_tool_plan_request(item['question'],store)} for item in chosen]
    report={'mode':'offline_preparation','requests':requests,'request_count':12,'max_input_tokens_conservative_each':4096,
            'max_output_tokens_each':400,'automatic_retry':False,'live_calls':0,'credential_read':False,
            'requires_new_budget_and_local_user_trigger':True,'prior_budget_available':False,
            'scope':'Development-only pilot; not sealed quality evaluation or true-user population.'}
    (ROOT/'reports').mkdir(exist_ok=True)
    (ROOT/'reports/assistant-llm-pilot-preparation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='requests'},ensure_ascii=False))


if __name__=='__main__':main()
