import plotly.express as px
import streamlit as st
from guanlan.weo import WEO_INDICATORS, WEO_UNITS_ZH, format_forecast_value, forecast_cross_section, growth_inflation_map
from guanlan.catalog import country_label
from .common import (select, source_line, initial_query, radio, multi, query_list, history_chart,
                     chart, download, sync_query, source_details)


def render(store):
    weo, meta = store.get("weo")
    st.subheader("IMF预测")
    if weo.empty:
        sync_query(view="compare",compare_view="IMF预测")
        return
    version = select("已加载发布版本", [meta["vintage"]], "outlook_version")
    source_line(meta, f"WEO {version} · 固定版本，不代表实时最新预测")
    names = weo.drop_duplicates("country_code").set_index("country_code").country_name.to_dict()
    options = sorted(names, key=lambda c: country_label(c,names[c]))
    a,b,c=st.columns([1.3,1.3,1])
    with a:
        country=select("预测经济体",options,"outlook_country",initial_query("country","CHN"),
                       format_func=lambda c:country_label(c,names[c]))
    with b:
        code=select("预测指标",list(WEO_INDICATORS),"outlook_indicator",initial_query("weo_indicator","NGDP_RPCH"),
                    format_func=lambda c:WEO_INDICATORS[c])
    years=sorted(map(int,weo.year.unique()))
    with c:
        year=select("预测年份",years,"outlook_year",int(initial_query("weo_year","2026"))
                    if initial_query("weo_year","2026").isdigit() else years[0])
    focus=weo.loc[(weo.country_code==country)&(weo.indicator_code==code)]
    cards=st.columns(3)
    for col,target in zip(cards,[years[0],years[1],years[-1]]):
        values=focus.loc[focus.year==target,"value"]
        col.metric(f"{target} 年预测",format_forecast_value(values.iloc[0] if not values.empty else None,code))
    unit=WEO_UNITS_ZH[code]
    representation=radio("预测展示",["中期路径","全球横截面"],"outlook_representation")
    peers=[country]
    if representation=="中期路径":
        peers=multi("预测对照经济体",options,"outlook_peers",query_list("weopeers",options,[country,"USA","DEU"]),
                    format_func=lambda c:country_label(c,names[c]))
        series=weo.loc[weo.country_code.isin(peers)&(weo.indicator_code==code)].copy()
        if not series.value.notna().any():
            st.info("当前选择没有有效预测。")
        else:
            fig=history_chart(series,f"{WEO_INDICATORS[code]} · {version}",unit,names,height=300)
            fig.update_traces(mode="lines+markers")
            chart(fig)
            download(series,f"guanlan_weo_{code}_{version.replace(' ','_')}.csv",meta=meta)
    else:
        distribution=forecast_cross_section(weo,code,year)
        scatter=growth_inflation_map(weo,year,country)
        if not scatter.empty:
            scatter["经济体"]=scatter.apply(lambda r:country_label(r.country_code,r.country_name),axis=1)
            fig=px.scatter(scatter,x="growth",y="inflation",size="gdp_billion_usd",hover_name="经济体",
                           size_max=35,title=f"{year} 年增长与通胀预测",color_discrete_sequence=["#146f7c"])
            fig.update_layout(height=330,xaxis_title="实际GDP增速（%）",yaxis_title="平均消费者价格涨幅（%）")
            chart(fig)
            st.caption("散点固定使用增长与通胀指标；按同版名义 GDP 选前 30 大经济体，并加入所选经济体。")
        distribution["经济体"]=distribution.apply(lambda r:country_label(r.country_code,r.country_name),axis=1)
        st.dataframe(distribution[["经济体","value"]].rename(columns={"value":f"{WEO_INDICATORS[code]}（{unit}）"}).round(2),
                     width="stretch",hide_index=True)
        download(distribution,f"guanlan_weo_{code}_{year}.csv",meta=meta)
    count=len(forecast_cross_section(weo,code,year))
    st.caption(f"{year} 年 {count}/{len(names)} 个经济体有当前指标预测。路径仅使用同一 WEO 版本，"
               "不与 WDI 历史观测拼接；来源未提供的不确定性区间不另行添加。")
    sync_query(view="compare",compare_view="IMF预测",country=country,weo_indicator=code,weo_year=year,
               weopeers=",".join(peers))
    source_details(meta)
