"""Finite directed merchandise-market exposure; no loss or causal model."""
from __future__ import annotations

import csv
import html
import io
import math
import re

import numpy as np
import pandas as pd

from .evidence_assistant import canonical, digest
from .catalog import COUNTRY_ZH, country_label

VERSION='trade-graph-v1'
LIMITS=[
    '当前修订历史BACI货物金额，不证明当时实时可得；压力为用户假设。',
    '同HS2两条出口连接不证明同一货物再出口、投入产出或供应链传导。',
    '直接/两跳/混合值是条件压力指数，不是GDP、出口、信贷损失或预测概率。',
    '断点权重保留，不重分配；固定两跳允许循环，不进行无限传播。',
    'SHA与离线重算只验证内部一致性，不是官方来源真实性签名。',
]
COLUMNS=['year','country_code','partner_code','hs2','trade_usd']
TOOLS={'direct':'直接市场压力','indirect':'两跳市场关联','concentration':'伙伴集中度','paths':'路径分解','sensitivity':'衰减敏感性','scenario':'完整情景'}


class TradeGraph:
    def __init__(self, frame: pd.DataFrame, year: int, hs2: str, provenance: dict | None=None):
        if type(year) is not int or not 2017<=year<=2024 or not isinstance(hs2,str) or not re.fullmatch(r'0[1-9]|[1-8][0-9]|9[0-7]',hs2):
            raise ValueError('图范围限2017—2024、两位HS2章01—97')
        if set(frame.columns)!=set(COLUMNS) or frame.empty or len(frame)>100000:
            raise ValueError('图源行为空、过大或列结构无效')
        data=frame[COLUMNS].copy()
        if data.isna().any().any() or not (data.year==year).all() or not (data.hs2==hs2).all():
            raise ValueError('源行缺失或混用年份/HS章')
        for column in ['country_code','partner_code']:
            if not data[column].map(lambda x:isinstance(x,str) and re.fullmatch(r'(?:[A-Z]{3}|S19)',x) is not None).all():
                raise ValueError('图节点代码无效')
        if data.duplicated(['country_code','partner_code']).any() or (data.country_code==data.partner_code).any():
            raise ValueError('图源行重复或含国内自环')
        if not pd.api.types.is_numeric_dtype(data.trade_usd) or pd.api.types.is_bool_dtype(data.trade_usd):raise ValueError('金额必须为数值类型')
        values=data.trade_usd.to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values<0).any():raise ValueError('图金额为负或非有限')
        data=data.loc[values>0].sort_values(['country_code','partner_code']).reset_index(drop=True)
        if data.empty:raise ValueError('图没有正额贸易边')
        data['year']=year
        data['trade_usd']=data.trade_usd.astype(float)
        self.year=year
        self.hs2=hs2
        self.edges=data.to_dict('records')
        self.nodes=sorted(set(data.country_code)|set(data.partner_code))
        if len(self.nodes)>500:raise ValueError('图节点过多')
        self.index={country:i for i,country in enumerate(self.nodes)}
        self.amounts=np.zeros((len(self.nodes),len(self.nodes)))
        for row in self.edges:self.amounts[self.index[row['country_code']],self.index[row['partner_code']]]=row['trade_usd']
        self.totals=self.amounts.sum(axis=1)
        if not np.isfinite(self.totals).all():raise ValueError('金额加总溢出')
        self.weights=np.divide(self.amounts,self.totals[:,None],out=np.zeros_like(self.amounts),where=self.totals[:,None]>0)
        self.provenance=provenance or {'kind':'synthetic_fixture','notice':'测试构造图，不是官方贸易材料'}
        if set(self.provenance)-{'kind','notice','provider','release','source_url','license','license_url','citation','partition_sha256','raw_zip_sha256','partition_rows'}:
            raise ValueError('来源元数据含未批准字段')
        if self.provenance.get('kind')=='BACI_official_aggregate':
            if self.provenance.get('provider')!='CEPII BACI' or self.provenance.get('release')!='HS17 V202601' or self.provenance.get('source_url')!='https://www.cepii.fr/DATA_DOWNLOAD/baci/data/BACI_HS17_V202601.zip':
                raise ValueError('来源标识不符合批准快照')
            for key in ['partition_sha256','raw_zip_sha256']:
                if not re.fullmatch(r'[0-9a-f]{64}',str(self.provenance.get(key,''))):raise ValueError('来源指纹无效')
        elif self.provenance.get('kind')!='synthetic_fixture':raise ValueError('来源类型无效')
        self.snapshot_hash=digest({'year':year,'hs2':hs2,'edges':self.edges,'provenance':self.provenance})

    def analyze(self, origin: str, shocks: dict[str,float], alpha: float=.5) -> dict:
        if origin not in self.index or self.totals[self.index[origin]]<=0:raise ValueError('所选出口国无该行业已报告正额出口')
        if type(alpha) not in (int,float) or not math.isfinite(alpha) or not 0<=alpha<=1:raise ValueError('衰减系数必须在0—1')
        if not isinstance(shocks,dict) or any(k not in self.index or type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=100 for k,v in shocks.items()):
            raise ValueError('压力市场必须是当前图节点，假设压力0—100')
        shocks={k:float(v) for k,v in sorted(shocks.items())}
        i=self.index[origin]
        w=self.weights[i]
        endpoint=w@self.weights
        pressure=np.array([shocks.get(country,0.) for country in self.nodes])
        direct=float(np.dot(w,pressure))
        indirect=float(np.dot(endpoint,pressure))
        blended=(direct+alpha*indirect)/(1+alpha)
        partners=[]
        for j in np.flatnonzero(w):
            partners.append({'partner':self.nodes[j],'trade_usd':float(self.amounts[i,j]),'share':float(w[j]),
                             'shock_pct':float(pressure[j]),'direct_contribution':float(w[j]*pressure[j]),
                             'onward_reported':bool(self.totals[j]>0)})
        partners.sort(key=lambda r:(-r['share'],r['partner']))
        paths=[]
        for j in np.flatnonzero(w):
            for k in np.flatnonzero(self.weights[j]):
                first=float(w[j]);second=float(self.weights[j,k]);coefficient=first*second
                contribution=coefficient*float(pressure[k])
                paths.append({'via':self.nodes[j],'endpoint':self.nodes[k],'first_trade_usd':float(self.amounts[i,j]),
                              'second_trade_usd':float(self.amounts[j,k]),'first_share':first,'second_share':second,
                              'coefficient':coefficient,'shock_pct':float(pressure[k]),'indirect_contribution':contribution,
                              'blended_indirect_contribution':alpha*contribution/(1+alpha),
                              'edge_ids':[f"flow:{self.year}:{self.hs2}:{origin}:{self.nodes[j]}",f"flow:{self.year}:{self.hs2}:{self.nodes[j]}:{self.nodes[k]}"]})
        paths.sort(key=lambda r:(-r['indirect_contribution'],-r['coefficient'],r['via'],r['endpoint']))
        hhi=math.fsum(r['share']**2 for r in partners)
        mass=math.fsum(r['coefficient'] for r in paths)
        if not math.isclose(math.fsum(r['indirect_contribution'] for r in paths),indirect,abs_tol=1e-10,rel_tol=1e-10):
            raise ValueError('路径加总与矩阵计算不一致')
        if not 0<=mass<=1+1e-10 or not -1e-10<=blended<=100+1e-10:
            raise ValueError('图质量或压力指数超出数学界限')
        sensitivity=[{'alpha':a,'direct':direct,'indirect':indirect,'blended':(direct+a*indirect)/(1+a)} for a in sorted({0.,.25,.5,.75,1.,float(alpha)})]
        comparisons=[{'scenario':'zero','shocks':{},'direct':0.,'indirect':0.,'blended':0.}]
        for country,shock in shocks.items():
            d=float(w[self.index[country]])*shock
            n=float(endpoint[self.index[country]])*shock
            comparisons.append({'scenario':country,'shocks':{country:shock},'direct':d,'indirect':n,'blended':(d+alpha*n)/(1+alpha)})
        comparisons.append({'scenario':'combined','shocks':shocks,'direct':direct,'indirect':indirect,'blended':blended})
        result={'version':VERSION,'snapshot_hash':self.snapshot_hash,'scope':{'year':self.year,'hs2':self.hs2,'origin':origin},
                'assumptions':{'shocks_pct':shocks,'alpha':float(alpha),'meaning':'假设市场需求收缩；不是已发生观测/GDP冲击','formula':'(W s + alpha W^2 s)/(1+alpha)'},
                'concentration':{'export_usd':float(self.totals[i]),'partner_count':len(partners),'hhi':hhi,'effective_partners':1/hhi,
                                 'top1_share':partners[0]['share'],'top5_share':math.fsum(p['share'] for p in partners[:5])},
                'exposure':{'direct':direct,'indirect':indirect,'blended':blended,'unit':'条件压力指数点',
                            'two_hop_retained_mass':mass,'two_hop_unreported_onward_mass':max(0.,1-mass),
                            'direct_shocked_market_weight':float(w[pressure>0].sum()),'two_hop_shocked_endpoint_weight':float(endpoint[pressure>0].sum()),
                            'cycle_return_coefficient':float(endpoint[i])},
                'partners':partners,'paths':paths,'sensitivity':sensitivity,'scenario_comparison':comparisons,
                'provenance':self.provenance,'graph_quality':{'nodes':len(self.nodes),'edges':len(self.edges),'deadend_nodes':int((self.totals==0).sum())},'limitations':LIMITS}
        return {**result,'analysis_id':digest(result)}


