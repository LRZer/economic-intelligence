const $ = (selector) => document.querySelector(selector);
const state = { data: null, selected: 'industrial_yoy', range: 12, customRange:null, compare: 'prices', group: '全部', query: '', qualityFilter:'issues', expanded:new Set(), analyzing:false };
const featured = ['industrial_yoy', 'retail_yoy', 'fai_ytd_yoy', 'manufacturing_pmi', 'cpi_yoy', 'unemployment'];
const themes = [
  ['生产与需求',['private_fai_ytd_yoy','manufacturing_fai_ytd_yoy','industrial_profit_ytd_yoy']],
  ['价格',['ppi_yoy','cpi_mom','ppi_mom']],
  ['货币与融资',['m1_yoy','m2_yoy','tsf_stock_yoy','loans_ytd']],
  ['财政与房地产',['fiscal_revenue_ytd_yoy','fiscal_spending_ytd_yoy','land_revenue_ytd_yoy','real_estate_fai_ytd_yoy','housing_sales_area_ytd_yoy']],
  ['外贸',['export_usd_yoy','import_usd_yoy','export_yoy','import_yoy']],
];
const comparePresets = {
  prices: {label:'价格同比',title:'消费与工业价格同比',description:'CPI 与 PPI · 单月同比 · %',keys:['cpi_yoy','ppi_yoy'],baseline:0},
  priceMomentum: {label:'价格环比',title:'消费与工业价格环比',description:'CPI 与 PPI · 单月环比 · %',keys:['cpi_mom','ppi_mom'],baseline:0},
  business: {label:'景气',title:'采购经理指数',description:'制造业、制造业新订单、非制造业 · 当月水平 · %',keys:['manufacturing_pmi','manufacturing_new_orders_pmi','nonmanufacturing_pmi'],baseline:50},
  trade: {label:'外贸',title:'货物进出口（美元口径）',description:'出口与进口 · 美元金额单月同比 · %',keys:['export_usd_yoy','import_usd_yoy'],baseline:0},
  fiscal: {label:'财政',title:'财政收支与土地收入',description:'财政部全国报告 · 年内累计同比 · %',keys:['fiscal_revenue_ytd_yoy','fiscal_spending_ytd_yoy','land_revenue_ytd_yoy'],baseline:0},
};
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const format = (value) => Math.abs(value)>=1000 ? Number(value).toLocaleString('zh-CN',{maximumFractionDigits:2}) : (Number.isInteger(value) ? value.toFixed(1) : Number(value).toFixed(2).replace(/0$/, ''));
const periodLabel = (period) => period ? `${period.slice(0,4)}年${Number(period.slice(5))}月` : '—';
const metric = (key) => state.data?.catalog.find(x => x.key === key);
const series = (key) => state.data?.series[key] || [];
const latest = (key) => state.data?.latest[key];
const sourceLabel = (source) => ({NBS:'国家统计局','NBS/GACC':'国家统计局 / 海关总署',PBC:'中国人民银行',MOFCOM:'商务部',MOF:'财政部'})[source] || source;
const isRepost = row => (row?.source_url||'').startsWith('https://fdi.mofcom.gov.cn/');
const publicationLabel = row => isRepost(row)?'网页转载日期':'官方发布日期';
const recordPublisher = (row, source) => isRepost(row)?'商务部转载 · 海关总署':sourceLabel(source);
const dateTime = value => value ? new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) : '未核实';
const comparison = key => state.data?.reader_summary?.changes[key];
const pages = {
  '/': {section:'overview', name:'总览', title:'总览'},
  '/quality': {section:'quality', name:'数据状态', title:'数据状态'},
  '/trends': {section:'trends', name:'趋势分析', title:'趋势分析'},
  '/data': {section:'data', name:'指标数据', title:'指标数据'},
  '/insights': {section:'insights', name:'本期观察', title:'本期观察'},
  '/sources': {section:'sources', name:'来源与方法', title:'来源与方法'},
};

function currentPagePath() {
  const legacy = location.hash.slice(1);
  if (Object.values(pages).some(page => page.section === legacy)) {
    const path = legacy === 'overview' ? '/' : `/${legacy}`;
    history.replaceState(null, '', path);
    return path;
  }
  return location.pathname.replace(/\/$/, '') || '/';
}

