"""Explicit context-preserving handoffs between existing research tasks."""
from __future__ import annotations

import streamlit as st

TASKS = {'宏观与行业风险研究', '中国月度预测与异常', '证据问答与工具', '真实贸易图与情景', '时序基础模型审计'}
FIELDS = {'china_indicator','china_view','ai_indicator','chronos_indicator','assistant_question','evidence_domain','sector_year','sector_country','sector_hs2','graph_year','graph_country','graph_hs2'}


def navigate(view: str, *, task: str | None = None, **selection) -> None:
    if view not in ('china','intelligence') or (view == 'intelligence' and task not in TASKS) or not set(selection) <= FIELDS:
        raise ValueError('Unsupported research handoff')
    st.session_state['research_navigation'] = '中国观察' if view == 'china' else '风险研究'
    if task:
        st.session_state['ai_task'] = task
        st.session_state['saved_ai_task'] = task
    for key,value in selection.items():
        st.session_state[key] = value
        st.session_state['saved_'+key] = value
    # Query state is subsequently rendered by the destination task; widget
    # callbacks run before the next script, preserving both restored and live keys.
    st.query_params.from_dict({'view':view, **({'ai_task':task} if task else {}), **{k:str(v) for k,v in selection.items()}})


def sector_to_graph(year: int, country: str, hs2: str) -> None:
    st.caption(f'模型输入年份为 {year}；可核查同年同国家、行业的完整已报告贸易图。')
    st.button(f'核查 {year} 年真实伙伴图', key='sector_open_graph', on_click=navigate,
              args=('intelligence',), kwargs={'task':'真实贸易图与情景','graph_year':str(year),'graph_country':country,'graph_hs2':hs2})


def graph_to_sector(store, year: int, country: str, hs2: str) -> None:
    target = year + 1
    frames = [store.get(stem,quiet=True)[0] for stem in ('sector_latest','sector_backtest')]
    available = any(not frame.empty and bool(((frame.year==target)&(frame.country_code==country)&(frame.hs2==hs2)).any()) for frame in frames)
    st.button(f'查看 {target} 年同对象行业研究', key='graph_open_sector', disabled=not available,
              on_click=navigate,args=('intelligence',),kwargs={'task':'宏观与行业风险研究','sector_year':str(target),'sector_country':country,'sector_hs2':hs2})
    if not available:
        st.caption('该年份、国家和行业没有已保存的合格模型记录；真实贸易图仍可独立核查。')
    else:
        st.caption('目标年对应当前贸易图的下一年；回到已保存模型记录，不重新训练或改变压力情景。')
