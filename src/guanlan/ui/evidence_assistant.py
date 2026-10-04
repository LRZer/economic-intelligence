from __future__ import annotations

import json
import pandas as pd
import streamlit as st

from guanlan.evidence_assistant import EvidenceStore, answer_question, export_answer
from .china import load_dashboard
from .common import sync_query

TOOL_LABELS={"observation":"官方读数","difference":"两期读数差","mean":"窗口均值","extrema":"窗口极值","evaluation":"固定模型对照","forecast":"下一期研究估计"}

EXAMPLES={
    "最新官方读数":"CPI同比最新官方读数是多少？",
    "两期读数差":"CPI同比在2026-07与2026-08的差值是多少？",
    "连续窗口均值":"制造业PMI从2026-04到2026-09的平均读数是多少？",
    "当前固定模型审计":"PPI同比的固定回测MAE与基线对比是否通过门槛？",
    "下一统计期估计":"CPI同比下一期的预测值及默认参考是多少？",
    "核查无法回答的结论":"为什么CPI同比变化，能证明确定原因吗？",
}


@st.cache_resource(max_entries=4,show_spinner=False)
def evidence_store(rows):
    return EvidenceStore(rows)


def render(store):
    sync_query(view="intelligence",ai_task="证据问答与工具")
    st.subheader("证据问答与受限工具")
    st.caption("中国七个月度指标 · 字符检索与确定性计算 · 口径、期别及来源可核验")
    st.info("支持官方读数、两期差值、连续2—24月均值/极值、当前固定模型对照和下一统计期研究估计。缺证据、历史实时版本、因果或交易结论会拒答。此处是离线助手，未调用大模型或付费服务。")
    dashboard=load_dashboard()
    rows=[row for part in dashboard["series"].values() for row in part]
    try:
        corpus=evidence_store(rows)
    except (ValueError,KeyError,TypeError):
        st.warning("没有可用的批准月度快照，或来源/期别/数值校验失败。可继续使用其他研究任务。")
        return
    example=st.selectbox("问题示例",list(EXAMPLES),key="assistant_example")
    if st.button("填入示例",key="assistant_use_example"):
        st.session_state["assistant_question"]=EXAMPLES[example]
    st.session_state.setdefault("assistant_question",EXAMPLES[example])
    with st.form("assistant_question_form"):
        question=st.text_input("研究问题",max_chars=400,key="assistant_question")
        submitted=st.form_submit_button("核查问题",type="primary")
    if submitted:
        try:
            with st.spinner("检索来源并执行批准工具…"):
                answer=answer_question(question,corpus)
            st.session_state["assistant_answer"]={"snapshot":corpus.snapshot_hash,"answer":answer}
        except (ValueError,RuntimeError):
            st.error("问答未完成，来源和计算未通过核验。请缩小问题范围。")
    saved=st.session_state.get("assistant_answer")
    if not saved:return
    if saved["snapshot"]!=corpus.snapshot_hash:
        st.warning("当前数据快照已变化；先前答案不对应本次数据，请重新核查。")
        return
    answer=saved["answer"]
    st.caption("本次已核查问题："+answer["question"])
    if answer["status"]=="answered":
        st.success("已完成来源检索与受限计算")
        st.write(answer["answer"])
    elif answer["status"]=="clarify":st.warning(answer["answer"])
    else:st.info(answer["answer"])
    if answer["scope"]:
        scope=answer["scope"]
        label=corpus.specs[scope["key"]]
        st.caption(f"范围：{label['name']} · {label['basis']} · 工具 {TOOL_LABELS[scope['tool']]} · {'、'.join(scope['periods']) or '当前固定快照'}")
        if scope["defaulted_period"]:st.caption("未指定单期时使用该指标最近已发布期；窗口与模型任务按已核验范围显示。")
    for evidence in answer["evidence"]:
        if evidence["kind"]=="official_observation":
            st.markdown(f"[{evidence['period']} 官方原文]({evidence['source_url']}) · {evidence['value']:g}%")
        else:
            st.caption("模型证据来自当前固定回测；实验结果与开发期默认基线分开，不声称预测优势。")
    with st.expander("数值、计算轨迹与检索证据"):
        if answer["numbers"]:st.dataframe(pd.DataFrame([{"字段":k,"数值":v} for k,v in answer["numbers"].items()]),hide_index=True,width="stretch")
        st.json({"scope":answer["scope"],"routing":answer["routing"],"retrieval":answer["retrieval"],"trace":answer["trace"]})
        st.code(answer["answer_id"],language=None)
    files=export_answer(answer,corpus)
    st.caption("导出对应上方已核查问题；编辑输入框不会悄悄改写已完成答案，须再次点击核查。")
    stem=f"evidence-answer-{answer['answer_id'][:12]}"
    for label,kind,mime in [("下载问答报告 HTML","html","text/html"),("下载问答证据 JSON","json","application/json"),("下载计算与引用 CSV","csv","text/csv")]:
        st.download_button(label,files[kind],file_name=f"{stem}.{kind}",mime=mime,on_click="ignore")
