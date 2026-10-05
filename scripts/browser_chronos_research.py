"""Actual Edge desktop/mobile checks of recorded model audit and downloads."""
from pathlib import Path
from urllib.parse import urlencode
import json

from playwright.sync_api import sync_playwright, expect

from guanlan.chronos_report import KEYS, LABELS, load_packaged_audit, strict_json, verify_report

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/chronos-browser-context-final'


def main():
    OUT.mkdir(exist_ok=False)
    _, protocol, _ = load_packaged_audit()
    source = (ROOT / 'src/china_macro/demo_data.json').read_bytes()
    results = []; errors = []; paid = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1050})
        def attach(target):
            target.on('pageerror', lambda error: errors.append(str(error)[:120]))
            target.on('request', lambda request: paid.append('paid-api') if request.url.startswith(('https://api.deepseek.com', 'https://api.openai.com')) else None)
        attach(page)
        def healthy(target):
            target.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').wait_for(timeout=90000)
            assert not target.locator('[data-testid="stException"], [data-testid="stAlertContentError"]').count()
            overflow = target.evaluate('Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)-innerWidth')
            assert overflow <= 0 and not errors and not paid
            return overflow
        def visit(target, key='cpi_yoy'):
            target.goto('http://127.0.0.1:8610/?' + urlencode({'view': 'intelligence', 'ai_task': '时序基础模型审计', 'chronos_indicator': key}), wait_until='domcontentloaded')
            target.get_by_role('button', name='下载基础模型审计 JSON', exact=True).wait_for(timeout=90000)
            healthy(target)
        def download(target, extension, stem):
            labels = {'json': '下载基础模型审计 JSON', 'csv': '下载基础模型逐期 CSV', 'html': '下载基础模型审计 HTML'}
            before = target.url
            with target.expect_download(timeout=90000) as pending:
                target.get_by_role('button', name=labels[extension], exact=True).click()
            pending.value.save_as(str(OUT / f'{stem}.{extension}'))
            assert target.url == before
            healthy(target)
            if extension == 'json':
                data = strict_json((OUT / f'{stem}.json').read_bytes())
                assert verify_report(data['report'], protocol, source)['status'] == 'passed'
                return data
        visit(page)
        page.locator('[data-testid="stMain"]').evaluate('(el)=>el.scrollTo(0,0)')
        page.screenshot(path=str(OUT / 'chronos-overview-desktop.png'), full_page=True)
        first = download(page, 'json', 'desktop-first')
        assert first['report']['model_predictions'] == 84 and not first['report']['production_default_changed']
        for extension in ('html', 'csv'):
            download(page, extension, 'desktop-first')
        page.locator('[data-testid="stPlotlyChart"]').scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / 'chronos-desktop.png'), full_page=True)
        results.append({'id': 'actual-full-audit-and-three-downloads', 'status': 'passed', 'overflow_px': healthy(page)})
        repeated = download(page, 'json', 'desktop-repeat')
        assert repeated['report']['report_id'] == first['report']['report_id']
        results.append({'id': 'repeat-download-keeps-report-and-page', 'status': 'passed'})
        for key in KEYS:
            selector = page.get_by_role('combobox', name='审计指标', exact=True)
            selector.click()
            page.get_by_role('option', name=LABELS[key], exact=True).click()
            expect(selector).to_have_value(LABELS[key])
            expect(page.locator('.gtitle')).to_have_text(LABELS[key] + ' · 单步回顾预测')
            healthy(page)
            assert 'chronos_indicator=' + key in page.url
            current = download(page, 'json', key)
            assert current['report']['report_id'] == first['report']['report_id']
            results.append({'id': 'indicator-' + key, 'status': 'passed', 'overflow_px': healthy(page)})
        page.get_by_text('训练边界、时间切片与复现证据', exact=True).click()
        healthy(page)
        expect(page.get_by_text('Chronos 审计预测只收到统计期之前的 48—59 个历史观测；开发期基线使用 36—47 个。', exact=False)).to_be_visible()
        page.screenshot(path=str(OUT / 'chronos-boundaries-desktop.png'), full_page=True)
        results.append({'id': 'boundary-and-year-slice-evidence', 'status': 'passed'})
        mobile = browser.new_page(viewport={'width': 390, 'height': 900}); attach(mobile)
        visit(mobile)
        mobile.locator('[data-testid="stPlotlyChart"]').scroll_into_view_if_needed()
        mobile.screenshot(path=str(OUT / 'chronos-mobile.png'), full_page=True)
        assert download(mobile, 'json', 'mobile')['report']['report_id'] == first['report']['report_id']
        results.append({'id': 'mobile-actual-chart-and-download', 'status': 'passed', 'overflow_px': healthy(mobile)})
        offline = browser.new_page(viewport={'width': 390, 'height': 900}); attach(offline)
        offline.goto((OUT / 'desktop-first.html').as_uri())
        assert not offline.locator('script').count()
        overflow = offline.evaluate('Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)-innerWidth')
        assert overflow <= 0
        assert offline.locator('.scroll').evaluate('(el)=>el.scrollWidth>el.clientWidth')
        offline.locator('.scroll').evaluate('(el)=>el.scrollLeft=el.scrollWidth')
        assert offline.locator('.scroll').evaluate('(el)=>el.scrollLeft>0')
        offline.locator('.scroll').evaluate('(el)=>el.scrollLeft=0')
        offline.screenshot(path=str(OUT / 'chronos-offline-mobile.png'), full_page=True)
        results.append({'id': 'offline-html-mobile-no-script', 'status': 'passed', 'overflow_px': overflow})
        browser.close()
    result = {'status': 'passed', 'browser': 'actual headless Microsoft Edge', 'cases': results,
              'viewport_widths': [1440, 390], 'page_errors': errors, 'paid_api_requests': len(paid),
              'first_attempt_failure': 'Driver read inner_text of an input-based Streamlit selector; actual selected value is input.value. First screenshots and downloads retained.',
              'second_attempt_failure': 'Offline HTML fixed revision text overflowed a 390px viewport; wrap-anywhere CSS added. Previous exports retained.',
              'third_attempt_failure': 'Existing preview retained imported old exporter code; inspected downloaded CSS and restarted only the owned preview.',
              'artifact_directory': str(OUT.relative_to(ROOT)),
              'screenshots': ['chronos-overview-desktop.png', 'chronos-desktop.png', 'chronos-boundaries-desktop.png', 'chronos-mobile.png', 'chronos-offline-mobile.png']}
    (ROOT / 'reports/chronos-browser-acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
