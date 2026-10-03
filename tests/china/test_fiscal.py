"""Fiscal source parsing, basis selection and snapshot integrity."""

import tempfile
import unittest
from pathlib import Path

from china_macro.audit import audit_fiscal_snapshots
from china_macro.fiscal import parse_fiscal_html, period_from_title, save_fiscal_snapshot


URL = "https://gks.mof.gov.cn/tongjishuju/202209/t20220916_3840932.htm"


def article(title: str, revenue: str, tax: str, land: str) -> bytes:
    return (f"<html><title>{title}</title><div class='TRS_Editor'>"
            f"全国一般公共预算收入74293亿元，{revenue}。税收收入62319亿元，{tax}。"
            "全国一般公共预算支出90000亿元，同比增长5%。"
            "全国政府性基金预算收入30000亿元，同比下降20%。"
            f"国有土地使用权出让收入15012亿元，{land}。"
            "</div></html>").encode("utf-8")


class FiscalTests(unittest.TestCase):
    def test_title_periods_keep_cumulative_reports_in_correct_month(self):
        self.assertEqual(period_from_title("2026年1-8月财政收支情况"), "2026-08")
        self.assertEqual(period_from_title("2024年8月财政收支情况"), "2024-08")
        self.assertEqual(period_from_title("2025年上半年财政收支情况"), "2025-06")
        self.assertEqual(period_from_title("2024年财政收支情况"), "2024-12")
        self.assertIsNone(period_from_title("2026年地方财政收支情况"))

    def test_2022_natural_basis_is_not_tax_refund_adjusted_rate(self):
        raw = article("2022年8月财政收支情况",
                      "扣除留抵退税因素后增长5%，按自然口径计算下降4.8%",
                      "扣除留抵退税因素后增长3.7%，按自然口径计算下降7.6%",
                      "比上年同期下降29.8%")
        rows = parse_fiscal_html(raw, URL, "2022年8月财政收支情况", "2022-08", "2022-09-16")
        values = {row["key"]: row["value"] for row in rows}
        self.assertEqual(len(rows), 10)
        self.assertEqual(values["fiscal_revenue_ytd_yoy"], -4.8)
        self.assertEqual(values["tax_revenue_ytd_yoy"], -7.6)
        self.assertEqual(values["land_revenue_ytd_yoy"], -29.8)

    def test_flat_and_tiny_growth_are_preserved(self):
        raw = article("2022年8月财政收支情况", "同比增长1%", "同比微增0.02%", "与去年同期持平")
        values = {row["key"]: row["value"] for row in parse_fiscal_html(
            raw, URL, "2022年8月财政收支情况", "2022-08", "2022-09-16")}
        self.assertEqual(values["tax_revenue_ytd_yoy"], 0.02)
        self.assertEqual(values["land_revenue_ytd_yoy"], 0)

    def test_article_publication_date_overrides_url_filename_date(self):
        raw = article("2022年8月财政收支情况", "同比增长1%", "同比增长2%", "同比下降3%")
        raw = raw.replace(b"<div class='TRS_Editor'>",
                          "<div class='laiyuan'>2022年9月17日 来源：国库司</div><div class='TRS_Editor'>".encode("utf-8"))
        rows = parse_fiscal_html(raw, URL, "2022年8月财政收支情况", "2022-08", "2022-09-16")
        self.assertTrue(all(row["published"] == "2022-09-17" for row in rows))

    def test_snapshot_audit_detects_tampering(self):
        raw = article("2022年8月财政收支情况", "同比增长1%", "同比增长2%", "同比下降3%")
        rows = parse_fiscal_html(raw, URL, "2022年8月财政收支情况", "2022-08", "2022-09-16")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = save_fiscal_snapshot(raw, URL, rows, root)
            self.assertEqual(audit_fiscal_snapshots(root, rows)["fiscal_snapshot_errors"], [])
            path = root / f"mof-fiscal-{manifest['sha256']}.html"
            path.write_bytes(raw + b"tampered")
            self.assertTrue(audit_fiscal_snapshots(root, rows)["fiscal_snapshot_errors"])


if __name__ == "__main__":
    unittest.main()
