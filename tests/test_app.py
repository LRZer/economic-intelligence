import json
from pathlib import Path
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / 'app.py'


def fresh(query=None):
    app = AppTest.from_file(str(APP), default_timeout=40)
    app.query_params = {key: [str(value)] for key, value in (query or {'view':'overview'}).items()}
    return app.run()


def healthy(app):
    assert not app.exception, [e.message for e in app.exception]
    assert not app.error, [e.value for e in app.error]


def test_six_pages_and_all_task_views_render():
    app = fresh()
    assert len(app.radio(key='research_navigation').options) == 8
    for page in app.radio(key='research_navigation').options:
        app.radio(key='research_navigation').set_value(page).run()
        healthy(app)
        if page == '跨国比较':
            for view in app.radio(key='compare_view').options:
                app.radio(key='compare_view').set_value(view).run()
                healthy(app)
        if page == '金融条件':
            for topic in app.radio(key='financial_topic').options:
                app.radio(key='financial_topic').set_value(topic).run()
                healthy(app)
        if page == '研究':
            app.radio(key='research_view').set_value('模型实验').run()
            healthy(app)
        if page == '贸易结构':
            app.radio(key='trade_topic').set_value('商品结构').run()
            healthy(app)


def test_complete_navigation_preserves_scoped_state_and_report_parameters(monkeypatch):
    from guanlan.ui import research
    bundles = []
    original = research.build_research_bundle
    def capture(*args, **kwargs):
        bundle = original(*args, **kwargs)
        bundles.append(bundle)
        return bundle
    monkeypatch.setattr(research, 'build_research_bundle', capture)
    app = fresh({'view': 'overview', 'country': 'USA', 'year': 2023})
    app.selectbox(key='overview_year').set_value(2022).run()
    app.radio(key='research_navigation').set_value('跨国比较').run()
    healthy(app)
    assert app.selectbox(key='compare_country').value == 'USA'
    assert app.selectbox(key='compare_year').value == 2022
    app.radio(key='research_navigation').set_value('贸易结构').run()
    healthy(app)
    assert app.selectbox(key='trade_country').value == 'USA'
    assert app.selectbox(key='trade_year').value == 2022
    assert 'overview_country' not in [e.key for e in app.selectbox]
    app.radio(key='trade_flow').set_value('进口').run()
    assert app.query_params['flow'] == '进口'
    app.radio(key='research_navigation').set_value('研究').run()
    healthy(app)
    assert bundles[-1].manifest['selection']['country_code'] == 'USA'
    assert bundles[-1].manifest['selection']['year'] == 2022
    assert 'flow' not in app.query_params
    assert '美国（USA）' in bundles[-1].markdown
    assert '2022 年' in bundles[-1].markdown
    app.radio(key='research_navigation').set_value('经济体概览').run()
    healthy(app)
    assert app.selectbox(key='overview_country').value == 'USA'
    assert app.selectbox(key='overview_year').value == 2022


def test_legacy_imf_link_and_forecast_filters_are_isolated():
    app = fresh({'view':'outlook','country':'GUY','weo_indicator':'GGXWDG_NGDP','weo_year':2029})
    healthy(app)
    assert app.radio(key='research_navigation').value == '跨国比较'
    assert app.radio(key='compare_view').value == 'IMF预测'
    assert app.selectbox(key='outlook_country').value == 'GUY'
    assert app.selectbox(key='outlook_indicator').value == 'GGXWDG_NGDP'
    assert app.selectbox(key='outlook_year').value == 2029
    assert 'compare_year' not in [e.key for e in app.selectbox]
    assert app.query_params['weo_year'] == '2029'


def test_old_url_cannot_revert_current_navigation():
    app = fresh({'view':'outlook'})
    app.radio(key='research_navigation').set_value('贸易结构').run()
    app.query_params['view'] = ['outlook']
    app.run()
    healthy(app)
    assert app.radio(key='research_navigation').value == '贸易结构'
    assert app.query_params['view'] == 'trade'


