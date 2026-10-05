from copy import deepcopy
from decimal import Decimal
import hashlib,json
from pathlib import Path
from unittest.mock import patch
import importlib.util

import pytest

from guanlan.assistant_plans import validate_tool_plan
from guanlan.llm_business import cost_bound,evaluate_saved,load_pilot,score_plan,sha,usage_cost

ROOT=Path(__file__).resolve().parents[1]


def test_default_cli_preflight_never_reads_a_key_or_calls_network(monkeypatch):
    spec=importlib.util.spec_from_file_location('pilot_runner',ROOT/'scripts/llm_business_pilot.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    outputs=[];monkeypatch.setattr(module,'dump',lambda path,value:outputs.append(value));monkeypatch.setattr(module.sys,'argv',['pilot'])
    with patch('requests.Session.post',side_effect=AssertionError('No API')),patch('getpass.getpass',side_effect=AssertionError('No key')):
        assert module.main()==0
    assert outputs[0]['live_calls']==0 and outputs[0]['credential_read'] is False and outputs[0]['local_guard_rejections']==6


def test_preflight_uses_frozen_public_inputs_without_network_or_credentials():
    with patch('requests.Session.post',side_effect=AssertionError('Network forbidden')),patch('getpass.getpass',side_effect=AssertionError('Credential read forbidden')):
        _,protocol,cases,gold,store=load_pilot(ROOT)
    assert protocol['new_live_calls']==0 and len(cases)==12 and len(gold['local_guard_cases'])==6
    for case in cases:
        material=json.loads(case['request']['messages'][1]['content'])
        assert set(material)=={'question','snapshot_hash','key','aliases','allowed_tools','available_periods','required_fields'}
        assert material['snapshot_hash']==store.snapshot_hash and 'value' not in material


def test_manifest_cannot_read_an_external_file(tmp_path):
    folder=tmp_path/'evaluation/llm-business-pilot-v1';folder.mkdir(parents=True)
    (folder/'manifest.json').write_text(json.dumps({'files':{'../outside':'ignored'}}),encoding='utf-8')
    with patch('guanlan.llm_business.sha',side_effect=AssertionError('External read forbidden')):
        with pytest.raises(ValueError):load_pilot(tmp_path)


def test_exact_decimal_budget_and_usage_failure_stop_rules():
    rates=(Decimal('.30'),Decimal('1.20'))
    assert 12*cost_bound(*rates)==Decimal('.0205056')
    clean,cost=usage_cost({'prompt_tokens':100,'completion_tokens':50,'total_tokens':150},*rates)
    assert clean['total_tokens']==150 and cost==Decimal('.00009')
    for value in [None,{}, {'prompt_tokens':True,'completion_tokens':0,'total_tokens':1},{'prompt_tokens':4097,'completion_tokens':0,'total_tokens':4097},{'prompt_tokens':1,'completion_tokens':401,'total_tokens':402},{'prompt_tokens':1,'completion_tokens':2,'total_tokens':4}]:
        with pytest.raises(ValueError):usage_cost(value,*rates)
    for rate in ['NaN','Infinity','-1','0']:
        with pytest.raises(ValueError):cost_bound(Decimal(rate),rates[1])


def fixture_run():
    # A synthetic plan fixture tests scoring only; never represents actual API quality.
    _,_,cases,gold,store=load_pilot(ROOT);case=cases[0];expected=gold['business'][0]['expected']
    plan={'snapshot_hash':store.snapshot_hash,'key':expected['key'],'tool':expected['tool'],'periods':expected['periods'],'direction':'max'}
    return case,expected,plan,store


def test_strict_business_scope_numeric_and_evidence_scoring_rejects_extras():
    case,expected,plan,store=fixture_run()
    assert score_plan(case['question'],plan,expected,store)['status']=='passed'
    for change in [{'tool':'shell'},{'key':'ppi_mom'},{'periods':['2025-09']},{'summary':'invented'}]:
        with pytest.raises(ValueError):validate_tool_plan(case['question'],{**plan,**change},store)
    bad=deepcopy(expected);bad['numbers']['value']+=1
    assert score_plan(case['question'],plan,bad,store)['status']=='failed'
    bad=deepcopy(expected);bad['evidence_ids']=['unapproved']
    assert score_plan(case['question'],plan,bad,store)['status']=='failed'


def test_mock_fixture_cannot_be_scored_as_a_recorded_actual_run():
    with pytest.raises(ValueError):evaluate_saved(ROOT,{'mode':'test_fixture','protocol_manifest_sha256':sha(ROOT/'evaluation/llm-business-pilot-v1/manifest.json')})


def test_saved_first_run_rejects_missing_usage_out_of_order_and_tampered_score():
    case,expected,plan,store=fixture_run()
    row={'id':case['id'],'status':'passed','validated_plan':plan,'score':score_plan(case['question'],plan,expected,store),
         'request_payload_sha256':hashlib.sha256(json.dumps(case['request'],ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
         'served_model':'deepseek-fixture-model','usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150},'conservative_usage_usd':'.00009'}
    run={'mode':'live_user_triggered','status':'incomplete','protocol_manifest_sha256':sha(ROOT/'evaluation/llm-business-pilot-v1/manifest.json'),
         'input_usd_per_million':'.30','output_usd_per_million':'1.20','local_cap_usd':'.03','records':[row]}
    # Local synthetic record exercises validation; test output is not published as business evidence.
    score=evaluate_saved(ROOT,run)
    assert score['recorded_requests']==1 and score['all_planned_denominator']==12 and not score['pipeline_gate_passed']
    for variant in ['missing-usage','out-of-order','tamper','false-complete']:
        bad=deepcopy(run)
        if variant=='missing-usage':del bad['records'][0]['usage']
        elif variant=='out-of-order':bad['records'][0]['id']='development:00:01'
        elif variant=='tamper':bad['records'][0]['score']['numbers']['value']=999
        else:bad['status']='complete'
        with pytest.raises(ValueError):evaluate_saved(ROOT,bad)
