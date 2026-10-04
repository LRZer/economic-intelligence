from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]


def fresh():
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=40)
    app.query_params={'view':['intelligence'],'ai_task':['宏观与行业风险研究']}
    return app.run()


def test_sector_normal_repeated_selection_and_preselected_reference():
    app=fresh()
    assert not app.exception and not app.error
    assert any('全样本历史事件率' in x.value for x in app.caption)
    assert any('逻辑回归' in x.value for x in app.caption)
    assert len(app.get('download_button'))==3
    for _ in range(2):
        app.selectbox(key='sector_country').set_value('USA').run()
        app.slider(key='sector_shock').set_value(-4.).run()
        assert not app.exception and not app.error
        assert app.query_params['country']=='USA'
        app.radio(key='ai_task').set_value('中国月度预测与异常').run()
        assert not app.exception and not app.error
        app.radio(key='ai_task').set_value('宏观与行业风险研究').run()
        assert app.selectbox(key='sector_country').value=='USA'
    assert not any(b.label.startswith('生成') and not b.disabled for b in app.button)


def test_sector_missing_source_remains_navigable(monkeypatch):
    from guanlan.ui.common import DataStore
    original=DataStore.get
    def absent(self,stem,**kwargs):
        return (pd.DataFrame(),{}) if stem.startswith('sector_') else original(self,stem,**kwargs)
    monkeypatch.setattr(DataStore,'get',absent)
    app=fresh()
    assert not app.exception and not app.error
    assert any('尚未安装' in x.value for x in app.info)
    app.radio(key='research_navigation').set_value('经济体概览').run()
    assert not app.exception and not app.error and app.metric


def test_sector_corrupt_network_exposes_safe_error_and_other_pages_work(monkeypatch):
    from guanlan.ui import sector
    def corrupt(*args):raise ValueError('fixture corrupted network')
    monkeypatch.setattr(sector,'network_partition',corrupt)
    app=fresh()
    assert not app.exception
    assert any('诊断编号' in x.value for x in app.error)
    app.radio(key='research_navigation').set_value('中国观察').run()
    assert not app.exception and not app.error


def test_sector_historical_year_peer_switching_and_no_future_history():
    app=fresh()
    for year in ['2023','2024','2025','2023']:
        app.selectbox(key='sector_year').set_value(year).run()
        assert not app.exception and not app.error
        assert app.query_params['sector_year']==year
        assert any('输入期别 '+str(int(year)-1) in x.value for x in app.caption)
        app.radio(key='sector_lens').set_value('同一行业 · 跨国家').run()
        app.selectbox(key='sector_country').set_value('USA').run()
        assert not app.exception and not app.error
        app.radio(key='sector_lens').set_value('同一国家 · 跨行业').run()
        assert not app.exception and not app.error
    assert len(app.get('download_button'))==3


def test_sector_latest_missing_still_supports_historical_research(monkeypatch):
    from guanlan.ui.common import DataStore
    original=DataStore.get
    def absent(self,stem,**kwargs):
        return (pd.DataFrame(),{}) if stem=="sector_latest" else original(self,stem,**kwargs)
    monkeypatch.setattr(DataStore,"get",absent)
    app=fresh()
    assert not app.exception and not app.error
    assert app.selectbox(key="sector_year").value=="2024"
    assert any("仍可查看" in x.value for x in app.info)
    assert len(app.get("download_button"))==3


def test_sector_missing_dataset_fingerprint_fails_closed_and_navigation_recovers(monkeypatch):
    from guanlan.ui.common import DataStore
    original=DataStore.get
    def absent(self,stem,**kwargs):
        frame,metadata=original(self,stem,**kwargs)
        if stem.startswith("sector_"):
            metadata=dict(metadata);metadata.pop("dataset_hash",None)
        return frame,metadata
    monkeypatch.setattr(DataStore,"get",absent)
    app=fresh()
    assert not app.exception and any("诊断编号" in e.value for e in app.error)
    app.radio(key="research_navigation").set_value("经济体概览").run()
    assert not app.exception and not app.error and app.metric