def test_profile_selection_and_color_mode():
    app = fresh({'view':'compare','compare_view':'多指标与同组参照','peers':'CHN,USA,DEU',
                 'profile':'NY.GDP.MKTP.KD.ZG,FP.CPI.TOTL.ZG'})
    healthy(app)
    assert len(app.multiselect(key='compare_peers').value) == 3
    assert len(app.multiselect(key='macro_profile_indicators').value) == 2
    figures = [json.loads(e.proto.spec) for e in app.get('plotly_chart')]
    heatmap = next(t for f in figures for t in f['data'] if t['type']=='heatmap')
    assert len(heatmap['x']) == 2 and len(heatmap['y']) == 3
    assert heatmap['showscale'] is False
    app.radio(key='profile_display').set_value('数值百分位').run()
    healthy(app)
    figures = [json.loads(e.proto.spec) for e in app.get('plotly_chart')]
    heatmap = next(t for f in figures for t in f['data'] if t['type']=='heatmap')
    assert heatmap['showscale'] is True


def test_model_view_has_no_irrelevant_country_or_year_controls():
    app = fresh({'view':'cycle','country':'CHN','year':2024})
    healthy(app)
    assert app.radio(key='research_view').value == '模型实验'
    assert not app.selectbox
    assert any('尚无稳定优于简单基线' in w.value for w in app.warning)
    assert any('当前图展示 295 个评估月' in c.value for c in app.caption)
    assert 'country' not in app.query_params and 'year' not in app.query_params


def test_corrupt_financial_source_does_not_block_overview_or_other_financial_modules(monkeypatch):
    from guanlan.ui import common
    original = common.cached_snapshot
    def fail_policy(stem, *args):
        if stem == 'bis_policy':
            raise ValueError('test corrupt snapshot')
        return original(stem, *args)
    monkeypatch.setattr(common, 'cached_snapshot', fail_policy)
    app = fresh()
    healthy(app)
    assert len(app.metric) == 4
    app.radio(key='research_navigation').set_value('金融条件').run()
    assert any('快照无法校验' in w.value for w in app.warning)
    assert not app.exception
    app.radio(key='financial_topic').set_value('信贷与GDP').run()
    healthy(app)
    assert app.get('plotly_chart')


def test_ai_brief_becomes_stale_after_selection_change(monkeypatch):
    from guanlan.ui import research
    sent = []
    def fake_generate(facts, api_key):
        sent.append(facts)
        return '测试解释性摘要'
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-only-key')
    monkeypatch.setenv('ENABLE_PAID_AI', '1')
    monkeypatch.setattr(research, 'generate_brief', fake_generate)
    app = fresh({'view':'report','country':'CHN','year':2024})
    healthy(app)
    next(b for b in app.button if b.label=='生成解释性摘要').click().run()
    healthy(app)
    assert sent[-1]['year'] == 2024
    assert sent[-1]['source_versions']['wdi']['parquet_sha256']
    app.selectbox(key='report_year').set_value(2023).run()
    healthy(app)
    assert any('解释性摘要需要更新' in w.value for w in app.warning)


def test_unavailable_trade_year_is_explained_and_matches_active_context():
    app = fresh({'view': 'overview', 'country': 'USA', 'year': 2000})
    app.radio(key='research_navigation').set_value('贸易结构').run()
    healthy(app)
    assert app.selectbox(key='trade_country').value == 'USA'
    assert app.selectbox(key='trade_year').value == 2024
    assert app.query_params['year'] == '2024'
    assert any('贸易快照不包含 2000 年' in notice.value for notice in app.info)


def test_unavailable_inherited_macro_context_is_explained():
    app = AppTest.from_file(str(APP), default_timeout=40)
    app.query_params = {'view': ['report']}
    app.session_state['research_selection'] = {'country': 'UNKNOWN', 'year': 1990}
    app.run()
    healthy(app)
    assert app.selectbox(key='report_country').value == 'CHN'
    assert app.selectbox(key='report_year').value == 2025
    assert app.query_params['country'] == 'CHN'
    assert app.query_params['year'] == '2025'
    assert any('不在本页 WDI 快照' in notice.value for notice in app.info)
    assert any('不包含 1990 年' in notice.value for notice in app.info)
