import plotly.express as px
import pandas as pd
import streamlit as st
from guanlan.catalog import country_label
from guanlan.analytics import trade_partner_table, trade_concentration
from guanlan.trade import annual_trade_totals, chapter_profile, compact_usd
from .common import (header, initial_query, select, source_line, color_for, chart,
                     download, radio, sync_query, source_details)


def render(store):
    header("贸易结构", "货物贸易规模、伙伴分布与商品结构")
    frame,meta=store.trade()
    if frame.empty:
        sync_query(view="trade")
        return
    names=frame.drop_duplicates("reporter_code").set_index("reporter_code").reporter_name.to_dict()
    options=sorted(names,key=lambda c:country_label(c,names[c]))
    inherited=st.session_state.get("research_selection",{})
    country_default=inherited.get("country",initial_query("country","CHN"))
    if "saved_trade_country" not in st.session_state and country_default not in options:
        fallback="CHN" if "CHN" in options else options[0]
        st.info(f"{country_label(country_default)}不在当前贸易快照中。当前选择 {country_label(fallback,names[fallback])}。")
        country_default=fallback
    a,b=st.columns([2,1])
    with a:
        country=select("报告经济体",options,"trade_country",country_default,
                       format_func=lambda c:country_label(c,names[c]))
    years=sorted(map(int,frame.loc[frame.reporter_code==country,"year"].unique()),reverse=True)
    year_default=inherited.get("year",int(initial_query("year","2024"))) if initial_query("year","2024").isdigit() else years[0]
    if "saved_trade_year" not in st.session_state and year_default not in years:
        st.info(f"贸易快照不包含 {year_default} 年，当前使用 {years[0]} 年。未借用该年度的数据计算原研究年度的贸易值。")
    with b:
        year=select("贸易年度",years,"trade_year",year_default)
    st.session_state["research_selection"]={"country":country,"year":year}
    is_baci=meta.get("provider")=="CEPII BACI"
    source_line(meta,f"{meta.get('revision','全部商品')} · V{meta.get('release','公开样本')} · {year} 年货物贸易")
    if not is_baci:
        st.warning("当前为 Comtrade 指定报告国的公开预览样本，覆盖有限。")
    timeline=annual_trade_totals(frame,country)
    current=timeline.loc[timeline.year==year].iloc[0]
    a,b,c=st.columns(3)
    a.metric("货物出口额 · 美元",compact_usd(current.exports_usd))
    b.metric("货物进口额 · 美元",compact_usd(current.imports_usd))
    c.metric("货物贸易差额 · 美元",compact_usd(current.balance_usd,signed=True))
    with st.expander("查看历年进出口总额"):
        series=timeline.melt(id_vars="year",value_vars=["exports_usd","imports_usd"],var_name="flow",value_name="value")
        series["十亿美元"]=series.value/1e9
        series["流向"]=series.flow.map({"exports_usd":"出口","imports_usd":"进口"})
        fig=px.line(series,x="year",y="十亿美元",color="流向",markers=True,
                    color_discrete_map={"出口":color_for("exports_usd"),"进口":color_for("imports_usd")})
        fig.update_layout(height=260,xaxis_title="",legend_title_text="",margin=dict(l=20,r=20,t=25,b=40))
        fig.update_xaxes(tickformat="d")
        chart(fig)
        st.caption("总额与本图始终同时包含进出口；下方流向只控制伙伴及商品分析。")
        download(timeline,f"guanlan_trade_totals_{country}.csv","下载进出口总额 · CSV",meta)
    st.subheader("伙伴与商品分析")
    flow_col,topic_col=st.columns([1,2])
    with flow_col:
        flow_name=radio("分析流向（伙伴与商品）",["出口","进口"],"trade_flow",initial_query("flow","出口"))
    flow="X" if flow_name=="出口" else "M"
    with topic_col:
        topic=radio("贸易分析视图",["伙伴分布","商品结构"] if is_baci else ["伙伴分布"],"trade_topic",initial_query("trade_topic","伙伴分布"))
    st.caption("以上年度总额包含进出口；此流向选择只控制下面的伙伴和商品。")
    sync_query(view="trade",country=country,year=year,flow=flow_name,trade_topic=topic)
    if topic=="伙伴分布":
        partners=trade_partner_table(frame,country,year,flow)
        concentration=trade_concentration(partners)
        if concentration is None:
            st.info("此经济体、年度与流向没有可用伙伴记录。")
            return
        st.markdown(f"**{flow_name}前五伙伴占比 {concentration['top5_share']:.1%}** · 有效伙伴 {concentration['partner_count']} 个")
        shown=partners.head(10).copy()
        shown["伙伴"]=shown.apply(lambda r:country_label(r.partner_code,r.partner_name),axis=1)
        shown["十亿美元"]=shown.trade_usd/1e9
        fig=px.bar(shown.iloc[::-1],x="十亿美元",y="伙伴",orientation="h",text="share",color_discrete_sequence=["#146f7c"],
                   title=f"{year} 年{flow_name}伙伴 · 前 10")
        fig.update_traces(texttemplate="%{text:.1%}",textposition="outside",cliponaxis=False)
        fig.update_layout(height=400,yaxis_title="",margin=dict(l=10,r=55,t=50,b=35))
        chart(fig)
        with st.expander("查看伙伴原值与集中度"):
            st.caption(f"伙伴 HHI {concentration['hhi']:.3f}，按伙伴贸易份额平方和计算，范围 0—1。")
            table=partners.copy()
            table["伙伴"]=table.apply(lambda r:country_label(r.partner_code,r.partner_name),axis=1)
            table["金额（十亿美元）"]=table.trade_usd/1e9
            table["份额（%）"]=table.share*100
            st.dataframe(table[["伙伴","金额（十亿美元）","份额（%）"]].round(2),hide_index=True,width="stretch")
        with st.expander("查看伙伴地图"):
            mapped=partners.copy()
            mapped["伙伴"]=mapped.apply(lambda r:country_label(r.partner_code,r.partner_name),axis=1)
            fig=px.choropleth(mapped,locations="partner_code",color="trade_usd",hover_name="伙伴",projection="natural earth",
                             color_continuous_scale=["#e6efed","#72aaa6","#206a65"])
            fig.update_layout(height=330,margin=dict(l=10,r=10,t=10,b=10),coloraxis_colorbar_title="美元")
            fig.update_geos(showframe=False)
            chart(fig)
        download(partners,f"guanlan_partner_{country}_{year}_{flow}.csv","下载当前伙伴数据 · CSV",meta)
    else:
        chapters,chapter_meta=store.get("baci_chapter")
        if chapters.empty:
            return
        if meta.get("build_id")!=chapter_meta.get("build_id"):
            raise ValueError("伙伴与商品快照版本不一致")
        profile=chapter_profile(chapters,country,year,flow)
        if profile.empty:
            st.info("本期无商品章记录。")
            return
        top=profile.head(10).copy()
        top["商品章"]="HS "+top.hs2+" · "+top.chapter
        top["十亿美元"]=top.trade_usd/1e9
        fig=px.bar(top.iloc[::-1],x="十亿美元",y="商品章",orientation="h",color_discrete_sequence=["#146f7c"])
        fig.update_layout(height=425,yaxis_title="",margin=dict(l=15,r=20,t=25,b=40))
        chart(fig)
        table=pd.DataFrame({"HS2":profile.hs2,"商品章":profile.chapter,"金额（十亿美元）":profile.trade_usd/1e9,
                            "份额（%）":profile.share*100})
        if flow=="X":
            table["RCA"]=profile.rca
        with st.expander("查看全部商品章原值"):
            st.dataframe(table.round(2),hide_index=True,width="stretch")
        st.caption("RCA 仅对出口计算，是本国商品章出口份额与全球同章出口份额之比，不代表投资回报。")
        download(profile,f"guanlan_hs2_{country}_{year}_{flow}.csv","下载当前商品结构 · CSV",chapter_meta)
    st.caption("BACI 为调和后的 HS6 货物双边流；伙伴及 HS2 图是聚合结果，不含服务贸易。"
               "进出口为相同双边流的两个视角，不能相加为全球贸易总量。")
    source_details(meta)
