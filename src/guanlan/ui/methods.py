import streamlit as st
import pandas as pd
from guanlan.analytics import observation_summary, country_observation_status, format_value
from guanlan.catalog import INDICATORS, INDICATOR_BY_CODE
from guanlan.data import refresh_audit
from .common import header, SOURCE_NAMES, date_label, macro_selection, sync_query


def render(store):
    header("数据与方法", "先检查来源状态、有效时点与覆盖限制，再解释读数")
    stems=["macro","weo","bis_policy","bis_credit","bis_eer","baci_partner","baci_chapter","us_monthly","us_cycle_backtest","sector_features","sector_backtest","sector_latest"]
    rows=[]
    for stem in stems:
        frame,meta=store.get(stem,quiet=True)
        if frame.empty:
            status=store.errors.get(stem,("未加载",))[0]
            scope="不可用"
        else:
            status="已加载并校验"
            if "year" in frame:
                scope=f"{int(frame.year.min())}—{int(frame.year.max())}"
            elif "date" in frame:
                scope=f"{frame.date.min():%Y-%m}—{frame.date.max():%Y-%m}"
            else:
                scope="详见数据详情"
        rows.append({"来源":SOURCE_NAMES[stem],"状态":status,"数据范围":scope,
                     "版本":meta.get("vintage") or meta.get("release") or date_label(meta),"快照日期":date_label(meta)})
    st.subheader("已加载来源与数据时点")
    st.dataframe(pd.DataFrame(rows),hide_index=True,width="stretch")
    for stem in store.errors:
        store.get(stem)
    selection=macro_selection(store,"methods",year_label="覆盖检查年度",country_label_text="检查经济体")
    if selection is None:
        sync_query(view="methods")
        return
    macro,meta,country,year,names=selection
    sync_query(view="methods",country=country,year=year)
    coverage=observation_summary(macro,year)
    low=coverage.loc[coverage.coverage_pct<50].sort_values("coverage_pct")
    if not low.empty:
        st.warning(f"{year} 年覆盖限制："+"；".join(f"{r.indicator} {r.coverage_pct:.1f}%" for r in low.itertuples())+
                   "。中位数只基于有值样本，不能代表全部经济体。")
    st.subheader(f"{year} 年 WDI 指标覆盖")
    current=macro.loc[macro.year==year]
    a,b,c=st.columns(3)
    a.metric("本年经济体集合",str(current.country_code.nunique()))
    b.metric("本年有效指标观测",f"{int(current.value.notna().sum()):,}")
    c.metric("全部历史有效指标观测",f"{int(macro.value.notna().sum()):,}")
    st.caption(f"全部历史统计范围 {int(macro.year.min())}—{int(macro.year.max())} 年；一条观测是一个经济体×一个年度×一个指标。")
    formatted=[]
    for row in coverage.itertuples():
        item=INDICATOR_BY_CODE[row.indicator_code]
        formatted.append({"指标":item.name,"有效经济体":row.observed,"覆盖率":f"{row.coverage_pct:.1f}%",
                          "有效样本中位数":format_value(row.median,item.format_kind),"单位":item.unit})
    st.dataframe(pd.DataFrame(formatted),hide_index=True,width="stretch")
    with st.expander("查看所选经济体逐指标状态"):
        status=country_observation_status(macro,country,year)
        status["状态"]=status.has_observation.map({True:"该年有效观测",False:"本年无记录，来源未提供原因"})
        status["截至所选年度最近有值年"]=status.latest_observed_year_through_selection.map(
            lambda v:str(int(v)) if pd.notna(v) else "来源未提供该序列")
        st.dataframe(status[["indicator","状态","截至所选年度最近有值年"]].rename(columns={"indicator":"指标"}),
                     hide_index=True,width="stretch")
    with st.expander("查看指标字典与来源校验值"):
        st.dataframe(pd.DataFrame([{"指标":i.name,"代码":i.code,"单位":i.unit,"定义":i.definition,
                                    "比较口径":i.comparison_note,"来源":i.source_url} for i in INDICATORS]),
                     hide_index=True,width="stretch")
        for stem in stems:
            _,metadata=store.get(stem,quiet=True)
            if metadata:
                st.markdown(f"**{SOURCE_NAMES[stem]}**")
                st.json(metadata)
    with st.expander("查看刷新与版本切换记录"):
        audit=refresh_audit()
        if audit.empty:
            st.caption("当前使用随附快照，尚无本地批次刷新记录。")
        else:
            audit["北京时间"]=pd.to_datetime(audit.at_utc,utc=True).dt.tz_convert("Asia/Shanghai").dt.strftime("%Y-%m-%d %H:%M")
            audit["状态"]=audit.status.map({"published":"已发布","failed":"失败","restored":"已回退"})
            st.dataframe(audit[["北京时间","状态","operation","batch_id"]].rename(columns={"operation":"操作","batch_id":"批次编号"}),
                         hide_index=True,width="stretch")
    st.caption("缺失值不插补；同组分类来自当前快照，未恢复历史分类。预测和历史观测独立展示，"
               "复现时须保留数据快照、指标代码、来源和筛选参数。")
