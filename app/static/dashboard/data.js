// @ts-check
/** @typedef {import('./contracts').Twin} Twin */
/** @typedef {import('./contracts').Observation} Observation */
/** @typedef {import('./contracts').MachineEvent} MachineEvent */
/** @typedef {import('./contracts').Route} Route */

/** Verified simulator integration-contract mappings, not a universal sensor catalog. */
const units = {temperature_c:['Temperature','°C'], vibration_rms:['Vibration RMS','synthetic relative units'],
  current_a:['Current','A'], speed_rpm:['Speed','RPM'], power_kw:['Power','kW'], state:['Sampled state','']};
/** @param {string} field @param {string} source */
export function measurement(field, source) {
  return source === 'factory_simulator' && Object.hasOwn(units, field)
    ? {label:units[field][0],unit:units[field][1]} : {label:field,unit:''};
}
/** @param {unknown} value */
export function valueText(value) {
  if (value === null || value === undefined || value === '') return 'Unavailable';
  if (typeof value === 'number') return Number.isFinite(value) ? String(Number(value.toPrecision(8))) : 'Unavailable';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}
/** @param {string} hash @returns {Route} */
export function parseRoute(hash) {
  const [path, query = ''] = hash.replace(/^#\/?/, '').split('?');
  const parts = path.split('/');
  const params = new URLSearchParams(query);
  const pages = ['overview','machines','kpi','health','history','decision'];
  let asset = params.get('asset') || '';
  try { if (['machines','decision'].includes(parts[0]) && parts[1]) asset = decodeURIComponent(parts[1]); } catch { asset = ''; }
  return {page:pages.includes(parts[0]) ? parts[0] : 'overview', asset,
    run:params.get('run') || '',source:params.get('source') || 'factory_simulator',
    search:params.get('search') || '',state:params.get('state') || '',
    factory:params.get('factory') || '',line:params.get('line') || ''};
}
/** @param {Partial<Route>} route */
export function routeUrl(route) {
  const path = ['machines','decision'].includes(route.page) && route.asset ? `${route.page}/${encodeURIComponent(route.asset)}` : route.page || 'overview';
  const params = new URLSearchParams();
  for (const key of ['asset','run','source','search','state','factory','line']) if(route[key]) params.set(key,route[key]);
  return `#/${path}${params.size ? '?'+params : ''}`;
}
/** @param {Twin[]} twins @param {Partial<Route>} filters */
export function filterTwins(twins, filters) {
  const needle = (filters.search || '').toLowerCase();
  return twins.filter(t => (!filters.factory || t.factory_id === filters.factory)
    && (!filters.line || t.line_id === filters.line) && (!filters.state || t.state === filters.state)
    && `${t.asset_id} ${t.asset_type} ${t.line_id}`.toLowerCase().includes(needle));
}
/** @param {Twin|null|undefined} twin @param {boolean|null} connected @param {boolean} [requestFailed] */
export function qualityLabel(twin, connected, requestFailed=false) {
  if (requestFailed || connected !== true) return 'Last-known / source unconfirmed';
  if (!twin?.quality?.valid) return 'Invalid / no telemetry';
  if (!twin.quality.fresh) return 'Stale sample';
  return 'Source reports valid & fresh';
}
/** @template {{id:number}} T @param {T[]} rows @param {T[]} page @returns {T[]} */
export function appendUnique(rows, page) {
  return [...new Map([...rows,...page].map(r=>[r.id,r])).values()].sort((a,b)=>a.id-b.id);
}
/** @param {string} value */
export function aware(value) { return /T.*(?:Z|[+-]\d{2}:\d{2})$/i.test(value) && Number.isFinite(Date.parse(value)); }
/** @param {string} start @param {string} end */
export function validWindow(start, end) {
  return aware(start) && aware(end) && Date.parse(end)>Date.parse(start) && Date.parse(end)-Date.parse(start)<=86400000;
}
/** Filter loaded receipt-time records only. No claim that unloaded history is covered.
 * @template {{observed_at:string}} T @param {T[]} rows @param {string} start @param {string} end @returns {T[]} */
export function receiptFilter(rows, start, end) {
  return rows.filter(r=>(!start || Date.parse(r.observed_at)>=Date.parse(start)) && (!end || Date.parse(r.observed_at)<Date.parse(end)));
}
/** Split before filtering unusable samples; never bridge a missing sample.
 * @param {Observation[]} rows @param {string} field @returns {number[][][]} */
export function trendSegments(rows, field) {
  const segments = []; let segment = []; let previous = null;
  for (const row of rows) {
    const y = row.telemetry_values?.[field], x = Date.parse(row.source_timestamp || '');
    const valid = row.valid && row.fresh && typeof y === 'number' && Number.isFinite(y) && Number.isFinite(x);
    const continuous = previous && row.asset_id===previous.asset_id && row.source===previous.source
      && row.run_id===previous.run_id && row.sequence===previous.sequence+1 && x>Date.parse(previous.source_timestamp);
    if (!valid || !continuous) { if(segment.length) segments.push(segment); segment=[]; }
    if (valid) segment.push([x,/** @type {number} */(y)]);
    previous=valid?row:null;
  }
  if(segment.length) segments.push(segment);
  return segments;
}
/** Convert separated segments to one aligned line with explicit null gaps.
 * Return null on overlapping/non-increasing source time instead of silently sorting it.
 * @param {number[][][]} segments @returns {[number[], (number|null)[]]|null} */
export function plotData(segments) {
  const xs=[],ys=[];
  for(const part of segments) {
    if(xs.length) {
      const last=xs[xs.length-1];
      if(part[0][0]<=last) return null;
      xs.push((last+part[0][0])/2); ys.push(null);
    }
    for(const [x,y] of part) { xs.push(x); ys.push(y); }
  }
  return [xs,ys];
}
/** @param {string} filename @param {unknown} payload */
export function exportJson(filename, payload) {
  const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
  const anchor=document.createElement('a'); anchor.href=url; anchor.download=filename; anchor.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
