"""Actual Edge acceptance of module cooperation; preserves earlier phase artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright,expect

from guanlan.monthly_review import verify_exported_review
from guanlan.evidence_assistant import verify_answer_report
from guanlan.trade_graph import verify_graph_report
from guanlan.chronos_report import LABELS

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',default='overall-browser-v1');args=parser.parse_args()
    if not args.output.startswith('overall-browser-') or '/' in args.output or '\\' in args.output:raise ValueError('Bounded report directory name required')
    out=ROOT/'reports'/args.output;out.mkdir(exist_ok=False)
    results=[];errors=[];paid=[];sources={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['app.py','src/guanlan/ui/workflow.py','src/guanlan/ui/china.py','src/guanlan/ui/intelligence.py','src/guanlan/ui/sector.py','src/guanlan/ui/trade_graph.py','src/guanlan/ui/chronos_research.py','src/guanlan/ui/research.py']}
    def record(name,**details):
        results.append({'id':name,'status':'passed',**details})
        (out/'progress.json').write_text(json.dumps({'status':'in_progress','cases':results,'source_sha256':sources},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Passed '+name,flush=True)
    with sync_playwright() as engine:
        browser=engine.chromium.launch(channel='msedge',headless=True)
        def create(width=1440,height=1050):
            p=browser.new_page(viewport={'width':width,'height':height})
            p.on('pageerror',lambda e:errors.append(type(e).__name__))
            p.on('request',lambda r:paid.append('paid-api') if r.url.startswith(('https://api.deepseek.com','https://api.openai.com')) else None)
            return p
        def healthy(p):
            p.wait_for_function("""()=>{const a=document.querySelector('[data-testid="stApp"]');if(!a||a.getAttribute('data-test-script-state')!=='notRunning'){window.overallIdleSince=0;return false}if(!window.overallIdleSince)window.overallIdleSince=performance.now();return performance.now()-window.overallIdleSince>1200}""",timeout=120000)
            p.evaluate('window.overallIdleSince=0')
            assert not p.locator('[data-testid="stException"], [data-testid="stAlertContentError"]').count()
            overflow=p.evaluate('Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)-innerWidth')
            assert overflow<=0 and not errors and not paid
            return overflow
        def visit(p,**query):
            p.goto('http://127.0.0.1:8610/?'+urlencode(query),wait_until='domcontentloaded')
            p.locator('h1').first.wait_for(timeout=120000);healthy(p)
        def click(p,label):
            p.get_by_role('button',name=label,exact=True).click();healthy(p)
        def shot(p,stem,chart=False):
            if chart:p.locator('[data-testid="stPlotlyChart"]').filter(visible=True).first.scroll_into_view_if_needed(timeout=60000)
            else:p.locator('[data-testid="stMain"]').evaluate('(e)=>e.scrollTo(0,0)')
            p.screenshot(path=str(out/(stem+'.png')),full_page=True)
        def download(p,stem,label,kind='json'):
            before=p.url
            with p.expect_download(timeout=90000) as pending:p.get_by_role('button',name=label,exact=True).click()
            pending.value.save_as(str(out/(stem+'.'+kind)));assert p.url==before;healthy(p)
            return json.loads((out/(stem+'.json')).read_text(encoding='utf-8')) if kind=='json' else None

        page=create()
        visit(page,view='china',china_indicator='ppi_mom')
        click(page,'分析当前指标：预测与异常核查')
        assert 'ai_indicator=ppi_mom' in page.url
        monthly=download(page,'ppi-monthly','下载核验包 JSON')
        assert monthly['bundle']['selection']['indicator_key']=='ppi_mom' and verify_exported_review(monthly)['status']=='passed'
        download(page,'ppi-monthly','下载核验单 HTML','html');download(page,'ppi-monthly','下载声明与证据 CSV','csv')
        shot(page,'monthly-workflow-desktop');record('source-to-monthly-same-scope-three-downloads',overflow_px=healthy(page))
        click(page,'核对该指标官方历史');assert 'china_indicator=ppi_mom' in page.url
        shot(page,'official-history-desktop',chart=True)
        click(page,'分析当前指标：预测与异常核查');click(page,'查看固定基础模型审计')
        assert 'chronos_indicator=ppi_mom' in page.url
        expect(page.get_by_role('combobox',name='审计指标',exact=True)).to_have_value(LABELS['ppi_mom'])
        shot(page,'chronos-workflow-desktop',chart=True)
        record('monthly-source-chronos-preserves-indicator',fixed_chronos_window='2025-09—2026-08',new_model_calls=0)
        click(page,'打开该指标当前月度研究');assert 'ai_indicator=ppi_mom' in page.url
        click(page,'用证据工具核查当前读数')
        question=page.get_by_role('textbox',name='研究问题',exact=True).input_value();assert 'PPI环比' in question
        click(page,'核查问题')
        answer=download(page,'ppi-question','下载问答证据 JSON')
        assert answer['answer']['status']=='answered' and answer['answer']['scope']['key']=='ppi_mom' and verify_answer_report(answer)['status']=='passed'
        official=json.loads((ROOT/'src/china_macro/demo_data.json').read_text(encoding='utf-8'))['rows']
        latest=sorted([r for r in official if r['key']=='ppi_mom'],key=lambda r:r['period'])[-1]
        assert answer['answer']['numbers']['value']==latest['value'] and answer['answer']['scope']['periods']==[latest['period']]
        shot(page,'evidence-workflow-desktop');record('monthly-to-original-assistant-official-number-verified',latest_period=latest['period'])

        visit(page,view='intelligence',ai_task='宏观与行业风险研究',sector_year='2025',country='USA',hs2='85')
        page.get_by_role('tab',name='研究报告',exact=True).click();healthy(page)
        before=download(page,'usa-sector-before','下载证据与协议 JSON')
        click(page,'核查 2024 年真实伙伴图')
        assert all(value in page.url for value in ['graph_year=2024','graph_country=USA','graph_hs2=85'])
        field=page.get_by_role('spinbutton').first;field.fill('7')
        click(page,'应用压力情景')
        graph=download(page,'usa-graph','下载贸易图证据 JSON')
        assert graph['analysis']['scope']=={'year':2024,'origin':'USA','hs2':'85'} and list(graph['analysis']['assumptions']['shocks_pct'].values())==[7.]
        assert verify_graph_report(graph)['status']=='passed'
        for kind,label in [('html','下载贸易图报告 HTML'),('csv','下载完整路径 CSV')]:download(page,'usa-graph',label,kind)
        page.get_by_role('tab',name='两跳路径',exact=True).click();healthy(page);shot(page,'graph-workflow-desktop',chart=True)
        record('sector-target2025-to-input2024-real-graph-three-downloads',target_year=2025,input_year=2024)
        click(page,'查看 2025 年同对象行业研究')
        assert 'sector_year=2025' in page.url
        page.get_by_role('tab',name='研究报告',exact=True).click();healthy(page)
        after=download(page,'usa-sector-after','下载证据与协议 JSON')
        assert before['scope']==after['scope']=={'country_code':'USA','hs2':'85','target_year':2025}
        assert before['research_estimate']==after['research_estimate']
        shot(page,'sector-workflow-desktop')
        click(page,'核查 2024 年真实伙伴图')
        repeated=download(page,'usa-graph-return','下载贸易图证据 JSON')
        assert repeated['report_id']==graph['report_id']
        record('graph-sector-roundtrip-keeps-applied-pressure-and-model-probabilities')

        navigation=[('风险研究','intelligence'),('中国观察','china'),('经济体概览','overview'),('跨国比较','compare'),('金融条件','financial'),('贸易结构','trade'),('研究','research'),('数据与方法','methods')]
        for label,view in navigation:
            page.get_by_text(label,exact=True).first.click();healthy(page)
            assert 'view='+view in page.url
            shot(page,'workspace-'+view)
            charts=page.locator('[data-testid="stPlotlyChart"]').filter(visible=True).count()
            if view not in ('research','methods'):assert charts>0
            for button in page.get_by_role('button',name='生成解释性摘要',exact=True).all():assert button.is_disabled()
            record('desktop-navigation-'+view,visible_charts=charts,overflow_px=healthy(page))
        page.get_by_text('风险研究',exact=True).first.click();healthy(page)
        for task in ['宏观与行业风险研究','中国月度预测与异常','全球年度GDP研究','美国周期风险研究','证据问答与工具','真实贸易图与情景','时序基础模型审计']:
            page.get_by_text(task,exact=True).first.click();healthy(page)
            assert task in __import__('urllib.parse',fromlist=['unquote']).unquote(page.url)
            record('desktop-task-'+task,visible_charts=page.locator('[data-testid="stPlotlyChart"]').filter(visible=True).count(),overflow_px=healthy(page))

        mobile=create(390,900)
        visit(mobile,view='china',china_indicator='ppi_mom');click(mobile,'分析当前指标：预测与异常核查')
        report=download(mobile,'mobile-monthly','下载核验包 JSON');assert report['bundle']['review_id']==monthly['bundle']['review_id']
        shot(mobile,'monthly-workflow-mobile');record('mobile-source-monthly-same-report',overflow_px=healthy(mobile))
        click(mobile,'查看固定基础模型审计');assert 'chronos_indicator=ppi_mom' in mobile.url
        shot(mobile,'chronos-workflow-mobile',chart=True);record('mobile-chronos-same-indicator',overflow_px=healthy(mobile))
        offline=create(390,900);offline.goto((out/'ppi-monthly.html').as_uri());assert not offline.locator('script').count()
        overflow=offline.evaluate('Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)-innerWidth');assert overflow<=0
        shot_path=out/'offline-monthly-mobile.png';offline.screenshot(path=str(shot_path),full_page=True)
        record('offline-html-mobile-no-script',overflow_px=overflow)
        browser.close()
    result={'status':'passed','browser':'actual headless Microsoft Edge','viewport_widths':[1440,390],'cases':results,'page_errors':errors,
            'browser_paid_api_requests':len(paid),'server_paid_api_configuration':'ENABLE_PAID_AI=0; separate regression traps credential lookup and requests',
            'source_sha256':sources,'new_chronos_model_calls':0,'llm_business_calls':0,
            'scope':'Current real-snapshot cross-module handoffs, all 8 navigation pages and 7 risk tasks; mobile handoff and offline HTML. Not every possible economic object/device or production certification.'}
    (out/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
