"""Real local browser scenarios; no paid API, no credential access."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from china_macro.catalog import INDICATORS
from guanlan.monthly_review import verify_exported_review

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/monthly-browser"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    errors = []
    api_requests = []
    dataset = json.loads((ROOT / "src/china_macro/demo_data.json").read_text(encoding="utf-8"))["rows"]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1050})
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        page.on("request", lambda request: api_requests.append("paid-api") if "api.deepseek.com" in request.url else None)
        query = urlencode({"view": "intelligence", "ai_task": "中国月度预测与异常", "ai_indicator": "cpi_yoy"})
        page.goto("http://127.0.0.1:8610/?" + query, wait_until="domcontentloaded")
        page.get_by_role("heading", name="月度研究核验单", exact=True).wait_for(timeout=60000)
        page.get_by_role("button", name="下载核验包 JSON", exact=True).wait_for(timeout=60000)
        page.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').wait_for(timeout=60000)

        def wait_current(key, comparison):
            rows = sorted([row for row in dataset if row["key"] == key], key=lambda row: row["period"])
            latest = rows[-1]
            definition = INDICATORS[key]
            text = f"{latest['period']}，{definition[0]}（{definition[2]}）官方读数为 {latest['value']:g}%。"
            page.get_by_text(text, exact=True).wait_for(timeout=60000)
            page.wait_for_function("([k,c]) => new URL(location.href).searchParams.get('ai_indicator') === k && new URL(location.href).searchParams.get('monthly_comparison') === c", arg=[key, comparison])
            page.get_by_text(f"当前报告范围：{definition[0]} · {latest['period']} · {'上个自然月' if comparison == 'previous_month' else '去年同月'}", exact=True).wait_for(timeout=60000)
            page.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').wait_for(timeout=60000)

        def healthy():
            assert not page.locator('[data-testid="stException"], [data-testid="stAlertContentError"]').count()
            assert not errors and not api_requests
            overflow = page.evaluate("Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)-innerWidth")
            assert overflow <= 0, f"Page overflow {overflow}"
            return overflow

        def download(kind, name, stem):
            before = page.url
            with page.expect_download() as pending:
                page.get_by_role("button", name=name, exact=True).click()
            pending.value.save_as(str(OUT / f"{stem}.{kind}"))
            assert page.url == before
            return OUT / f"{stem}.{kind}"

        def exported(stem, key, comparison, planner="local"):
            wait_current(key, comparison)
            for kind, label in [("html", "下载核验单 HTML"), ("json", "下载核验包 JSON"), ("csv", "下载声明与证据 CSV")]:
                download(kind, label, stem)
            report = json.loads((OUT / f"{stem}.json").read_text(encoding="utf-8"))
            assert report["bundle"]["selection"]["indicator_key"] == key
            assert report["bundle"]["selection"]["comparison"] == comparison
            assert report["planner"] == planner
            assert verify_exported_review(report)["status"] == "passed"
            results.append({"id": stem, "status": "passed", "review_id": report["bundle"]["review_id"],
                            "planner": planner, "overflow_px": healthy()})
            return report

        report = exported("cpi-month-desktop", "cpi_yoy", "previous_month")
        page.get_by_role("heading", name="研究与风险分析", exact=True).scroll_into_view_if_needed()
        page.evaluate("document.querySelector('[data-testid=stMain]')?.scrollTo(0,0)")
        page.screenshot(path=str(OUT / "monthly-review-desktop.png"), full_page=True)
        for index, (key, name) in enumerate([("ppi_yoy", "工业生产者出厂价格 PPI"), ("manufacturing_pmi", "制造业采购经理指数 PMI"), ("cpi_yoy", "居民消费价格 CPI")]):
            combo = page.get_by_role("combobox", name="建模指标")
            combo.scroll_into_view_if_needed()
            combo.focus()
            combo.press("ArrowDown")
            page.get_by_role("option", name=name, exact=True).click()
            # React controls update before the Streamlit server finishes the fit.
            # Wait for the selected observation before issuing the next action.
            current = "previous_month" if index == 0 else "previous_year"
            wait_current(key, current)
            page.get_by_text("对比去年同月", exact=True).click()
            wait_current(key, "previous_year")
            report = exported(f"selected-{index}-{key}", key, "previous_year")

        page.get_by_text("摘要编排与证据核查", exact=True).click()
        plan = {"review_id": report["bundle"]["review_id"], "claim_ids": ["latest", "method", "limits"]}
        plan_path = OUT / "valid-plan.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        page.locator('input[type="file"]').set_input_files(str(plan_path))
        page.get_by_text("编排结构通过；展示文本仍由本地证据生成，不代表外部模型业务质量已验证。", exact=True).wait_for()
        imported = exported("accepted-plan", "cpi_yoy", "previous_year", "imported_untrusted")
        assert imported["plan"] == plan
        page.get_by_text("对比上个自然月", exact=True).click()
        page.get_by_text("编排被拒绝：结构、声明或核验包不匹配。已保留当前本地完整核验单。", exact=True).wait_for()
        exported("stale-plan-fallback", "cpi_yoy", "previous_month")
        invalid_path = OUT / "invalid-plan.json"
        invalid_path.write_text(json.dumps({**plan, "summary": "经济必然崩溃"}, ensure_ascii=False), encoding="utf-8")
        page.locator('input[type="file"]').set_input_files(str(invalid_path))
        page.wait_for_timeout(700)
        exported("unsafe-plan-fallback", "cpi_yoy", "previous_month")
        # Repeated download must preserve scope and remain a local fallback.
        exported("repeated-download", "cpi_yoy", "previous_month")
        page.screenshot(path=str(OUT / "monthly-review-plan-rejection.png"), full_page=True)

        mobile = browser.new_page(viewport={"width": 390, "height": 900})
        mobile.on("pageerror", lambda error: errors.append(type(error).__name__))
        mobile.on("request", lambda request: api_requests.append("paid-api") if "api.deepseek.com" in request.url else None)
        mobile.goto("http://127.0.0.1:8610/?" + query, wait_until="domcontentloaded")
        mobile.get_by_role("button", name="下载核验包 JSON", exact=True).wait_for(timeout=60000)
        assert not mobile.locator('[data-testid="stException"], [data-testid="stAlertContentError"]').count()
        overflow = mobile.evaluate("Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)-innerWidth")
        assert overflow <= 0
        mobile.screenshot(path=str(OUT / "monthly-review-mobile.png"), full_page=True)
        with mobile.expect_download() as pending:
            mobile.get_by_role("button", name="下载核验包 JSON", exact=True).click()
        pending.value.save_as(str(OUT / "mobile.json"))
        assert verify_exported_review(json.loads((OUT / "mobile.json").read_text(encoding="utf-8")))["status"] == "passed"
        results.append({"id": "mobile-download", "status": "passed", "overflow_px": overflow})

        offline = browser.new_page(viewport={"width": 390, "height": 900})
        offline.goto((OUT / "cpi-month-desktop.html").as_uri())
        assert not offline.locator("script").count()
        overflow = offline.evaluate("Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)-innerWidth")
        assert overflow <= 0
        offline.screenshot(path=str(OUT / "monthly-review-offline-mobile.png"), full_page=True)
        results.append({"id": "offline-html-mobile", "status": "passed", "overflow_px": overflow, "script_elements": 0})
        assert not errors and not api_requests
        browser.close()
    result = {"status": "passed", "browser": "headless Edge", "viewport_widths": [1440, 390],
              "cases": results, "page_errors": errors, "paid_api_requests": len(api_requests),
              "screenshots": ["monthly-review-desktop.png", "monthly-review-plan-rejection.png", "monthly-review-mobile.png", "monthly-review-offline-mobile.png"]}
    (ROOT / "reports/monthly-browser-acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__": main()
