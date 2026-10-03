import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from guanlan.analytics import GROWTH, INFLATION, format_value
from guanlan.catalog import INDICATOR_BY_CODE, country_label
from guanlan.macro_profile import PROFILE_INDICATORS, PROFILE_SHORT_NAMES, DEFAULT_PROFILE_INDICATORS, build_macro_profile
from guanlan.research import COHORTS, peer_context
from .common import (header, radio, initial_query, macro_selection, multi, query_list, select,
                     sync_query, source_line, history_chart, chart, download, color_map,
                     color_for, number, date_label, run_module)
from . import outlook


def render(store):
    header("跨国比较", "同年原值、历史走势与独立版本的机构预测")
    view = radio("比较视图", ["历史走势", "当年横截面", "多指标与同组参照", "IMF预测"], "compare_view",
                 "IMF预测" if initial_query("view") == "outlook" else initial_query("compare_view", "历史走势"))
    if view == "IMF预测":
        return outlook.render(store)
    selection = macro_selection(store, "compare", country_label_text="同组参照经济体")
    if selection is None:
        sync_query(view="compare",compare_view=view)
        return
    macro, meta, focus, year, names = selection
    options = sorted(names, key=lambda c: country_label(c, names[c]))
    peers_col,indicator_col=st.columns([2,1])
    with peers_col:
        peers = multi("比较经济体（最多 6 个）", options, "compare_peers",
                      query_list("peers", options, list(dict.fromkeys([focus, "USA", "DEU", "JPN", "IND"]))),
                      format_func=lambda c: country_label(c, names[c]))
    with indicator_col:
        code = select("比较指标", list(INDICATOR_BY_CODE), "compare_indicator", initial_query("indicator", GROWTH),
                      format_func=lambda c: f"{INDICATOR_BY_CODE[c].name}（{INDICATOR_BY_CODE[c].unit}）")
    item = INDICATOR_BY_CODE[code]
    parameters=dict(view="compare", compare_view=view, country=focus, year=year, peers=",".join(peers), indicator=code)
    source_line(meta, f"{year} 年 · 比较对象 {len(peers)} 个")
    if not peers:
        sync_query(**parameters)
        return
    if view == "历史走势":
        series = macro.loc[macro.country_code.isin(peers) & (macro.indicator_code == code)].copy()
        fig=history_chart(series, f"{item.name} · 完整历史序列", item.unit, names, height=390)
        fig.add_vline(x=year,line_color="#9bafb9",line_dash="dot",line_width=1)
        chart(fig)
        st.caption("年度筛选用于标记研究时点；本视图显示全部历史记录，缺失年份断线。")
        download(series, f"guanlan_compare_{code}_{year}.csv", meta=meta)
    elif view == "当年横截面":
        world = macro.loc[(macro.year == year) & (macro.indicator_code == code)].copy()
        valid = world.loc[world.value.notna()].copy()
        shown = world.loc[world.country_code.isin(peers)].copy()
        shown["经济体"] = shown.country_code.map(lambda c: country_label(c, names[c]))
        representation = radio("横截面展示", ["所选经济体", "世界地图", "全球原值表"], "compare_representation",
                               initial_query("representation","所选经济体"))
        parameters["representation"]=representation
        st.caption(f"全球有效样本 {len(valid)}/{world.country_code.nunique()} 个经济体。只使用 {year} 年原值。")
        if representation == "所选经济体":
            fig = px.bar(shown.dropna(subset=["value"]).sort_values("value"), x="value", y="经济体", orientation="h",
                         color="经济体", color_discrete_map=color_map(names), text="value", title=f"{year} 年 · {item.name}")
            fig.update_traces(texttemplate="%{text:.2f}", textposition="outside", cliponaxis=False)
            fig.update_layout(height=max(270, 52*len(peers)+110), showlegend=False, xaxis_title=item.unit,
                              yaxis_title="", margin=dict(l=10, r=65, t=50, b=45))
            chart(fig)
            for row in shown.loc[shown.value.isna()].itertuples():
                st.caption(f"{row.经济体}：本年无记录。")
        elif representation == "世界地图":
            map_view(valid, item, year)
        else:
            valid["经济体"] = valid.country_code.map(lambda c: country_label(c, names[c]))
            st.dataframe(valid[["经济体", "value"]].sort_values("value", ascending=False).rename(
                columns={"value": f"原值（{item.unit}）"}).round(2), width="stretch", hide_index=True)
        download(world, f"guanlan_world_{code}_{year}.csv", "下载全部经济体当年原值 · CSV", meta)
    else:
        profile_codes=run_module("多指标对照", lambda: profile_view(macro, meta, peers, names, year))
        cohort=run_module("同组参照", lambda: peer_view(macro, meta, focus, year, code, names))
        parameters["profile"]=",".join(profile_codes or [])
        parameters["cohort"]=cohort
    sync_query(**parameters)
    with st.expander("查看当前指标口径"):
        st.write(item.definition)
        st.write(item.comparison_note)
        st.markdown(f"[世界银行源指标]({item.source_url})")


