"""观澜中文研究台：公共品牌框架与独立页面路由。"""
from pathlib import Path
import sys
import streamlit as st
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from guanlan.ui.common import DataStore, run_module
from guanlan.ui import overview, compare, financial, trade, research, methods, china, intelligence
st.set_page_config(page_title='观澜｜宏观与行业研究', page_icon='🌐', layout='wide')
st.markdown(f"<style>{(Path(__file__).parent / 'assets/guanlan.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
# 仅声明中文语言和翻译策略；不替换文本，不修改 React 节点方法，不吞前端错误。
st.iframe('''<script>
try {
 const d = window.parent.document;
 d.documentElement.setAttribute('lang', 'zh-CN');
 d.documentElement.setAttribute('translate', 'no');
 let m = d.head.querySelector('meta[name="google"]');
 if (!m) { m = d.createElement('meta'); m.name = 'google'; d.head.appendChild(m); }
 m.content = 'notranslate';
 if (window.frameElement) { window.frameElement.setAttribute('aria-hidden', 'true'); }
} catch (e) { console.info('Guanlan locale metadata unavailable in this embed'); }
</script>''', height=1, tab_index=-1, alt='中文语言设置')
PAGES = {'风险研究': ('intelligence', intelligence.render), '中国观察': ('china', china.render),
         '经济体概览': ('overview', overview.render), '跨国比较': ('compare', compare.render),
         '金融条件': ('financial', financial.render), '贸易结构': ('trade', trade.render),
         '研究': ('research', research.render), '数据与方法': ('methods', methods.render)}
LEGACY = {'outlook': 'compare', 'cycle': 'research', 'report': 'research', 'ai': 'research'}
if 'initial_query' not in st.session_state:
 st.session_state['initial_query'] = st.query_params.to_dict()
if 'research_navigation' not in st.session_state:
 requested = st.session_state['initial_query'].get('view', 'intelligence')
 requested = LEGACY.get(requested, requested)
 st.session_state['research_navigation'] = next((label for label, (slug, _) in PAGES.items() if slug == requested), '经济体概览')
st.markdown('<div class="top-brand" translate="no"><div class="brand-mark">观</div><div class="brand">观澜 <span>GUANLAN</span></div><div class="top-brand-divider"></div><div class="brand-sub">宏观与行业研究</div><div class="top-brand-note">ECONOMIC INTELLIGENCE</div></div>', unsafe_allow_html=True)
page = st.radio('研究工作区', list(PAGES), horizontal=True, label_visibility='collapsed', key='research_navigation', width='stretch')
store = DataStore()
with st.empty().container():
 run_module(page, lambda: PAGES[page][1](store))
st.markdown('<div class="site-foot" translate="no">固定快照的描述性研究 · 官方历史数据可能修订 · 不构成投资建议</div>', unsafe_allow_html=True)
