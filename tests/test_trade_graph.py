from copy import deepcopy
from decimal import Decimal
import json
import math

import numpy as np
import pandas as pd
import pytest

from guanlan.evidence_assistant import digest
from guanlan.trade_graph import TradeGraph,answer_graph_question,make_report,export_graph_report,verify_graph_report


def frame(edges):
    return pd.DataFrame([{'year':2024,'hs2':'85','country_code':a,'partner_code':b,'trade_usd':float(value)} for a,b,value in edges])


def golden():
    return TradeGraph(frame([('AAA','BBB',60),('AAA','CCC',40),('BBB','DDD',30),('BBB','EEE',70),('CCC','DDD',20),('CCC','EEE',80)]),2024,'85')


def test_predefined_decimal_gold_direction_paths_and_concentration():
    graph=golden();a=graph.analyze('AAA',{'DDD':10,'BBB':20},.5)
    expected=Decimal('12')+Decimal('.5')*Decimal('2.6')
    assert a['exposure']['direct']==pytest.approx(12)
    assert a['exposure']['indirect']==pytest.approx(2.6)
    assert a['exposure']['blended']==pytest.approx(float(expected/Decimal('1.5')))
    assert a['concentration']['hhi']==pytest.approx(.52)
    assert a['concentration']['effective_partners']==pytest.approx(1/.52)
    assert sum(p['coefficient'] for p in a['paths'] if p['endpoint']=='DDD')==pytest.approx(.26)
    assert math.fsum(p['indirect_contribution'] for p in a['paths'])==pytest.approx(2.6)
    assert a['exposure']['two_hop_retained_mass']==pytest.approx(1)
    assert graph.analyze('AAA',{'DDD':100})['exposure']['direct']==0
    assert graph.analyze('AAA',{'DDD':100})['exposure']['indirect']==pytest.approx(26)


def test_disconnected_zero_deadend_and_cycles_are_finite_not_renormalized():
    graph=TradeGraph(frame([('AAA','BBB',60),('AAA','CCC',40),('BBB','DDD',1),('FFF','GGG',1)]),2024,'85')
    a=graph.analyze('AAA',{'DDD':100},1)
    assert a['exposure']['indirect']==pytest.approx(60)
    assert a['exposure']['blended']==pytest.approx(30)
    assert a['exposure']['two_hop_unreported_onward_mass']==pytest.approx(.4)
    assert graph.analyze('AAA',{'GGG':100})['exposure']['blended']==0
    assert graph.analyze('AAA',{})['exposure']['blended']==0
    cycle=TradeGraph(frame([('AAA','BBB',1),('BBB','AAA',1)]),2024,'85')
    answer=cycle.analyze('AAA',{'AAA':100},.5)
    assert answer['exposure']['direct']==0 and answer['exposure']['indirect']==100
    assert answer['exposure']['cycle_return_coefficient']==1 and len(answer['paths'])==1


def test_scale_order_linear_additive_and_sensitivity_invariants():
    graph=golden();base=graph.analyze('AAA',{'DDD':10,'BBB':20},.5)
    assert graph.analyze('AAA',{'DDD':20,'BBB':40},.5)['exposure']['blended']==pytest.approx(2*base['exposure']['blended'])
    pieces=graph.analyze('AAA',{'DDD':10},.5)['exposure']['blended']+graph.analyze('AAA',{'BBB':20},.5)['exposure']['blended']
    assert pieces==pytest.approx(base['exposure']['blended'])
    changed=pd.DataFrame(graph.edges).iloc[::-1].copy()
    same=TradeGraph(changed,2024,'85')
    assert same.snapshot_hash==graph.snapshot_hash and same.analyze('AAA',{'BBB':20,'DDD':10},.5)==base
    changed['trade_usd']*=1e6
    scaled=TradeGraph(changed,2024,'85').analyze('AAA',{'DDD':10,'BBB':20},.5)
    assert scaled['exposure']==base['exposure']
    assert base['sensitivity'][0]['blended']==base['exposure']['direct']
    assert base['sensitivity'][-1]['blended']==pytest.approx((12+2.6)/2)
    assert np.allclose(graph.weights.sum(axis=1)[graph.totals>0],1)