def map_view(valid, item, year):
    if valid.empty:
        st.info("本年无有效值。")
        return
    world = valid.copy()
    world["经济体"] = world.apply(lambda r: country_label(r.country_code, r.country_name), axis=1)
    if item.code in [GROWTH, INFLATION]:
        # 跨年份固定边界，开放端点保留极端原值；不改变源数据。
        world["色阶"] = np.digitize(world.value, [-10, -2, 0, 2, 5, 10])
        labels = ["<−10", "−10—−2", "−2—0", "0—2", "2—5", "5—10", "≥10"]
        colors = ["#9c3b31", "#ca7661", "#ebc4b8", "#edf1ef", "#b0d2cd", "#5c9d98", "#1f655f"]
        scale = []
        for i,c in enumerate(colors):
            scale.extend([[i/7,c],[(i+1)/7,c]])
        fig = px.choropleth(world, locations="country_code", color="色阶", range_color=(-.5,6.5),
                            custom_data=["value"], hover_name="经济体", color_continuous_scale=scale, projection="natural earth")
        fig.update_layout(coloraxis_colorbar=dict(title=item.unit, tickvals=list(range(7)), ticktext=labels))
        st.caption("色阶边界跨年份固定；两端为开放区间，悬浮显示未经截断的原值。零区分正负变化。")
    else:
        fig = px.choropleth(world, locations="country_code", color="value", custom_data=["value"], hover_name="经济体",
                            color_continuous_scale=["#e1efed", "#78aca8", "#1f655f"], projection="natural earth")
        st.caption("色阶按本年原值自动缩放，跨年份相同颜色不代表相同数值。")
    fig.update_traces(hovertemplate=f"%{{hovertext}}<br>原值：%{{customdata[0]:,.2f}} {item.unit}<extra></extra>")
    fig.update_geos(showframe=False, showcoastlines=True, coastlinecolor="#cad5d9", showland=True, landcolor="#e4eaed")
    fig.update_layout(title=f"{year} 年 · {item.name}", height=380, margin=dict(l=10, r=10, t=45, b=10))
    chart(fig)


