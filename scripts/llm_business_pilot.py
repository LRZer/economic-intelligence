"""Default offline preflight; --live requires fresh local user approval and key entry."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
from decimal import Decimal
import getpass
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import requests

from guanlan.assistant_plans import validate_tool_plan
from guanlan.llm_business import COUNT,cost_bound,evaluate_saved,load_pilot,score_plan,sha,usage_cost

ROOT=Path(__file__).resolve().parents[1]


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--max-usd',default='0.03')
    parser.add_argument('--input-usd-per-million',default='0.30')
    parser.add_argument('--output-usd-per-million',default='1.20')
    parser.add_argument('--confirmed-price-date',default='')
    args=parser.parse_args()
    manifest,protocol,cases,gold,store=load_pilot(ROOT)
    cap=Decimal(args.max_usd);input_rate=Decimal(args.input_usd_per_million);output_rate=Decimal(args.output_usd_per_million)
    reserve=cost_bound(input_rate,output_rate)
    if not cap.is_finite() or cap<=0 or cap>Decimal('0.03') or reserve*COUNT>cap:
        raise ValueError('Invalid or insufficient separately approved USD cap')
    local_rejections=[]
    from guanlan.assistant_plans import prepare_tool_plan_request
    for item in gold['local_guard_cases']:
        try:prepare_tool_plan_request(item['question'],store)
        except ValueError:local_rejections.append(item['id'])
        else:raise ValueError('Local guard case no longer rejects; no live run')
    preflight={'mode':'offline_preflight','planned_public_requests':COUNT,'model':'deepseek-flash','input_tokens_bound_each':4096,'output_tokens_bound_each':400,
               'conservative_peak_cache_miss_usd_upper_estimate':str(reserve*COUNT),'local_cap_usd':str(cap),
               'local_guard_rejections':len(local_rejections),'local_guards_are_not_llm_safety_results':True,
               'payload_fields':'Question,public indicator aliases,available months,tool schema,snapshot fingerprint;no raw observations,IMF or personal data.',
               'live_calls':0,'credential_read':False,'manifest_sha256':sha(ROOT/'evaluation/llm-business-pilot-v1/manifest.json')}
    (ROOT/'reports').mkdir(exist_ok=True)
    dump(ROOT/'reports/llm-business-preflight.json',preflight)
    print(json.dumps(preflight,ensure_ascii=False),flush=True)
    if not args.live:return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():raise ValueError('Only the user in a local interactive terminal may trigger live mode')
    today=datetime.now(timezone.utc).date().isoformat()
    if args.confirmed_price_date!=today:raise ValueError("User must recheck official current price and pass today's UTC date")
    print('此运行需新的调用授权。12次上限、0.03美元本地预算；无重试，首次异常停止。先前预算不适用。')
    if input('本人确认请输入 LIVE 12 0.03：').strip()!='LIVE 12 0.03':return 2
    marker=ROOT/'reports/llm-business-first-attempt.json'
    with marker.open('x',encoding='utf-8') as stream:
        json.dump({'mode':'first_user_triggered_attempt','at_utc':datetime.now(timezone.utc).isoformat(),'manifest_sha256':preflight['manifest_sha256']},stream)
    output=ROOT/'reports/llm-business-first-run'
    output.mkdir(exist_ok=False)
    key=getpass.getpass('本人输入本次密钥（隐藏输入，不读文件或环境）：').strip()
    result:dict={'mode':'live_user_triggered','status':'incomplete','protocol_manifest_sha256':preflight['manifest_sha256'],
            'records':[],'planned_requests':COUNT,'automatic_retry':False,'cost_upper_estimate_usd':'0','local_cap_usd':str(cap),
            'input_usd_per_million':str(input_rate),'output_usd_per_million':str(output_rate),
            'local_guard_rejections':local_rejections,'scope':'Already-seen development pilot;not sealed,prospective or unrestricted LLM financial analysis.'}
    if not key:
        result['stop_reason']='empty_user_key_no_request_sent';dump(output/'run.json',result)
        print('No key entered; first attempt recorded without any request. Do not delete the attempt marker.')
        return 2
    expected={r['id']:r['expected'] for r in gold['business']}
    session=requests.Session();session.trust_env=False;used=Decimal(0);started=time.monotonic()
    try:
        for item in cases:
            if used+reserve>cap or time.monotonic()-started>900:
                result['stop_reason']='local_budget_or_wall_limit';break
            row={'id':item['id'],'status':'incomplete','request_payload_sha256':hashlib.sha256(json.dumps(item['request'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
            result['records'].append(row)
            try:
                with session.post('https://api.deepseek.com/chat/completions',json=item['request'],headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},timeout=(10,60),allow_redirects=False,stream=True) as response:
                    row['http_status']=response.status_code
                    if not 200<=response.status_code<300:raise ValueError('http_failure')
                    body=b''
                    for chunk in response.iter_content(8192):
                        body+=chunk
                        if len(body)>1024*1024:raise ValueError('oversized_response')
                row['response_sha256']=hashlib.sha256(body).hexdigest()
                value=json.loads(body)
                usage,cost=usage_cost(value.get('usage'),input_rate,output_rate)
                used+=cost;row['usage']=usage;row['conservative_usage_usd']=str(cost)
                served=value.get('model')
                if not isinstance(served,str) or not re.fullmatch(r'deepseek-[A-Za-z0-9._-]{1,90}',served):raise ValueError('unknown_served_model')
                row['served_model']=served
                identifier=value.get('id');row['provider_request_id_sha256']=hashlib.sha256(identifier.encode()).hexdigest() if isinstance(identifier,str) else None
                choice=value['choices'][0]
                if choice.get('finish_reason')!='stop':raise ValueError('truncated_response')
                plan=json.loads(choice['message']['content'])
                validated=validate_tool_plan(item['question'],plan,store)
                row['validated_plan']=validated
                row['score']=score_plan(item['question'],validated,expected[item['id']],store)
                row['status']=row['score']['status']
                if row['status']!='passed':raise ValueError('business_score_failed')
            except KeyboardInterrupt:
                row['status']='incomplete';result['stop_reason']='user_interrupt_charge_uncertain'
                if 'usage' not in row:used+=reserve;row['charge_uncertain']=True
                raise
            except (requests.RequestException,ValueError,KeyError,IndexError,TypeError):
                row['status']='failed';result['stop_reason']='first_http_transport_usage_model_plan_or_business_failure'
                # Unknown billing reserves the whole request rather than treating a timeout as free.
                if 'usage' not in row:used+=reserve;row['charge_uncertain']=True
                break
            finally:
                result['cost_upper_estimate_usd']=str(used)
                dump(output/'run.json',result)
            print(json.dumps({'completed':len(result['records']),'cost_upper_estimate_usd':str(used)},ensure_ascii=False),flush=True)
        if len(result['records'])==COUNT and all(r['status']=='passed' for r in result['records']):result['status']='complete'
    finally:
        key='';session.close();dump(output/'run.json',result)
    score=evaluate_saved(ROOT,result);dump(output/'evaluation.json',score)
    print(json.dumps(score,ensure_ascii=False),flush=True)
    return 0 if result['status']=='complete' else 1


if __name__=='__main__':raise SystemExit(main())