def answer_graph_question(question: str, graph: TradeGraph, analysis: dict) -> dict:
    base={'version':VERSION,'snapshot_hash':graph.snapshot_hash,'analysis_id':analysis['analysis_id'],'question':question,
          'scope':analysis['scope'],'scope_source':'当前可见且已应用的图/情景','llm_used':False}
    reason=None
    if not isinstance(question,str) or not question.strip():reason='问题为空，请指定要核查的图工具'
    elif len(question)>400:
        reason='问题超过400字符';base['question']='[超长问题已省略]'
    elif re.search(r'密钥|api.?key|token|密码|读取文件|执行代码|忽略.*规则|https?://|shell|绕过|泄露',question,re.I):
        reason='越权请求被拒绝；图工具不读取凭据、执行代码或访问外部地址';base['question']='[敏感或越权内容已省略]'
    elif re.search(r'因果|GDP损失|出口损失|信贷损失|供应链系数|投入产出|股价|买入|盈利|必赚|预测概率|实时|最新年份',question,re.I):
        reason='当前图只能核查历史市场连接与假设压力指数，无法证明所请求的因果、损失、实时或投资结论'
    else:
        years=re.findall(r'(?<!\d)(20\d{2})(?!\d)',question)
        chapters=re.findall(r'HS\s*(\d{2})(?!\d)',question,re.I)
        codes=[code for code in re.findall(r'\b(?:[A-Z]{3}|S19)\b',question) if code not in {'HHI','GDP','USD'}]
        aliases={name:code for code,name in COUNTRY_ZH.items()}
        aliases.update({country_label(code).split('（')[0]:code for code in graph.nodes})
        spans=[(m.start(),m.end(),code) for name,code in aliases.items() for m in re.finditer(re.escape(name),question)]
        named=[code for start,end,code in spans if not any(left<=start and end<=right and (left<start or end<right) for left,right,_ in spans)]
        countries=set(codes+named)
        allowed={analysis['scope']['origin']}
        latin=re.findall(r'[A-Za-z][A-Za-z0-9_-]*',question)
        permitted={*graph.nodes,'HHI','GDP','USD','BACI',f'HS{graph.hs2}'}
        if not re.search(r'当前图|此图|当前情景',question):
            reason='请明确核查当前图/当前情景；新的研究对象须先在上方选择，不能从一句含糊问题猜测'
        elif re.search(r'欧盟|欧元区|供应链系数|投入产出系数',question):
            reason='此图不提供未定义市场组或供应链系数，须显式选择当前批准市场'
        elif any(token.upper() not in permitted for token in latin):
            reason='无法明确解析外文范围；请使用当前图、中文工具名称及上方显示的来源代码'
        elif any(int(y)!=graph.year for y in years) or any(h!=graph.hs2 for h in chapters) or countries-allowed:
            reason='问题范围与上方已应用的国家/HS2/年份/压力市场不一致，请先修改研究范围与情景'
        elif re.search(r'\d+(?:\.\d+)?\s*[%％]|衰减\s*[=＝]?\s*\d',question):
            reason='数值情景必须在上方表单显式应用，问题文字不能悄悄替换已核查参数'
    tool=None
    if reason is None:
        families={'direct':r'直接|一跳','indirect':r'间接|两跳|二跳','concentration':r'集中|HHI|有效伙伴|前五',
                  'paths':r'路径|分解','sensitivity':r'敏感|衰减','scenario':r'完整情景|综合|混合|情景比较'}
        matched=[name for name,pattern in families.items() if re.search(pattern,question,re.I)]
        if 'paths' in matched:tool='paths'
        elif 'sensitivity' in matched:tool='sensitivity'
        elif len(matched)==1:tool=matched[0]
        else:reason='请一次核查直接、两跳、集中度、路径、敏感性或完整情景中的一项'
    numbers={}
    evidence=[]
    if reason is None:
        if tool in {'direct','indirect','scenario'}:
            keys=[tool] if tool!='scenario' else ['direct','indirect','blended']
            numbers={k:analysis['exposure'][k] for k in keys}
            text='；'.join(f'{TOOLS.get(k,"混合压力")} {v:.6f} 指数点' for k,v in numbers.items())+'。均为条件情景，不是经济损失。'
        elif tool=='concentration':
            numbers=analysis['concentration'].copy()
            text=f"伙伴HHI {numbers['hhi']:.6f}，有效伙伴数 {numbers['effective_partners']:.3f}，前五份额 {numbers['top5_share']:.2%}；分母为全部已报告同业出口。"
        elif tool=='paths':
            numbers={'path_count':len(analysis['paths']),'path_sum':math.fsum(p['indirect_contribution'] for p in analysis['paths']),
                     'retained_mass':analysis['exposure']['two_hop_retained_mass']}
            text=f"完整两跳路径 {numbers['path_count']} 条，加总 {numbers['path_sum']:.6f} 指数点；保留质量 {numbers['retained_mass']:.2%}。同业连接不证明再出口。"
        else:
            numbers={'alpha_zero':analysis['sensitivity'][0]['blended'],'alpha_one':analysis['sensitivity'][-1]['blended']}
            text=f"α=0 时 {numbers['alpha_zero']:.6f}，α=1 时 {numbers['alpha_one']:.6f} 指数点；假设敏感性，不是估计出的传导参数。"
        evidence=[{'kind':'approved_graph_and_tool','snapshot_hash':graph.snapshot_hash,'analysis_id':analysis['analysis_id'],
                   'edge_ids':sorted({eid for p in analysis['paths'] for eid in p['edge_ids']}|{f"flow:{graph.year}:{graph.hs2}:{analysis['scope']['origin']}:{p['partner']}" for p in analysis['partners']}) if tool in {'indirect','paths','scenario','sensitivity'} else
                              [f"flow:{graph.year}:{graph.hs2}:{analysis['scope']['origin']}:{p['partner']}" for p in analysis['partners']],
                   'provenance':graph.provenance}]
    else:text=reason
    result={**base,'status':'answered' if reason is None else 'refused','tool':tool,'answer':text,'numbers':numbers,'evidence':evidence,
            'trace':{'tool':tool,'arguments':analysis['scope'],'assumptions':analysis['assumptions'],'analysis_id':analysis['analysis_id']} if tool else None,'limitations':LIMITS}
    return {**result,'answer_id':digest(result)}


