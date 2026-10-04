from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]


def fresh(task='真实贸易图与情景'):
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=60)
    app.query_params={'view':['intelligence'],'ai_task':[task]}
    return app.run()


def button(app,label):return next(b for b in app.button if b.label==label)


def test_graph_actual_scope_zero_apply_question_refusal_repeat_and_prior_domain():
    app=fresh()
    assert not app.exception and not app.error
    assert len(app.get('download_button'))==3
    assert any('2017—2024' in c.value for c in app.caption)
    for question in ['当前图直接压力','当前图两跳路径分解','当前图HHI集中度','当前图衰减敏感性','证明GDP损失']:
        app.text_input(key='graph_question').set_value(question)
        button(app,'核查图问题').click().run()
        assert not app.exception and not app.error
        assert app.session_state['graph_answer']['answer']['status']==('refused' if '损失' in question else 'answered')
    app.multiselect[0].set_value([]).run()
    button(app,'应用压力情景').click().run()
    assert not app.exception and not app.error
    assert app.session_state['graph_applied']['shocks']=={}
    assert all(float(m.value)==0 for m in list(app.metric)[:3])
    app.selectbox(key='graph_country').set_value('USA').run()
    app.selectbox(key='graph_year').set_value('2023').run()
    assert not app.exception and not app.error
    assert app.query_params['graph_year']=='2023' and app.query_params['graph_country']=='USA'
    app.radio(key='ai_task').set_value('证据问答与工具').run()
    assert not app.exception and app.radio(key='evidence_domain').value=='中国月度'
    app.radio(key='evidence_domain').set_value('真实贸易图').run()
    assert not app.exception and not app.error and len(app.get('download_button'))==3
    app.radio(key='evidence_domain').set_value('中国月度').run()
    assert not app.exception and any('中国七个' in c.value for c in app.caption)


def test_graph_absent_or_corrupt_source_keeps_navigation_and_does_not_call_paid_api(monkeypatch):
    from guanlan.ui import trade_graph
    from guanlan import ai
    def invalid(*args,**kwargs):raise ValueError('fixture invalid graph')
    def paid(*args,**kwargs):raise AssertionError('paid request forbidden')
    monkeypatch.setattr(trade_graph,'get_graph',invalid)
    monkeypatch.setattr(ai,'_post',paid)
    app=fresh()
    assert not app.exception and not app.error
    assert any('校验失败' in w.value for w in app.warning)
    assert not app.get('download_button')
    app.radio(key='research_navigation').set_value('中国观察').run()
    assert not app.exception and not app.error
