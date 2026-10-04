from __future__ import annotations

import hashlib
import json
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from guanlan.catalog import country_label
from guanlan.evidence_assistant import digest
from guanlan.trade import HS_CHAPTERS, compact_usd
from guanlan.trade_graph import TOOLS, answer_graph_question, make_report, export_graph_report
from guanlan.trade_graph_data import load_trade_graph
from .common import ROOT, chart, initial_query, select, sync_query


@st.cache_resource(max_entries=4,show_spinner=False)
def cached_graph(year,hs2,manifest_hash,partition_mtime,partition_size):
    return load_trade_graph(ROOT/'data/network',year,hs2)


def get_graph(year,hs2):
    directory=ROOT/'data/network'
    signature=hashlib.sha256((directory/'manifest.json').read_bytes()).hexdigest()
    part=directory/f'sector_partner_{year}.parquet'
    stat=part.stat()
    return cached_graph(year,hs2,signature,stat.st_mtime_ns,stat.st_size)


def path_figure(paths,origin,label):
    selected=[p for p in paths if p['indirect_contribution']>0][:20]
    keys=sorted({(1,p['via']) for p in selected}|{(2,p['endpoint']) for p in selected})
    keys=[(0,origin),*keys]
    positions={key:i for i,key in enumerate(keys)}
    links: dict[tuple[int,int],float]={}
    for p in selected:
        for start,end in [((0,origin),(1,p['via'])),((1,p['via']),(2,p['endpoint']))]:
            pair=(positions[start],positions[end]);links[pair]=links.get(pair,0.)+p['indirect_contribution']
    levels={level:[code for lev,code in keys if lev==level] for level in range(3)}
    figure=go.Figure(go.Sankey(arrangement='snap',
                               node={'label':[code for _,code in keys],
                                     'customdata':[f'{["起点","中间","端点"][level]} · {label(code)}' for level,code in keys],
                                     'hovertemplate':'%{customdata}<extra></extra>',
                                     'x':[{0:.03,1:.5,2:.95}[level] for level,_ in keys],
                                     'color':['#172d3b' if level==0 else '#146f7c' if level==1 else '#b95d42' for level,_ in keys],'pad':8},
                               link={'source':[p[0] for p in links],'target':[p[1] for p in links],'value':list(links.values()),
                                     'hovertemplate':'两跳条件压力贡献 %{value:.6f} 指数点<extra></extra>'}))
    figure.update_layout(title='两跳压力贡献 · 前20条',height=max(430,len(levels[1])*24+100),
                         margin={'l':5,'r':8,'t':55,'b':20},font={'size':11})
    return figure,math.fsum(p['indirect_contribution'] for p in selected)


