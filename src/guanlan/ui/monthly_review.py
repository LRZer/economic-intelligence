from __future__ import annotations

import json
import pandas as pd
import streamlit as st

from guanlan.monthly_review import (build_monthly_review, default_plan, export_monthly_review,
                                    selected_claims, validate_plan)
from .common import radio, initial_query, sync_query

LABELS = {"对比上个自然月": "previous_month", "对比去年同月": "previous_year"}


@st.cache_data(show_spinner=False, max_entries=32)
def review_bundle(spec, rows, comparison):
    return build_monthly_review(spec, rows, comparison)


@st.cache_data(show_spinner=False, max_entries=32)
def review_files(bundle, plan, planner):
    return export_monthly_review(bundle, plan, planner)


def render_review(spec, rows):
    st.subheader("月度研究核验单")
    initial = next((label for label, code in LABELS.items() if code == initial_query("monthly_comparison")), "对比上个自然月")
    comparison = radio("观察比较", list(LABELS), "monthly_comparison", initial)
    sync_query(view="intelligence", ai_task="中国月度预测与异常", ai_indicator=spec["key"], monthly_comparison=LABELS[comparison])
    try:
        with st.spinner("计算本地研究与证据核验单…"):
            bundle = review_bundle(spec, rows, LABELS[comparison])
    except (ValueError, KeyError, TypeError):
        st.error("月度核验单无法生成：请核对重复期别、非有限值、指标口径及官方来源。其他研究任务仍可使用。")
        return None
    plan = default_plan(bundle)
    planner = "local"
    with st.expander("摘要编排与证据核查"):
        st.caption("默认使用本地完整声明，无网络请求。可导入受限编排 JSON；外部模型只能选择声明 ID，不能写入正文、数字、因果解释或交易建议。读数、方法决策和局限必须保留。")
        upload = st.file_uploader("导入受限编排 JSON", type=["json"], key="monthly_plan_upload")
        if upload is not None:
            try:
                if upload.size > 16384:
                    raise ValueError
                plan = validate_plan(json.loads(upload.getvalue().decode("utf-8")), bundle)
                planner = "imported_untrusted"
                st.success("编排结构通过；展示文本仍由本地证据生成，不代表外部模型业务质量已验证。")
            except (UnicodeError, ValueError, TypeError, RecursionError):
                st.warning("编排被拒绝：结构、声明或核验包不匹配。已保留当前本地完整核验单。")
        st.download_button("下载当前受限编排示例", json.dumps(default_plan(bundle), ensure_ascii=False, indent=2).encode("utf-8"),
                           file_name=f"monthly-plan-{spec['key']}-{bundle['review_id'][:12]}.json", mime="application/json", on_click="ignore")
        st.dataframe(pd.DataFrame([{ "声明": c["id"], "类型": c["kind"], "证据": " · ".join(c["evidence_ids"])} for c in bundle["claims"]]),
                     hide_index=True, width="stretch")
        st.code(bundle["review_id"], language=None)
    evidence = {row["id"]: row for row in bundle["evidence"]}
    for claim in selected_claims(bundle, plan):
        st.write(claim["text"])
        links = [f"[{evidence[eid]['period']} 官方原文]({evidence[eid]['source_url']})"
                 for eid in claim["evidence_ids"] if evidence[eid]["kind"] == "official_observation"]
        if links:
            st.markdown(" · ".join(links))
    st.caption("Ridge 与 IsolationForest 在本机实际计算；声明文字由确定性模板生成，不冒充语言模型判断。缺少首次发布版本与异常真值标签。")
    files = review_files(bundle, plan, planner)
    st.caption(f"当前报告范围：{spec['name']} · {bundle['selection']['latest_period']} · {'上个自然月' if LABELS[comparison] == 'previous_month' else '去年同月'}")
    stem = f"monthly-review-{spec['key']}-{bundle['selection']['latest_period']}-{bundle['selection']['comparison']}-{bundle['review_id'][:12]}"
    for label, extension, mime in [("下载核验单 HTML", "html", "text/html"), ("下载核验包 JSON", "json", "application/json"),
                                   ("下载声明与证据 CSV", "csv", "text/csv")]:
        st.download_button(label, files[extension], file_name=f"{stem}.{extension}", mime=mime, on_click="ignore")
    return bundle