def profile_view(macro, meta, peers, names, year):
    st.subheader("多指标对照")
    codes = multi("对照指标（最多 7 项）", PROFILE_INDICATORS, "macro_profile_indicators",
                  query_list("profile", PROFILE_INDICATORS, DEFAULT_PROFILE_INDICATORS),
                  format_func=lambda c: PROFILE_SHORT_NAMES[c], limit=7)
    if not codes:
        return
    mode = radio("单元格显示", ["原值", "数值百分位"], "profile_display")
    profile = build_macro_profile(macro, peers, year, codes)
    raw = profile.pivot(index="country_code", columns="indicator_code", values="value").reindex(index=peers, columns=codes)
    pct = profile.pivot(index="country_code", columns="indicator_code", values="global_percentile").reindex(index=peers, columns=codes)
    coverage = profile.drop_duplicates("indicator_code").set_index("indicator_code")
    low=[PROFILE_SHORT_NAMES[c] for c in codes if coverage.loc[c,"global_observed"]<coverage.loc[c,"global_total"]/2]
    if low:
        st.warning("有效覆盖不足一半："+"、".join(low)+"。数值位置可能受样本选择影响。")
    xlabels = [f"{PROFILE_SHORT_NAMES[c]}<br>n={int(coverage.loc[c,'global_observed'])}" for c in codes]
    ylabels = [country_label(c, names[c]) for c in peers]
    if mode == "原值":
        z = np.where(raw.notna(), 1., np.nan)
        text = [[number(v, suffix="%", missing="本年无记录") for v in row] for row in raw.to_numpy()]
        custom = pct.to_numpy()
        hover = "%{y}<br>%{x}<br>原值：%{text}<br>数值百分位：%{customdata:.1f}<extra></extra>"
        colors = [[0,"#eaf2f3"],[1,"#eaf2f3"]]
    else:
        z = pct.to_numpy()
        text = [[number(v, precision=1, missing="本年无记录") for v in row] for row in z]
        custom = raw.to_numpy()
        hover = "%{y}<br>%{x}<br>数值百分位：%{text}<br>原值：%{customdata:.2f}%<extra></extra>"
        colors = [[0,"#edf4f4"],[.5,"#9abfc0"],[1,"#286f77"]]
    fig = go.Figure(go.Heatmap(z=z, x=xlabels, y=ylabels, text=text, customdata=custom,
                              hovertemplate=hover, colorscale=colors, zmin=0, zmax=100 if mode!="原值" else 1,
                              showscale=mode!="原值", colorbar=dict(title="数值百分位")))
    for i,y in enumerate(ylabels):
        for j,x in enumerate(xlabels):
            fig.add_annotation(x=x,y=y,text=text[i][j],showarrow=False,
                               font=dict(size=13,color="white" if mode!="原值" and z[i][j]>=76 else "#244451"))
    fig.update_layout(height=max(275, 52*len(peers)+115), margin=dict(l=90,r=20,t=65,b=20),
                      xaxis=dict(side="top"), yaxis=dict(autorange="reversed"), plot_bgcolor="#e1e7ea")
    chart(fig)
    st.caption("n 为该列本年全球有效样本数。百分位采用并列值中秩，只表示数值位置，不能相加为评分。")
    with st.expander("查看覆盖率与严格五年端点变化"):
        st.dataframe(profile[["country_code", "indicator_code", "value", "global_observed", "global_total", "delta_pp"]].round(2),
                     hide_index=True, width="stretch")
        st.caption(f"变化只比较 {year-5} 与 {year} 年端点；缺失不借用邻近年度。")
    download(profile, f"guanlan_macro_profile_{year}.csv", "下载多指标对照底稿 · CSV", meta)
    return codes


def peer_view(macro, meta, country, year, code, names):
    st.subheader("同组参照")
    cohort = select("参照范围", list(COHORTS), "compare_cohort", initial_query("cohort","同收入组"))
    distribution, peer = peer_context(macro, country, year, code, cohort)
    item = INDICATOR_BY_CODE[code]
    st.caption(f"{year} 年 · {peer.group_value} · 分组采用 WDI 快照 {date_label(meta)} 的地区与收入分类，"
               "不是该年度历史分类；快照未提供分类生效年份。")
    a,b,c = st.columns(3)
    a.metric("同组有效样本", f"{peer.observed_economies}/{peer.total_economies}")
    b.metric("有效样本中位数", format_value(peer.median, item.format_kind))
    c.metric("本国数值百分位", number(peer.percentile, precision=1, missing="本年无记录"))
    if peer.observed_economies < peer.total_economies/2:
        st.warning("同组有效覆盖不足一半，样本位置可能存在选择偏差。")
    if not distribution.empty:
        fig=go.Figure(go.Box(x=distribution.value, name="同组有效样本", orientation="h", boxpoints="all",
                             marker=dict(color="#7fa7ae",size=5), jitter=.3))
        if peer.selected_value is not None:
            fig.add_trace(go.Scatter(x=[peer.selected_value], y=["同组有效样本"], mode="markers",
                                     name=country_label(country,names[country]), marker=dict(size=13,color=color_for(country))))
        fig.update_layout(height=235,xaxis_title=item.unit,margin=dict(l=20,r=20,t=25,b=50),showlegend=False)
        chart(fig)
    download(distribution, f"guanlan_peers_{country}_{year}_{code}.csv", "下载同组样本 · CSV", meta)
    return cohort