def render(store,task='真实贸易图与情景'):
    st.subheader('真实贸易图与压力情景')
    st.caption('出口国 → 进口伙伴 → 该伙伴出口目的地 · CEPII BACI HS17 V202601 · 2017—2024历史快照')
    st.info('市场需求压力为用户假设。两跳连接不证明同货物再出口或供应链关系；所有指数均不等于GDP、出口或信贷损失，也不改变原模型概率。')
    try:
        directory=ROOT/'data/network'
        manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        years=sorted([str(p['year']) for p in manifest['partitions']],reverse=True)
        a,b=st.columns(2)
        with a:year=int(select('贸易统计年',years,'graph_year',initial_query('graph_year','2024')))
        with b:
            hs_options=[f'{h:02d}' for h in range(1,98) if h!=77]
            hs2=select('贸易图行业',hs_options,'graph_hs2',initial_query('graph_hs2','85'),format_func=lambda h:f'HS{h} · {HS_CHAPTERS.get(h,"未命名章")}')
        with st.spinner('核验BACI分区并建立同年同业有向图…'):graph=get_graph(year,hs2)
        countries=pd.read_csv(directory/'country_codes.csv').set_index('iso3')['name'].to_dict()
    except (OSError,ValueError,KeyError,TypeError):
        st.warning('贸易图来源为空、缺失或校验失败。当前工具停止；可继续其他研究导航。')
        sync_query(view='intelligence',ai_task=task)
        return
    label=lambda code:'其他亚洲，未另列明（BACI:S19）' if code=='S19' else country_label(code,countries.get(code,code))
    origins=[code for code in graph.nodes if graph.totals[graph.index[code]]>0]
    origin=select('图研究出口国',origins,'graph_country',initial_query('graph_country','CHN'),format_func=label)
    sync_query(view='intelligence',ai_task=task,graph_year=year,graph_hs2=hs2,graph_country=origin)
    scope_id=digest({'graph':graph.snapshot_hash,'origin':origin})
    state=st.session_state.get('graph_applied')
    if not state or state['scope_id']!=scope_id:
        default='USA' if origin!='USA' and 'USA' in graph.index else 'CHN' if 'CHN' in graph.index else graph.nodes[0]
        state={'scope_id':scope_id,'shocks':{default:10.},'alpha':.5}
        st.session_state['graph_applied']=state
    with st.expander('情景假设 · 修改后点击应用',expanded=True):
        chosen=st.multiselect('压力市场（最多5个，可清空）',graph.nodes,default=list(state['shocks']),max_selections=5,format_func=label,key='graph_market_selection_'+scope_id[:12])
        with st.form('graph_scenario_form'):
            proposed={code:st.number_input(f'{label(code)} 假设需求收缩（%）',min_value=0.,max_value=100.,value=state['shocks'].get(code,10.),step=1.,key='graph_pressure_'+scope_id[:12]+code) for code in chosen}
            alpha=st.slider('两跳衰减 α（假设）',0.,1.,float(state['alpha']),.05,key='graph_alpha_'+scope_id[:12])
            applied=st.form_submit_button('应用压力情景',type='primary')
        if applied:
            state={'scope_id':scope_id,'shocks':proposed,'alpha':alpha}
            st.session_state['graph_applied']=state
    analysis=graph.analyze(origin,state['shocks'],state['alpha'])
    st.caption(f"已应用情景：{year} · {label(origin)} · HS{hs2} · "+('，'.join(f'{label(c)} {v:g}%' for c,v in state['shocks'].items()) or '全零压力')+f" · α={state['alpha']:g}。报告绑定此情景；未提交的修改不改变结果。")
    e=analysis['exposure'];c=analysis['concentration']
    a,b,c1,d=st.columns(4)
    a.metric('直接压力指数',f"{e['direct']:.4f}")
    b.metric('两跳关联指数',f"{e['indirect']:.4f}")
    c1.metric('衰减混合指数',f"{e['blended']:.4f}")
    d.metric('伙伴 HHI',f"{c['hhi']:.4f}")
    st.caption(f"分母：{c['partner_count']}个已报告伙伴，出口额{compact_usd(c['export_usd'])}，有效伙伴{c['effective_partners']:.2f}，前五{c['top5_share']:.2%}。当前图{len(graph.nodes)}节点/{len(graph.edges):,}正额边，未使用原ML筛选。")
    if e['two_hop_unreported_onward_mass']>1e-10:
        st.warning(f"两跳无后续报告出口的权重 {e['two_hop_unreported_onward_mass']:.2%}，原样保留而未重新分配；不表示经济真实零出口。")
    st.caption(f"两跳存续质量 {e['two_hop_retained_mass']:.2%}；返回起点路径系数 {e['cycle_return_coefficient']:.4f}。固定两跳，不无限循环传播。")
    tabs=st.tabs(['直接伙伴','两跳路径','假设与敏感性','证据工具问答'],key='trade_graph_tabs')
    with tabs[0]:
        direct=pd.DataFrame(analysis['partners']);top=direct.head(12).iloc[::-1]
        fig=go.Figure(go.Bar(x=top.share,y=top.partner.map(label),orientation='h',marker_color='#146f7c'))
        fig.update_layout(title='已报告同业出口伙伴 · 前12位',xaxis_tickformat='.0%',height=410,margin={'l':10,'r':10,'b':55},xaxis_title='全部行业出口中的份额')
        chart(fig)
        st.caption(f"未展示伙伴份额 {1-float(top.share.sum()):.2%}；完整伙伴见下表与导出。")
        st.dataframe(direct.rename(columns={'partner':'伙伴','trade_usd':'真实出口额（美元）','share':'份额','shock_pct':'假设压力%','direct_contribution':'直接贡献点','onward_reported':'后续同业出口已报告'}),hide_index=True,width='stretch')
    with tabs[1]:
        positive=[p for p in analysis['paths'] if p['indirect_contribution']>0]
        if positive:
            fig,shown=path_figure(analysis['paths'],origin,label);chart(fig)
            st.caption(f"图中为前20条两跳压力贡献，不是美元流分配。已展示{shown:.6f}点，未展示残差{e['indirect']-shown:.6f}点，完整加总{e['indirect']:.6f}点。")
        else:st.info('当前情景无正压力两跳路径；两跳指数为0，不制造不存在的连接。')
        st.dataframe(pd.DataFrame(analysis['paths'][:100])[['via','endpoint','first_share','second_share','coefficient','shock_pct','indirect_contribution']].rename(columns={'via':'中间伙伴','endpoint':'压力端点','first_share':'首段份额','second_share':'次段份额','coefficient':'两跳系数','shock_pct':'假设压力%','indirect_contribution':'两跳贡献点'}) if analysis['paths'] else pd.DataFrame(),hide_index=True,width='stretch')
        st.caption('图中依次为出口国 → 中间伙伴 → 压力端点；短代码对应下表，悬停可看完整名称。')
        st.caption(f"页面表截前100条，完整{len(analysis['paths']):,}条（含零压力路径）在JSON/CSV；各条携带两段真实边ID与金额。")
    with tabs[2]:
        sensitivity=pd.DataFrame(analysis['sensitivity'])
        fig=go.Figure(go.Scatter(x=sensitivity.alpha,y=sensitivity.blended,mode='lines+markers',line={'color':'#b95d42'}))
        fig.update_layout(title='改变两跳衰减的条件压力指数',xaxis_title='假设 α',yaxis_title='混合指数点',height=320,margin={'l':40,'r':10,'b':50})
        chart(fig)
        st.dataframe(pd.DataFrame(analysis['scenario_comparison']).drop(columns='shocks'),hide_index=True,width='stretch')
        st.write('D = W s；I = W² s；混合 = (D + α I)/(1 + α)。未报告后续出口的行全0；分母不改为存续质量。')
        for limit in analysis['limitations']:st.caption(limit)
    with tabs[3]:
        st.caption('问答只核查上方已应用范围与情景；问题中出现新年份/国家/HS章/数值须先显式修改，不会另取数据。离线工具，未调用LLM。')
        with st.form('graph_question_form'):
            question=st.text_input('图研究问题',value='当前图的两跳路径如何分解？',max_chars=400,key='graph_question')
            submitted=st.form_submit_button('核查图问题')
        if submitted:
            st.session_state['graph_answer']={'analysis_id':analysis['analysis_id'],'answer':answer_graph_question(question,graph,analysis)}
        saved=st.session_state.get('graph_answer')
        if saved and saved['analysis_id']==analysis['analysis_id']:
            answer=saved['answer']
            st.caption('本次已核查图问题：'+answer['question'])
            if answer['status']=='answered':st.success(answer['answer'])
            else:st.warning(answer['answer'])
            st.json({'工具':TOOLS.get(answer['tool'],answer['tool']),'数值':answer['numbers'],'范围与情景':answer['trace'],'analysis_id':answer['analysis_id']})
        elif saved:st.info('先前图答案对应另一情景；请重新核查当前问题。')
    saved=st.session_state.get('graph_answer')
    answer=saved['answer'] if saved and saved['analysis_id']==analysis['analysis_id'] else None
    report=make_report(graph,analysis,answer)
    exports=export_graph_report(report)
    st.subheader('核验与导出')
    st.markdown('[CEPII BACI 官方来源](https://www.cepii.fr/CEPII/fr/bdd_modele/bdd_modele_item.asp?id=37) · Etalab 2.0 · Gaulier and Zignago (2010)')
    st.caption('导出含同年同章全图源边、完整路径与已应用假设，可离线重算；哈希不证明来源真实。')
    st.code(report['report_id'],language=None)
    stem=f"trade-graph-{year}-{origin}-HS{hs2}-{report['report_id'][:10]}"
    for label_text,kind,mime in [('下载贸易图报告 HTML','html','text/html'),('下载贸易图证据 JSON','json','application/json'),('下载完整路径 CSV','csv','text/csv')]:
        st.download_button(label_text,exports[kind],file_name=f'{stem}.{kind}',mime=mime,on_click='ignore')
