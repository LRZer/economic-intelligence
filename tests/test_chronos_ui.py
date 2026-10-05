from pathlib import Path
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def fresh():
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=90)
    app.query_params = {'view': ['intelligence'], 'ai_task': ['时序基础模型审计']}
    return app.run()


def test_actual_audit_all_indicators_defaults_repeat_and_previous_navigation():
    from guanlan.chronos_report import KEYS
    app = fresh()
    assert not app.exception and not app.error
    assert len(app.get('download_button')) == 3
    assert any('84 / 84' == m.value for m in app.metric)
    assert any('回顾实验' in w.value for w in app.warning)
    assert any('生产默认参考保持原研究基线' in item.value for item in list(app.info) + list(app.success))
    for key in KEYS:
        app.selectbox(key='chronos_indicator').set_value(key).run()
        assert not app.exception and not app.error
        assert app.query_params['chronos_indicator'] == key
        assert len(app.get('download_button')) == 3
    app.run()
    assert not app.exception and len(app.get('download_button')) == 3
    app.radio(key='ai_task').set_value('中国月度预测与异常').run()
    assert not app.exception and not app.error
    assert any('默认研究参考' in c.value for c in app.caption)


def test_missing_invalid_and_retry_state_do_not_start_model_or_paid_api(monkeypatch):
    from guanlan.ui import chronos_research
    from guanlan import ai
    def absent(): raise ValueError('fixture invalid packaged audit')
    def paid(*args, **kwargs): raise AssertionError('Paid API forbidden')
    clears = []
    absent.clear = lambda: clears.append('cleared')
    monkeypatch.setattr(chronos_research, 'audit_bundle', absent)
    monkeypatch.setattr(ai, '_post', paid)
    app = fresh()
    assert not app.exception and not app.error
    assert any('缺失或校验失败' in w.value for w in app.warning)
    assert not app.get('download_button')
    app.button(key='chronos_retry').click().run()
    assert clears == ['cleared'] and not app.exception and not app.error
    assert not app.get('download_button')
    app.radio(key='research_navigation').set_value('中国观察').run()
    assert not app.exception and not app.error
