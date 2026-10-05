"""Offline preparation/scoring for a small separately approved live planner pilot."""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import math
import re
from pathlib import Path

from .assistant_plans import prepare_tool_plan_request, execute_tool_plan
from .evidence_assistant import EvidenceStore

COUNT=12
INPUT_BOUND=4096
OUTPUT_BOUND=400


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_pilot(root: Path) -> tuple[dict,dict,list,dict,EvidenceStore]:
    folder=root/'evaluation/llm-business-pilot-v1'
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest['files'].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root.resolve()):raise ValueError('Pilot freeze cannot reference files outside its checkout')
        if sha(path)!=expected:raise ValueError('Frozen pilot source/input changed: '+name)
    protocol=json.loads((folder/'protocol.json').read_text(encoding='utf-8'))
    requests=json.loads((folder/'requests.json').read_text(encoding='utf-8'))
    gold=json.loads((folder/'gold.json').read_text(encoding='utf-8'))
    source=json.loads((root/'src/china_macro/demo_data.json').read_text(encoding='utf-8'))
    store=EvidenceStore(source['rows'])
    if len(requests)!=COUNT or len(gold['business'])!=COUNT:raise ValueError('Pilot request count changed')
    for item in requests:
        if item['request']!=prepare_tool_plan_request(item['question'],store):raise ValueError('Pilot payload changed')
        tokens=sum(len(m['content'].encode()) for m in item['request']['messages'])+1024
        if tokens>INPUT_BOUND or item['request']['max_tokens']!=OUTPUT_BOUND:raise ValueError('Pilot token bound not met')
    return manifest,protocol,requests,gold,store


def cost_bound(input_rate: Decimal, output_rate: Decimal) -> Decimal:
    if not input_rate.is_finite() or not output_rate.is_finite() or input_rate<=0 or output_rate<=0:
        raise ValueError('Invalid reviewed token rates')
    return (INPUT_BOUND*input_rate+OUTPUT_BOUND*output_rate)/Decimal(1000000)


def usage_cost(usage: object, input_rate: Decimal, output_rate: Decimal) -> tuple[dict,Decimal]:
    if not isinstance(usage,dict):raise ValueError('Missing actual usage; stop with reserved-cost uncertainty')
    keys=('prompt_tokens','completion_tokens','total_tokens')
    if any(type(usage.get(k)) is not int or usage[k]<0 for k in keys):raise ValueError('Invalid token usage')
    if usage['prompt_tokens']>INPUT_BOUND or usage['completion_tokens']>OUTPUT_BOUND or usage['total_tokens']!=usage['prompt_tokens']+usage['completion_tokens']:
        raise ValueError('Reported usage exceeds approved assumptions; stop')
    return {k:usage[k] for k in keys},(usage['prompt_tokens']*input_rate+usage['completion_tokens']*output_rate)/Decimal(1000000)


def score_plan(question: str, plan: object, expected: dict, store: EvidenceStore) -> dict:
    answer=execute_tool_plan(question,plan,store)
    scope=answer['scope']
    same=scope['key']==expected['key'] and scope['tool']==expected['tool'] and scope['periods']==expected['periods']
    numbers=answer['numbers'];target=expected['numbers']
    numeric=numbers.keys()==target.keys() and all(math.isfinite(numbers[k]) and math.isclose(numbers[k],target[k],rel_tol=1e-9,abs_tol=1e-9) for k in target)
    cited={e['id'] for e in answer['evidence']}
    supported=set(expected['evidence_ids'])==cited
    return {'status':'passed' if same and numeric and supported else 'failed','scope_matches':same,'numbers_match':numeric,
            'evidence_ids_match':supported,'numbers':numbers,'evidence_ids':sorted(cited),'answer_id':answer['answer_id']}


def evaluate_saved(root: Path, run: dict) -> dict:
    _,_,requests,gold,store=load_pilot(root)
    if run.get('mode')!='live_user_triggered' or run.get('protocol_manifest_sha256')!=sha(root/'evaluation/llm-business-pilot-v1/manifest.json'):
        raise ValueError('Not a recorded actual pilot for this frozen protocol')
    by_id={item['id']:item for item in requests};expected={r['id']:r['expected'] for r in gold['business']}
    records=run.get('records',[])
    if not isinstance(records,list) or len(records)>COUNT or any(not isinstance(r,dict) for r in records):raise ValueError('Invalid first-run record count')
    if [r.get('id') for r in records]!=[r['id'] for r in requests[:len(records)]]:raise ValueError('First run must preserve the frozen ordered prefix')
    input_rate=Decimal(run['input_usd_per_million']);output_rate=Decimal(run['output_usd_per_million'])
    reserve=cost_bound(input_rate,output_rate)
    cap=Decimal(run['local_cap_usd'])
    if not cap.is_finite() or cap<=0 or cap>Decimal('0.03') or COUNT*reserve>cap:raise ValueError('Invalid recorded budget')
    total=Decimal(0)
    correct=0;accepted=0
    for index,row in enumerate(records):
        if row['id'] not in by_id:raise ValueError('Unknown pilot case')
        payload_hash=hashlib.sha256(json.dumps(by_id[row['id']]['request'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if row.get('request_payload_sha256')!=payload_hash:raise ValueError('Recorded payload hash differs')
        if row.get('status') not in ('passed','failed','incomplete') or (row.get('status')!='passed' and index!=len(records)-1):raise ValueError('A failed first attempt cannot continue')
        if 'usage' in row:
            _,cost=usage_cost(row['usage'],input_rate,output_rate)
            if Decimal(row['conservative_usage_usd'])!=cost:raise ValueError('Recorded cost differs')
            total+=cost
        else:
            total+=reserve
        if row['status']=='passed' and ('usage' not in row or not re.fullmatch(r'deepseek-[A-Za-z0-9._-]{1,90}',row.get('served_model',''))):raise ValueError('Actual model/usage missing')
        if 'validated_plan' in row:
            rescored=score_plan(by_id[row['id']]['question'],row['validated_plan'],expected[row['id']],store)
            if rescored!=row['score']:raise ValueError('Pilot score differs from independent recomputation')
            accepted+=1;correct+=rescored['status']=='passed'
            if row['status']=='passed' and rescored['status']!='passed':raise ValueError('Incorrect task marked passed')
    if total>cap:raise ValueError('Saved costs exceed local budget assumptions')
    complete=run.get('status')=='complete' and len(records)==COUNT and all(r['status']=='passed' for r in records)
    if run.get('status')=='complete' and not complete:raise ValueError('Incomplete first run marked complete')
    return {'status':'complete' if run.get('status')=='complete' and len(records)==COUNT else 'incomplete',
            'planned_requests':COUNT,'recorded_requests':len(records),'accepted_plans':accepted,'correct_business_tasks':correct,
            'all_planned_denominator':COUNT,'pipeline_gate_passed':correct==COUNT and complete,
            'recomputed_cost_usd_upper_estimate':str(total),
            'actual_service_model_versions':sorted(set(r.get('served_model','unknown') for r in records)),
            'score_recomputed_offline':True,'new_live_calls':0,
            'limit':'Small already-seen development pilot; local guard cases do not evaluate the LLM refusal ability. Logs/usage are run evidence, not independently authenticated provider attestations.'}
