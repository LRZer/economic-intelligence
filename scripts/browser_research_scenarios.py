from pathlib import Path
import json
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
out=root/'output/browser-scenario-exports'
out.mkdir(parents=True,exist_ok=True)
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1050})
    for year in [2023,2024,2025,2023]:
        page.goto(f'http://127.0.0.1:8610/?view=intelligence&ai_task=宏观与行业风险研究&country=USA&hs2=85&sector_year={year}',wait_until='domcontentloaded')
        page.locator('[data-testid="stPlotlyChart"]').filter(visible=True).first.wait_for(timeout=60000)
        page.get_by_role('tab',name='同组对照',exact=True).click()
        page.get_by_text('同一行业 · 跨国家',exact=True).click()
        page.wait_for_timeout(900)
        assert page.get_by_role('tab',name='同组对照',exact=True).get_attribute('aria-selected')=='true'
        assert not page.locator('[data-testid="stException"], [data-testid="stAlertContentError"]').count()
        page.screenshot(path=str(out/f'USA-HS85-{year}-comparison.png'),full_page=True)
        page.get_by_role('tab',name='研究报告',exact=True).click()
        for kind,label in [('html','下载研究报告 HTML'),('json','下载证据与协议 JSON'),('csv','下载当前估计 CSV')]:
            try:
                with page.expect_download() as pending:page.get_by_role('button',name=label,exact=True).click()
            except Exception:
                page.screenshot(path=str(out/f'failed-{year}-{kind}.png'),full_page=True)
                print({'failed_year':year,'failed_format':kind,'selected_tabs':page.get_by_role('tab').evaluate_all('(items)=>items.map(e=>[e.textContent,e.getAttribute("aria-selected")])')})
                raise
            assert page.get_by_role('tab',name='研究报告',exact=True).get_attribute('aria-selected')=='true'
            pending.value.save_as(str(out/f'USA-HS85-{year}.{kind}'))
        evidence=json.loads((out/f'USA-HS85-{year}.json').read_text(encoding='utf-8'))
        assert evidence['scope']=={'country_code':'USA','hs2':'85','target_year':year}
        assert evidence['research_estimate']['train_end']==year-1
        assert all(r['year']<=year for r in evidence['history'])
        context=evidence['comparison_context']
        assert context['lens']=='industry' and context['target_year']==year
        assert context['training_event_context']['last_label_year']==year-1
        assert all(r['year']==year and r['hs2']=='85' and r['train_end']<year for r in context['peers'])
        assert evidence['partner_evidence_reconciled'] is True
        results.append({'country':'USA','hs2':'85','target_year':year,'peer_count':context['peer_count'],
                        'last_label_year':context['training_event_context']['last_label_year'],'status':'passed'})
    browser.close()
(root/'reports/research-scenario-browser.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
