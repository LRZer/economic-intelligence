import os
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from guanlan.ai import generate_brief
from guanlan.analytics import GROWTH, research_facts, format_value
from guanlan.catalog import INDICATOR_BY_CODE, country_label
from guanlan.research import COHORTS
from guanlan.research_bundle import build_research_bundle
from guanlan.research_compare import compare_with_current, comparison_csv_bytes
from guanlan.cycle_diagnostics import paired_block_brier_interval, cycle_period_breakdown
from .common import (header, radio, initial_query, sync_query, run_module, macro_selection,
                     select, source_line, fingerprint, number, log_failure, date_label,
                     chart, download, source_details)


def render(store):
    header("研究", "可读的研究报告与明确标记的模型实验")
    view=radio("研究视图",["研究报告","模型实验"],"research_view",
               "模型实验" if initial_query("view")=="cycle" else initial_query("research_view","研究报告"))
    if view=="模型实验":
        sync_query(view="research",research_view="模型实验")
        return run_module("美国周期实验",lambda:cycle_view(store))
    return report_view(store)


def report_view(store):
    selection=macro_selection(store,"report",country_label_text="研究经济体")
    if selection is None:
        sync_query(view="research",research_view="研究报告")
        return
    macro,meta,country,year,names=selection
    a,b=st.columns([2,1])
    with a:
        indicator=select("同组参照指标",list(INDICATOR_BY_CODE),"report_indicator",initial_query("indicator",GROWTH),
                         format_func=lambda c:INDICATOR_BY_CODE[c].name)
    with b:
        cohort=select("报告参照范围",list(COHORTS),"report_cohort",initial_query("cohort","同收入组"))
    sync_query(view="research",research_view="研究报告",country=country,year=year,indicator=indicator,cohort=cohort)
    trade,trade_meta=store.trade()
    weo,weo_meta=store.get("weo")
    policy,policy_meta=store.get("bis_policy")
    credit,credit_meta=store.get("bis_credit")
    bundle=build_research_bundle(macro,trade,meta,trade_meta,country,year,indicator,cohort,
                                 weo=weo,weo_meta=weo_meta,bis_policy=policy,bis_credit=credit,
                                 bis_policy_meta=policy_meta,bis_credit_meta=credit_meta)
    if st.session_state.get("report_render_id")!=bundle.report_id:
        st.session_state["report_render_id"]=bundle.report_id
        st.session_state["report_generated_at"]=pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y-%m-%d %H:%M")
    st.subheader(f"{country_label(country,names[country])} · {year} 年宏观研究报告")
    source_line(meta,f"生成时间 {st.session_state['report_generated_at']} · 当前已加载版本")
    export=select("导出报告",["离线阅读版 HTML","完整研究包 ZIP","Markdown 正文"],"report_export")
    data,mime,ext={"离线阅读版 HTML":(bundle.html.encode(),"text/html","html"),
                   "完整研究包 ZIP":(bundle.archive,"application/zip","zip"),
                   "Markdown 正文":(bundle.markdown.encode(),"text/markdown","md")}[export]
    st.download_button("导出",data,file_name=f"guanlan_{country}_{year}_{bundle.report_id}.{ext}",mime=mime)
    # 正文直接可读；完整追踪信息仍保留在导出文件与详情中。
    body=bundle.markdown[bundle.markdown.index("## 年度宏观指标"):]
    readable=body.split("## 来源、方法与限制")[0]
    for code in INDICATOR_BY_CODE:
        readable=readable.replace(f"WDI {code}","世界银行 WDI")
    for source_meta in [meta,trade_meta,weo_meta,policy_meta,credit_meta]:
        if source_meta.get("downloaded_at_utc"):
            readable=readable.replace(source_meta["downloaded_at_utc"],date_label(source_meta))
    st.markdown(readable)
    st.caption("历史位置以此前十年有效样本为参照；同组分类采用当前 WDI 快照，未恢复历史分类版本。"
               "BIS 为所选年内最后记录，IMF 为独立预测版本，各来源不跨年填补。")
    run_module("解释性摘要",lambda:ai_view(macro,trade,meta,trade_meta,weo,weo_meta,country,year,bundle))
    with st.expander("查看来源、计算方法与研究包清单"):
        st.markdown("## 来源、方法与限制"+body.split("## 来源、方法与限制",1)[1])
        st.caption(f"报告编号 {bundle.report_id}")
        st.json(bundle.manifest)
    with st.expander("比较旧研究包的数据版本"):
        compare_previous(bundle)


def clear_key():
    st.session_state["ai_session_key"]=""


def configured_key():
    if st.session_state.get("ai_session_key"):
        return st.session_state["ai_session_key"]
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    try:
        return st.secrets.get("DEEPSEEK_API_KEY")
    except (FileNotFoundError, st.errors.StreamlitAPIException):
        return None