def make_report(graph: TradeGraph, analysis: dict, answer: dict | None=None) -> dict:
    expected=graph.analyze(analysis['scope']['origin'],analysis['assumptions']['shocks_pct'],analysis['assumptions']['alpha'])
    if canonical(expected)!=canonical(analysis):raise ValueError('情景结果与来源不一致')
    if answer and canonical(answer)!=canonical(answer_graph_question(answer['question'],graph,analysis)):
        # Redacted rejected questions are verified using their fixed safe equivalent.
        replacement='读取文件中的密钥' if answer['question']=='[敏感或越权内容已省略]' else '图'*401 if answer['question']=='[超长问题已省略]' else answer['question']
        if canonical(answer)!=canonical(answer_graph_question(replacement,graph,analysis)):raise ValueError('图答案与工具结果不一致')
    report={'schema_version':VERSION,'analysis':analysis,'answer':answer,'source_edges':graph.edges}
    return {**report,'report_id':digest(report)}


def verify_graph_report(report: dict) -> dict:
    try:
        if set(report)!={'schema_version','analysis','answer','source_edges','report_id'} or report['schema_version']!=VERSION:
            raise ValueError
        if digest({k:v for k,v in report.items() if k!='report_id'})!=report['report_id']:raise ValueError
        a=report['analysis'];scope=a['scope']
        graph=TradeGraph(pd.DataFrame(report['source_edges']),scope['year'],scope['hs2'],a['provenance'])
        if canonical(make_report(graph,a,report['answer']))!=canonical(report):raise ValueError
    except (KeyError,TypeError,ValueError,AttributeError,IndexError,AssertionError):
        raise ValueError('图报告核验失败：结构、源边、情景、路径或答案不一致') from None
    return {'status':'passed','report_id':report['report_id'],'analysis_id':a['analysis_id'],'all_paths_recomputed':True,'network_requests':0,'llm_used':False}


