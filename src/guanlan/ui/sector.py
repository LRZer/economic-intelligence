from __future__ import annotations

import hashlib
import html
import json

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from guanlan.catalog import country_label
from guanlan.panel_ai import TARGET
from guanlan.sector_analysis import (cohort_for_year, comparison_frame, feature_peer_profile,
    historical_event_context, validate_context, validate_partner_evidence)
from guanlan.sector_report import clean_records, export_bundle, scenario
from guanlan.sector_risk import LABELS, METHODS
from guanlan.trade import HS_CHAPTERS, compact_usd
from .common import ROOT, chart, initial_query, radio, select, sync_query

NAMES={'global_rate':'全样本历史事件率','sector_rate':'同业历史事件率（强基线）',
       'logistic':'逻辑回归对照','joint_hgb':'宏观×网络模型','trade_only_hgb':'仅贸易与集中度（消融）'}


@st.cache_data(show_spinner=False,max_entries=8)
def network_partition(year: int,signature: str):
    directory=ROOT/'data/network'
    meta=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    part=next(p for p in meta['partitions'] if p['year']==year)
    path=directory/part['file']
    if path.name!=f'sector_partner_{year}.parquet' or path.parent.resolve()!=directory.resolve():
        raise ValueError('网络清单路径不在当前数据目录内')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=part['sha256']:
        raise ValueError('行业网络与来源清单校验不一致')
    return pd.read_parquet(path)


