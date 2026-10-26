// All dashboard network traffic is same-origin GET. Never render source HTML.
export const $ = id => document.getElementById(id);
export const display = value => value === null || value === undefined || value === '' ? 'Unavailable' : typeof value === 'object' ? JSON.stringify(value) : String(value);
export function node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = display(text); if (className) el.className = className; return el; }
export function fields(entries) { const dl = node('dl'); for (const [key,value] of entries) dl.append(node('dt',key),node('dd',value)); return dl; }
export function message(id, text, error=false) { $(id).textContent=text; $(id).className=error?'error':''; }
export async function get(path, signal) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort',abort,{once:true});
  if(signal?.aborted) controller.abort();
  const timer=setTimeout(abort,10000);
  try { const response=await fetch(path,{method:'GET',signal:controller.signal,cache:'no-store'});
    const body=await response.json();
    if(!response.ok) throw new Error(`HTTP ${response.status}: ${display(body.detail ?? body)}`);
    return body;
  } catch(error) { if(controller.signal.aborted && !signal?.aborted) throw new Error('Request timed out (10 seconds)'); throw error; }
  finally { clearTimeout(timer); signal?.removeEventListener('abort',abort); }
}
export function table(headers, rows) { const el=node('table'); const head=node('thead'), tr=node('tr'); headers.forEach(h=>{const th=node('th',h);th.scope='col';tr.append(th);});head.append(tr);el.append(head);const body=node('tbody');rows.forEach(row=>{const r=node('tr');row.forEach(v=>r.append(node('td',v)));body.append(r);});el.append(body);return el; }
export function context() { return {asset:$('asset').value.trim(),run:$('run').value.trim()}; }
export function endpoint(kind, ctx, params={}) { return `/api/twins/${encodeURIComponent(ctx.asset)}/${kind}?${new URLSearchParams({...params,run_id:ctx.run})}`; }
