import pandas as pd

from guanlan.analytics import GROWTH
from guanlan.research import build_research_report, peer_context


def _macro():
    rows = []
    countries = {
        "AAA": ("甲国", "东区", "中收入"),
        "BBB": ("乙国", "东区", "中收入"),
        "CCC": ("丙国", "西区", "中收入"),
        "DDD": ("丁国", "东区", "高收入"),
    }
    values = {"AAA": 4.0, "BBB": 4.0, "CCC": 1.0, "DDD": None}
    for code, (name, region, income) in countries.items():
        rows.append({
            "country_code": code, "country_name": name, "region": region,
            "income_level": income, "year": 2024, "indicator_code": GROWTH,
            "value": values[code],
        })
    rows.append({**rows[1], "year": 2025, "value": 100.0})
    return pd.DataFrame(rows)


def test_peer_context_uses_exact_year_and_midrank_for_ties():
    frame, result = peer_context(_macro(), "AAA", 2024, GROWTH, "全球")
    assert len(frame) == 3
    assert result.total_economies == 4
    assert result.observed_economies == 3
    assert result.selected_value == 4
    assert result.rank_descending == 1
    assert result.percentile == 100 * (1 + 0.5 * 2) / 3
    assert result.median == 4


def test_peer_context_filters_group_without_filling_missing_year():
    _, region = peer_context(_macro(), "AAA", 2024, GROWTH, "同地区")
    _, income = peer_context(_macro(), "AAA", 2024, GROWTH, "同收入组")
    assert (region.total_economies, region.observed_economies) == (3, 2)
    assert (income.total_economies, income.observed_economies) == (3, 3)
    assert region.selected_value == 4


def test_report_preserves_missing_values_and_does_not_borrow_trade_year():
    trade = pd.DataFrame([
        {"reporter_code": "AAA", "partner_code": "BBB", "partner_name": "乙国",
         "year": 2023, "flow": "X", "trade_usd": 100.0}
    ])
    report = build_research_report(
        _macro(), trade,
        {"downloaded_at_utc": "2026-01-01T00:00:00+00:00", "source_last_updated": "2025-12-01"},
        {"downloaded_at_utc": "2026-01-01T00:00:00+00:00"},
        "AAA", 2024, GROWTH, "同地区",
    )
    assert "2026-01-01T00:00:00+00:00" in report
    assert "| 国内生产总值 | 暂无数据 |" in report
    assert "没有本项目已下载的出口伙伴样本" in report
    assert "100.0%" not in report


def test_report_separates_imf_forecast_from_wdi_observation():
    outlook = pd.DataFrame([{
        "country_code": "AAA", "indicator_code": "NGDP_RPCH", "year": 2026, "value": 4.4,
    }])
    report = build_research_report(
        _macro(), pd.DataFrame(), {"downloaded_at_utc": "2026-01-01T00:00:00+00:00"},
        {}, "AAA", 2024, weo=outlook,
        weo_meta={"vintage": "April 2026", "source_url": "https://data.imf.org/Datasets/WEO"},
    )
    assert "IMF 中期预测附录（独立数据版次）" in report
    assert "实际GDP增速（%） | 4.40 | 暂无预测" in report
    assert "不属于上文 WDI 所选年份的历史发布值" in report