def render(store):
    with st.spinner('读取并核对固定研究快照…'):
        latest,meta=store.get('sector_latest')
        backtest,back_meta=store.get('sector_backtest')
        features,feature_meta=store.get('sector_features')
    if backtest.empty or features.empty:
        st.info('行业研究快照尚未安装。按 README 运行完整 BACI 网络构建后，可离线开展国家—行业研究。')
        sync_query(view='intelligence',ai_task='宏观与行业风险研究')
        return
    versions=[back_meta.get('dataset_hash'),feature_meta.get('dataset_hash')]
    if not latest.empty:versions.append(meta.get('dataset_hash'))
    if len(set(versions))!=1 or not versions[0]:
        raise ValueError('行业估计、评估与特征来自不同数据版本')
    research=back_meta['research']
    reference=research['selected_reference_on_validation']
    available=pd.concat([frame.year for frame in [latest,backtest] if not frame.empty])
    years=sorted({str(int(y)) for y in available if y>=2023},reverse=True)
    pending=set() if latest.empty else set(latest.year.astype(str))
    if latest.empty:st.info('待核验年度快照不可用；仍可查看已验证的历史留出年份。')
    macro,_=store.get('macro')
    if macro.empty:
        st.info('世界银行快照不可用，无法核对伙伴宏观证据。其他研究模块仍可使用。')
        return
    names: dict[str,str]=macro.drop_duplicates('country_code').set_index('country_code').country_name.to_dict()
    a,b,c=st.columns([1,2,2])
    with a:
        year=int(select('研究目标年',years,'sector_year',initial_query('sector_year','2025'),
                        format_func=lambda y:y+(' · 待核验' if y in pending else ' · 历史留出')))
    cohort=cohort_for_year(latest,backtest,year)
    countries=sorted(cohort.country_code.unique(),key=lambda v:country_label(str(v),names.get(str(v),str(v))))
    with b:
        country=select('行业研究经济体',countries,'sector_country',initial_query('country','CHN'),
                       format_func=lambda v:country_label(str(v),names.get(str(v),str(v))))
    selected=cohort.loc[cohort.country_code==country].sort_values('hs2')
    with c:
        hs2=select('研究行业',selected.hs2.tolist(),'sector_hs2',initial_query('hs2','85'),
                   format_func=lambda h:f'HS{h} · {HS_CHAPTERS.get(h,"未命名章")}')
    row=selected.loc[selected.hs2==hs2].iloc[0]
    sync_query(view='intelligence',ai_task='宏观与行业风险研究',country=country,hs2=hs2,sector_year=year)
    scope=backtest.loc[(backtest.country_code==country)&(backtest.hs2==hs2)&(backtest.year<=year)]
    outcome='标签尚待核验' if pd.isna(row.outcome) else ('实际下行≥10%' if row.outcome==1 else '实际未下行≥10%')
    st.caption(f'{year} 年历史研究 · {outcome} · 输入期别 {int(row.feature_year)} 年 · 最后训练标签 {int(row.train_end)} 年（{int(row.train_n):,}样本） · BACI HS17 V202601 / 固定 WDI')
    values=[('默认 · 开发期选定参考',f'{row[reference]:.1%}'),('实验 · 宏观网络下行概率',f'{row.joint_hgb:.1%}'),
            ('上年行业出口额',compact_usd(row.lag_export_usd)),('伙伴 GDP 匹配权重',f'{row.partner_gdp_coverage:.1%}')]
    st.markdown('<div class="research-stats">'+''.join(f'<div><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>' for label,value in values)+'</div>',unsafe_allow_html=True)
    gate='通过固定同业比较门槛' if research['passes_research_gate'] else '未通过固定同业比较门槛'
    st.caption(f'{gate}；逻辑回归总体留出 Brier 更低，跨期及未见国家优势不足。默认仍为开发期选定的{NAMES[reference]}，没有按留出成绩切换。')
    with st.expander('数据时点、模型局限与使用边界'):
        st.write('BACI 与 WDI 为当前修订历史版，缺少首次公开版本。目标年选择用于回顾固定研究估计，不代表在当年实时可得。完整协议的总体评估可能包含所选年之后的留出结果，仅作回顾诊断，不进入该年训练。')
        st.write(f'本国宏观输入缺失 {int(row.missing_own_features)}/5；GDP未匹配的伙伴不填零。模型为实验研究估计，条件冲击不改变模型概率，不用于推导因果出口损失或投资收益。')
        if bool(row.get('target_sector_unreported',False)):
            st.write('本年行业流未在 BACI 报告；标签的零金额不代表确认的真实经济零值。')
    tabs=st.tabs(['行业证据与情景','同组对照','验证与解释','研究报告'],key='sector_sections',on_change='rerun')
    manifest=ROOT/'data/network/manifest.json'
    network=network_partition(int(row.weight_year),hashlib.sha256(manifest.read_bytes()).hexdigest())
    partners=network.loc[(network.country_code==country)&(network.hs2==hs2),['partner_code','trade_usd']].copy()
    partners['share']=partners.trade_usd/partners.trade_usd.sum()
    partners['伙伴']=partners.partner_code.map(lambda v:country_label(str(v),names.get(str(v),str(v))))
    gdp=macro.loc[(macro.indicator_code==TARGET)&(macro.year==int(row.macro_year)),['country_code','value']]
    partners=partners.merge(gdp.rename(columns={'country_code':'partner_code','value':'gdp_growth'}),on='partner_code',how='left',validate='one_to_one').sort_values('trade_usd',ascending=False)
    validate_partner_evidence(row.to_dict(),partners)
    incidence=historical_event_context(features,hs2,year)
    with tabs[0]:
        left,right=st.columns([3,2])
        with left:
            top=partners.head(12).iloc[::-1]
            fig=px.bar(top,x='share',y='伙伴',orientation='h',color_discrete_sequence=['#146f7c'])
            fig.update_layout(title=f'{int(row.weight_year)} 年该行业出口伙伴',xaxis_tickformat='.0%',height=390,yaxis_title='',xaxis_title='行业出口权重')
            chart(fig)
        with right:
            st.subheader('伙伴需求条件情景')
            partner=select('设定情景的伙伴',partners.partner_code.tolist(),'sector_partner',partners.partner_code.iloc[0],
                           format_func=lambda v:country_label(str(v),names.get(str(v),str(v))))
            shock=st.slider('该伙伴 GDP 增速冲击（百分点）',-10.,10.,-2.,.5,key='sector_shock')
            shock_result=scenario(partners,{partner:shock})
            st.metric('加权 GDP 冲击暴露',f'{shock_result["weighted_gdp_shock_pp"]:+.3f} 个百分点')
            st.caption(shock_result['limits'])
            own='未提供' if pd.isna(row.own_gdp) else f'{row.own_gdp:.2f}%'
            st.write(f'伙伴 HHI **{row.partner_hhi:.3f}** · 前五份额 **{row.top5_share:.1%}**')
            st.write(f'伙伴加权 GDP **{row.partner_gdp:.2f}%** · 本国 GDP **{own}**')
        displayed=partners[['伙伴','partner_code','trade_usd','share','gdp_growth']].copy()
        displayed['trade_usd']=displayed.trade_usd.map(lambda v:f'{v/1e9:,.3f}')
        displayed['share']=displayed['share'].map(lambda v:f'{v:.2%}')
        displayed['gdp_growth']=displayed.gdp_growth.map(lambda v:'未匹配' if pd.isna(v) else f'{v:.2f}')
        st.dataframe(displayed.rename(columns={'partner_code':'代码','trade_usd':'出口额（十亿美元）','share':'份额','gdp_growth':'GDP增速（%）'}),hide_index=True,width='stretch')
        if not scope.empty:
            fig=go.Figure()
            for key in ['sector_rate','logistic','joint_hgb']:
                fig.add_trace(go.Scatter(x=scope.year,y=scope[key],name={'sector_rate':'同行率','logistic':'逻辑回归','joint_hgb':'宏观网络（实验）'}[key],mode='lines+markers'))
            fig.add_trace(go.Scatter(x=scope.year,y=scope.outcome,name='实际下行标签',mode='markers',marker={'symbol':'diamond','size':10,'color':'#172d3b'}))
            fig.update_layout(title='同一国家—行业历史估计与实际标签',yaxis_tickformat='.0%',xaxis_tickformat='d',height=300,legend={'orientation':'h','y':-.25},margin={'b':85})
            chart(fig)
    with tabs[1]:
        lens_label=radio('对照范围',['同一国家 · 跨行业','同一行业 · 跨国家'],'sector_lens','同一国家 · 跨行业')
        lens='country' if lens_label.startswith('同一国家') else 'industry'
        peers=comparison_frame(cohort,country,hs2,lens)
        peers['对象']=peers.hs2.map(lambda h:f'HS{h} {HS_CHAPTERS.get(h,"")}') if lens=='country' else peers.country_code.map(lambda v:country_label(str(v),names.get(str(v),str(v))))
        view=peers.assign(export_bn=peers.lag_export_usd/1e9)
        fig=px.scatter(view,x='export_bn',y='joint_hgb',hover_name='对象',color='selected',symbol='selected',
                       color_discrete_map={False:'#597887',True:'#b65c3b'},symbol_map={False:'circle',True:'diamond'},
                       hover_data={'sector_rate':':.2%','logistic':':.2%','partner_hhi':':.3f','selected':False},labels={'sector_rate':'同行率','logistic':'逻辑回归','partner_hhi':'伙伴HHI','export_bn':'出口额（十亿美元）','joint_hgb':'实验概率'},log_x=True)
        fig.update_traces(marker_size=9,marker_line_width=1)
        fig.update_layout(title=f'{year} 年同组规模与实验风险 · {len(peers)}个对象',xaxis_title='上年行业出口额（十亿美元，对数）',yaxis_title='宏观网络实验概率',yaxis_tickformat='.0%',showlegend=False,height=340,margin={'t':50,'b':60})
        chart(fig)
        st.caption('橙色菱形为当前选择，灰蓝圆点为同组对象；所有符合固定规则的对象保留，未按留出成绩筛选。规模只覆盖合格研究样本，不能当作全国全行业或世界总出口。')
        table=peers[['对象','lag_export_usd','sector_rate','logistic','joint_hgb','model_disagreement_pp','partner_gdp','partner_hhi','partner_gdp_coverage','missing_own_features']].copy()
        table['lag_export_usd']=table.lag_export_usd.map(lambda v:f'{v/1e9:,.3f}')
        for field in ['sector_rate','logistic','joint_hgb','partner_gdp_coverage']:table[field]=table[field].map(lambda v:f'{v:.2%}')
        st.dataframe(table.rename(columns={'lag_export_usd':'出口额（十亿美元）','sector_rate':'同行率','logistic':'逻辑回归','joint_hgb':'宏观网络','model_disagreement_pp':'网络减逻辑回归（百分点）','partner_gdp':'伙伴GDP（%）','partner_hhi':'HHI','partner_gdp_coverage':'GDP匹配','missing_own_features':'缺失本国输入'}),hide_index=True,width='stretch')
        profile=feature_peer_profile(row.to_dict(),peers)
        shown=profile.copy();shown['feature']=shown.feature.map(LABELS)
        shown['midrank_percentile']=shown.midrank_percentile.map(lambda v:'未提供' if pd.isna(v) else f'{v:.0%}')
        st.subheader('当前输入与同组分布')
        st.dataframe(shown.rename(columns={'feature':'输入','unit':'单位','selected_value':'当前原值','peer_median':'同组中位数','midrank_percentile':'同组分位','n_non_missing':'有效样本数','peer_constant':'同组值相同'}),hide_index=True,width='stretch')
        st.caption('分位采用相同年输入的并列中位排序；同国宏观值可能全部相同。该表是证据对照，不能解释为模型加性贡献或因果效应。上期增长为比值，宏观指标为原始百分比单位。')
        low,high=incidence['historical_event_rate_cluster_interval_95'] or [np.nan,np.nan]
        st.write(f'截至 {incidence["last_label_year"]} 年，HS{hs2}训练历史包含 **{incidence["n"]:,}** 条、**{incidence["countries"]}** 个国家，实际事件率 **{incidence["event_rate"]:.1%}**，按国家整组抽样95%区间 **[{low:.1%}, {high:.1%}]**。')
        st.caption(incidence['limits'])
        analysis={'country_code':country,'hs2':hs2,'target_year':year,'lens':lens,'peer_count':len(peers),
                  'peers':clean_records(peers.drop(columns='对象')),'feature_profile':clean_records(profile),'training_event_context':incidence,
                  'limits':'同年固定输入与实验估计对照；不是因果贡献、投资排序或个体预测置信区间。'}
        validate_context(analysis,row.to_dict())
    with tabs[2]:
        render_validation(research)
    with tabs[3]:
        st.subheader('当前国家—行业证据包')
        st.write(f'**{country_label(country,names.get(country,country))} · HS{hs2} {HS_CHAPTERS.get(hs2,"")} · {year}年**')
        st.caption('报告包含当前年份、同组范围、训练期发生率区间、原始输入和伙伴情景；可离线复核。')
        bundle=export_bundle(row.to_dict(),partners,scope,research,shock_result,analysis)
        for kind,label in [('html','下载研究报告 HTML'),('json','下载证据与协议 JSON'),('csv','下载当前估计 CSV')]:
            st.download_button(label,bundle[kind],file_name=f'guanlan-sector-{country}-{hs2}-{year}.{kind}',
                               mime={'html':'text/html','json':'application/json','csv':'text/csv'}[kind],key=f'sector_export_{kind}',on_click='ignore')
        st.code(research['dataset_hash'],language=None)
        st.markdown('[CEPII BACI 数据与许可](https://www.cepii.fr/CEPII/fr/bdd_modele/bdd_modele_item.asp?id=37) · [世界银行 WDI](https://data.worldbank.org/)')


