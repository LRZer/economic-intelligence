const assert = require('node:assert/strict');
const {windowFor, detailRows, niceScale, validPeriod} = require('../../src/china_macro/web/chart_model.js');
assert.equal(validPeriod('2026-13'), false);
assert.equal(validPeriod('2026-09'), true);

const points = [
  {period:'2025-06',value:8.3},
  {period:'2026-03',value:7.1},
  {period:'2026-05',value:6.8},
  {period:'2026-08',value:7.4},
];
const six = windowFor(points, 6);
assert.deepEqual(six.periods, ['2026-03','2026-04','2026-05','2026-06','2026-07','2026-08']);
assert.deepEqual(six.points.map(row=>row.period), ['2026-03','2026-05','2026-08']);
assert.equal(windowFor(points, 12).points.length, 3);
assert.equal(windowFor(points, 'all').points.length, 4);

const detail = detailRows(six, ['2026-04','2026-07'], ['2026-06'], '2021-09');
assert.deepEqual(detail.map(row=>row.status), [
  '已收录','待补录','已收录','待发布','待补录','已收录',
]);
assert.equal(detailRows(windowFor([{period:'2026-02',value:1}], 2), [], [], '2021-09')[0].status,
             '记录状态未核实');
assert.deepEqual(windowFor([], 6).periods, []);
const anchored = windowFor(points, 12, '2026-09');
assert.equal(anchored.periods.at(-1), '2026-09');
assert.equal(detailRows(anchored, [], [], null, [{period:'2026-09',code:'pending',label:'待发布'}]).at(-1).code, 'pending');
assert.deepEqual(windowFor(points, {start:'2026-04',end:'2026-07'}).points.map(row=>row.period), ['2026-05']);
assert.deepEqual(windowFor(points, {start:'2026-07',end:'2026-04'}).points, []);
const scale = niceScale([4.1,4.5,5.7]);
assert.equal(scale.step, .5);
assert.deepEqual(scale.ticks, [3.5,4,4.5,5,5.5,6]);
const constant = niceScale([0,0]);
assert(constant.max>constant.min && constant.ticks.every(Number.isFinite));
assert(niceScale([48.5,49],50).max >= 50);
console.log('chart calendar and status tests passed');