def ai_view(macro,trade,meta,trade_meta,weo,weo_meta,country,year,bundle):
    st.subheader("解释性摘要")
    facts=research_facts(macro,trade,country,year,trade_meta,weo,weo_meta)
    facts["source_versions"]=bundle.manifest.get("sources",{})
    facts["report_id"]=bundle.report_id
    facts["selection"]=bundle.manifest.get("selection",{})
    identity=fingerprint(facts)
    st.markdown("**事实摘要**")
    rows=[]
    for code,reading in facts["indicators"].items():
        item=INDICATOR_BY_CODE[code]
        display=format_value(reading["value"],item.format_kind) if item.format_kind in ("usd","count") else number(reading["value"])
        rows.append({"指标":reading["name"],"年度":str(year),"数值":display,"单位":reading["unit"],"来源":"世界银行 WDI"})
    st.dataframe(pd.DataFrame(rows),hide_index=True,width="stretch")
    with st.expander("摘要设置与发送内容"):
        st.caption("点击生成时，以上年度事实、贸易汇总和独立 IMF 预测及版本信息将发送至 DeepSeek（api.deepseek.com）。"
                   "不发送完整原始快照。服务器密钥从环境变量或 Streamlit Secrets 读取。")
        st.text_input("临时会话密钥（可选）",type="password",key="ai_session_key")
        st.caption("临时密钥只保留在当前会话服务端内存，不写入文件；可主动清除，断开会话后由运行服务释放。")
        st.button("清除临时密钥",on_click=clear_key)
        st.json(facts)
    paid_enabled = os.getenv("ENABLE_PAID_AI", "0") == "1"
    secret=configured_key() if paid_enabled else None
    if not secret:
        st.caption("尚未配置摘要服务。配置可在摘要设置中完成，研究报告和事实摘要可直接阅读。")
    if not paid_enabled:
        st.caption("付费摘要默认关闭。部署者确认费用与发送内容后可启用；本地分析不受影响。")
    st.caption("可选LLM摘要尚未完成真实业务质量评测；输出须逐项人工核对，连接测试和mock不构成质量验收。")
    if st.button("生成解释性摘要",type="primary",disabled=not bool(secret) or not paid_enabled):
        with st.spinner("正在生成摘要……"):
            try:
                result=generate_brief(facts,api_key=secret)
            except (ValueError,RuntimeError,OSError,requests.RequestException) as exc:
                ref=log_failure("DeepSeek 解释性摘要",exc)
                st.error(f"摘要暂时无法生成，请核对服务配置后重试。报告正文仍可使用。诊断编号 {ref}。")
            else:
                st.session_state["report_brief"]={"fingerprint":identity,"text":result,"country":country,"year":year}
    previous=st.session_state.get("report_brief")
    if previous:
        if previous["fingerprint"]==identity:
            st.markdown(previous["text"])
            st.caption("生成内容对应当前报告及来源版本，请逐项对照事实摘要与正文中的来源指标。")
        else:
            st.warning("解释性摘要需要更新：研究对象、参数或数据版本已变化。")
            with st.expander("查看已过期摘要"):
                st.caption(f"旧摘要：{previous['country']} · {previous['year']} 年，不能用于当前报告。")
                st.markdown(previous["text"])


def compare_previous(bundle):
    st.caption("上传同经济体、年度和参照设置的旧版 ZIP。先核验包内文件，再比较来源、样本和原值。")
    previous=st.file_uploader("旧研究包",type="zip",key="previous_research_bundle")
    if previous is None:
        return
    try:
        comparison=compare_with_current(previous.getvalue(),bundle)
    except ValueError:
        st.warning("研究包无法核验或研究参数不同，请选择对应的旧研究包。")
        return
    st.markdown(comparison.markdown)
    with st.expander("查看版本变化"):
        st.dataframe(comparison.source_changes,hide_index=True,width="stretch")
        if comparison.report_diff:
            st.code(comparison.report_diff,language="diff")
    for i,(label,table) in enumerate(comparison.tables.items()):
        with st.expander(f"查看{label}差异"):
            changed=table.loc[table["变化类型"]!="未变化"]
            st.dataframe(changed,hide_index=True,width="stretch")
            st.download_button("下载完整差异 · CSV",comparison_csv_bytes(table),
                               file_name=f"guanlan_revision_{i}.csv",mime="text/csv",key=f"revision_export_{i}")