def render_validation(research):
    st.subheader('完整固定协议 · 2023—2024同一留出样本')
    st.caption('总体结果用于完整协议的回顾诊断；即使选择2023年，也不将2024年结果作为该年模型输入或重新选择参考。')
    metrics=pd.DataFrame([{'方法':NAMES[m],**research['test'][m]} for m in METHODS]).rename(columns={'n':'样本数','events':'下行事件数','event_rate':'实际下行比例','brier':'Brier','log_loss':'对数损失','roc_auc':'ROC-AUC','average_precision':'平均精确率'})
    st.dataframe(metrics,hide_index=True,width='stretch')
    lo,hi=research['paired_country_brier_difference_95']
    st.caption(f'宏观网络模型减同业基线 Brier 的国家整组抽样95%区间 [{lo:.6f}, {hi:.6f}]；负值表示模型误差较低。共 {research["test_countries"]} 个国家、{research["test_hs2"]} 个行业。')
    left,right=st.columns(2)
    with left:
        fig=go.Figure(go.Scatter(x=[0,1],y=[0,1],mode='lines',name='理想校准',line={'dash':'dot','color':'#8a969e'}))
        styles={'sector_rate':('#597887','square','dash'),'joint_hgb':('#146f7c','circle','solid'),'trade_only_hgb':('#b65c3b','diamond','dot')}
        for method in ['sector_rate','joint_hgb','trade_only_hgb']:
            table=pd.DataFrame(research['calibration'][method]);table=table.loc[table.n>0]
            color,symbol,dash=styles[method]
            fig.add_trace(go.Scatter(x=table.mean_prediction,y=table.event_rate,mode='lines+markers',name=NAMES[method],line={'color':color,'dash':dash},marker={'symbol':symbol},text=table.n,hovertemplate='%{x:.3f} / %{y:.3f}<br>样本 %{text}'))
        fig.update_layout(title='概率可靠性 · 10个固定等宽分箱',xaxis_title='平均预测概率',yaxis_title='实际下行比例',height=350,legend={'orientation':'h','y':-.3},margin={'b':95})
        chart(fig)
    with right:
        importance=pd.DataFrame({'feature':list(research['development_feature_importance']),
                                 'importance':list(research['development_feature_importance'].values())}).sort_values('importance')
        importance['feature']=importance.feature.map(LABELS)
        fig=px.bar(importance,x='importance',y='feature',orientation='h',color_discrete_sequence=['#146f7c'])
        fig.update_layout(title='2022开发数据 · 置换关联重要性',height=350,yaxis_title='',xaxis_title='置换增加的 Brier')
        chart(fig)
    st.caption('解释在开发数据计算，不能视为因果贡献。所有模型参数固定；概率未使用留出数据重校准。')
    with st.expander('逐年度、国家、行业与数据质量全量诊断'):
        st.json({k:research[k] for k in ['yearly_metrics','unseen_country_development_2022','quality'] if k in research})
        st.dataframe(pd.DataFrame([{'国家':c,'方法':NAMES[m],**values[m]} for c,values in research['country_slices'].items() for m in METHODS]),hide_index=True)
        st.dataframe(pd.DataFrame([{'HS2':c,'方法':NAMES[m],**values[m]} for c,values in research['industry_slices'].items() for m in METHODS]),hide_index=True)
