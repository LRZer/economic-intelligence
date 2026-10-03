import json
import hashlib
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from guanlan.panel_ai import evaluate
from guanlan.panel_benchmark import dataset as reference_dataset
from guanlan.catalog import country_label
from .common import ROOT, chart, select, source_line


@st.cache_data(show_spinner=False, max_entries=4)
def cached_panel(frame, digest):
    return evaluate(frame)


def render(store):
    frame, meta = store.get("macro")
    if frame.empty:
        st.info("未安装可校验的WDI快照，全球模型暂不可用。")
        return
    source_line(meta, "CC BY 4.0默认许可；保留来源归属")
    with st.spinner("计算跨国年度时间顺序回测…"):
        result = cached_panel(frame, meta.get("parquet_sha256", ""))
    if result["status"] != "evaluated":
        st.info(result.get("reason","样本不足"));return
    a,b,c = st.columns(3)
    a.metric("留出模型MAE（百分点）", f"{result['test']['prediction']['mae']:.3f}")
    b.metric("上年GDP增速基线MAE", f"{result['test']['baseline']['mae']:.3f}")
    c.metric("留出国家 / 观测", f"{result['test_countries']} / {result['test']['prediction']['n']}")
    st.caption("模型：直方图梯度提升树。每年仅训练此前年度标签；开发期2015—2019，固定留出期2020—2024。缺失特征由树原生处理，目标标签不填补。")
    st.warning("WDI为当前修订版，特征发布日未构成实时可用性保证；本结果不代表可实施的实时预测。")
    if not result['passes_research_gate']:
        failures=[str(r['year']) for r in result['yearly_metrics'] if r['prediction']['mae']>=r['baseline']['mae']]
        st.info(f"未通过逐年度研究门槛；未优于基线年度：{', '.join(failures)}。90%经验带实际留出覆盖 {result['test_interval_coverage']:.1%}。完整失败与覆盖结果保留。")
    else:
        st.success("通过逐年度基线研究检查；仍需独立时期与实时版次验证。")
    reference_path=ROOT/'docs/validation/wdi-reference-benchmark.json'
    if reference_path.exists():
        reference=json.loads(reference_path.read_text(encoding='utf-8'))
        if reference['snapshot_hash']==hashlib.sha256(pd.util.hash_pandas_object(reference_dataset(frame),index=True).values.tobytes()).hexdigest():
            st.subheader('补充强对照 · 已见历史时期的有限重检')
            st.dataframe(pd.DataFrame([{'方法':m,**v} for m,v in reference['test'].items()]),hide_index=True,width='stretch')
            st.info('五年中位数在总体留出期的 MAE 低于梯度提升模型；开发期选定参考为 ridge10，未按留出结果更换赢家。补充对照不是新的未触碰留出实验。')
            st.caption('未见国家诊断与逐年度门槛未通过；2025附加历史年成绩也不能替代原失败门槛。')
    rows = pd.DataFrame(result['backtest'])
    codes = sorted(rows.country_code.unique())
    names = frame.drop_duplicates('country_code').set_index('country_code').country_name.to_dict()
    country = select("研究经济体", codes, "panel_country", "CHN", format_func=lambda c:country_label(c,names.get(c,c)))
    country_rows=rows.loc[rows.country_code==country]
    figure=go.Figure()
    for field,label,color in [('actual','官方实际GDP增速','#172d3b'),('prediction','梯度提升逐期估计','#146f7c'),('baseline','上年值基线','#b95d42')]:
        figure.add_trace(go.Scatter(x=country_rows.year,y=country_rows[field],name=label,mode='lines+markers',line={'color':color}))
    figure.add_vline(x=2019.5,line_dash='dash',line_color='#83939a')
    figure.update_layout(title=f"{country_label(country,names.get(country,country))} · 年度GDP回测",yaxis_title='%',height=420,
                         legend={'orientation':'h','y':-.2,'x':0},margin={'l':45,'r':20,'t':65,'b':95})
    chart(figure)
    st.caption(f"开发误差90%经验带半径 {result['interval_radius']:.3f} 个百分点；留出覆盖 {result['test_interval_coverage']:.1%}。样本的国家相关性与结构变化未消除。")
    diagnostic=pd.DataFrame([{'年度':r['year'],'观测数':r['prediction']['n'],'模型MAE':r['prediction']['mae'],
                              '基线MAE':r['baseline']['mae'],'模型减基线':r['prediction']['mae']-r['baseline']['mae']}
                             for r in result['yearly_metrics']])
    st.dataframe(diagnostic.round(3),hide_index=True,width='stretch')
    importance=pd.DataFrame({'特征':list(result.get('development_feature_importance',{})),
                             '开发期置换导致MAE增加':list(result.get('development_feature_importance',{}).values())})
    st.dataframe(importance,hide_index=True,width='stretch')
    st.caption("解释来自2019年开发样本的置换重要性；负值表示该特征在这段样本没有可见帮助，不表示因果。")
    with st.expander("逐年度诊断与训练边界"):
        st.json(result['yearly_metrics'])
        st.dataframe(country_rows,hide_index=True,width='stretch')
        st.code(result['snapshot_hash'],language=None)
    future=pd.DataFrame(result.get('next_year_research',[]))
    if not future.empty and country in future.country_code.values:
        f=future.loc[future.country_code==country].iloc[0]
        st.write(f"下一观测年度研究估计：{int(f.year)} 年 {f.prediction:.2f}% · 经验带 [{f.lower:.2f}, {f.upper:.2f}]。训练标签截至 {int(f.train_end)} 年。")
        st.caption(f"该经济体有 {int(f.missing_features)} 个缺失特征；估计是否仍属未来须与当前日期、官方发布核对。")
    st.download_button("下载全球逐期回测CSV", rows.to_csv(index=False).encode('utf-8-sig'),file_name='wdi-panel-backtest.csv',mime='text/csv')
    st.download_button("下载全球模型审计JSON",json.dumps(result,ensure_ascii=False,indent=2).encode(),file_name='wdi-panel-ai.json',mime='application/json')
