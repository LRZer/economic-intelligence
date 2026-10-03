"""Headless browser acceptance against the explicitly started local app."""
from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / 'assets' / 'screenshots'
SCREENSHOTS.mkdir(parents=True, exist_ok=True)
report = {'pages': [], 'console_errors': [], 'paid_api_requests': []}

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width':1440,'height':1050}, device_scale_factor=1)
    page.on('pageerror', lambda error: report['console_errors'].append(str(error)))
    page.on('request', lambda request: report['paid_api_requests'].append(request.url)
            if 'api.deepseek.com' in request.url else None)
    for view, extra, name, title in [
        ('intelligence','&ai_task=中国月度预测与异常','ai-china','AI 研究工作区'),
        ('intelligence','&ai_task=宏观与行业风险研究','ai-sector','AI 研究工作区'),
        ('intelligence','&ai_task=全球年度GDP研究','ai-global','AI 研究工作区'),
        ('intelligence','&ai_task=美国周期风险研究','ai-us','AI 研究工作区'),
        ('china','','china-observation','中国经济观察'),
        ('overview','','global-overview','经济体概览'),
        ('trade','','trade-structure','贸易结构'),
    ]:
        page.goto(f'http://127.0.0.1:8610/?view={view}{extra}', wait_until='domcontentloaded')
        page.locator('h1').filter(has_text=title).wait_for(timeout=30000)
        page.locator('[data-testid="stPlotlyChart"]').filter(visible=True).first.wait_for(timeout=30000)
        page.wait_for_timeout(1500)
        errors = page.locator('[data-testid="stException"], [data-testid="stAlertContentError"]').all_text_contents()
        assert not errors, (name, errors)
        paid_buttons = page.get_by_role('button',name=re.compile('^生成'))
        if paid_buttons.count():
            assert all(paid_buttons.nth(i).is_disabled() for i in range(paid_buttons.count()))
        page.screenshot(path=str(SCREENSHOTS / f'{name}.png'), full_page=True)
        if name=='ai-sector':
            page.get_by_role('tab',name='验证与解释',exact=True).click()
            page.wait_for_timeout(800)
            page.locator('[data-testid=stMain]').evaluate('(e) => e.scrollTop = 650')
            page.wait_for_timeout(300)
            page.screenshot(path=str(SCREENSHOTS/'ai-sector-validation.png'),full_page=True)
            page.locator('[data-testid=stMain]').evaluate('(e) => e.scrollTop = 0')
            page.get_by_role('tab',name='行业证据与情景',exact=True).click()
            page.wait_for_timeout(800)
            page.locator('[data-testid=stMain]').evaluate('(e) => e.scrollTop = 600')
            page.screenshot(path=str(SCREENSHOTS/'ai-sector-network.png'),full_page=True)
            page.locator('[data-testid=stMain]').evaluate('(e) => e.scrollTop = 0')
            page.get_by_role('tab',name='研究报告',exact=True).click()
            demo=ROOT/'assets/demo';demo.mkdir(exist_ok=True)
            for kind,label in [('html','下载研究报告 HTML'),('json','下载证据与协议 JSON'),('csv','下载当前估计 CSV')]:
                with page.expect_download() as pending:
                    page.get_by_role('button',name=label,exact=True).click()
                pending.value.save_as(str(demo/f'CHN-HS85-2025.{kind}'))
            exported=json.loads((demo/'CHN-HS85-2025.json').read_text(encoding='utf-8'))
            assert exported['scope']=={'country_code':'CHN','hs2':'85','target_year':2025}
            assert exported['default_reference']=='global_rate' and exported['evaluation_scope']
            assert '<script>' not in (demo/'CHN-HS85-2025.html').read_text(encoding='utf-8')
            report['sector_exports_verified']=True
        report['pages'].append({'name':name,'view':view,'charts':page.locator('[data-testid="stPlotlyChart"]').count(),
                                'errors':errors,'screenshot':f'assets/screenshots/{name}.png'})
    # Repeated navigation must keep selectors valid and render the same scope.
    for _ in range(2):
        page.get_by_text('中国观察',exact=True).click()
        page.get_by_text('数据质量',exact=True).click()
        page.get_by_text('官方观测',exact=True).wait_for()
        page.get_by_text('AI研究',exact=True).click()
        page.get_by_text('中国月度预测与异常',exact=True).click()
        page.get_by_text('留出期模型 MAE',exact=True).wait_for()
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(SCREENSHOTS/'ai-mobile.png'),full_page=True)
    report['horizontal_overflow_px']=page.evaluate('Math.max(0,document.documentElement.scrollWidth-window.innerWidth)')
    assert report['horizontal_overflow_px']==0
    page.get_by_text('宏观与行业风险研究',exact=True).click()
    page.get_by_text('默认 · 开发期选定参考',exact=True).wait_for(timeout=30000)
    page.wait_for_timeout(1000)
    page.screenshot(path=str(SCREENSHOTS/'ai-sector-mobile.png'),full_page=True)
    report['sector_mobile_overflow_px']=page.evaluate('Math.max(0,document.documentElement.scrollWidth-window.innerWidth)')
    assert report['sector_mobile_overflow_px']==0
    page.goto((ROOT/'assets/demo/CHN-HS85-2025.html').resolve().as_uri())
    page.locator('h1').wait_for()
    report['offline_report_mobile_overflow_px']=page.evaluate('Math.max(0,document.documentElement.scrollWidth-window.innerWidth)')
    assert report['offline_report_mobile_overflow_px']==0
    page.set_viewport_size({'width':1440,'height':1250})
    page.screenshot(path=str(SCREENSHOTS/'sector-offline-report.png'),full_page=True)
    report['offline_report_rendered']=True
    assert not report['console_errors']
    assert not report['paid_api_requests']
    browser.close()

(ROOT/'reports'/'browser-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
