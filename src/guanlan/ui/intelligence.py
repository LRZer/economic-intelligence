from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from guanlan.forecast import MODEL_KEYS
from .china import load_dashboard
from .common import header, select, radio, sync_query, initial_query, chart
from .research import cycle_view
from . import global_ai, sector, evidence_assistant, trade_graph, chronos_research
from .monthly_review import render_review


def render(store):
    header("研究与风险分析", "本地机器学习 · 时间顺序评估 · 基线比较 · 来源证据")
    task = radio("研究任务", ["宏观与行业风险研究", "中国月度预测与异常", "全球年度GDP研究", "美国周期风险研究", "证据问答与工具", "真实贸易图与情景", "时序基础模型审计"], "ai_task", initial_query("ai_task", "宏观与行业风险研究"))
    if task == "时序基础模型审计":
        return chronos_research.render(store)
    if task == "真实贸易图与情景":
        return trade_graph.render(store)
    if task == "证据问答与工具":
        domain=radio("证据工具范围", ["中国月度", "真实贸易图"], "evidence_domain", "中国月度")
        if domain == "真实贸易图":
            return trade_graph.render(store, task=task)
        return evidence_assistant.render(store)
    if task == "宏观与行业风险研究":
        return sector.render(store)
    if task == "全球年度GDP研究":
        sync_query(view="intelligence", ai_task=task)
        return global_ai.render(store)
    if task == "美国周期风险研究":
        sync_query(view="intelligence", ai_task=task)
        return cycle_view(store)
    data = load_dashboard()
    catalog = {s["key"]: s for s in data["catalog"]}
    keys = [k for k in MODEL_KEYS if data["series"].get(k)]
    if not keys:
        st.info("暂无可评估的中国月度数据。安装真实来源快照后可离线运行模型。")
        sync_query(view="intelligence", ai_task=task)
        return
    key = select("建模指标", keys, "ai_indicator", initial_query("ai_indicator", "cpi_yoy"), format_func=lambda k: catalog[k]["name"])
    sync_query(view="intelligence", ai_task=task, ai_indicator=key)
    spec = catalog[key]
    rows = data["series"][key]
    st.caption(f"{spec['basis']} · {spec['unit']} · {len(rows)} 个真实观测 · 最新 {rows[-1]['period']}")
    st.warning("使用当前修订版历史数据，不是逐期实时版本回测。结果用于研究核查，不能作为交易信号。")
    bundle = render_review(spec, rows)
    if bundle is None:
        return
    result, abnormal = bundle["model"], bundle["anomaly"]
    st.subheader("回测与模型细节")
    if result["status"] != "evaluated":
        st.info(result["reason"])
        return
    metrics = result["metrics"]["test"]
    a, b, c, d = st.columns(4)
    a.metric("留出期模型 MAE", f"{metrics['ridge']['mae']:.3f}")
    b.metric("开发期选定基线 MAE", f"{metrics[result['baseline']]['mae']:.3f}")
    c.metric("留出评估月", result["test_n"])
    d.metric("90%经验带实际覆盖", f"{result['test_interval_coverage']:.0%}")
    baseline_name = "上期值" if result["baseline"] == "persistence" else "去年同月值"
    st.caption(f"基线在开发验证期选择：{baseline_name}。留出期从 {result['test_start']} 开始，每个预测都重新拟合此前数据。")
    lo, hi = result["paired_mae_difference_95"]
    if result["passes_research_gate"]:
        st.success("模型通过本快照研究门槛；仍需新的独立时期及实时数据版本验证。")
    else:
        st.info("模型尚未通过研究门槛：需优于两项简单基线的留出 MAE，并使与开发期选定基线的配对误差差值区间完全低于零。保留全部评估结果供核查。")
    st.caption(f"默认研究参考为开发期预先选定的{baseline_name}基线；岭回归估计单列为实验结果。")
    st.caption(f"模型减基线绝对误差：3月移动块抽样的描述性95%区间 [{lo:.3f}, {hi:.3f}]。样本小，不能推断稳定投资效力。")
    backtest = pd.DataFrame(result["backtest"])
    test = backtest.loc[backtest.split == "test"]
    figure = go.Figure()
    for column, label, color, dash in (("actual", "官方观测", "#172d3b", "solid"),
                                       ("ridge", "岭回归逐期预测", "#146f7c", "solid"),
                                       (result["baseline"], f"基线 · {baseline_name}", "#b95d42", "dot")):
        figure.add_trace(go.Scatter(x=test.period, y=test[column], name=label, mode="lines+markers",
                                   line={"color": color, "dash": dash, "width": 2}))
    figure.add_trace(go.Scatter(x=test.period, y=test.ridge + result["interval_radius"], mode="lines", line={"width": 0},
                               showlegend=False, hoverinfo="skip"))
    figure.add_trace(go.Scatter(x=test.period, y=test.ridge - result["interval_radius"], mode="lines", fill="tonexty",
                               fillcolor="rgba(20,111,124,.12)", line={"width": 0}, name="90%开发期经验误差带", hoverinfo="skip"))
    figure.update_layout(title=f"{spec['name']} · 最后12个自然月留出回测", yaxis_title=spec["unit"], height=450,
                         legend={"orientation":"h", "y":-.2, "x":0}, margin={"l":45,"r":20,"t":65,"b":105})
    chart(figure)
    forecast = result.get("forecast")
    if forecast:
        with st.expander("下一期研究估计与模型解释", expanded=True):
            st.write(f"预测统计期别：**{forecast['period']}**，最后训练标签：{forecast['train_end']}。")
            a, b = st.columns(2)
            a.metric(f"默认参考 · {baseline_name}基线（{spec['unit']}）", f"{forecast['baseline']:.3f}")
            b.metric(f"实验模型估计（{spec['unit']}）", f"{forecast['ridge']:.3f}")
            st.caption(f"经验区间 [{forecast['lower']:.3f}, {forecast['upper']:.3f}]，由 {result['interval_calibration_n']} 个开发验证误差校准，不保证未来90%覆盖。")
            contributions = pd.DataFrame({"特征": list(forecast["contributions"]), "对预测的加性贡献": list(forecast["contributions"].values())})
            contribution_plot = go.Figure(go.Bar(x=contributions["对预测的加性贡献"], y=contributions["特征"], orientation="h",
                                                marker_color=["#146f7c" if x >= 0 else "#b95d42" for x in contributions["对预测的加性贡献"]]))
            contribution_plot.update_layout(title="标准化岭回归：线性贡献分解", height=300, xaxis_title=spec["unit"])
            chart(contribution_plot)
            st.caption(f"各贡献加上截距 {forecast['intercept']:.3f} 等于模型估计；表示模型关系，不表示经济因果。")
    st.subheader("本期异常核查")
    if abnormal["status"] == "scored":
        st.write(f"{abnormal['period']} · {'建议复核来源与经济冲击' if abnormal['flag'] else '未触发异常阈值'} · 分数 {abnormal['score']:.4f}")
        st.caption(f"训练截至 {abnormal['train_end']}，{abnormal['train_n']} 个历史样本；本期不参与训练。{abnormal['limits']}")
        st.json(abnormal["inputs"])
    else:
        st.info(abnormal["reason"])
    st.markdown(f"[最新官方数据证据]({rows[-1]['source_url']})")
    with st.expander("全部评估、训练边界与复现信息"):
        st.dataframe(pd.DataFrame([{ "分段": stage, "方法": method, **score}
                                   for stage, entries in result["metrics"].items() for method, score in entries.items()]), hide_index=True)
        st.dataframe(backtest, hide_index=True, width="stretch")
        st.code(result["snapshot_hash"], language=None)
        st.write("固定参数：Ridge alpha=10；每期训练内标准化；自然月滞后1/2/3/12；末12自然月留出；缺失不插值。IsolationForest 200棵树、阈值10%、seed=42。")
    st.download_button("下载逐期回测 CSV", backtest.to_csv(index=False).encode("utf-8-sig"), file_name=f"backtest-{key}.csv", mime="text/csv", on_click="ignore")
