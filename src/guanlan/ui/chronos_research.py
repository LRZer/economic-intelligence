"""Foundation model audit workbench; model execution stays outside the app."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from guanlan.chronos_report import KEYS, LABELS, METHODS, csv_rows, export_audit, load_packaged_audit
from .common import chart, initial_query, select, sync_query
from .workflow import navigate


@st.cache_data(show_spinner=False, max_entries=2)
def audit_bundle():
    return load_packaged_audit()


def render(store):
    sync_query(view='intelligence', ai_task='时序基础模型审计')
    st.subheader('时序基础模型 · 固定协议审计')
    st.caption('Chronos-2-Synth · 官方月度数据 · 固定权重零样本预测 · 四项基线同窗比较')
    try:
        with st.spinner('校验真实数据、历史边界与已记录指标…'):
            report, protocol, provenance = audit_bundle()
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError):
        st.warning('审计结果缺失或校验失败，暂不展示模型结论。可继续使用其他研究任务；安装完整发行包后重新核查。')
        if st.button('重新核查审计结果', key='chronos_retry'):
            audit_bundle.clear(); st.rerun()
        return
    st.warning('这是当前修订版历史快照的回顾实验：历史标签已被查看，缺少逐期首次发布版本。不能作为盲测、实时预测或交易信号。')
    if report['descriptive_retrospective_screen']:
        st.success('通过预先固定的描述性回顾门槛。仍需新的独立时期与实时数据版本验证；生产默认参考保持原研究基线。')
    else:
        st.info('未通过预先固定的描述性回顾门槛。全部结果保留；生产默认参考保持原研究基线。')
    a, b, c, d = st.columns(4)
    a.metric('真实模型审计预测', '84 / 84')
    b.metric('开发期模型预测', '0')
    c.metric('模型宏观 MASE', f"{report['macro_equal_indicator_mase']['challenger']:.3f}")
    d.metric('优于开发期参考的指标', f"{report['indicators_beating_development_reference']} / 7")
    st.caption('审计期：2025-09—2026-08。开发期：2024-09—2025-08，仅用于预选基线；没有模型调参或微调。')
    overview = pd.DataFrame([{'方法': METHODS[method], '等权宏观 MASE': value}
                             for method, value in report['macro_equal_indicator_mase'].items()])
    st.dataframe(overview, hide_index=True, width='stretch')
    st.caption('每项先用该预测时点历史前缀的季节差值归一化，再对七项等权。没有混合百分比与指数点的原始误差。')
    key = select('审计指标', list(KEYS), 'chronos_indicator', initial_query('chronos_indicator', 'cpi_yoy'), format_func=lambda x: LABELS[x])
    sync_query(view='intelligence', ai_task='时序基础模型审计', chronos_indicator=key)
    st.button("打开该指标当前月度研究", key="chronos_open_monthly", on_click=navigate, args=("intelligence",), kwargs={"task":"中国月度预测与异常","ai_indicator":key})
    reference = report['audit_references'][key]
    scores = report['audit_metrics'][key]
    diagnostic = report['interval_diagnostics'][key]
    unit = '百分点' if key in ('cpi_yoy', 'ppi_yoy', 'cpi_mom', 'ppi_mom') else '指数点'
    st.markdown(f'**{LABELS[key]}** · 同窗 12 个月 · 开发期预选参考：{METHODS[reference]}')
    a, b, c = st.columns(3)
    a.metric(f'模型 MAE（{unit}）', f"{scores['challenger']['mae']:.3f}")
    b.metric(f'参考 MAE（{unit}）', f"{scores[reference]['mae']:.3f}")
    c.metric('80% 分位数带实际覆盖', f"{diagnostic['coverage']:.1%}")
    records = [r for r in report['records']['audit'] if r['key'] == key]
    periods = [r['target'] for r in records]
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=periods, y=[r['quantiles']['p90'] for r in records], mode='lines', line={'width': 0}, showlegend=False, hoverinfo='skip'))
    figure.add_trace(go.Scatter(x=periods, y=[r['quantiles']['p10'] for r in records], mode='lines', line={'width': 0}, fill='tonexty', fillcolor='rgba(20,111,124,.12)', name='原生 p10—p90'))
    for label, values, color, dash in [
        ('官方观测', [r['actual'] for r in records], '#172d3b', 'solid'),
        ('Chronos p50', [r['quantiles']['p50'] for r in records], '#146f7c', 'solid'),
        (f'开发期参考 · {METHODS[reference]}', [r['predictions'][reference] for r in records], '#b95d42', 'dot'),
    ]:
        figure.add_trace(go.Scatter(x=periods, y=values, mode='lines+markers', name=label, line={'color': color, 'dash': dash, 'width': 2}))
    figure.update_layout(title=f'{LABELS[key]} · 单步回顾预测', yaxis_title=unit, height=430,
                         legend={'orientation': 'h', 'y': -.22, 'x': 0}, margin={'l': 40, 'r': 15, 't': 65, 'b': 115})
    chart(figure)
    st.caption('p50 是固定点预测；p10—p90 为未经本经济快照校准的原生分位数带，不保证未来 80% 覆盖。')
    lo, hi = report['paired_block_descriptive_95']['indicator_vs_baselines'][key][reference]
    macro_lo, macro_hi = report['paired_block_descriptive_95']['macro_vs_development_reference']
    st.caption(f'模型减参考的归一化绝对误差：当前指标描述性 95% 区间 [{lo:.3f}, {hi:.3f}]；七项等权 [{macro_lo:.3f}, {macro_hi:.3f}]。三月循环块、2000 次、seed42；小样本描述，不是显著性检验。')
    with st.expander('训练边界、时间切片与复现证据'):
        st.write('Chronos 审计预测只收到统计期之前的 48—59 个历史观测；开发期基线使用 36—47 个。目标实际值在预测返回后加入评分。每项独立、horizon=1、batch=1；无协变量、跨指标学习或微调。')
        st.dataframe(pd.DataFrame(csv_rows(report, key=key)), hide_index=True, width='stretch')
        st.dataframe(pd.DataFrame([{'切片': label, '方法': METHODS[method], **metric}
                                   for label, metrics in report['time_slices'][key].items() for method, metric in metrics.items()]), hide_index=True, width='stretch')
        st.write('2025 年末与 2026 年分别核查；不能把当前修订版本当作首次发布版本。')
        st.json({'模型': provenance['model_id'], '固定 revision': provenance['revision'],
                 '权重 SHA-256': provenance['weights_sha256'], 'CPU 环境依赖锁 SHA-256': provenance['requirements_sha256'],
                 '科学协议 SHA-256': provenance['protocol_sha256'], '报告指纹': report['report_id'],
                 '实际运行秒数': provenance['audit_elapsed_seconds'], '实际计算线程': 4})
        st.caption('页面离线重算基线、指标和历史边界，不重新执行基础模型。运行来源的依据另存为模型文件哈希、固定依赖与本机运行记录。')
    exported = export_audit(report, protocol, provenance)
    for extension, label, mime in [('html', '下载基础模型审计 HTML', 'text/html'), ('json', '下载基础模型审计 JSON', 'application/json'), ('csv', '下载基础模型逐期 CSV', 'text/csv')]:
        st.download_button(label, exported[extension], file_name=f'chronos-synth-audit-{report["report_id"][:12]}.{extension}', mime=mime, on_click='ignore')
    st.caption('界面展示本机已执行结果，不需要安装 PyTorch，也不发起模型下载或付费 API 请求。')