def cycle_view(store):
    st.subheader("美国周期研究 · 实验模型")
    st.caption("固定研究美国；预测目标为六个月后工业产出指数低于预测起始月，即“六个月工业产出收缩事件”。")
    monthly,monthly_meta=store.get("us_monthly")
    backtest,meta=store.get("us_cycle_backtest")
    if monthly.empty or backtest.empty:
        return
    if meta.get("source_snapshot_utc")!=monthly_meta.get("downloaded_at_utc"):
        raise ValueError("美国官方数据与回测版本不同")
    metrics=meta["metrics"]
    interval=paired_block_brier_interval(backtest)
    delta=interval["brier_difference_model_minus_baseline"]
    if interval["ci_95_upper"]>=0 or not meta.get("validated_for_decision",False):
        st.warning("当前验证状态：尚无稳定优于简单基线、可用于实时决策的证据。")
    st.markdown(f"本次模型 Brier 点估计{'较差' if delta>0 else '较低'}（模型−基线 {delta:+.3f}）；"
                f"描述性 95% 区间 {interval['ci_95_lower']:+.3f} 至 {interval['ci_95_upper']:+.3f}。"
                "Brier 损失越低越好，区间跨零时不据此宣称显著优劣。")
    st.caption("仅使用当前快照中的修订后历史数据，不是实时数据版本回测；各特征发布时间不同。最新模型概率不作为决策信号。")
    st.info("默认参考为训练样本事件频率基线。混合模型未优于基线，图中默认隐藏，可主动展开核查。")
    source_line(monthly_meta,"美国月度序列 · 回顾性试验")
    a,b,c=st.columns(3)
    a.metric("默认基线 Brier",f"{metrics['baseline_brier']:.3f}")
    b.metric("实验模型 Brier",f"{metrics['model_brier']:.3f}")
    c.metric("完整回测评估月份",str(metrics["months"]))
    plot_mode=radio("回测图范围",["完整回测","2010 年以来"],"cycle_plot_range")
    plot=backtest if plot_mode=="完整回测" else backtest.loc[backtest.date>=pd.Timestamp("2010-01-01")]
    st.caption(f"完整回测 {metrics['first_month'][:7]}—{metrics['last_month'][:7]} · {len(backtest)} 个评估月；"
               f"当前图展示 {len(plot)} 个评估月。")
    fig=go.Figure()
    fig.add_trace(go.Scatter(x=plot.date,y=plot.baseline,name="训练样本基线",line=dict(color="#146f7c",width=3)))
    if st.checkbox("显示实验模型",value=False,key="cycle_show_experimental"):
        fig.add_trace(go.Scatter(x=plot.date,y=plot.risk,name="实验模型历史概率",line=dict(color="#967027",dash="dash")))
    events=plot.loc[plot.outcome==1]
    fig.add_trace(go.Scatter(x=events.date,y=[1]*len(events),mode="markers",name="事后工业产出收缩事件",marker=dict(color="#b95d42",size=5)))
    fig.update_layout(height=360,yaxis_range=[0,1.04],yaxis_title="概率 / 事件",xaxis_title="预测起始月份",
                      legend=dict(orientation="h",y=-.25),margin=dict(l=25,r=20,t=20,b=80))
    chart(fig)
    download(plot,"guanlan_us_cycle_current_view.csv","下载当前图表回测数据 · CSV",meta)
    with st.expander("查看验证方法、历史分组与分阶段诊断"):
        signal=meta["signal"]
        st.write(f"最新共同观测月 {signal['as_of'][:7]}；历史状态分组 {signal['state']}，仅用于样本探索。")
        st.write(f"AUC：{number(metrics.get('roc_auc'),precision=3,missing='当前样本不适用')}；"
                 f"事后工业产出收缩事件 {metrics['events']}/{metrics['months']} 个评估月。")
        st.caption(f"目标窗口 {metrics['horizon_months']} 个月；滚动训练窗口最多 {metrics['lookback_months']} 个月。"
                   f"移动块 {interval['block_observations']} 个已评估月，重复 {interval['replications']} 次；"
                   "仅重采样误差，不重新训练，未修正数据修订、模型选择或结构变化。")
        segments=cycle_period_breakdown(backtest)
        st.dataframe(segments.rename(columns={"period":"时期","months":"评估月数","events":"收缩月数",
                     "model_brier":"模型 Brier","baseline_brier":"基线 Brier","difference":"模型减基线"}).round(3),
                     hide_index=True,width="stretch")
        download(backtest,"guanlan_us_cycle_full.csv","下载完整回测 · CSV",meta)
        download(segments,"guanlan_us_cycle_periods.csv","下载分阶段诊断 · CSV",meta)
        st.markdown("直接官方来源：[BLS · 失业率与CPI](https://www.bls.gov/developers/)、"
                    "[美联储 G.17 · 工业产出](https://www.federalreserve.gov/releases/g17/download.htm)、"
                    "[美联储 H.15 · 月均利率](https://www.federalreserve.gov/datadownload/Choose.aspx?rel=H15)。")
        st.caption(monthly_meta.get("source_disclaimer", ""))
    source_details(monthly_meta)
