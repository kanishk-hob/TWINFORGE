import {$,node,fields,get,message,context,endpoint} from './api.js';
let controller, generation=0;
export function invalidateKpi(reason='Selection changed. Calculate again.') {generation++;controller?.abort();$('kpi-result').replaceChildren();message('kpi-message',reason);}
export function renderKpi(result, target=$('kpi-result')) {
  target.replaceChildren(fields(Object.entries(result).filter(([key])=>!['metrics','downtime_reasons_seconds'].includes(key))));
  const grid=node('div',undefined,'grid');
  for(const [name,metric] of Object.entries(result.metrics)) {const card=node('article');card.append(node('h3',name),node('p',`${metric.value === null ? 'Unavailable' : metric.value} ${metric.unit}`),node('p',metric.status === 'estimated' ? 'Estimated' : metric.status),node('p',metric.reason ?? 'No additional reason supplied'));grid.append(card);}
  target.append(grid,node('h3','Sampled downtime reasons (seconds; not OEE downtime)'),fields(Object.entries(result.downtime_reasons_seconds ?? {status:'Unavailable'})));
}
export function setupKpi() { $('kpi-form').addEventListener('submit',async event=>{
  event.preventDefault();generation++;controller?.abort();message('kpi-message','Loading KPI result… Previous result, if shown, is last-known.');const token=generation;controller=new AbortController();
  const ctx=context(),start=$('start').value.trim(),end=$('end').value.trim();
  const aware=v=>/T.*(?:Z|[+-]\d{2}:\d{2})$/i.test(v)&&Number.isFinite(Date.parse(v));
  if(!ctx.asset||!ctx.run||!aware(start)||!aware(end)||Date.parse(end)<=Date.parse(start)||Date.parse(end)-Date.parse(start)>86400000){message('kpi-message','Enter an asset, run and timezone-aware positive window no longer than 24 hours.',true);return;}
  try{const result=await get(endpoint('kpis',ctx,{start,end}),controller.signal);if(token!==generation)return;renderKpi(result);message('kpi-message',`Result received by browser: ${new Date().toISOString()}`);}
  catch(error){if(token===generation)message('kpi-message',`${error.message}. Previous result, if shown, is last-known.`,true);}
 }); }
