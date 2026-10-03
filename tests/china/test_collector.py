import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from bs4 import BeautifulSoup

from china_macro.backfill_nbs_gaps import article_title
from china_macro.collector import directory_publication_date, fetch, month_from_title, nbs_links, parse_nbs, parse_nbs_special, parse_pbc, ppi_month_change
from china_macro.quality import coverage, known_source_gap


class ReleaseParsingTests(unittest.TestCase):
    def test_disclosure_report_title_comes_from_official_metadata(self):
        soup = BeautifulSoup("<title>国家统计局信息公开</title><meta name='ArticleTitle' content='一季度国民经济实现良好开局'><h2></h2>", "html.parser")
        self.assertEqual(article_title(soup), "一季度国民经济实现良好开局")

    def test_chinese_directory_date_is_normalized(self):
        self.assertEqual(directory_publication_date("2026年8月份规模以上工业增加值增长5.2% 2026年09月15日"),
                         "2026-09-15")

    def test_legacy_directory_uses_original_release_date_not_migration_url(self):
        html = """<li><a href='./202302/t20230203_1901240.html'>前三季度国民经济总体保持恢复态势</a>
                  <span>2021-10-18</span></li>"""
        with patch("china_macro.collector.fetch", return_value=BeautifulSoup(html, "html.parser")), patch("china_macro.collector.time.sleep"):
            links = nbs_links(None, pages=1, archive="main", start_year=2021, through_year=2021)
        self.assertEqual(links[0][2:], ("overview", "2021-09", "2021-10-18"))

    def test_legacy_article_markup_and_directory_date(self):
        html = "<div class='TRS_Editor'>9月份，规模以上工业增加值同比实际增长3.1%。</div>"
        rows = parse_nbs_special(BeautifulSoup(html, "html.parser"),
                                 "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901241.html",
                                 "2021年9月份规模以上工业增加值增长3.1%", "industry",
                                 period_override="2021-09", published_hint="2021-10-18")
        self.assertEqual([(row["period"], row["value"], row["published"]) for row in rows],
                         [("2021-09", 3.1, "2021-10-18")])

    def test_annual_release_is_december_cumulative_not_january(self):
        url = "https://www.stats.gov.cn/sj/zxfb/202601/t20260119_1962326.html"
        title = "2025年全国固定资产投资基本情况"
        self.assertEqual(month_from_title(title, url, "2026-01-19"), "2025-12")
        html = """<div class='trs_editor_view'>2025年，全国固定资产投资（不含农户）485186亿元，比上年下降3.8%（详见附注7）。
          其中，民间固定资产投资比上年下降6.4%。制造业投资增长0.6%。
          基础设施投资（不含电力、热力、燃气及水生产和供应业）比上年下降2.2%。</div>"""
        rows = parse_nbs_special(BeautifulSoup(html, "html.parser"), url, title,
                                 "investment", published_hint="2026-01-19")
        self.assertEqual({row["key"]: row["value"] for row in rows}, {
            "fai_ytd_yoy": -3.8, "private_fai_ytd_yoy": -6.4,
            "manufacturing_fai_ytd_yoy": 0.6,
            "infrastructure_ex_utilities_ytd_yoy": -2.2,
        })
        self.assertTrue(all(row["period"] == "2025-12" for row in rows))

    def test_legacy_annual_housing_label_and_private_amount(self):
        estate_title = "2021年全国房地产开发投资增长4.4%"
        estate_url = "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901340.html"
        self.assertEqual(month_from_title(estate_title, estate_url, "2022-01-17"), "2021-12")
        estate = "<div class='TRS_Editor'>2021年，全国房地产开发投资147602亿元，比上年增长4.4%。2021年，商品房销售面积179433万平方米，比上年增长1.9%。</div>"
        rows = parse_nbs_special(BeautifulSoup(estate, "html.parser"), estate_url,
                                 estate_title, "estate", published_hint="2022-01-17")
        self.assertEqual({row["key"]: row["value"] for row in rows}, {
            "real_estate_fai_ytd_yoy": 4.4, "housing_sales_area_ytd_yoy": 1.9,
        })
        investment = "<div class='trs_editor_view'>2024年，全国固定资产投资（不含农户）514374亿元，比上年增长3.2%。其中，民间固定资产投资257574亿元，下降0.1%。</div>"
        rows = parse_nbs_special(BeautifulSoup(investment, "html.parser"),
                                 "https://www.stats.gov.cn/sj/zxfb/202501/t20250117_1958329.html",
                                 "2024年全国固定资产投资增长3.2%", "investment",
                                 published_hint="2025-01-17")
        self.assertEqual({row["key"]: row["value"] for row in rows}, {
            "fai_ytd_yoy": 3.2, "private_fai_ytd_yoy": -0.1,
        })

    def test_historical_monthly_investment_and_housing_wording(self):
        investment = "<div class='TRS_Editor'>1—6月份，全国固定资产投资（不含农户）243113亿元，同比增长3.8%。民间固定资产投资128570亿元，下降0.2%。制造业投资增长6.0%。</div>"
        rows = parse_nbs_special(BeautifulSoup(investment, "html.parser"),
                                 "https://www.stats.gov.cn/sj/zxfb/202307/t20230717_1941290.html",
                                 "2023年1—6月份全国固定资产投资基本情况", "investment",
                                 period_override="2023-06", published_hint="2023-07-17")
        self.assertEqual(next(row["value"] for row in rows if row["key"] == "private_fai_ytd_yoy"), -0.2)
        estate = "<div class='TRS_Editor'>1—6月份，全国房地产开发投资58550亿元，同比下降7.9%。商品房销售面积59515万平方米，同比下降5.3%。</div>"
        rows = parse_nbs_special(BeautifulSoup(estate, "html.parser"),
                                 "https://www.stats.gov.cn/sj/zxfb/202307/t20230717_1941291.html",
                                 "2023年1—6月份全国房地产市场基本情况", "estate",
                                 period_override="2023-06", published_hint="2023-07-17")
        self.assertEqual(next(row["value"] for row in rows if row["key"] == "housing_sales_area_ytd_yoy"), -5.3)

    def test_private_investment_flat_requires_table_confirmation(self):
        html = "<div class='trs_editor_view'>1—2月份，民间固定资产投资26717亿元，总量与去年同期基本持平。其中：民间投资 0.0 按构成分，制造业投资增长1.2%。</div>"
        rows = parse_nbs_special(BeautifulSoup(html, "html.parser"),
                                 "https://www.stats.gov.cn/sj/zxfb/202503/t20250317_1958999.html",
                                 "2025年1—2月份全国固定资产投资基本情况", "investment",
                                 period_override="2025-02", published_hint="2025-03-17")
        self.assertEqual(next(row["value"] for row in rows if row["key"] == "private_fai_ytd_yoy"), 0.0)

    def test_annual_infrastructure_growth_without_repeated_comparison_word(self):
        html = """<div class='trs_editor_view'>2023年，全国固定资产投资（不含农户）503036亿元，比上年增长3.0%。
          其中，制造业投资增长6.5%；基础设施投资（不含电力、热力、燃气及水生产和供应业）增长5.9%。</div>"""
        rows = parse_nbs_special(BeautifulSoup(html, "html.parser"),
                                 "https://www.stats.gov.cn/sj/zxfb/202401/t20240116_1946620.html",
                                 "2023年全国固定资产投资增长3.0%", "investment",
                                 published_hint="2024-01-17")
        self.assertEqual(next(row["value"] for row in rows
                              if row["key"] == "infrastructure_ex_utilities_ytd_yoy"), 5.9)

    def test_http_200_verification_page_is_an_error(self):
        class FakeResponse:
            content = b'<html><noscript>Please enable JavaScript and refresh the page.</noscript></html>'

            def raise_for_status(self):
                pass

        class FakeSession:
            def get(self, *args, **kwargs):
                return FakeResponse()

        with self.assertRaisesRegex(ValueError, "verification page"):
            fetch(FakeSession(), "https://www.stats.gov.cn/sj/zxfb/")

    def test_monthly_retail_does_not_use_cumulative_rate(self):
        html = "<div class='trs_editor_view'>1—8月份，社会消费品零售总额327569亿元，同比增长1.1%。8月份，社会消费品零售总额39824亿元，同比增长0.4%。</div>"
        soup = BeautifulSoup(html, "html.parser")
        rows = parse_nbs(soup, "https://www.stats.gov.cn/sj/zxfb/202609/t20260915_123.html", "8月份国民经济运行")
        self.assertEqual(next(row["value"] for row in rows if row["key"] == "retail_yoy"), 0.4)

    def test_monthly_trade_ignores_quarter_totals_and_keeps_both_rates(self):
        html = """<div class='trs_editor_view'>一季度，货物进出口总额103013亿元，同比增长1.3%。
        其中，出口61314亿元，增长6.9%；进口41700亿元，下降6.0%。
        3月份，进出口总额37663亿元，同比增长6.0%。其中，出口22515亿元，增长13.5%；进口15148亿元，下降3.5%。</div>"""
        rows = parse_nbs(BeautifulSoup(html, "html.parser"),
                         "https://www.stats.gov.cn/sj/zxfb/202504/overview.html",
                         "一季度国民经济开局良好", period_override="2025-03")
        self.assertEqual({row["key"]: row["value"] for row in rows},
                         {"export_yoy": 13.5, "import_yoy": -3.5})

    def test_combined_january_february_trade_is_not_two_monthly_rates(self):
        html = """<div class='trs_editor_view'>1—2月份，货物进出口总额62044亿元，同比增长13.3%。
        其中，出口34716亿元，增长13.6%；进口27328亿元，增长12.9%。</div>"""
        rows = parse_nbs(BeautifulSoup(html, "html.parser"),
                         "https://www.stats.gov.cn/sj/zxfb/202203/overview.html",
                         "1—2月份国民经济恢复好于预期", period_override="2022-02")
        self.assertFalse({row["key"] for row in rows} & {"export_yoy", "import_yoy"})

    def test_unemployment_paired_months_keep_national_last_month(self):
        html = """<div class='trs_editor_view'>4月份，全国城镇调查失业率为6.1%；5、6月份连续回落，分别为5.9%、5.5%。
        6月份，本地户籍人口调查失业率为5.3%。</div>"""
        rows = parse_nbs(BeautifulSoup(html, "html.parser"),
                         "https://www.stats.gov.cn/sj/zxfb/202207/overview.html",
                         "上半年国民经济企稳回升", period_override="2022-06")
        self.assertEqual({row["key"]: row["value"] for row in rows},
                         {"unemployment": 5.5})

    def test_ppi_month_can_follow_cumulative_sentence(self):
        html = "<div class='trs_editor_view'>1—7月份，全国工业生产者出厂价格同比上涨1.8%。其中，7月份同比上涨3.5%，环比下降0.7%。</div>"
        soup = BeautifulSoup(html, "html.parser")
        rows = parse_nbs(soup, "https://www.stats.gov.cn/sj/zxfb/202608/t20260817_123.html", "1—7月份国民经济运行")
        self.assertEqual(next(row["value"] for row in rows if row["key"] == "ppi_yoy"), 3.5)

    def test_pbc_accepts_ascii_parentheses(self):
        html = "<div class='content'>6月末，广义货币(M2)余额356.71万亿元,同比增长8%。狭义货币(M1)余额118.48万亿元,同比增长4%。</div>"
        soup = BeautifulSoup(html, "html.parser")
        rows = parse_pbc(soup, "https://www.pbc.gov.cn/diaochatongjisi/116219/116225/20260715/index.html", "2026年上半年金融统计数据报告")
        self.assertEqual({row["key"]: row["value"] for row in rows}, {"m1_yoy": 4.0, "m2_yoy": 8.0})

    def test_investment_report_keeps_ytd_subseries(self):
        html = "<div class='trs_editor_view'>1—8月份，全国固定资产投资（不含农户）293092亿元，同比下降7.2%。工业投资同比下降2.9%。其中，制造业投资下降2.3%。基础设施投资（口径详见附注1）同比下降4.0%。1—8月份，民间固定资产投资同比下降10.1%。</div>"
        soup = BeautifulSoup(html, "html.parser")
        rows = parse_nbs_special(soup, "https://www.stats.gov.cn/sj/zxfb/202609/t20260915_1.html", "2026年1—8月份全国固定资产投资基本情况", "investment")
        self.assertEqual({row["key"]: row["value"] for row in rows}, {
            "fai_ytd_yoy": -7.2, "private_fai_ytd_yoy": -10.1,
            "manufacturing_fai_ytd_yoy": -2.3, "infrastructure_fai_ytd_yoy": -4.0,
        })

    def test_infrastructure_scope_change_is_a_separate_series(self):
        html = "<meta name='PubDate' content='2025/10/20 10:00'><div class='trs_editor_view'>1—9月份，全国固定资产投资（不含农户）371535亿元，同比下降0.5%。基础设施投资（不含电力、热力、燃气及水生产和供应业）同比增长1.1%。</div>"
        soup = BeautifulSoup(html, "html.parser")
        rows = parse_nbs_special(soup, "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202510/t20251020_1.html", "2025年1—9月份全国固定资产投资基本情况", "investment")
        self.assertEqual({row["key"]: row["value"] for row in rows}, {
            "fai_ytd_yoy": -0.5, "infrastructure_ex_utilities_ytd_yoy": 1.1,
        })
        self.assertTrue(all(row["published"] == "2025-10-20" for row in rows))

    def test_pmi_headline_and_nonmanufacturing_are_distinct(self):
        html = "<div class='trs_editor_view'>8月份，制造业采购经理指数（PMI）为49.8%。新订单指数为50.6%。8月份，非制造业商务活动指数为49.0%。</div>"
        soup = BeautifulSoup(html, "html.parser")
        rows = parse_nbs_special(soup, "https://www.stats.gov.cn/sj/zxfb/202608/t20260831_1.html", "2026年8月中国采购经理指数运行情况", "pmi")
        self.assertEqual({row["key"]: row["value"] for row in rows}, {
            "manufacturing_pmi": 49.8, "manufacturing_new_orders_pmi": 50.6,
            "nonmanufacturing_pmi": 49.0,
        })

    def test_older_pmi_report_with_china_prefix(self):
        html = "<div class='trs_editor_view'>10月份，中国制造业采购经理指数（PMI）为49.2%。新订单指数为48.8%。10月份，非制造业商务活动指数为52.4%。</div>"
        rows = parse_nbs_special(BeautifulSoup(html, "html.parser"),
                                 "https://www.stats.gov.cn/sj/zxfb/202302/pmi.html",
                                 "2021年10月中国采购经理指数运行情况", "pmi",
                                 period_override="2021-10")
        self.assertEqual({row["key"]: row["value"] for row in rows}, {
            "manufacturing_pmi": 49.2, "manufacturing_new_orders_pmi": 48.8,
            "nonmanufacturing_pmi": 52.4,
        })

    def test_price_month_on_month_is_read_from_headline_not_subgroups(self):
        cpi = "<div class='trs_editor_view'>8月份，全国居民消费价格同比上涨0.8%。8月份，全国居民消费价格环比上涨0.4%。其中，食品价格环比下降1.4%。</div>"
        rows = parse_nbs_special(BeautifulSoup(cpi, "html.parser"),
                                 "https://www.stats.gov.cn/sj/zxfb/202609/cpi.html",
                                 "2026年8月份居民消费价格同比上涨0.8%", "cpi",
                                 period_override="2026-08", published_hint="2026-09-09")
        self.assertEqual({row["key"]: row["value"] for row in rows},
                         {"cpi_yoy": 0.8, "cpi_mom": 0.4})
        ppi = "<div class='trs_editor_view'>8月份，全国工业生产者出厂价格同比上涨3.8%，环比上涨0.4%。工业生产者购进价格同比上涨5.8%，环比上涨0.3%。</div>"
        rows = parse_nbs_special(BeautifulSoup(ppi, "html.parser"),
                                 "https://www.stats.gov.cn/sj/zxfb/202609/ppi.html",
                                 "2026年8月份工业生产者出厂价格同比上涨3.8%", "ppi",
                                 period_override="2026-08", published_hint="2026-09-09")
        self.assertEqual({row["key"]: row["value"] for row in rows},
                         {"ppi_yoy": 3.8, "ppi_mom": 0.4})

    def test_price_flat_and_unrelated_purchase_rate(self):
        cpi = "<div class='trs_editor_view'>6月份，全国居民消费价格同比持平。6月份，全国居民消费价格环比持平。</div>"
        rows = parse_nbs_special(BeautifulSoup(cpi, "html.parser"),
                                 "https://www.stats.gov.cn/sj/zxfb/202307/cpi.html",
                                 "2023年6月份居民消费价格同比持平", "cpi",
                                 period_override="2023-06")
        self.assertEqual({row["key"]: row["value"] for row in rows},
                         {"cpi_yoy": 0.0, "cpi_mom": 0.0})
        ppi = "<div class='trs_editor_view'>6月份，全国工业生产者出厂价格同比下降5.4%。工业生产者购进价格环比下降1.1%。</div>"
        rows = parse_nbs_special(BeautifulSoup(ppi, "html.parser"),
                                 "https://www.stats.gov.cn/sj/zxfb/202307/ppi.html",
                                 "2023年6月份工业生产者出厂价格同比下降5.4%", "ppi",
                                 period_override="2023-06")
        self.assertEqual({row["key"]: row["value"] for row in rows}, {"ppi_yoy": -5.4})

    def test_ppi_month_rate_handles_turns_and_joint_headlines(self):
        cases = [
            ("工业生产者出厂价格同比下降0.8%，环比由上月上涨0.2%转为下降0.2%；工业生产者购进价格环比上涨0.1%。", -0.2),
            ("工业生产者出厂价格和购进价格环比分别下降0.2%、0.3%。", -0.2),
            ("工业生产者出厂价格同比下降2.9%。工业生产者出厂价格环比继续持平。工业生产者购进价格环比上涨0.1%。", 0.0),
            ("工业生产者出厂价格同比下降2.1%；环比由上月持平转为上涨0.1%。", 0.1),
            ("工业生产者出厂价格同比下降2.2%；工业生产者出厂价格和购进价格环比均上涨0.1%。", 0.1),
        ]
        for narrative, expected in cases:
            with self.subTest(narrative=narrative):
                self.assertEqual(ppi_month_change(narrative), expected)

    def test_price_headline_table_fills_missing_prose_rates(self):
        html = """<div class='trs_editor_view'>1月份，工业生产者出厂价格同比降幅收窄。
        <table><tr><td>指标</td><td>环比涨跌幅（%）</td><td>同比涨跌幅（%）</td></tr>
        <tr><td>一、工业生产者出厂价格</td><td>-0.2</td><td>-2.5</td></tr>
        <tr><td>工业生产者购进价格</td><td>0.3</td><td>-1.9</td></tr></table></div>"""
        rows = parse_nbs_special(BeautifulSoup(html, "html.parser"),
                                 "https://www.stats.gov.cn/sj/zxfb/202402/ppi.html",
                                 "2024年1月份工业生产者出厂价格降幅收窄", "ppi",
                                 period_override="2024-01")
        self.assertEqual({row["key"]: row["value"] for row in rows},
                         {"ppi_yoy": -2.5, "ppi_mom": -0.2})

    def test_price_headline_table_disagreement_rejects_report(self):
        html = """<div class='trs_editor_view'>8月份，全国居民消费价格同比上涨0.8%。8月份，全国居民消费价格环比上涨0.4%。
        <table><tr><td>指标</td><td>环比涨跌幅</td><td>同比涨跌幅</td></tr>
        <tr><td>居民消费价格</td><td>0.3</td><td>0.8</td></tr></table></div>"""
        with self.assertRaisesRegex(ValueError, "narrative differs"):
            parse_nbs_special(BeautifulSoup(html, "html.parser"),
                              "https://www.stats.gov.cn/sj/zxfb/202609/cpi.html",
                              "2026年8月份居民消费价格同比上涨0.8%", "cpi",
                              period_override="2026-08")

    def test_coverage_excludes_january_february_for_monthly_industry(self):
        result = coverage({"industrial_yoy": [{"period": "2026-03", "value": 5.2}]}, window=3)
        item = next(row for row in result["metrics"] if row["key"] == "industrial_yoy")
        self.assertEqual((item["observed"], item["expected"], item["coverage_pct"]), (1, 1, 100.0))

    def test_trade_gap_explanation_is_source_specific(self):
        combined = known_source_gap("export_yoy", "2025-02")
        self.assertIn("1—2月累计", combined["reason"])
        self.assertTrue(combined["source_url"].startswith("https://www.stats.gov.cn/"))
        self.assertIsNone(known_source_gap("export_yoy", "2025-09"))
        self.assertIsNone(known_source_gap("export_usd_yoy", "2025-02"))

    def test_coverage_respects_infrastructure_scope_periods(self):
        result = coverage({"infrastructure_fai_ytd_yoy": [{"period": "2026-08", "value": -4.0}]}, window=24)
        current = next(row for row in result["metrics"] if row["key"] == "infrastructure_fai_ytd_yoy")
        old = next(row for row in result["metrics"] if row["key"] == "infrastructure_ex_utilities_ytd_yoy")
        self.assertEqual(current["expected"], 7)
        self.assertEqual(old["expected"], 15)

    def test_scheduled_release_is_pending_until_publication_time(self):
        china = timezone(timedelta(hours=8))
        series = {"cpi_yoy": [{"period": "2026-08", "value": 0.8}]}
        before = coverage(series, as_of=datetime(2026, 9, 27, 12, tzinfo=china))
        after = coverage(series, as_of=datetime(2026, 9, 28, 10, tzinfo=china))
        old = next(row for row in before["metrics"] if row["key"] == "industrial_profit_ytd_yoy")
        new = next(row for row in after["metrics"] if row["key"] == "industrial_profit_ytd_yoy")
        self.assertEqual(old["pending"], ["2026-08"])
        self.assertNotIn("2026-08", old["missing"])
        self.assertIn("2026-08", new["missing"])


if __name__ == "__main__":
    unittest.main()