function applyPage() {
  const path = currentPagePath();
  const page = pages[path] || pages['/'];
  if (page.section==='trends') {
    const params=new URLSearchParams(location.search), key=params.get('metric'), range=params.get('range');
    if (key && /^[a-z][a-z0-9_]+$/.test(key) && (!state.data||metric(key))) state.selected=key;
    if (['6','12','24','all','custom'].includes(range)) state.range=range;
    if (range==='custom' && /^\d{4}-\d{2}$/.test(params.get('start')||'') && /^\d{4}-\d{2}$/.test(params.get('end')||'')) state.customRange={start:params.get('start'),end:params.get('end')};
  }
  document.querySelectorAll('.page-view').forEach(view => { view.hidden = view.id !== page.section; });
  document.querySelectorAll('.nav-link').forEach(link => {
    const active = link.getAttribute('href') === path;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  $('#pageTitle').textContent = page.title;
  $('#breadcrumbPage').textContent = page.name;
  document.title = `${page.name} · 经纬`;
  if (page.section === 'trends' && state.data) requestAnimationFrame(() => { renderSelect();renderRangeControls();renderChart(); renderCompare(); });
}

function navigatePage(path) {
  const target=new URL(path,location.origin);
  if (!pages[target.pathname]) return;
  if (location.pathname+location.search !== target.pathname+target.search || location.hash) history.pushState(null, '', target.pathname+target.search);
  applyPage();
  window.scrollTo({top:0, behavior:'instant'});
}

function openMetric(key) {if(metric(key)){state.selected=key;navigatePage(`/trends?metric=${encodeURIComponent(key)}&range=${state.range==='custom'?'12':state.range}`);}}
function updateTrendURL() {
  const params=new URLSearchParams({metric:state.selected,range:String(state.range)});
  if(state.range==='custom'&&state.customRange){params.set('start',state.customRange.start);params.set('end',state.customRange.end);}
  history.replaceState(null,'',`/trends?${params}`);
}

function showNotice(message, success=false) {
  const box = $('#notice');
  box.textContent = message;
  box.className = `notice${success ? ' success' : ''}`;
  box.hidden = !message;
}

async function getDashboard() {
  const response = await fetch('/api/dashboard', {cache:'no-store'});
  if (!response.ok) throw new Error('无法读取本地数据');
  state.data = await response.json();
  render();
}

function render() {
  const data = state.data;
  if (!data) return;
  const refreshed = data.last_refresh ? dateTime(data.last_refresh) : null;
  $('#syncStatus').textContent = data.refreshing ? '正在同步官方来源…' : (refreshed ? `最近同步 ${refreshed}` : '核验快照');
  $('#pageContext').textContent = data.quality?.as_of ? `核查于 ${dateTime(data.quality.as_of).split(' ')[0]}` : '';
  $('#refreshBtn').disabled = data.refreshing;
  if (data.last_error) showNotice('本次同步有来源未完成，已有数据可继续查看。请到“数据状态”页核查采集记录。');
  else if (!refreshed && data.demo_captured_at) showNotice(`当前展示 ${data.demo_captured_at.slice(0,10)} 保存的核验快照，尚无本机同步记录。`);
  else showNotice('');
  renderOverview();renderCards(); renderQuality(); renderSelect();renderRangeControls(); renderChart(); renderCompare(); renderFilters(); renderTable(); renderResearch(); renderObservations(); renderAI();
}

function difference(key) {
  const item=comparison(key);
  return item?.delta!==null && item?.delta!==undefined ? {value:item.delta,period:item.comparison_period,direction:item.direction} : null;
}

function renderQuality() {
  const quality = state.data.quality;
  if (!quality) return;
  const revisions=state.data.recent_changes||[];
  const valueRevisions=revisions.filter(x=>x.change_type==='value_revision');
  const cards=[['待补录',quality.expected-quality.observed,'近24个月的预期记录缺口'],['待发布',quality.pending_count||0,'未到已核实的官方计划时间'],['发布时间待确认',quality.unconfirmed_count||0,'近期未核实发布日，暂不计缺失'],['最近数值修订',valueRevisions.length,'最近20条变更记录中的数值修订']];
  $('#qualityStats').innerHTML=cards.map(([label,value,note])=>`<div class="status-stat"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join('');
  const long=state.data.quality_60m;
  $('#qualityMeta').textContent=`${quality.populated_indicators}/${quality.indicator_count}项指标 · ${quality.observation_count.toLocaleString('zh-CN')}条记录 · 近24个月收录覆盖${quality.coverage_pct}% · 近5年${long?.coverage_pct??'—'}%`;
  $('#qualityWindow').textContent=`窗口截止 ${quality.latest_period||'—'}`;
  const items=quality.metrics.filter(item=>state.qualityFilter==='all'||state.qualityFilter==='missing'&&item.missing.length||state.qualityFilter==='pending'&&item.pending.length||state.qualityFilter==='issues'&&(item.missing.length||item.pending.length||item.unconfirmed?.length));
  if(state.qualityFilter!=='all')items.sort((a,b)=>b.missing.length-a.missing.length||(b.unconfirmed?.length||0)-(a.unconfirmed?.length||0)||b.pending.length-a.pending.length);
  $('#qualityRows').innerHTML=items.map(item=>{
    const states=item.period_states||[];
    const band=states.map(entry=>`<button type="button" class="month-cell ${entry.code}" data-status-key="${item.key}" data-period="${entry.period}" aria-label="${escapeHTML(item.name+' '+entry.period+' '+entry.label)}" title="${escapeHTML(entry.period+' · '+entry.label+' · '+entry.reason)}">${Number(entry.period.slice(5))}</button>`).join('');
    const counts=[item.missing.length?`${item.missing.length}期待补录`:'',item.pending.length?`${item.pending.length}期待发布`:'',item.unconfirmed?.length?`${item.unconfirmed.length}期日期待确认`:''].filter(Boolean).join(' · ');
    return `<tr><td><button class="metric-name" type="button" data-open-metric="${item.key}">${escapeHTML(item.name)}</button><small>${escapeHTML(sourceLabel(item.source))}${item.inactive?' · 旧口径已结束':''}</small></td><td>${item.latest||'—'}</td><td><div class="month-band">${band}</div><div class="band-caption"><span>${states[0]?.period||''}</span><span>${states.at(-1)?.period||''}</span></div></td><td>${counts||'无待处理记录'}<small>已收录 ${item.observed}/${item.expected} 个预期值 · ${item.coverage_pct}%</small></td></tr>`;
  }).join('')||'<tr><td colspan="4">当前筛选下没有需处理的记录。</td></tr>';
  document.querySelectorAll('[data-quality-filter]').forEach(button=>{button.classList.toggle('active',button.dataset.qualityFilter===state.qualityFilter);button.setAttribute('aria-pressed',button.dataset.qualityFilter===state.qualityFilter);});
  document.querySelectorAll('[data-status-key]').forEach(button=>button.addEventListener('click',()=>showPeriodStatus(button.dataset.statusKey,button.dataset.period)));
  $('#revisionNote').textContent=valueRevisions.length?valueRevisions.map(item=>`${metric(item.key)?.name||item.key} ${item.period}：${format(item.old_value)} → ${format(item.new_value)}（${dateTime(item.detected_at)}发现）`).join('；'):'暂无已记录的数值修订；后续原值变更保留审计记录。';
  const run=(state.data.ingestion_runs||[])[0];
  if (run) {
    const status={complete:'完成',success:'完成',partial:'部分完成',failed:'失败',rejected:'拒绝入库'}[run.status]||run.status;
    const kind={backfill:'历史回填',annual_backfill:'年末报告回填',nbs_gap_backfill:'统计局专题补缺',trade_backfill:'外贸回填',cny_trade_backfill:'人民币外贸补缺',pbc_backfill:'央行历史回填',fiscal_backfill:'财政回填',refresh:'日常更新',date_hydration:'发布日期补齐'}[run.kind]||run.kind;
    const time=dateTime(run.finished_at);
    const warning=run.warnings?.length?`；${run.warnings.length} 项来源警告：${run.warnings[0]}`:'';
    const addedLabel=run.kind==='date_hydration'?'补齐发布日期':'新增观测';
    const parsedLabel=run.kind==='date_hydration'?'篇目录报告':'条指标记录';
    $('#ingestionNote').textContent=`最近采集：${kind} · ${status} · ${time} · 处理 ${run.parsed_count} ${parsedLabel}，${addedLabel} ${run.added_count} 条${warning}`;
  } else $('#ingestionNote').textContent='尚无采集运行记录；当前数据可能来自项目附带快照。';
}

function showPeriodStatus(key,period) {
  const info=metric(key), item=state.data.quality.metrics.find(entry=>entry.key===key);
  const entry=item?.period_states.find(entry=>entry.period===period), row=series(key).find(row=>row.period===period);
  if(!entry)return;
  const source=row?.source_url||entry.source_url;
  $('#qualityDetailBody').innerHTML=`<p><strong>${escapeHTML(info.name)} · ${periodLabel(period)}</strong><span class="record-status ${entry.code}">${entry.label}</span></p><p>${escapeHTML(entry.reason)}</p>${row?`<p>读数：${format(row.value)} ${info.unit} · ${escapeHTML(info.basis)}</p><p>${publicationLabel(row)}：${row.published||'未核实'}</p>`:''}${entry.scheduled_at?`<p>官方计划：${dateTime(entry.scheduled_at)}（北京时间，计划可能调整）</p>`:''}${source?`<p><a href="${safeOfficialURL(source)}" target="_blank" rel="noopener noreferrer">${row?escapeHTML(row.source_title):'查看判定依据'} ↗</a></p>`:''}`;
  $('#qualityDetail').showModal();
}

function renderOverview() {
  const groups=[['景气',['manufacturing_pmi','manufacturing_new_orders_pmi','nonmanufacturing_pmi']],['生产与需求',['industrial_yoy','retail_yoy','fai_ytd_yoy']],['价格',['cpi_yoy','ppi_yoy']]];
  $('#dataFreshness').innerHTML=groups.map(([label,keys])=>{
    const values=keys.map(key=>latest(key)?.period).filter(Boolean).sort();
    const period=values.length?values[0]===values.at(-1)?periodLabel(values[0]):`${values[0]}—${values.at(-1)}`:'暂无记录';
    return `<span><strong>${label}</strong> 更新至 ${period}${values.length<keys.length?'（部分未收录）':''}</span>`;
  }).join('')+`<span>最近同步：${state.data.last_refresh?dateTime(state.data.last_refresh):'暂无本机同步记录'}</span>`;
  const summary=state.data.reader_summary;
  $('#overviewHeadline').textContent=summary?.headline||'暂缺连续月份的比较依据';
  $('#overviewLeadPeriod').textContent=summary?.headline_period?`${periodLabel(summary.headline_period)} · 连续月份读数比较`:'本期变化';
}

function deltaHTML(key) {
  const delta = difference(key);
  if (!delta) return `<span class="delta">${escapeHTML(comparison(key)?.reason||'暂无连续上月读数')}</span>`;
  const info=metric(key);
  return `<span class="delta">较${periodLabel(delta.period)}${delta.direction}${delta.value===0?'':` ${format(Math.abs(delta.value))} ${info?.unit==='%'?'个百分点':escapeHTML(info?.unit||'')}`}</span>`;
}

function sparkline(key) {
  const view=ChartModel.windowFor(series(key),12),points=view.points;
  if(points.length<2)return '<span class="muted">历史不足</span>';
  const scale=ChartModel.niceScale(points.map(row=>row.value)),W=118,H=40;
  const x=row=>3+(ChartModel.monthNumber(row.period)-view.start)*112/11;
  const y=row=>3+(scale.max-row.value)*34/(scale.max-scale.min);
  let runs=[],run=[],prior=null;
  points.forEach(row=>{const month=ChartModel.monthNumber(row.period);if(prior!==null&&month-prior>1){runs.push(run);run=[];}run.push(row);prior=month;});if(run.length)runs.push(run);
  const paths=runs.map(items=>`<path d="${items.map((row,i)=>`${i?'L':'M'}${x(row).toFixed(1)},${y(row).toFixed(1)}`).join(' ')}" fill="none" stroke="#287f6a" stroke-width="1.8"/>`).join('');
  const last=points.at(-1);
  return `<svg class="sparkline" viewBox="0 0 ${W} ${H}" aria-hidden="true">${paths}<circle cx="${x(last)}" cy="${y(last)}" r="2.5" fill="#287f6a"/></svg>`;
}

function renderCards() {
  $('#featuredMetrics').innerHTML = featured.map(key => {
    const info = metric(key), row = latest(key);
    if (!info) return '';
    return `<button type="button" class="metric-card" data-open-metric="${key}" aria-label="查看${escapeHTML(info.name)}趋势"><div class="card-top"><span>${escapeHTML(info.basis)}</span><span>${row?row.period:'暂无数据'}</span></div><h3>${escapeHTML(info.name)}</h3><div class="metric-body"><div class="value">${row?format(row.value):'—'}<span class="unit">${escapeHTML(info.unit)}</span></div>${sparkline(key)}</div><div class="card-bottom">${deltaHTML(key)}</div></button>`;
  }).join('');
  $('#themeMetrics').innerHTML=themes.map(([label,keys])=>`<section class="theme-group"><h3>${label}</h3>${keys.map(key=>{const info=metric(key),row=latest(key);return `<button type="button" class="theme-row" data-open-metric="${key}"><span>${escapeHTML(info.name)}</span><strong>${row?format(row.value)+' '+escapeHTML(info.unit):'—'}</strong><small>${row?.period||'未收录'} · ${escapeHTML(info.basis)}</small></button>`;}).join('')}</section>`).join('');
}

function renderSelect() {
  if(!metric(state.selected))state.selected='industrial_yoy';
  $('#metricSelect').innerHTML = state.data.catalog.map(info => `<option value="${info.key}">${escapeHTML(info.name)}</option>`).join('');
  $('#metricSelect').value = state.selected;
}

function renderRangeControls() {
  const end=state.data.quality.latest_period;
  if(state.customRange&&(!ChartModel.validPeriod(state.customRange.start)||!ChartModel.validPeriod(state.customRange.end)||state.customRange.start>state.customRange.end||state.customRange.end>end||ChartModel.monthNumber(state.customRange.end)-ChartModel.monthNumber(state.customRange.start)>=600)){
    state.customRange=null;
    if(state.range==='custom'){state.range=12;showNotice('链接中的日期区间无效，已显示最近12个月。');if(location.pathname==='/trends')updateTrendURL();}
  }
  document.querySelectorAll('[data-range]').forEach(button=>{const selected=String(state.range)===button.dataset.range;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',selected);});
  $('#customRangeForm').hidden=state.range!=='custom';
  if(!state.customRange&&end)state.customRange={start:ChartModel.periodFromNumber(ChartModel.monthNumber(end)-11),end};
  if(state.customRange){$('#chartStart').value=state.customRange.start;$('#chartEnd').value=state.customRange.end;}
  $('#chartStart').max=end||'';$('#chartEnd').max=end||'';
}

function renderChart() {
  const info = metric(state.selected);
  if (!info) return;
  const points = series(state.selected);
  const view = ChartModel.windowFor(points, state.range==='custom'?state.customRange:state.range, state.data.quality.latest_period);
  const shown = view.points;
  const quality = state.data.quality_60m;
  const qualityItem = quality?.metrics.find(item => item.key === state.selected);
  const coverageStart = quality?.latest_period ? ChartModel.periodFromNumber(ChartModel.monthNumber(quality.latest_period) - 59) : null;
  const detail = ChartModel.detailRows(view, qualityItem?.missing, qualityItem?.pending, coverageStart,qualityItem?.period_states);
  $('#chartTitle').textContent = info.name;
  $('#chartSubtitle').textContent = `${info.basis} · 单位：${info.unit}${state.selected.includes('infrastructure')?' · 新旧口径分列':state.selected==='m1_yoy'?' · 2025新口径，含2024年官方回溯':state.selected==='m1_legacy_yoy'?' · 旧口径至2024年末，不与新口径拼接':''}`;
  const current=latest(state.selected);
  $('#chartLatest').innerHTML=current?`<strong>${format(current.value)} ${escapeHTML(info.unit)}</strong><small>最新已收录 ${current.period}</small>`:'未收录';
  $('#chartCount').textContent = `${shown.length} 条观测 / ${view.periods.length} 个自然月`;
  const diff = difference(state.selected);
  const absentCount = detail.filter(item => item.code === 'missing').length;
  const waiting=detail.filter(item=>item.code==='pending').length;
  $('#chartTakeaway').textContent = `${diff ? `${current.period}较${diff.period}${diff.direction}${diff.value===0?'':` ${format(Math.abs(diff.value))} ${info.unit==='%'?'个百分点':info.unit}`}` : comparison(state.selected)?.reason||'暂无连续的可比上月'}；区间内${absentCount}期待补录${waiting?`、${waiting}期待发布`:''}。`;
  renderChartDetails(detail, info, qualityItem);
  const target = $('#chart');
  if (!shown.length) { target.innerHTML = '<div class="chart-empty">暂无符合筛选条件的数据</div>'; return; }
  const W=Math.max(target.clientWidth,300),H=target.clientHeight||300,R=20,T=18,B=38;
  const values=shown.map(d=>d.value);
  const isPMI=['manufacturing_pmi','manufacturing_new_orders_pmi','nonmanufacturing_pmi'].includes(state.selected);
  const reference=isPMI?50:Math.min(...values)<0&&Math.max(...values)>0?0:null;
  const scale=ChartModel.niceScale(values,reference),min=scale.min,max=scale.max;
  const L=Math.max(48,...scale.ticks.map(value=>value.toFixed(scale.decimals).length*7+12));
  const xMonth=month=>L+(view.end===view.start?(W-L-R)/2:(month-view.start)*(W-L-R)/(view.end-view.start));
  const x=(i)=>xMonth(ChartModel.monthNumber(shown[i].period));
  const y=(value)=>T+(max-value)*(H-T-B)/(max-min);
  const grid=scale.ticks.map(level=>{
    const yy=y(level);
    return `<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#dce5e2" stroke-width="1"/><text data-axis-tick="${level}" x="${L-10}" y="${yy+4}" text-anchor="end" fill="#53676f" font-size="12">${level.toFixed(scale.decimals)}</text>`;
  }).join('');
  const pts=shown.map((row,i)=>[x(i),y(row.value)]);
  const runs=[]; let run=[];
  shown.forEach((row,i)=>{
    const monthNumber=ChartModel.monthNumber(row.period);
    const previous=i?ChartModel.monthNumber(shown[i-1].period):null;
    if(i && monthNumber-previous>1){
      runs.push(run);run=[];
    }
    run.push(pts[i]);
  });
  if(run.length) runs.push(run);
  const paths=runs.map(group=>group.map(([xx,yy],i)=>`${i?'L':'M'} ${xx.toFixed(1)} ${yy.toFixed(1)}`).join(' '));
  const solidLines=paths.map(path=>`<path d="${path}" fill="none" stroke="#287f6a" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>`).join('');
  const tickStep=Math.max(1,Math.ceil(view.periods.length/Math.max(2,Math.floor((W-L-R)/75))));
  const labels=view.periods.map((period,i)=>i%tickStep===0||i===view.periods.length-1
    ?`<text x="${xMonth(view.start+i)}" y="${H-11}" text-anchor="middle" fill="#53676f" font-size="12">${period.slice(2).replace('-','/')}</text>`:'').join('');
  const missingMarkers=detail.filter(item=>item.code==='missing').map(item=>{
    const xx=xMonth(ChartModel.monthNumber(item.period));
    return `<line x1="${xx}" y1="${T}" x2="${xx}" y2="${H-B}" stroke="#a45b2e" stroke-width="1" stroke-dasharray="3 5"><title>${item.period} 待补录</title></line>`;
  }).join('');
  const dots=shown.map((row,i)=>`<circle cx="${x(i)}" cy="${y(row.value)}" r="4.5" fill="#fff" stroke="#258e7c" stroke-width="2.4"><title>${row.period}：${format(row.value)}${info.unit}</title></circle>`).join('');
  const baseline=reference!==null?`<line x1="${L}" y1="${y(reference)}" x2="${W-R}" y2="${y(reference)}" stroke="#8b6b31" stroke-dasharray="5 5"/><text x="${W-R}" y="${y(reference)-7}" text-anchor="end" fill="#725723" font-size="12">${isPMI?'50参考线':'零线'}</text>`:'';
  target.innerHTML=`<svg viewBox="0 0 ${W} ${H}" aria-hidden="true">${grid}${baseline}${missingMarkers}${solidLines}${dots}${labels}</svg>`;
  target.setAttribute('aria-label', `${info.name}，${view.periods.at(0)} 至 ${view.periods.at(-1)}，${shown.length} 条观测，${absentCount} 期待补录；缺口不连线，纵轴${min}至${max}。${shown.map(x=>`${x.period} ${x.value}${info.unit}`).join('，')}`);
}

function renderChartDetails(detail, info, qualityItem) {
  const missing=detail.filter(item=>item.code==='missing').length;
  $('#chartDetailNote').textContent=detail.length?`${detail[0].period}—${detail.at(-1).period} · ${detail.filter(item=>item.row).length}条观测 · ${missing}期待补录`:'暂无记录';
  $('#chartDetailRows').innerHTML=[...detail].reverse().map(({period,row,status,code,evidence})=>{
    const safe=row?safeOfficialURL(row.source_url):'#';
    const gap=evidence||((qualityItem?.missing_details||[]).find(entry=>entry.period===period));
    const gapUrl=gap?safeOfficialURL(gap.source_url):'#';
    const source=safe!=='#'
      ?`<a href="${escapeHTML(safe)}" target="_blank" rel="noopener noreferrer">${escapeHTML(row.source_title||'官方报告')} ↗</a>`
      :gap?`${gapUrl!=='#'?`<a href="${escapeHTML(gapUrl)}" target="_blank" rel="noopener noreferrer">判定依据 ↗</a>`:''}<small class="gap-explanation">${escapeHTML(gap.reason)}</small>`:'—';
    return `<tr><td>${period}</td><td><span class="record-status ${code}">${escapeHTML(status)}</span></td><td class="num">${row?format(row.value)+' '+escapeHTML(info.unit):'—'}</td><td>${row?.published?`${isRepost(row)?'转载 ':''}${escapeHTML(row.published)}`:gap?.scheduled_at?`计划 ${escapeHTML(dateTime(gap.scheduled_at))}`:'未核实'}</td><td>${source}</td></tr>`;
  }).join('');
  state.chartDetail=detail;
}

function renderCompare() {
  const preset=comparePresets[state.compare];
  const colors=['#197c6c','#c77b42','#496da8'];
  const endPeriod=state.data.quality.latest_period;
  $('#compareTitle').textContent=preset.title;
  $('#compareDescription').textContent=preset.description;
  $('#comparePresets').innerHTML=Object.entries(comparePresets).map(([key,item])=>
    `<button type="button" data-compare="${key}" class="${state.compare===key?'active':''}" aria-pressed="${state.compare===key}">${item.label}</button>`).join('');
  document.querySelectorAll('[data-compare]').forEach(button=>button.addEventListener('click',()=>{
    state.compare=button.dataset.compare;renderCompare();
  }));
  if (!endPeriod) {
    $('#compareLegend').innerHTML='';
    $('#compareChart').innerHTML='<div class="chart-empty">暂无可比较的数据</div>';
    return;
  }
  const monthNo=period=>Number(period.slice(0,4))*12+Number(period.slice(5))-1;
  const end=monthNo(endPeriod),start=end-23;
  const selected=preset.keys.map((key,index)=>({key,index,info:metric(key),points:series(key).filter(row=>{
    const month=monthNo(row.period);return month>=start&&month<=end;
  })}));
  $('#compareLegend').innerHTML=selected.map(item=>{
    const row=item.points.at(-1);
    return `<button type="button" data-compare-key="${item.key}" class="compare-legend-item"><i style="background:${colors[item.index]}"></i><span>${escapeHTML(item.info.name)}</span><strong>${row?format(row.value)+'%':'—'}</strong><small>${row?escapeHTML(row.period):'暂无数据'} · 近24个月收录${item.points.length}期</small></button>`;
  }).join('');
  document.querySelectorAll('[data-compare-key]').forEach(button=>button.addEventListener('click',()=>{
    state.selected=button.dataset.compareKey;renderSelect();updateTrendURL();renderChart();
  }));
  const all=selected.flatMap(item=>item.points.map(row=>row.value));
  if (!all.length) {
    $('#compareChart').innerHTML='<div class="chart-empty">最近 24 个月暂无可比较的数据</div>';
    return;
  }
  const compareTarget=$('#compareChart');
  const W=Math.max(compareTarget.clientWidth,300),H=compareTarget.clientHeight||290,L=52,R=24,T=19,B=40;
  const scale=ChartModel.niceScale(all,preset.baseline),min=scale.min,max=scale.max;
  const x=month=>L+(month-start)*(W-L-R)/23;
  const y=value=>T+(max-value)*(H-T-B)/(max-min);
  const grid=scale.ticks.map(level=>{
    const yy=y(level);
    return `<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#dce5e2"/><text x="${L-10}" y="${yy+4}" text-anchor="end" fill="#53676f" font-size="12">${level.toFixed(scale.decimals)}</text>`;
  }).join('');
  const tickStep=W<520?6:4;
  const axis=Array.from({length:24},(_,i)=>i).filter(i=>i%tickStep===0||i===23).map(i=>{
    const number=start+i,year=Math.floor(number/12),month=number%12+1;
    return `<text x="${x(number)}" y="${H-12}" text-anchor="middle" fill="#53676f" font-size="12">${year.toString().slice(2)}/${String(month).padStart(2,'0')}</text>`;
  }).join('');
  const baseline=`<line x1="${L}" y1="${y(preset.baseline)}" x2="${W-R}" y2="${y(preset.baseline)}" stroke="#ad8c62" stroke-width="1.2" stroke-dasharray="5 5"/>`;
  const seriesSVG=selected.map(item=>{
    let segments=[],segment=[],previous=null;
    for(const row of item.points){
      const month=monthNo(row.period);
      if(previous!==null&&month-previous>1){segments.push(segment);segment=[];}
      segment.push({x:x(month),y:y(row.value),row});previous=month;
    }
    if(segment.length)segments.push(segment);
    return segments.map(group=>{
      const line=group.length>1?`<path d="${group.map((point,i)=>`${i?'L':'M'}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')}" fill="none" stroke="${colors[item.index]}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>`:'';
      const dots=group.map(point=>`<circle cx="${point.x}" cy="${point.y}" r="3.4" fill="white" stroke="${colors[item.index]}" stroke-width="2"><title>${escapeHTML(item.info.name)} ${point.row.period}: ${format(point.row.value)}%</title></circle>`).join('');
      return line+dots;
    }).join('');
  }).join('');
  compareTarget.innerHTML=`<svg viewBox="0 0 ${W} ${H}" aria-hidden="true">${grid}${baseline}${seriesSVG}${axis}</svg>`;
  $('#compareChart').setAttribute('aria-label',`${preset.title}，最近24个月；缺失期别不连线。${selected.map(item=>`${item.info.name}已收录${item.points.length}期`).join('；')}`);
}

function renderFilters() {
  $('#groupSelect').innerHTML=state.data.groups.map(group=>`<option value="${escapeHTML(group)}">${escapeHTML(group)}</option>`).join('');
  $('#groupSelect').value=state.group;
}

function safeOfficialURL(url) {
  try { const parsed=new URL(url); return parsed.protocol==='https:' && ['www.stats.gov.cn','www.pbc.gov.cn','data.mofcom.gov.cn','fdi.mofcom.gov.cn','gks.mof.gov.cn','www.mof.gov.cn'].includes(parsed.hostname) ? parsed.href : '#'; }
  catch {return '#';}
}

function exportChartCSV() {
  const info=metric(state.selected);
  const detail=state.chartDetail||[];
  if (!info || !detail.length) return;
  const rows=[['统计期别','状态','指标','数值','单位','发布或转载日期','日期类型','计划发布时间','官方原文或判定依据','标题或状态说明'],
    ...detail.map(({period,row,status,evidence})=>[period,status,info.name,row?.value??'',info.unit,
      row?.published||'',row?.published?publicationLabel(row):'未核实',evidence?.scheduled_at||'',safeOfficialURL(row?.source_url||evidence?.source_url).replace(/^#$/,''),row?.source_title||evidence?.reason||''])];
  downloadCSV(rows,`${state.selected}_${detail[0].period}_${detail.at(-1).period}.csv`);
}

function downloadCSV(rows,filename) {
  const cell=value=>`"${(typeof value==='number'?String(value):String(value??'').replace(/^([=+\-@\t\r])/, "'$1")).replaceAll('"','""')}"`;
  const csv='\uFEFF'+rows.map(row=>row.map(cell).join(',')).join('\r\n')+'\r\n';
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const anchor=document.createElement('a');
  anchor.href=url;
  anchor.download=filename;
  anchor.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function filteredCatalog() {
  const query=state.query.toLowerCase();
  return state.data.catalog.filter(info=>(state.group==='全部'||info.group===state.group)&&`${info.name} ${info.basis} ${sourceLabel(info.source)} ${info.key}`.toLowerCase().includes(query));
}

function exportDataCSV() {
  const rows=[['指标','分类','统计口径','期别','最新值','单位','较上期变化','变化单位','比较期','发布或转载日期','日期类型','原文标题','来源链接'],...filteredCatalog().map(info=>{
    const row=latest(info.key),diff=difference(info.key);
    return [info.name,info.group,info.basis,row?.period||'',row?.value??'',info.unit,diff?.value??'',diff?(info.unit==='%'?'个百分点':info.unit):'',diff?.period||'',row?.published||'',row?.published?publicationLabel(row):'未核实',row?.source_title||'',row?.source_url||''];
  })];
  downloadCSV(rows,`macro_latest_${state.group}.csv`);
}

function renderTable() {
  const catalog=filteredCatalog();
  $('#dataRows').innerHTML=catalog.map(info=>{
    const row=latest(info.key), diff=difference(info.key);
    const change=diff?`${diff.value>0?'+':''}${format(diff.value)} ${info.unit==='%'?'个百分点':info.unit}`:'不计算';
    const expanded=state.expanded.has(info.key);
    const warning=info.key.includes('infrastructure')?'新旧口径分列':info.key==='m1_yoy'?'2025新口径 · 含2024官方回溯':info.key==='m1_legacy_yoy'?'旧口径已结束 · 与新口径分列':info.key==='housing_sales_area_ytd_yoy'?'历年名称与定义见原文':'';
    const revisions=(state.data.recent_changes||[]).filter(item=>item.key===info.key&&item.period===row?.period&&item.change_type==='value_revision');
    const detail=expanded?`<tr class="expanded-row" id="detail-${info.key}"><td colspan="6"><div class="record-details"><p class="full"><strong>采用的发布记录</strong>${row?`<a href="${safeOfficialURL(row.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(row.source_title)} ↗</a>`:'暂无记录'}</p><p><strong>数据期别 / 口径</strong>${row?.period||'—'} · ${escapeHTML(info.basis)} · ${escapeHTML(info.unit)}</p><p><strong>${publicationLabel(row)}</strong>${row?.published||'未核实；不以同步时间替代'}</p><p><strong>当前入库版本</strong>${row?.fetched_at?`读取于 ${escapeHTML(dateTime(row.fetched_at))}`:'读取时间未核实'}${revisions.length?` · 最近记录含${revisions.length}次数值修订`:''}</p><p><strong>比较依据</strong>${diff?`对比 ${diff.period} 同指标，${diff.direction}${diff.value===0?'':` ${format(Math.abs(diff.value))} ${info.unit==='%'?'个百分点':info.unit}`}`:escapeHTML(comparison(info.key)?.reason||'暂无比较依据')}</p><p class="full">${escapeHTML(info.description)} · <button type="button" class="button button-text" data-open-metric="${info.key}">查看历史趋势 →</button></p></div></td></tr>`:'';
    return `<tr><td><button type="button" class="metric-name" data-expand="${info.key}" aria-expanded="${expanded}" aria-controls="detail-${info.key}"><span class="expand-icon" aria-hidden="true">${expanded?'−':'+'}</span>${escapeHTML(info.name)}</button>${warning?`<small>${warning}</small>`:''}</td><td class="num">${row?format(row.value):'—'} ${escapeHTML(info.unit)}</td><td>${escapeHTML(info.basis)}</td><td>${row?.period||'—'}</td><td><span class="trend-mark">${change}</span><small>${diff?`对比 ${diff.period}`:escapeHTML(comparison(info.key)?.reason||'暂无依据')}</small></td><td>${row?`<a class="release-link" href="${safeOfficialURL(row.source_url)}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(row.source_title)}">${escapeHTML(row.source_title)} ↗</a><small>${escapeHTML(recordPublisher(row,info.source))} · ${isRepost(row)?'转载':'发布'} ${row.published||'未核实'}</small>`:'未收录'}</td></tr>${detail}`;
  }).join('') || '<tr><td colspan="6">没有匹配的指标</td></tr>';
  $('#tableCount').textContent=`显示 ${catalog.length}/${state.data.catalog.length} 项指标 · “导出当前列表”包含当前筛选后的最新读数，“全部历史 CSV”包含全部历史观测`;
}

function renderResearch() {
  const analysis=state.data.computed_analysis;
  $('#researchVersion').textContent=analysis?`计算规则 v${analysis.version}`:'等待计算';
  $('#researchMethod').textContent=analysis?.methodology||'尚无足够数据计算历史比较。';
  const breadth=analysis?.pmi_breadth;
  $('#researchBreadth').textContent=breadth?
    `${periodLabel(breadth.period)}三项 PMI 读数中，${breadth.above_50} 项高于 50，${breadth.equal_50} 项等于 50。此计数不构成综合景气指数。`:
    '三项 PMI 暂无同一期完整数据，暂不计算景气读数计数。';
  $('#researchRows').innerHTML=(analysis?.findings||[]).map(item=>{
    const diff=item.year_ago_delta_pp;
    const comparison=diff===null?'—':`${diff>0?'+':''}${format(diff)} 个百分点`;
    const rank=item.percentile_60m===null?'样本或覆盖不足':`${format(item.percentile_60m)}% · ${item.sample_size} 期`;
    const lastSource=`<a href="${safeOfficialURL(item.latest.source_url)}" target="_blank" rel="noopener noreferrer">本期原文 ↗</a>`;
    const priorSource=item.year_ago?`<a href="${safeOfficialURL(item.year_ago.source_url)}" target="_blank" rel="noopener noreferrer">去年同期 ↗</a>`:'';
    return `<tr><td><strong>${escapeHTML(item.name)}</strong><small>${escapeHTML(item.basis)}</small></td><td class="num">${format(item.latest.value)}${escapeHTML(item.unit)}<small>${escapeHTML(item.latest.period)}</small></td><td>${comparison}${item.year_ago?`<small>对比 ${escapeHTML(item.year_ago.period)}</small>`:''}</td><td>${rank}<small>覆盖 ${format(item.coverage_60m_pct)}%</small></td><td class="research-source">${lastSource}${priorSource}</td></tr>`;
  }).join('')||'<tr><td colspan="5">当前没有满足比较或历史分位条件的指标。</td></tr>';
}

function renderObservations() {
  const summary=state.data.reader_summary;
  $('#observationContext').textContent=`连续自然月读数比较 · 各主题标明数据期别 · 快照 ${state.data.snapshot_hash} · 自动计算，未作因果推断`;
  $('#observationList').innerHTML=(summary?.observations||[]).map(item=>`<article class="observation"><div class="observation-label"><span>${escapeHTML(item.topic)}</span><span>${item.period}</span></div><h2>${escapeHTML(item.title)}</h2>${item.keys.map(key=>{
    const entry=comparison(key),current=entry.current,previous=entry.previous;
    return `<div class="evidence-row"><strong><button class="metric-name" type="button" data-open-metric="${key}">${escapeHTML(entry.name)}</button></strong><span class="evidence-change">${entry.delta>0?'+':''}${format(entry.delta)} ${entry.unit==='%'?'个百分点':escapeHTML(entry.unit)}</span><span class="evidence-values">${current.period} ${format(current.value)}${escapeHTML(entry.unit)} ← ${previous.period} ${format(previous.value)}${escapeHTML(entry.unit)} · ${escapeHTML(entry.basis)}</span><span class="evidence-links"><a href="${safeOfficialURL(current.source_url)}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(current.source_title)}">本期原文 ↗</a><a href="${safeOfficialURL(previous.source_url)}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(previous.source_title)}">比较期原文 ↗</a></span></div>`;
  }).join('')}<p class="observation-boundary"><strong>解释边界：</strong>${escapeHTML(item.boundary)}</p></article>`).join('')||'<p>缺少连续自然月的同口径读数，暂不形成变化观察。可在指标数据页核查已收录记录。</p>';
}

function renderAIText(content) {
  const inline = (line) => escapeHTML(line).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\[([^\[\]]+·20\d{2}-\d{2})\]/g, (full, labels) => {
    const pieces=labels.split(/[、；;,，]/).map(label=>label.trim());
    if(!pieces.every(label=>/^.+·20\d{2}-\d{2}$/.test(label)))return full;
    return pieces.map(label=>{
      const match=label.match(/^(.*)·(20\d{2}-\d{2})$/);
      const info=state.data.catalog.find(x=>x.name===match?.[1]);
      const row=info && series(info.key).find(x=>x.period===match[2]);
      return row ? `<a class="cite" href="${safeOfficialURL(row.source_url)}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(row.source_title)}">${label} ↗</a>` : `[${label}]`;
    }).join(' ');
  });
  return content.split(/\r?\n/).map(raw=>{
    const line=raw.trim();
    if (!line) return '';
    if (/^#{1,3}\s/.test(line)) return `<h4>${inline(line.replace(/^#{1,3}\s+/,''))}</h4>`;
    if (line==='---') return '<hr>';
    if (line.startsWith('- ')) return `<div class="ai-item"><span>•</span><p>${inline(line.slice(2))}</p></div>`;
    const ordered=line.match(/^(\d+)\.\s+(.+)$/);
    if (ordered) return `<div class="ai-item"><span>${ordered[1]}.</span><p>${inline(ordered[2])}</p></div>`;
    return `<p>${inline(line)}</p>`;
  }).join('');
}

function renderAI() {
  const data=state.data, analysis=data.analysis;
  const button=$('#analyzeBtn');
  const busy=state.analyzing||data.ai_analyzing;
  button.disabled=!data.ai_ready||busy||data.refreshing;
  button.textContent=busy?'生成中…':data.refreshing?'数据同步中…':data.ai_ready?'生成观察摘要':'需配置 API Key';
  button.title=data.ai_ready?'基于当前已收录数据生成解读':'服务端未配置 DEEPSEEK_API_KEY';
  const current=analysis?.snapshot_hash===data.snapshot_hash && analysis?.recipe_version===data.ai_recipe_version;
  const suffix=current?'':' · 旧版本未用于当前页面';
  const keyStatus=data.ai_ready?'':' · 当前未配置 API Key';
  $('#aiMeta').textContent=analysis ? `${analysis.model} · 生成于${dateTime(analysis.created_at)} · 数据快照${analysis.snapshot_hash} · 未人工审核${suffix}${keyStatus}` : `DeepSeek · 当前快照${data.snapshot_hash} · AI辅助生成，未人工审核${keyStatus}`;
  $('#aiResult').hidden=!(analysis?.content&&current);
  if(analysis?.content&&current){$('#aiContent').innerHTML=renderAIText(analysis.content);$('#aiNotice').textContent='生成内容需结合上方原文证据复核；涉及原因的解释需要额外材料。';}
  else {
    $('#aiContent').textContent='';
    $('#aiNotice').textContent=!data.ai_ready?'服务端缺少API Key。请在本机 .env 配置 DEEPSEEK_API_KEY，重启后刷新页面。':analysis?'数据或摘要规则已更新，旧摘要已收起。可生成当前版本；上方变化观察仍可使用。':'可按当前读数生成观察摘要；上方变化观察和统计依据无需模型即可使用。';
  }
}

$('#metricSelect').addEventListener('change',event=>{state.selected=event.target.value;updateTrendURL();renderChart();});
$('#chartExportBtn').addEventListener('click',exportChartCSV);
document.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>{
  state.range=button.dataset.range;
  renderRangeControls();updateTrendURL();
  renderChart();
}));
$('#searchInput').addEventListener('input',event=>{state.query=event.target.value.trim();renderTable();});
$('#groupSelect').addEventListener('change',event=>{state.group=event.target.value;renderTable();});
$('#exportDataBtn').addEventListener('click',exportDataCSV);
$('#customRangeForm').addEventListener('submit',event=>{
  event.preventDefault();const start=$('#chartStart').value,end=$('#chartEnd').value;
  if(!ChartModel.validPeriod(start)||!ChartModel.validPeriod(end)||start>end||end>state.data.quality.latest_period||ChartModel.monthNumber(end)-ChartModel.monthNumber(start)>=600){$('#rangeError').textContent='请选择先后顺序正确、已收录期别以内且不超过50年的区间。';return;}
  $('#rangeError').textContent='';state.customRange={start,end};state.range='custom';updateTrendURL();renderChart();
});
$('#qualityFilters').addEventListener('click',event=>{const button=event.target.closest('[data-quality-filter]');if(button){state.qualityFilter=button.dataset.qualityFilter;renderQuality();}});
$('#closeQualityDetail').addEventListener('click',()=>$('#qualityDetail').close());
$('#qualityDetail').addEventListener('click',event=>{if(event.target===$('#qualityDetail')){const rect=event.target.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)event.target.close();}});
document.addEventListener('click',event=>{
  const metricButton=event.target.closest('[data-open-metric]');if(metricButton){openMetric(metricButton.dataset.openMetric);return;}
  const expand=event.target.closest('[data-expand]');if(expand){const key=expand.dataset.expand;state.expanded.has(key)?state.expanded.delete(key):state.expanded.add(key);renderTable();document.querySelector(`[data-expand="${key}"]`)?.focus();}
});
let chartResizeTimer;
window.addEventListener('resize',()=>{
  clearTimeout(chartResizeTimer);
  chartResizeTimer=setTimeout(()=>{if(state.data){renderChart();renderCompare();}},120);
});
$('#refreshBtn').addEventListener('click',async()=>{
  const button=$('#refreshBtn');button.disabled=true;button.textContent='同步中…';showNotice('正在核查官方来源和最新发布记录。',true);
  try {const response=await fetch('/api/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const result=await response.json();await getDashboard();showNotice(result.ok?`更新完成：${result.count} 条记录。${result.warnings?.length?'部分来源有提示，请检查。':''}`:result.message, result.ok);}
  catch(error){showNotice(`更新失败：${error.message}`);}
  finally{button.textContent='↻ 同步数据';button.disabled=false;}
});
$('#analyzeBtn').addEventListener('click',async()=>{
  state.analyzing=true;renderAI();
  try {const response=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const result=await response.json();if(!result.ok)throw new Error(result.message);await getDashboard();window.scrollTo({top:0,behavior:'instant'});}
  catch(error){showNotice(error.message);}
  finally{state.analyzing=false;renderAI();}
});
document.querySelectorAll('.nav-link, .brand, [data-page-link]').forEach(link=>link.addEventListener('click',event=>{
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  navigatePage(link.getAttribute('href'));
}));
window.addEventListener('popstate',()=>{applyPage();window.scrollTo({top:0,behavior:'instant'});});
window.addEventListener('hashchange',applyPage);
applyPage();
getDashboard().then(()=>{if(state.data.refreshing){const timer=setInterval(async()=>{await getDashboard();if(!state.data.refreshing)clearInterval(timer);},5000);}}).catch(error=>showNotice(error.message));