def export_graph_report(report: dict) -> dict[str,bytes]:
    import json
    verify_graph_report(report)
    a=report['analysis'];s=a['scope'];e=a['exposure']
    encoded=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
    rows=''.join(f"<tr><td>{html.escape(p['via'])}</td><td>{html.escape(p['endpoint'])}</td><td>{p['coefficient']:.8f}</td><td>{p['indirect_contribution']:.6f}</td></tr>" for p in a['paths'][:30])
    residual=e['indirect']-math.fsum(p['indirect_contribution'] for p in a['paths'][:30])
    response=f"<article>{html.escape(report['answer']['answer'])}</article>" if report['answer'] else ''
    document=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>观澜 · 真实贸易图</title>
<style>body{{font:16px/1.6 system-ui;max-width:1000px;margin:30px auto;padding:0 16px;color:#172d3b;background:#f7faf9;overflow-wrap:anywhere}}h1{{color:#146f7c}}code,pre{{white-space:pre-wrap;overflow-wrap:anywhere}}table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{padding:5px;border-bottom:1px solid #ddd}}article{{padding:12px;background:white}}</style>
<h1>观澜 · 真实贸易图与情景</h1><p>{s['year']} · {html.escape(s['origin'])} · HS{s['hs2']} · 用户假设压力 {html.escape(str(a['assumptions']['shocks_pct']))} · α={a['assumptions']['alpha']}</p>
<article>直接 {e['direct']:.6f} · 两跳 {e['indirect']:.6f} · 混合 {e['blended']:.6f} 条件压力指数点。不是经济损失。</article>{response}
<p>HHI {a['concentration']['hhi']:.6f}；无后续报告权重 {e['two_hop_unreported_onward_mass']:.2%}。</p>
<p>来源：{html.escape(str(a['provenance']))}</p><ul>{''.join('<li>'+html.escape(t)+'</li>' for t in LIMITS)}</ul>
<h2>前30条两跳路径（完整路径在JSON/CSV）</h2><table><tr><th>中间</th><th>端点</th><th>路径系数</th><th>压力贡献</th></tr>{rows}</table><p>未展示残差 {residual:.6f} 指数点。</p>
<p>报告SHA256 <code>{report['report_id']}</code>，一致性不证明来源真实。</p><details><summary>完整证据JSON</summary><pre>{html.escape(encoded.decode('utf-8'))}</pre></details></html>'''
    output=io.StringIO(newline='')
    fields=['record_kind','origin','year','hs2','via','endpoint','coefficient','shock_pct','contribution','first_trade_usd','second_trade_usd','analysis_id']
    writer=csv.DictWriter(output,fieldnames=fields);writer.writeheader()
    common={'origin':s['origin'],'year':s['year'],'hs2':s['hs2'],'analysis_id':a['analysis_id']}
    for p in a['partners']:
        writer.writerow({**common,'record_kind':'direct','endpoint':p['partner'],'coefficient':p['share'],'shock_pct':p['shock_pct'],'contribution':p['direct_contribution'],'first_trade_usd':p['trade_usd']})
    for p in a['paths']:
        writer.writerow({**common,'record_kind':'two_hop','via':p['via'],'endpoint':p['endpoint'],'coefficient':p['coefficient'],'shock_pct':p['shock_pct'],
                         'contribution':p['indirect_contribution'],'first_trade_usd':p['first_trade_usd'],'second_trade_usd':p['second_trade_usd']})
    return {'html':document.encode('utf-8'),'json':encoded,'csv':output.getvalue().encode('utf-8-sig')}
