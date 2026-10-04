"""Deterministic graph engineering audit, not a sealed prediction/LLM benchmark."""
from pathlib import Path
from decimal import Decimal
import hashlib,json,math
import pandas as pd

from guanlan.trade_graph import make_report,export_graph_report,verify_graph_report
from guanlan.trade_graph_data import load_trade_graph

ROOT=Path(__file__).resolve().parents[1]
CASES=[(2024,'85','CHN',{'USA':10.,'DEU':5.},.5),(2023,'85','USA',{'CHN':20.},1.),
       (2022,'87','DEU',{'USA':15.,'GBR':10.},.25),(2021,'27','JPN',{'CHN':10.},.75),
       (2020,'10','BRA',{'CHN':20.},0.),(2017,'85','IND',{},.5)]


def oracle(edges,origin,shocks):
    # Independent row/group dictionary + Decimal arithmetic; does not call graph matrix/path tools.
    out={}
    for r in edges:out.setdefault(r['country_code'],{})[r['partner_code']]=Decimal(str(r['trade_usd']))
    totals={c:sum(v.values()) for c,v in out.items()}
    shares={c:{p:amount/totals[c] for p,amount in values.items()} for c,values in out.items()}
    direct=sum((w*Decimal(str(shocks.get(p,0))) for p,w in shares[origin].items()),Decimal(0))
    indirect=Decimal(0);mass=Decimal(0);path_count=0
    for via,w in shares[origin].items():
        for target,v in shares.get(via,{}).items():
            mass+=w*v;indirect+=w*v*Decimal(str(shocks.get(target,0)));path_count+=1
    hhi=sum(w*w for w in shares[origin].values())
    return {'direct':float(direct),'indirect':float(indirect),'mass':float(mass),'hhi':float(hhi),'path_count':path_count}


def main():
    results=[];reports=ROOT/'reports/trade-graph-engineering';reports.mkdir(exist_ok=True)
    for year,hs2,origin,shocks,alpha in CASES:
        graph=load_trade_graph(ROOT/'data/network',year,hs2)
        a=graph.analyze(origin,shocks,alpha);gold=oracle(graph.edges,origin,shocks)
        for key in ['direct','indirect']:assert math.isclose(a['exposure'][key],gold[key],rel_tol=1e-10,abs_tol=1e-10)
        assert math.isclose(a['exposure']['two_hop_retained_mass'],gold['mass'],abs_tol=1e-10)
        assert math.isclose(a['concentration']['hhi'],gold['hhi'],abs_tol=1e-10)
        assert len(a['paths'])==gold['path_count']
        assert math.isclose(a['exposure']['blended'],(gold['direct']+alpha*gold['indirect'])/(1+alpha),abs_tol=1e-10)
        report=make_report(graph,a);assert verify_graph_report(report)['status']=='passed'
        files=export_graph_report(report)
        stem=f'{year}-{origin}-HS{hs2}'
        for kind,data in files.items():(reports/f'{stem}.{kind}').write_bytes(data)
        results.append({'year':year,'hs2':hs2,'origin':origin,'shocks_pct':shocks,'alpha':alpha,'status':'passed','oracle':gold,
                        'actual':a['exposure'],'analysis_id':a['analysis_id'],'report_id':report['report_id'],
                        'graph_nodes':len(graph.nodes),'graph_edges':len(graph.edges),'report_bytes':{k:len(v) for k,v in files.items()}})
    result={'mode':'deterministic_engineering_audit','cases':results,'case_count':len(results),'all_passed':True,
            'protocol_sha256':hashlib.sha256((ROOT/'docs/TRADE_GRAPH_PROTOCOL.md').read_bytes()).hexdigest(),
            'llm_used':False,'new_ml_training':False,'network_requests':0,
            'limits':'Known public snapshots and explicit deterministic oracle; no unseen/sealed predictive or real-user/LLM quality inference.'}
    (ROOT/'reports/trade-graph-engineering-evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
