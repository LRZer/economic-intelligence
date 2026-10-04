"""Independent oracle grading; sealed run is allowed only after source freeze."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
FROZEN=['src/guanlan/evidence_assistant.py','src/guanlan/assistant_plans.py','src/guanlan/ai.py','src/guanlan/ui/evidence_assistant.py',
        'src/guanlan/forecast.py','src/guanlan/monthly_review.py','src/china_macro/catalog.py','scripts/assistant_worker.py',
        'scripts/create_assistant_cases.py','scripts/evaluate_assistant.py','docs/ASSISTANT_EVAL_PROTOCOL.md','requirements.lock.txt','src/china_macro/demo_data.json']


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def wilson(success,n):
    if n==0:return None
    z=1.959963984540054;p=success/n;den=1+z*z/n
    center=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [center-half,center+half]


def equal_numbers(actual,expected):
    return set(actual)==set(expected) and all(type(actual[key]) in (int,float) and math.isfinite(actual[key]) and
           math.isclose(float(actual[key]),float(value),rel_tol=1e-9,abs_tol=1e-9) for key,value in expected.items())


def score(answers,gold,questions,source_rows):
    indexed={r['id']:r for r in answers}
    assert set(indexed)=={r['id'] for r in gold}
    source={f"obs:{r['key']}:{r['period']}":r for r in source_rows if r['key'] in {'cpi_yoy','cpi_mom','ppi_yoy','ppi_mom','manufacturing_pmi','manufacturing_new_orders_pmi','nonmanufacturing_pmi'}}
    qmap={r['id']:r for r in questions}
    checks=[]
    for row in gold:
        expected=row['expected'];answer=indexed[row['id']]['answer']
        answerable=expected['status']=='answered';answered=answer['status']=='answered'
        scope=answer.get('scope') or {}
        number_ok=answered and equal_numbers(answer['numbers'],expected['numbers'])
        evidence=answer.get('evidence',[])
        ids=[r['id'] for r in evidence]
        support=answered and ids==expected['evidence_ids']
        if support:
            for item in evidence:
                if item['kind']=='official_observation':
                    original=source.get(item['id'])
                    support=support and original is not None and item['period']==original['period'] and item['value']==original['value'] and item['source_url']==original['source_url']
                else:
                    support=support and item['kind']=='model_evaluation' and item['key']==expected['key'] and all(i in source for i in item['source_ids'])
        if answerable:
            correct=answered and scope.get('key')==expected['key'] and scope.get('tool')==expected['tool'] and scope.get('periods')==expected['periods'] and number_ok and support
            correct=correct and all(answer['details'].get(k)==v for k,v in expected['details'].items())
        else:
            correct=not answered and answer['reason']==expected['reason']
        checks.append({'id':row['id'],'group':row['group'],'correct':bool(correct),'answerable':answerable,'answered':answered,
                       'numeric_correct':bool(number_ok) if answerable and answered else None,'citation_supported':bool(support) if answerable and answered else None,
                       'expected_status':expected['status'],'actual_status':answer['status'],'expected_tool':expected['tool'],
                       'actual_tool':scope.get('tool'),'expected_reason':expected['reason'],'actual_reason':answer['reason'],
                       'latency_ms':indexed[row['id']]['latency_ms']})
    def metric(rows,key):
        values=[r[key] for r in rows if r[key] is not None]
        return {'success':sum(values),'n':len(values),'rate':sum(values)/len(values) if values else None,'wilson_95':wilson(sum(values),len(values))}
    answerable=[r for r in checks if r['answerable']]
    refusal=[r for r in checks if not r['answerable']]
    groups=sorted({r['group'] for r in checks})
    group_rates=[statistics.mean(r['correct'] for r in checks if r['group']==group) for group in groups]
    rng=np.random.default_rng(42)
    resamples=rng.integers(0,len(groups),size=(2000,len(groups)))
    grouped_interval=np.quantile(np.asarray(group_rates)[resamples].mean(axis=1),[.025,.975]).tolist()
    latencies=[r['latency_ms'] for r in checks]
    failures=[{**r,'question':qmap[r['id']]['question']} for r in checks if not r['correct']]
    return {'task_correct':metric(checks,'correct'),'answerable_coverage':metric(answerable,'answered'),
            'numeric_correct_answered':metric(answerable,'numeric_correct'),'citation_support_answered':metric(answerable,'citation_supported'),
            'refusal_correct':metric(refusal,'correct'),'task_correct_family_bootstrap_95':grouped_interval,
            'family_count':len(groups),'latency_median_ms':statistics.median(latencies),'latency_p95_ms':float(np.quantile(latencies,.95)),
            'failures':failures,'case_checks':checks,'family_results':[{'group':g,'correct':sum(r['correct'] for r in checks if r['group']==g),'n':sum(r['group']==g for r in checks)} for g in groups]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--split',choices=['development','sealed'],required=True)
    parser.add_argument('--freeze',action='store_true')
    args=parser.parse_args()
    directory=args.directory
    frozen={name:sha(ROOT/name) for name in FROZEN}
    freeze_file=directory/'source-freeze.json'
    if args.freeze:
        if args.split!='development' or freeze_file.exists():raise SystemExit('Freeze must follow development and cannot be replaced.')
        freeze_file.write_text(json.dumps({'files':frozen,'threshold':.08,'recorded_at_utc':datetime.now(timezone.utc).isoformat()},indent=2)+'\n',encoding='utf-8')
    if args.split=='sealed':
        if not freeze_file.is_file() or json.loads(freeze_file.read_text(encoding='utf-8'))['files']!=frozen:raise SystemExit('Frozen source changed or not frozen.')
        marker=directory/'sealed-attempt.json'
        with marker.open('x',encoding='utf-8') as stream:json.dump({'requested_at_utc':datetime.now(timezone.utc).isoformat(),'runs_allowed':1},stream)
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    assert manifest[args.split]['question_sha256']==sha(directory/f'{args.split}-questions.json')
    assert manifest[args.split]['gold_sha256']==sha(directory/f'{args.split}-gold.json')
    questions=json.loads((directory/f'{args.split}-questions.json').read_text(encoding='utf-8'))
    gold=json.loads((directory/f'{args.split}-gold.json').read_text(encoding='utf-8'))
    source_rows=json.loads((ROOT/'src/china_macro/demo_data.json').read_text(encoding='utf-8'))['rows']
    results={}
    for policy in ['keyword','tfidf']:
        request={'source_rows':source_rows,'questions':questions,'policy':policy,'threshold':.08}
        response=subprocess.run([sys.executable,str(ROOT/'scripts/assistant_worker.py')],cwd=ROOT,input=json.dumps(request,ensure_ascii=False),capture_output=True,text=True,encoding='utf-8',check=True)
        body=json.loads(response.stdout)
        assert not body['forbidden_attempts'] and body['gold_received'] is False and body['network_requests']==0
        results[policy]=score(body['answers'],gold,questions,source_rows)
        (directory/f'{args.split}-{policy}-answers.json').write_text(json.dumps(body,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    main_result=results['tfidf']
    gates={'task_correct':main_result['task_correct']['rate']>=.9,'coverage':main_result['answerable_coverage']['rate']>=.85,
           'numeric':(main_result['numeric_correct_answered']['rate'] or 0)>=.98,'citations':(main_result['citation_support_answered']['rate'] or 0)>=.95,
           'refusal':main_result['refusal_correct']['rate']>=.9,'unsafe_execution_or_reads':True}
    report={'split':args.split,'case_count':len(questions),'source_freeze':frozen,'threshold':.08,'policies':results,
            'gates':gates,'passes_application_gate':all(gates.values()),'llm_used':False,'network_requests':0,
            'gold_received_by_worker':False,'source_manifest':manifest,
            'limits':'Program-generated grouped task benchmark using already-viewed public economic data; not true-user/LLM/production quality or unseen predictive holdout.'}
    (directory/f'{args.split}-evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'split':args.split,'case_count':len(questions),'gates':gates,'passes_application_gate':report['passes_application_gate'],
                      'metrics':{policy:{k:v for k,v in result.items() if k not in {'failures','case_checks','family_results'}} for policy,result in results.items()}},ensure_ascii=False))
    if args.split=='development':
        print(json.dumps({'development_failures':main_result['failures']},ensure_ascii=False))


if __name__=='__main__':main()
