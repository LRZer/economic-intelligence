from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]


def fresh(query):
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=90)
    app.query_params={key:[value] for key,value in query.items()}
    return app.run()


def healthy(app):
    assert not app.exception and not app.error


def test_monthly_source_audit_and_question_preserve_indicator_round_trip():
    with patch('requests.post',side_effect=AssertionError('No paid calls')):
        app=fresh({'view':'china','china_indicator':'ppi_mom'})
        healthy(app)
        app.button(key='china_analyze_current').click().run();healthy(app)
        assert app.selectbox(key='ai_indicator').value=='ppi_mom'
        app.button(key='monthly_open_source').click().run();healthy(app)
        assert app.selectbox(key='china_indicator').value=='ppi_mom'
        app.button(key='china_analyze_current').click().run();healthy(app)
        app.button(key='monthly_open_chronos').click().run();healthy(app)
        assert app.selectbox(key='chronos_indicator').value=='ppi_mom'
        app.button(key='chronos_open_monthly').click().run();healthy(app)
        assert app.selectbox(key='ai_indicator').value=='ppi_mom'
        app.button(key='monthly_open_assistant').click().run();healthy(app)
        assert 'PPI环比' in app.text_input(key='assistant_question').value
        next(b for b in app.button if b.label=='核查问题').click().run();healthy(app)
        answer=app.session_state['assistant_answer']['answer']
        assert answer['status']=='answered' and answer['scope']['key']=='ppi_mom'


def test_sector_input_year_graph_handoff_and_applied_scenario_round_trip():
    app=fresh({'view':'intelligence','ai_task':'宏观与行业风险研究','sector_year':'2025','country':'USA','hs2':'85'})
    healthy(app)
    app.button(key='sector_open_graph').click().run();healthy(app)
    assert app.selectbox(key='graph_year').value=='2024'
    assert app.selectbox(key='graph_country').value=='USA' and app.selectbox(key='graph_hs2').value=='85'
    prior=dict(app.session_state['graph_applied'])
    app.button(key='graph_open_sector').click().run();healthy(app)
    assert app.selectbox(key='sector_year').value=='2025' and app.selectbox(key='sector_country').value=='USA'
    app.button(key='sector_open_graph').click().run();healthy(app)
    assert app.session_state['graph_applied']==prior
    app.selectbox(key='graph_year').set_value('2017').run();healthy(app)
    assert app.button(key='graph_open_sector').disabled


def test_graph_research_independent_of_missing_model_snapshot(monkeypatch):
    from guanlan.ui.common import DataStore
    old=DataStore.get
    def missing(self,stem,**kwargs):
        return (pd.DataFrame(),{}) if stem.startswith('sector_') else old(self,stem,**kwargs)
    monkeypatch.setattr(DataStore,'get',missing)
    app=fresh({'view':'intelligence','ai_task':'真实贸易图与情景'})
    healthy(app)
    assert app.button(key='graph_open_sector').disabled
    assert len(app.get('download_button'))==3


def test_disabled_research_summary_does_not_lookup_any_credentials(monkeypatch):
    monkeypatch.setenv('ENABLE_PAID_AI','0')
    with patch('guanlan.ui.research.configured_key',side_effect=AssertionError('Credential lookup forbidden')):
        app=fresh({'view':'research','country':'CHN','year':'2024'})
        healthy(app)
        assert next(b for b in app.button if b.label=='生成解释性摘要').disabled