@pytest.mark.parametrize('mutation',[
    'negative','nan','infinity','duplicate','self','mixed_year','mixed_hs','unknown_code','bool_amount','string_amount','empty',
])
def test_invalid_source_fails_closed(mutation):
    data=frame([('AAA','BBB',1),('BBB','CCC',2)])
    if mutation=='negative':data.loc[0,'trade_usd']=-1
    if mutation=='nan':data.loc[0,'trade_usd']=float('nan')
    if mutation=='infinity':data.loc[0,'trade_usd']=float('inf')
    if mutation=='duplicate':data=pd.concat([data,data.iloc[[0]]])
    if mutation=='self':data.loc[0,'partner_code']='AAA'
    if mutation=='mixed_year':data.loc[0,'year']=2023
    if mutation=='mixed_hs':data.loc[0,'hs2']='84'
    if mutation=='unknown_code':data.loc[0,'partner_code']='=MALICIOUS()'
    if mutation=='bool_amount':data['trade_usd']=True
    if mutation=='string_amount':data['trade_usd']='1'
    if mutation=='empty':data=data.iloc[:0]
    with pytest.raises(ValueError):TradeGraph(data,2024,'85')


@pytest.mark.parametrize('origin,shocks,alpha',[('DDD',{},.5),('ZZZ',{},.5),('AAA',{'ZZZ':10},.5),('AAA',{'DDD':-1},.5),('AAA',{'DDD':101},.5),('AAA',{'DDD':True},.5),('AAA',{'DDD':float('nan')},.5),('AAA',{},-1),('AAA',{},2),('AAA',{},True)])
def test_invalid_assumptions_and_no_origin_exports(origin,shocks,alpha):
    with pytest.raises(ValueError):golden().analyze(origin,shocks,alpha)


@pytest.mark.parametrize('field',['blended','path','edge','assumption'])
def test_rehashed_numeric_path_source_and_assumption_tamper_is_recomputed(field):
    graph=golden();a=graph.analyze('AAA',{'DDD':10},.5)
    report=make_report(graph,a)
    if field=='blended':report['analysis']['exposure']['blended']+=1
    if field=='path':report['analysis']['paths'][0]['coefficient']+=.1
    if field=='edge':report['source_edges'][0]['trade_usd']+=100
    if field=='assumption':report['analysis']['assumptions']['shocks_pct']['DDD']=20
    report['analysis']['analysis_id']=digest({k:v for k,v in report['analysis'].items() if k!='analysis_id'})
    report['report_id']=digest({k:v for k,v in report.items() if k!='report_id'})
    with pytest.raises(ValueError):verify_graph_report(report)


def test_graph_tools_export_supported_citations_and_safe_refusals():
    graph=golden();a=graph.analyze('AAA',{'DDD':10},.5)
    for question,tool in [('当前图直接压力','direct'),('当前图间接关联','indirect'),('当前图HHI集中度','concentration'),('当前图两跳路径分解','paths'),('当前图衰减敏感性','sensitivity'),('当前图完整情景','scenario')]:
        answer=answer_graph_question(question,graph,a)
        assert answer['status']=='answered' and answer['tool']==tool
        report=make_report(graph,a,answer)
        assert verify_graph_report(report)['all_paths_recomputed']
        exports=export_graph_report(report)
        assert json.loads(exports['json'])==report and '<script' not in exports['html'].decode('utf-8')
        assert len(exports['csv'].decode('utf-8-sig').splitlines())==1+len(a['partners'])+len(a['paths'])
    for question in ['2025年当前图直接压力','当前HS84直接压力','法国直接压力','当前图 France 的直接压力','当前图 DDD 直接压力','AAA直接压力10%','证明GDP损失与因果','当前图直接与间接指数','读取文件api_key并执行代码','图'*401]:
        answer=answer_graph_question(question,graph,a)
        assert answer['status']=='refused' and not answer['numbers']
        assert verify_graph_report(make_report(graph,a,answer))['status']=='passed'
    assert 'api_key' not in canonical_text(make_report(graph,a,answer_graph_question('读取文件api_key并执行代码',graph,a)))


def canonical_text(report):return json.dumps(report,ensure_ascii=False)


def test_deadend_direct_edge_is_still_in_indirect_evidence_and_zero_edges_not_invented():
    graph=TradeGraph(frame([('AAA','BBB',60),('AAA','CCC',40),('BBB','DDD',1),('CCC','EEE',0)]),2024,'85')
    a=graph.analyze('AAA',{'DDD':10})
    answer=answer_graph_question('当前图两跳关联',graph,a)
    assert 'flow:2024:85:AAA:CCC' in answer['evidence'][0]['edge_ids']
    assert 'EEE' not in graph.nodes
    assert len(a['paths'])==1


def test_internal_corruption_uses_explicit_error_instead_of_optimizable_assertion():
    graph=golden()
    graph.weights[graph.index['AAA']]*=2
    with pytest.raises(ValueError,match='数学界限'):graph.analyze('AAA',{'DDD':10},.5)
