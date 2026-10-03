const ChartModel = (() => {
  const validPeriod = period => /^\d{4}-(0[1-9]|1[0-2])$/.test(period || '');
  const monthNumber = period => Number(period.slice(0, 4)) * 12 + Number(period.slice(5)) - 1;
  const periodFromNumber = number => `${Math.floor(number / 12)}-${String(number % 12 + 1).padStart(2, '0')}`;

  function windowFor(points, range, anchorPeriod = null) {
    if (!points.length) return {start: null, end: null, points: [], periods: []};
    const custom = range && typeof range === 'object';
    if (custom && (!validPeriod(range.start) || !validPeriod(range.end)))
      return {start:null, end:null, points:[], periods:[]};
    const end = custom ? monthNumber(range.end) : monthNumber(anchorPeriod || points.at(-1).period);
    const start = custom ? monthNumber(range.start) : range === 'all' ? monthNumber(points[0].period) : end - Number(range) + 1;
    if (!Number.isFinite(start) || !Number.isFinite(end) || start > end || end - start >= 600)
      return {start:null, end:null, points:[], periods:[]};
    const selected = points.filter(row => monthNumber(row.period) >= start && monthNumber(row.period) <= end);
    const periods = Array.from({length: end - start + 1}, (_, index) => periodFromNumber(start + index));
    return {start, end, points: selected, periods};
  }

  function detailRows(view, missing = [], pending = [], coverageStart = null, states = []) {
    const byPeriod = new Map(view.points.map(row => [row.period, row]));
    const absent = new Set(missing);
    const waiting = new Set(pending);
    const byState = new Map(states.map(item => [item.period, item]));
    return view.periods.map(period => {
      const row = byPeriod.get(period) || null;
      const evidence = byState.get(period);
      let status = '已收录', code = 'recorded';
      if (!row) {
        if (evidence) { status = evidence.label; code = evidence.code; }
        else if (waiting.has(period)) {status = '待发布';code='pending';}
        else if (absent.has(period)) {status = '待补录';code='missing';}
        else {status = '记录状态未核实';code='unconfirmed';}
      }
      return {period, row, status, code, evidence};
    });
  }

  function niceScale(values, reference = null) {
    const numbers = values.filter(Number.isFinite);
    if (reference !== null && Number.isFinite(reference)) numbers.push(reference);
    if (!numbers.length) return {min:0,max:1,step:.2,ticks:[0,.2,.4,.6,.8,1],decimals:1};
    let low = Math.min(...numbers), high = Math.max(...numbers);
    const spread = Math.max(high-low, Math.abs(high)*.05, .5);
    low -= spread*.08; high += spread*.08;
    const raw = (high-low)/5, power = 10**Math.floor(Math.log10(raw));
    const factor = [1,2,2.5,5,10].find(item => item*power >= raw-1e-10) || 10;
    const step = factor*power;
    const min = Math.floor(low/step)*step, max = Math.ceil(high/step)*step;
    const decimals = Math.max(0, -Math.floor(Math.log10(step)) + (factor===2.5 ? 1 : 0));
    const ticks = Array.from({length:Math.round((max-min)/step)+1}, (_,i) => Number((min+i*step).toFixed(Math.min(decimals+2,10))));
    return {min,max,step,ticks,decimals};
  }

  return {validPeriod, monthNumber, periodFromNumber, windowFor, detailRows, niceScale};
})();

if (typeof module !== 'undefined') module.exports = ChartModel;
