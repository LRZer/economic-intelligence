from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]


def fresh():
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=40)
    app.query_params={'view':['intelligence'],'ai_task':['证据问答与工具']}
    return app.run()


def submit(app,question):
    app.text_input(key='assistant_question').set_value(question)
    next(button for button in app.button if button.label=='核查问题').click().run()
    return app


def test_research_qa_normal_refused_and_repeated_no_api_or_key_lookup(monkeypatch):
    monkeypatch.setenv('ENABLE_PAID_AI','0')
    with patch('requests.post') as post,patch('guanlan.ui.research.configured_key',side_effect=AssertionError('No key lookup')):
        app=fresh()
        for q in ['CPI同比最新官方读数是多少？','CPI同比在2026-07与2026-08的差值是多少？','为什么CPI同比变化？','CPI同比最新官方读数是多少？']:
            submit(app,q)
            assert not app.exception and not app.error
            assert len(app.get('download_button'))==3
            assert app.session_state['assistant_answer']['answer']['question']==q
        assert not any(button.label.startswith('生成') for button in app.button)
    post.assert_not_called()


def test_empty_data_explained_and_other_task_remains_usable(monkeypatch):
    from guanlan.ui import evidence_assistant
    monkeypatch.setattr(evidence_assistant,'load_dashboard',lambda:{'series':{}})
    app=fresh()
    assert not app.exception and any('没有可用' in warning.value for warning in app.warning)
    app.radio(key='ai_task').set_value('宏观与行业风险研究').run()
    assert not app.exception and not app.error
