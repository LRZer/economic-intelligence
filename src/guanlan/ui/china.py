from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from china_macro import app as china_app
from .common import header, radio, select, sync_query, initial_query, chart
from .workflow import navigate
from guanlan.forecast import MODEL_KEYS


def load_dashboard():
    china_app.initialize()
    return china_app.dashboard()


def render(store):
    header("中国经济观察", "官方月度读数、连续自然月趋势与可追溯的来源证据")
    view = radio("中国研究视图", ["指标趋势", "本期观察", "数据质量"], "china_view", initial_query("china_view", "指标趋势"))
    data = load_dashboard()
    st.caption(f"本地快照采集时间：{data.get('demo_captured_at') or '未提供'} · 各指标实际期别分别展示 · 自动采集默认关闭")
    if not data["latest"]:
        st.info("暂无中国观测。请安装来源快照，或在确认来源使用要求后手动采集。")
        sync_query(view="china", china_view=view)
        return
    if view == "数据质量":
        sync_query(view="china", china_view=view)
        a, b, c = st.columns(3)
        a.metric("官方观测", data["quality"]["observation_count"])
        b.metric("近24个月覆盖", f"{data['quality']['coverage_pct']:.1f}%")
        c.metric("近60个月覆盖", f"{data['quality_60m']['coverage_pct']:.1f}%")
        quality = pd.DataFrame(data["quality_60m"]["metrics"])
        columns = [x for x in ("name", "observed", "expected", "coverage_pct", "missing") if x in quality]
        st.dataframe(quality[columns], hide_index=True, width="stretch")
        st.caption("待发布、不单列及口径未启用月份排除于分母；覆盖率不等于逐条人工审核率。")
        with st.expander("修订和采集记录"):
            st.dataframe(pd.DataFrame(data["recent_changes"]), hide_index=True)
            st.dataframe(pd.DataFrame(data["ingestion_runs"]), hide_index=True)
        st.info("采集操作由显式命令执行；原文校验可运行 python -m china_macro.audit。")
        return
    if view == "本期观察":
        sync_query(view="china", china_view=view)
        summary = data["reader_summary"]
        st.subheader(summary["headline"])
        for observation in summary["observations"]:
            st.markdown(f"**{observation['topic']} · {observation['period']}**：{observation['title']}")
            for key in observation["keys"]:
                change = summary["changes"][key]
                a, b = change["current"], change["previous"]
                st.write(f"{change['name']}：{b['period']} 的 {b['value']} → {a['period']} 的 {a['value']} {change['unit']}")
                st.markdown(f"[本期原文]({a['source_url']}) · [比较期原文]({b['source_url']})")
            st.caption(observation["boundary"])
        st.button("打开中国月度研究", key="china_open_monthly", on_click=navigate, args=("intelligence",), kwargs={"task":"中国月度预测与异常","ai_indicator":"cpi_yoy"})
        return
    specs = {s["key"]: s for s in data["catalog"]}
    keys = [k for k in specs if data["series"].get(k)]
    key = select("研究指标", keys, "china_indicator", initial_query("china_indicator", "cpi_yoy"), format_func=lambda k: specs[k]["name"])
    if key in MODEL_KEYS:
        st.button("分析当前指标：预测与异常核查", key="china_analyze_current", on_click=navigate, args=("intelligence",), kwargs={"task":"中国月度预测与异常","ai_indicator":key})
    window = select("自然月窗口", [12, 24, 60], "china_window", 24, format_func=lambda n: f"近{n}个月")
    sync_query(view="china", china_view=view, china_indicator=key)
    spec = specs[key]
    rows = pd.DataFrame(data["series"][key])
    rows["date"] = pd.to_datetime(rows["period"])
    end = rows.date.max()
    index = pd.date_range(end - pd.DateOffset(months=window-1), end, freq="MS")
    aligned = rows.set_index("date").reindex(index)
    last = rows.iloc[-1]
    a, b, c = st.columns([1, 1, 2])
    a.metric("最新官方读数", f"{last['value']:g} {spec['unit']}")
    b.metric("实际统计期别", last["period"])
    c.write(f"**{spec['basis']}** · {spec['source']}\n\n{spec['description']}")
    figure = go.Figure(go.Scatter(x=index, y=aligned.value, mode="lines+markers", connectgaps=False,
                                 line={"color": "#146f7c", "width": 3}, name="官方观测"))
    figure.update_layout(title=f"{spec['name']} · {spec['basis']}", yaxis_title=spec["unit"], height=400)
    chart(figure)
    st.caption("自然月缺口不连线、不插值。不同币种、累计口径与新旧统计范围不拼接。")
    st.markdown(f"[查看最新官方来源]({last['source_url']})")
    st.dataframe(rows.drop(columns="date").rename(columns={"period": "期别", "value": "读数", "source_url": "官方原文"}), hide_index=True, width="stretch")
    st.download_button("下载同口径完整历史 CSV", rows.drop(columns="date").to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"china-{key}.csv", mime="text/csv")
    macro, meta = store.get("macro", quiet=True)
    if not macro.empty:
        annual = macro.loc[(macro.country_code == "CHN") & (macro.indicator_code == "NY.GDP.MKTP.KD.ZG")].sort_values("year")
        if not annual.empty:
            record = annual.iloc[-1]
            st.info(f"跨国背景：WDI 中国年度 GDP 增速，{int(record.year)} 年 {record.value:.2f}%。年度与月度数据分别展示，不直接合并。")
