import test from 'node:test';
import assert from 'node:assert/strict';
import {segments, mergePage, setupHistory, invalidateHistory} from '../../app/static/dashboard/history.js';
import {renderKpi} from '../../app/static/dashboard/kpi.js';
import {display, get} from '../../app/static/dashboard/api.js';

const row = (id, extra = {}) => ({
  id, run_id: 'fixture', source: 'test', sequence: id,
  valid: true, fresh: true,
  source_timestamp: `2024-01-01T00:00:0${id}Z`,
  telemetry_values: {reading: id}, ...extra,
});

test('null, zero, false and missing values remain distinct', () => {
  assert.equal(display(null), 'Unavailable');
  assert.equal(display(undefined), 'Unavailable');
  assert.equal(display(0), '0');
  assert.equal(display(false), 'false');
});
test('pagination retries deduplicate and preserve deterministic order', () => {
  assert.deepEqual(mergePage([row(2),row(1)], [row(2),row(3)]).map(r=>r.id), [1,2,3]);
});
test('valid consecutive samples form a segment', () => {
  assert.equal(segments([row(1),row(2)], 'reading')[0].length, 2);
});
for (const [name, extra] of Object.entries({
  run: {run_id:'other'}, source: {source:'other'}, gap: {sequence:4},
  stale: {fresh:false}, invalid: {valid:false}, missingTime: {source_timestamp:null},
  reversedTime: {source_timestamp:'2023-01-01T00:00:00Z'},
  null: {telemetry_values:{reading:null}}, string: {telemetry_values:{reading:'2'}},
  infinite: {telemetry_values:{reading:Infinity}},
})) test(`trend breaks at ${name}`, () => {
  const parts = segments([row(1),row(2,extra)], 'reading');
  assert.ok(parts.every(part=>part.length===1));
});
test('HTTP failures remain explicit; transport uses GET', async () => {
  const original = globalThis.fetch;
  try {
    for (const status of [404,422,503]) {
      globalThis.fetch = async (_, options) => {
        assert.equal(options.method, 'GET');
        return {ok:false,status,json:async()=>({detail:'fixture failure'})};
      };
      await assert.rejects(get('/fixture'), new RegExp(`HTTP ${status}: fixture failure`));
    }
  } finally { globalThis.fetch = original; }
});

// Minimal DOM double, not a browser: exercise rendering and request coordination
// without a package dependency. Actual visual/keyboard checks remain manual.
class Element extends EventTarget {
  constructor() { super(); this.children=[]; this.value=''; this.text=''; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children=items; this.text=''; }
  get firstChild() { return this.children[0]; }
  set textContent(value) { this.text=String(value); this.children=[]; }
  get textContent() { return this.text+this.children.map(c=>c.textContent).join(' '); }
}
test('history cap, explicit extension, failed-page retention and retry', async () => {
  const originalFetch=globalThis.fetch, originalDocument=globalThis.document;
  const elements=new Map();
  globalThis.document=Object.assign(new EventTarget(), {
    getElementById(id) { if(!elements.has(id))elements.set(id,new Element());return elements.get(id); },
    createElement() { return new Element(); },
  });
  const el=id=>document.getElementById(id);
  const wait=async()=>{for(let i=0;i<100&&el('telemetry-more').disabled;i++)await new Promise(resolve=>setImmediate(resolve));};
  try {
    el('asset').value='fixture';el('run').value='fixture';
    let calls=[], failAt=null;
    globalThis.fetch=async path=>{
      const url=new URL(path,'http://fixture'),after=Number(url.searchParams.get('after_id')),limit=Number(url.searchParams.get('limit'));
      if(url.pathname.endsWith('/history'))return {ok:true,json:async()=>[]};
      calls.push({after,limit});
      if(after===failAt)return {ok:false,status:503,json:async()=>({detail:'fixture outage'})};
      const page=Array.from({length:Math.min(limit,2300-after)},(_,i)=>row(after+i+1));
      return {ok:true,json:async()=>page};
    };
    setupHistory();el('history-refresh').dispatchEvent(new Event('click'));await wait();
    assert.equal(calls.length,10);assert.ok(calls.every(c=>c.limit===200));
    assert.match(el('telemetry-message').textContent,/2000 loaded/);
    el('telemetry-more').dispatchEvent(new Event('click'));await wait();
    assert.match(el('telemetry-message').textContent,/2300 loaded/);
    assert.equal(el('telemetry-table').firstChild.children[1].children.length,2300);
    invalidateHistory();calls=[];failAt=400;
    el('history-refresh').dispatchEvent(new Event('click'));await wait();
    assert.match(el('telemetry-message').textContent,/400 last-known rows retained.*HTTP 503/);
    failAt=null;el('telemetry-more').dispatchEvent(new Event('click'));await wait();
    assert.match(el('telemetry-message').textContent,/2000 loaded/);
    assert.equal(el('telemetry-table').firstChild.children[1].children.length,2000);
    const target=new Element();
    renderKpi({coverage:0,metrics:{oee:{value:null,unit:'fraction',status:'unknown',reason:'Missing schedule'},energy:{value:0,unit:'kWh',status:'estimated'}},downtime_reasons_seconds:null},target);
    for(const text of ['Unavailable fraction','Missing schedule','0 kWh','Estimated'])assert.ok(target.textContent.includes(text));
  } finally {globalThis.fetch=originalFetch;globalThis.document=originalDocument;}
});
