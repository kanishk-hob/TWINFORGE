import {api} from './client.js';
import {appendUnique,receiptFilter,aware,exportJson} from './data.js';
import {el,panel,field,button,notice,table,eventList} from './components.js';
import {chart} from './charts.js';

// Each stream has an exclusive ID cursor. A failed page never discards accepted pages.
export function evidenceView(host,selection,onRows=()=>{}){
  const p=panel('Persistent evidence','Forward pages of 200 records • initial cap 2,000 per stream. Time filters apply only to loaded records.');host.append(p);
  const controls=el('div','toolbar');const start=field('Receipt start (inclusive)','','ISO timestamp with Z or offset');const end=field('Receipt end (exclusive)','','ISO timestamp with Z or offset');
  const status=el('div','live-message');status.setAttribute('role','status');const body=el('div');let rows=[],events=[],busy=false,dead=false,controller=new AbortController(),dispose=()=>{};let cursors={telemetry:0,history:0},done={telemetry:false,history:false};let cap=2000;
  const load=button('Load recorded history',()=>fetchPages());const more=button('Load more / retry',()=>{if(rows.length>=cap||events.length>=cap)cap+=2000;fetchPages();},'button secondary');
  const apply=button('Apply loaded-time filter',render,'button secondary');const exp=button('Export loaded selection',()=>{const selected=filtered();if(selected)exportJson('twinforge-loaded-history.json',{scope:'Loaded receipt-time selection only',...selection,start:start.input.value,end:end.input.value,...selected});},'button secondary');
  controls.append(start.wrap,end.wrap,apply,load,more,exp);p.append(controls,status,body);
  function filtered(){if((start.input.value&&!aware(start.input.value))||(end.input.value&&!aware(end.input.value))||(start.input.value&&end.input.value&&Date.parse(start.input.value)>=Date.parse(end.input.value))){status.replaceChildren(notice('Use timezone-aware, increasing receipt bounds.','error'));return null;}return {observations:receiptFilter(rows.filter(r=>r.source===selection.source),start.input.value,end.input.value),events:receiptFilter(events.filter(r=>r.source===selection.source),start.input.value,end.input.value)};}
  function render(){const selected=filtered();if(!selected)return;dispose();body.replaceChildren();const obs=selected.observations;
    body.append(notice(`Loaded ${rows.length} telemetry and ${events.length} events; showing ${obs.length} / ${selected.events.length} after source and time filtering. ${done.telemetry&&done.history?'End of current query reached.':'More records may exist.'}`));
    if(obs.length)body.append(el('p','mono muted',`Loaded receipt extent: ${obs[0].observed_at} → ${obs.at(-1).observed_at}`));
    const graph=panel('Telemetry trend','Source timestamps are independent of receipt time. No assumed measurement units.');body.append(graph);dispose=chart(graph,obs);
    body.append(table(['ID / sequence','Run / source','Source timestamp','Receipt timestamp','Quality','Measurements'],obs.map(r=>[`${r.id} / ${r.sequence}`,`${r.run_id} / ${r.source}`,r.source_timestamp,r.observed_at,`${r.valid?'valid':'invalid'} / ${r.fresh?'fresh':'stale'} ${r.reason||''}`,JSON.stringify(r.telemetry_values)])));
    const timeline=panel('Observed event timeline','Events use receipt time; a recovered event is not proof of physical repair.');timeline.append(eventList(selected.events));body.append(timeline);onRows(obs,selected.events);
  }
  async function fetchPages(){if(busy||dead)return;if(!selection.asset||!selection.run){status.replaceChildren(notice('Choose an asset and recorded run ID first.','error'));return;}busy=true;load.disabled=more.disabled=true;status.replaceChildren(notice('Loading persisted records…'));
    try{for(const kind of ['telemetry','history']){while(!done[kind]&&(kind==='telemetry'?rows:events).length<cap){const page=await api.history(selection,kind,cursors[kind],controller.signal);if(dead)return;if(page.length&&page.at(-1).id<=cursors[kind])throw Error('History cursor did not advance');if(kind==='telemetry')rows=appendUnique(rows,page);else events=appendUnique(events,page);if(page.length)cursors[kind]=page.at(-1).id;done[kind]=page.length<200;render();}}status.replaceChildren(notice('Recorded pages loaded. Scope is limited to this asset, run and the loaded extent.'));}
    catch(e){if(!dead)status.replaceChildren(notice(`${e.message}. Last loaded records retained. Retry resumes after the last accepted ID.`,'error'));}
    finally{busy=false;if(!dead){load.disabled=false;more.disabled=done.telemetry&&done.history;}}
  }render();return {destroy(){dead=true;controller.abort();dispose();},load:fetchPages};
}
