from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from guanlan.catalog import country_label
from guanlan.panel_ai import TARGET
from guanlan.sector_report import export_bundle, scenario
from guanlan.sector_risk import LABELS, METHODS
from guanlan.trade import HS_CHAPTERS, compact_usd
from .common import ROOT, chart, initial_query, select, sync_query

NAMES={'global_rate':'全样本历史事件率','sector_rate':'同业历史事件率（强基线）',
       'logistic':'逻辑回归对照','joint_hgb':'宏观×网络模型','trade_only_hgb':'仅贸易与集中度（消融）'}


@st.cache_data(show_spinner=False,max_entries=8)
def network_partition(year: int,signature: str):
    directory=ROOT/'data/network'
    meta=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    part=next(p for p in meta['partitions'] if p['year']==year)
    path=directory/part['file']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=part['sha256']:
        raise ValueError('行业网络与来源清单校验不一致')
    return pd.read_parquet(path)


def render(store):
    latest,meta=store.get('sector_latest')
    backtest,back_meta=store.get('sector_backtest')
    if latest.empty or backtest.empty:
        st.info('行业研究快照尚未安装。按 README 运行完整 BACI 网络构建后，可离线开展国家—行业研究。')
        sync_query(view='intelligence',ai_task='宏观与行业风险研究')
        return
    if meta.get('dataset_hash')!=back_meta.get('dataset_hash'):
        raise ValueError('行业估计与评估来自不同数据版本')
    research=back_meta['research']
    reference=research['selected_reference_on_validation']
    st.caption('宏观 × 双边贸易网络 · 国家—HS2行业 · 一年时距 · 有证据的研究与导出')
    st.warning('当前展示2025年待标签核验的历史研究估计，输入来自2024年；不是实时未来预测。BACI 与 WDI 为当前修订历史版，缺少首次公开时点验证。')
    macro,_=store.get('macro',quiet=True)
    names: dict[str,str]=macro.drop_duplicates('country_code').set_index('country_code').country_name.to_dict() if not macro.empty else {}
    countries=sorted(latest.country_code.unique(),key=lambda c:country_label(str(c),names.get(str(c),str(c))))
    a,b=st.columns([1,2])
    with a:
        country=select('行业研究经济体',countries,'sector_country',initial_query('country','CHN'),
                       format_func=lambda c:country_label(str(c),names.get(str(c),str(c))))
    selected=latest.loc[latest.country_code==country].sort_values('sector_rate',ascending=False)
    with b:
        hs2=select('研究行业',selected.hs2.tolist(),'sector_hs2',initial_query('hs2','85'),
                   format_func=lambda h:f'HS{h} · {HS_CHAPTERS.get(h,"未命名章")}')
    row=selected.loc[selected.hs2==hs2].iloc[0]
    sync_query(view='intelligence',ai_task='宏观与行业风险研究',country=country,hs2=hs2)
    scope=backtest.loc[(backtest.country_code==country)&(backtest.hs2==hs2)]
    a,b,c,d=st.columns(4)
    a.metric('默认 · 开发期选定参考',f'{row[reference]:.1%}')
    b.metric('实验 · 宏观网络下行概率',f'{row.joint_hgb:.1%}')
    c.metric('上年行业出口额',compact_usd(row.lag_export_usd))
    d.metric('伙伴 GDP 匹配权重',f'{row.partner_gdp_coverage:.1%}')
    if research['passes_research_gate']:
        st.success('通过预先固定的同业事件率比较门槛。默认参考仍按开发期选择；这不代表领先所有对照或稳定跨期、跨国有效。')
    else:
        st.info('尚未通过固定研究门槛。默认参考按开发期选择；宏观网络模型保留为实验研究结果。')
    st.caption(f'开发期预定规则选定：{NAMES[reference]}。全部对照均保留，未按留出成绩更换推荐。')
    if research['test']['logistic']['brier']<research['test']['joint_hgb']['brier']:
        st.info('强对照核查：逻辑回归在总体留出期的 Brier 更低；宏观网络模型的开发期、未见国家及部分年度消融结果未呈现稳定优势。')
    st.caption(f'最后训练标签 {int(row.train_end)} 年 · {int(row.train_n):,} 个训练样本 · 贸易/宏观年 {int(row.feature_year)} · 本国缺失输入 {int(row.missing_own_features)}/5')
    tabs=st.tabs(['行业证据与情景','验证与解释','研究报告'])
    manifest=ROOT/'data/network/manifest.json'
    network=network_partition(int(row.weight_year),hashlib.sha256(manifest.read_bytes()).hexdigest())
    partners=network.loc[(network.country_code==country)&(network.hs2==hs2),['partner_code','trade_usd']].copy()
    partners['share']=partners.trade_usd/partners.trade_usd.sum()
    partners['伙伴']=partners.partner_code.map(lambda c:country_label(str(c),names.get(str(c),str(c))))
    if not macro.empty:
        gdp=macro.loc[(macro.indicator_code==TARGET)&(macro.year==int(row.macro_year)),['country_code','value']]
        partners=partners.merge(gdp.rename(columns={'country_code':'partner_code','value':'gdp_growth'}),on='partner_code',how='left',validate='one_to_one')
    partners=partners.sort_values('trade_usd',ascending=False)
    with tabs[0]:
        left,right=st.columns([3,2])
        with left:
            top=partners.head(12).iloc[::-1]
            fig=px.bar(top,x='share',y='伙伴',orientation='h',color_discrete_sequence=['#146f7c'])
            fig.update_layout(title=f'{int(row.weight_year)} 年该行业出口伙伴',xaxis_tickformat='.0%',height=430,yaxis_title='',xaxis_title='行业出口权重')
            chart(fig)
        with right:
            st.subheader('伙伴需求条件情景')
            partner=select('设定情景的伙伴',partners.partner_code.tolist(),'sector_partner',partners.partner_code.iloc[0],
                           format_func=lambda c:country_label(str(c),names.get(str(c),str(c))))
            shock=st.slider('该伙伴 GDP 增速冲击（百分点）',-10.,10.,-2.,.5,key='sector_shock')
            shock_result=scenario(partners,{partner:shock})
            st.metric('加权 GDP 冲击暴露',f'{shock_result["weighted_gdp_shock_pp"]:+.3f} 个百分点')
            st.caption(shock_result['limits'])
            st.write(f'伙伴 HHI **{row.partner_hhi:.3f}**；前五伙伴份额 **{row.top5_share:.1%}**。')
            own_gdp='未提供' if pd.isna(row.own_gdp) else f'{row.own_gdp:.2f}%'
            st.write(f'伙伴加权 GDP 增速 **{row.partner_gdp:.2f}%**；本国 GDP **{own_gdp}**。')
        st.dataframe(partners.rename(columns={'share':'份额','trade_usd':'出口金额（美元）','gdp_growth':'同期GDP增速（%）'}),hide_index=True,width='stretch')
        if not scope.empty:
            history=scope[['year','outcome','joint_hgb','sector_rate']]
            fig=go.Figure()
            for key in ['sector_rate','joint_hgb']:
                fig.add_trace(go.Scatter(x=history.year,y=history[key],name=NAMES[key],mode='lines+markers'))
            fig.add_trace(go.Scatter(x=history.year,y=history.outcome,name='实际下行标签',mode='markers',marker={'symbol':'diamond','size':10}))
            fig.update_layout(title='该国家—行业逐年回测',yaxis_tickformat='.0%',xaxis_tickformat='d',height=280)
            chart(fig)
    with tabs[1]:
        st.subheader('全部固定模型 · 同一留出样本')
        metrics=pd.DataFrame([{'方法':NAMES[m],**research['test'][m]} for m in METHODS]).rename(columns={'n':'样本数','events':'下行事件数','event_rate':'实际下行比例','brier':'Brier','log_loss':'对数损失','roc_auc':'ROC-AUC','average_precision':'平均精确率'})
        st.dataframe(metrics,hide_index=True,width='stretch')
        lo,hi=research['paired_country_brier_difference_95']
        st.caption(f'宏观网络模型减同业基线 Brier 的国家整组抽样95%区间 [{lo:.6f}, {hi:.6f}]；负值表示模型误差较低。共 {research["test_countries"]} 个国家、{research["test_hs2"]} 个行业。')
        left,right=st.columns(2)
        with left:
            fig=go.Figure(go.Scatter(x=[0,1],y=[0,1],mode='lines',name='理想校准',line={'dash':'dot'}))
            for method in ['sector_rate','joint_hgb','trade_only_hgb']:
                table=pd.DataFrame(research['calibration'][method]);table=table.loc[table.n>0]
                fig.add_trace(go.Scatter(x=table.mean_prediction,y=table.event_rate,mode='lines+markers',name=NAMES[method],text=table.n,hovertemplate='%{x:.3f} / %{y:.3f}<br>样本 %{text}'))
            fig.update_layout(title='概率可靠性 · 10个固定等宽分箱',xaxis_title='平均预测概率',yaxis_title='实际下行比例',height=350,legend={'orientation':'h','y':-.3})
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
    with tabs[2]:
        st.subheader('当前国家—行业证据包')
        st.write(f'**{country_label(country,names.get(country,country))} · HS{hs2} {HS_CHAPTERS.get(hs2,"")}**')
        st.caption('HTML 报告可离线打开；JSON 保存参数、数据指纹、来源、训练边界与情景；CSV 为当前估计原值。')
        bundle=export_bundle(row.to_dict(),partners,scope,research,shock_result)
        for kind,label in [('html','下载研究报告 HTML'),('json','下载证据与协议 JSON'),('csv','下载当前估计 CSV')]:
            st.download_button(label,bundle[kind],file_name=f'guanlan-sector-{country}-{hs2}-2025.{kind}',
                               mime={'html':'text/html','json':'application/json','csv':'text/csv'}[kind],key=f'sector_export_{kind}')
        st.code(research['dataset_hash'],language=None)
        st.markdown('[CEPII BACI 数据与许可](https://www.cepii.fr/CEPII/fr/bdd_modele/bdd_modele_item.asp?id=37) · [世界银行 WDI](https://data.worldbank.org/)')
