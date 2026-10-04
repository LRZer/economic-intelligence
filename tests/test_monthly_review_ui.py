from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def fresh():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=40)
    app.query_params = {"view": ["intelligence"], "ai_task": ["中国月度预测与异常"]}
    return app.run()


def test_monthly_flow_switching_and_defaults_never_lookup_key_or_call_api(monkeypatch):
    monkeypatch.setenv("ENABLE_PAID_AI", "0")
    with patch("guanlan.ui.research.configured_key", side_effect=AssertionError("key lookup forbidden")), patch("requests.post") as post:
        app = fresh()
        assert not app.exception and not app.error
        for key, comparison in [("ppi_yoy", "对比去年同月"), ("manufacturing_pmi", "对比上个自然月"), ("cpi_yoy", "对比去年同月")]:
            app.selectbox(key="ai_indicator").set_value(key).run()
            app.radio(key="monthly_comparison").set_value(comparison).run()
            assert not app.exception and not app.error
            assert app.query_params["ai_indicator"] == key
            assert len(app.get("download_button")) == 5
        assert not any(b.label.startswith("生成") for b in app.button)
    post.assert_not_called()


def test_empty_monthly_data_keeps_navigation_usable(monkeypatch):
    from guanlan.ui import intelligence
    monkeypatch.setattr(intelligence, "load_dashboard", lambda: {"catalog": [], "series": {}})
    app = fresh()
    assert not app.exception and not app.error and any("暂无" in i.value for i in app.info)
    app.radio(key="research_navigation").set_value("经济体概览").run()
    assert not app.exception and not app.error


def test_invalid_monthly_source_stops_review_safely_and_other_task_works(monkeypatch):
    from guanlan.ui import intelligence
    original = intelligence.load_dashboard
    def invalid():
        import copy
        data = copy.deepcopy(original())
        data["series"]["cpi_yoy"][-1]["source_url"] = "https://unapproved.invalid/"
        return data
    monkeypatch.setattr(intelligence, "load_dashboard", invalid)
    app = fresh()
    assert not app.exception and any("无法生成" in e.value for e in app.error)
    app.selectbox(key="ai_indicator").set_value("ppi_yoy").run()
    assert not app.exception and not app.error
