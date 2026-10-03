import plotly.express as px
import pandas as pd
import streamlit as st
from guanlan.catalog import country_label
from guanlan.financial import period_comparison, eer_with_12m_change
from guanlan.bis import BIS_POLICY_PAGE, BIS_CREDIT_PAGE, BIS_EER_PAGE
from .common import (header, radio, initial_query, multi, query_list, select, source_line,
                     chart, color_for, number, download, sync_query)


def render(store):
    header("金融条件", "按月度或季度对齐政策利率、信贷及有效汇率")
    topic=radio("金融专题",["政策利率","信贷与GDP","有效汇率"],"financial_topic",initial_query("financial_topic","政策利率"))
    stem={"政策利率":"bis_policy","信贷与GDP":"bis_credit","有效汇率":"bis_eer"}[topic]
    frame,meta=store.get(stem)
    if frame.empty:
        sync_query(view="financial",financial_topic=topic)
        return
    names=frame.drop_duplicates("country_code").set_index("country_code").country_name.to_dict()
    options=sorted(names,key=lambda c:country_label(c,names[c]))
    label=lambda c: "欧元区（XEA · 区域汇总）" if c=="XEA" else country_label(c,names[c])
    peerkey="eer_peer_selection" if topic=="有效汇率" else f"financial_{stem}_peers"
    querykey="eerpeers" if topic=="有效汇率" else "finpeers"
    peers=multi("对照经济体或区域（最多 6 个）",options,peerkey,query_list(querykey,options,["CHN","USA","DEU","JPN","IND"]),format_func=label)
    a,b,c=st.columns([1.4,1,1])
    with a:
        mode=select("数值比较方式",["同一期比较","各经济体最新可得值"],f"{stem}_mode",initial_query("finmode","同一期比较"))
    dates=sorted(frame.date.unique(),reverse=True)
    default_date=pd.Timestamp(dates[0])
    requested=initial_query("finperiod","")
    if requested:
        try:
            candidate=pd.Timestamp(requested)
            if candidate in dates:
                default_date=candidate
        except ValueError:
            pass
    elif initial_query("year").isdigit():
        in_year=[d for d in dates if pd.Timestamp(d).year==int(initial_query("year"))]
        if in_year:
            default_date=pd.Timestamp(in_year[0])
    with b:
        cutoff=select("比较期" if mode=="同一期比较" else "截至期",[pd.Timestamp(d) for d in dates],f"{stem}_period",default_date,
                      format_func=lambda d:f"{d.year}-Q{d.quarter}" if topic=="信贷与GDP" else d.strftime("%Y-%m"))
    with c:
        lookback=select("历史区间",[5,10,20],f"{stem}_lookback",10,format_func=lambda n:f"近 {n} 年")
    source_line(meta, f"{'季度' if topic=='信贷与GDP' else '月度'} · 截至 {cutoff.strftime('%Y-%m')}")
    if not peers:
        return
    chosen=frame.copy()
    measure=None
    unit="年利率（%）"
    if topic=="信贷与GDP":
        measures={"信贷/GDP 缺口":"gap","实际信贷/GDP":"ratio","BIS 单边趋势":"trend"}
        measure_label=radio("信贷指标",list(measures),"credit_measure",
                            next((k for k,v in measures.items() if v==initial_query("credit_measure","gap")),list(measures)[0]))
        measure=measures[measure_label]
        captions={"gap":"信贷/GDP 缺口（百分点）","ratio":"私人非金融部门信贷/GDP（%）","trend":"BIS 单边趋势（%）"}
        st.markdown(f"**{captions[measure]}**")
        chosen=frame.loc[frame.measure==measure].copy()
        unit="百分点" if measure=="gap" else "占 GDP（%）"
    elif topic=="有效汇率":
        measure=radio("有效汇率类型",["实际有效汇率（REER）","名义有效汇率（NEER）"],"eer_measure_selection",
                      "名义有效汇率（NEER）" if initial_query("eertype")=="nominal" else "实际有效汇率（REER）")
        measure="real" if measure.startswith("实际") else "nominal"
        chosen=eer_with_12m_change(frame,peers)
        chosen=chosen.loc[chosen.measure==measure].copy()
        chosen["index_value"]=chosen.value
        chosen["value"]=chosen.change_12m_pct
        unit="12 个月变化（%）"
    history=chosen.loc[chosen.country_code.isin(peers)&(chosen.date<=cutoff)&
                       (chosen.date>=cutoff-pd.DateOffset(years=lookback))].copy()
    history["经济体"]=history.country_code.map(label)
    fig=px.line(history,x="date",y="value",color="经济体",color_discrete_map={label(c):color_for(c) for c in peers},
                title=f"{topic} · {unit}")
    fig.update_traces(connectgaps=False,line_width=2.5)
    fig.update_layout(height=350,xaxis_title="",yaxis_title=unit,legend=dict(orientation="h",y=-.2,title_text=""),
                      margin=dict(l=25,r=20,t=50,b=70),hovermode="x unified")
    chart(fig)
    latest=period_comparison(chosen,peers,cutoff,"common" if mode=="同一期比较" else "latest")
    display=[]
    for row in latest.itertuples():
        period=(f"{row.date.year}-Q{row.date.quarter}" if topic=="信贷与GDP" else row.date.strftime("%Y-%m")) if pd.notna(row.date) else "本期无记录"
        state="有效观测"
        if pd.isna(row.value):
            state="来源标记缺失" if row.obs_status=="M" else "本期无有效值"
            if topic=="政策利率" and row.country_code=="DEU":
                state="国家序列止于 1998-12；本快照未加载欧元区政策序列"
        elif mode!="同一期比较" and row.date<cutoff:
            state="最近有效期早于截至期"
        if topic=="政策利率" and row.country_code=="DEU" and pd.notna(row.last_record_date) and row.last_record_date.year<1999:
            state="国家序列止于 1998-12；本快照未加载欧元区政策序列"
        display.append({"经济体":label(row.country_code),"实际观察期":period,"数值":number(row.value),"状态":state})
    st.markdown(f"**{mode}**")
    st.dataframe(pd.DataFrame(display),hide_index=True,width="stretch")
    st.caption("同一期模式不借用其他期；最新可得值模式允许更早的有效观测，实际观察期随数值列出。")
    if topic=="有效汇率":
        st.caption("指数基期 2020=100；升高表示升值。主表展示当前选择的 12 个月变化，不按跨国指数水平排序。")
        with st.expander("查看当前选择的指数水平"):
            index_selected=period_comparison(frame.loc[frame.measure==measure],peers,cutoff,"common" if mode=="同一期比较" else "latest")
            index_selected["经济体"]=index_selected.country_code.map(label)
            index_selected["观察月"]=index_selected.date.dt.strftime("%Y-%m").fillna("本期无记录")
            index_selected["指数"]=index_selected.value.map(number)
            st.dataframe(index_selected[["经济体","观察月","指数"]],hide_index=True,width="stretch")
    download(history,f"guanlan_{stem}_{cutoff.strftime('%Y%m')}_{measure or 'policy'}_history.csv","下载当前历史序列 · CSV",meta)
    download(latest,f"guanlan_{stem}_{cutoff.strftime('%Y%m')}_{measure or 'policy'}_comparison.csv","下载当前比较期数据 · CSV",meta)
    with st.expander("查看序列口径与原始状态"):
        if topic=="政策利率":
            st.write("月度值为当月最后营业日；不同经济体使用不同政策工具，历史序列可能拼接。国家序列与货币区序列不会静默替代。")
            for code in peers:
                areas=frame.loc[frame.country_code==code,"bis_area_code"].unique()
                note=meta.get("country_series_notes",{}).get(areas[0],{}) if len(areas) else {}
                st.markdown(f"**{label(code)}**：{note.get('compilation') or '来源未提供编制说明。'}")
            url=BIS_POLICY_PAGE
        elif topic=="信贷与GDP":
            st.write("私人非金融部门、全部放贷部门。缺口=实际信贷/GDP−BIS 单边 HP 趋势；比率、趋势和缺口为同季度记录。")
            url=BIS_CREDIT_PAGE
        else:
            st.write("月度宽口径贸易权重；实际指数经相对 CPI 调整。12 个月变化要求同序列恰好前 12 个日历月有值。")
            url=BIS_EER_PAGE
        st.markdown(f"[BIS 原始数据与方法]({url})")
        st.dataframe(latest,hide_index=True,width="stretch")
    sync_query(view="financial",financial_topic=topic,finmode=mode,finperiod=cutoff.strftime("%Y-%m-%d"),
               **{querykey:",".join(peers)},eertype=measure if topic=="有效汇率" else None,
               credit_measure=measure if topic=="信贷与GDP" else None)
