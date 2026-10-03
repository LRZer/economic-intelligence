import html
import pandas as pd
import streamlit as st

from guanlan.analytics import GDP, GROWTH, INFLATION, classify_regime, format_value
from guanlan.catalog import INDICATOR_BY_CODE, country_label
from .common import header, macro_selection, sync_query, source_line, source_details, chart, history_chart, download


def render(store):
    header("经济体概览", "年度宏观指标与相对历史位置")
    selection = macro_selection(store, "overview")
    if selection is None:
        sync_query(view="overview")
        return
    macro, meta, country, year, names = selection
    sync_query(view="overview", country=country, year=year)
    source_line(meta, f"{country_label(country, names[country])} · {year} 年")
    current = macro.loc[(macro.country_code == country) & (macro.year == year)].set_index("indicator_code").value
    cols = st.columns(4)
    for col, code, label in zip(cols, [GDP, GROWTH, INFLATION, "SL.UEM.TOTL.ZS"],
                                ["GDP 总量 · 现价美元", "实际GDP增速", "消费者价格涨幅", "失业率 · ILO 模型估计"]):
        value = current.get(code)
        col.metric(label, format_value(value, INDICATOR_BY_CODE[code].format_kind) if pd.notna(value) else "本年无记录")
    st.subheader("增长与价格走势")
    left, right = st.columns([1.75, 1], gap="large")
    history = macro.loc[(macro.country_code == country) & macro.indicator_code.isin([GROWTH, INFLATION])]
    with left:
        chart(history_chart(history.loc[history.indicator_code == GROWTH], "实际GDP增速", "%", names,
                            indicator=GROWTH, area=True, height=450, selected_year=year))
    with right:
        chart(history_chart(history.loc[history.indicator_code == INFLATION], "消费者价格涨幅", "%", names,
                            indicator=INFLATION, height=245, selected_year=year))
        regime = classify_regime(macro, country, year)
        if regime:
            st.markdown('<div class="research-brief" translate="no"><span class="brief-eyebrow">相对历史位置</span>'
                        f'<strong>{html.escape(regime.label)}</strong><div class="brief-rule"></div>'
                        f'<div class="brief-row"><span>实际GDP增速</span><b>{regime.growth:.2f}%</b>'
                        f'<small>中位数 {regime.growth_reference:.2f}%</small></div>'
                        f'<div class="brief-row"><span>消费者价格涨幅</span><b>{regime.inflation:.2f}%</b>'
                        f'<small>中位数 {regime.inflation_reference:.2f}%</small></div></div>', unsafe_allow_html=True)
            st.caption(f"参照：{regime.reference_start}—{regime.reference_end} 年；增长有效 {regime.observations_growth} 期，"
                       f"价格有效 {regime.observations_inflation} 期。不含所选年及后续年份。")
        else:
            st.info("本年指标缺失或此前十年有效观测不足 5 期，无法计算历史位置。")
    st.caption(f"虚线标记 {year} 年，历史图展示完整快照。选择数据年度并不恢复该年度当时发布的数据版本。"
               "摘要卡保留 1 位小数，研究详情保留 2 位，导出保留原始精度。")
    download(history, f"guanlan_{country}_{year}_growth_inflation.csv", meta=meta)
    with st.expander("查看近十年原值与指标定义"):
        values = history.loc[history.year.between(year-9, year)].pivot(index="year", columns="indicator_code", values="value")
        values.columns = [INDICATOR_BY_CODE[c].name for c in values]
        values.index.name = "年度"
        table = values.reset_index()
        table["年度"] = table["年度"].astype(str)
        st.dataframe(table.round(2), hide_index=True, width="stretch")
        for code in [GDP, GROWTH, INFLATION, "SL.UEM.TOTL.ZS"]:
            item = INDICATOR_BY_CODE[code]
            st.markdown(f"**{item.name}**：{item.definition} [来源定义]({item.source_url})")
    source_details(meta)
