import {api} from './client.js';
import {parseRoute,routeUrl,filterTwins,qualityLabel,measurement,valueText,exportJson} from './data.js';
import {el,panel,field,select,button,notice,stat,table,facts,link,badge} from './components.js';
import {decisionView} from './decision-view.js';
import {analysisView} from './analysis-view.js';
import {evidenceView} from './evidence-view.js';
import {patchDisplay,createPolling} from './refresh.js';

const titles={overview:'Factory Overview',machines:'Machine Details',kpi:'KPI Analytics',health:'Health Assessment',history:'History & Telemetry',decision:'Decision Support'};
window.__twinforgeDispose?.();
let route=parseRoute(location.hash),twins=[],source=null,persistence=null,errors={},lastRefresh=null,busy=false,view;
const main=document.querySelector('#content'),nav=document.querySelector('#navigation'),top=document.querySelector('#system-status');
function connected(){return !errors.source&&source?.connected===true&&Date.now()-Date.parse(source.last_sync_at)<=source.stale_after_seconds*1000;}
function navigate(next){location.hash=routeUrl({...route,...next});}
function sourceScores(t){const p=panel('Source-reported scores','Last observed source values. Not independently validated predictions.');p.append(facts({'Health score':t?.health?.health_score,'Anomaly score':t?.health?.anomaly_score,Origin:t?.quality?.source,'Source timestamp':t?.telemetry?.timestamp}));return p;}
function twinFacts(t){return facts({'Canonical ID':t.asset_id,Type:t.asset_type,Factory:t.factory_id,Line:t.line_id,'Observed state':t.state,'Current job':t.current_job_id,'Reported fault':t.active_fault,Sequence:t.sequence,'Source timestamp':t.telemetry?.timestamp,'Quality source':t.quality?.source,'Quality reason':t.quality?.reason,Upstream:t.relationships?.upstream,Downstream:t.relationships?.downstream});}
function renderShell(){for(const [page,label] of Object.entries({overview:'Overview',machines:'Machines',kpi:'KPI Analytics',health:'Health Assessment',history:'History',decision:'Decision Support'})){let a=nav.querySelector(`[data-page="${page}"]`);if(!a){a=link(label,{...route,page});a.dataset.page=page;nav.append(a);}a.href=routeUrl({...route,page});a.className='nav-link'+(route.page===page?' active':'');if(route.page===page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
  const assets=document.querySelector('#known-assets');if(assets){patchDisplay(assets,...twins.map(twin=>{const option=el('option');option.value=twin.asset_id;return option;}));}
  const current=twins.find(t=>t.asset_id===route.asset);document.querySelector('#factory-context').textContent=current?`${current.factory_id} / ${current.line_id}`:'Canonical factory workspace';
  patchDisplay(top,badge(errors.source?'Source status unknown':connected()?'Source reported connected':'Source disconnected / stale',connected()?'success':'warning'),el('span','muted mono',`Last sync: ${valueText(source?.last_sync_at)}`));
  const health=document.querySelector('#connection-details');patchDisplay(health,el('strong','',errors.persistence?'Persistence status unknown':persistence?.enabled?'Persistence enabled':'Persistence disabled'),el('span','mono',`Last write: ${valueText(persistence?.last_persisted_at)}`),el('span','',persistence?.last_error||errors.persistence||'Past activity; not a database health probe.'),el('span','',source?.last_sync_error||errors.source||''));
  const msg=document.querySelector('#refresh-status');msg.textContent=`Last data check: ${lastRefresh||'Not yet'} (background polling every 3s)${errors.twins?' • '+errors.twins+' • Last-known twins retained.':''}`;
}
function chooser(host){const p=el('form','selection-bar');const asset=field('Machine',route.asset,'Canonical asset ID');asset.input.setAttribute('list','known-assets');const list=el('datalist');list.id='known-assets';for(const t of twins){const o=el('option');o.value=t.asset_id;list.append(o);}const run=field('Run context',route.run,'Recorded run ID');const src=field('Source',route.source);const current=button('Use current source run',()=>{if(source?.run_id)run.input.value=source.run_id;},'button secondary');const go=button('Open selection',()=>navigate({asset:asset.input.value,run:run.input.value,source:src.input.value}));p.onsubmit=e=>{e.preventDefault();go.click();};p.append(asset.wrap,list,run.wrap,src.wrap,current,go);host.append(p);}
function mount(){view?.destroy();route=parseRoute(location.hash);renderShell();main.replaceChildren();const header=el('div','page-heading');header.append(el('div','eyebrow','TWINFORGE / OPERATIONS'),el('h1','',titles[route.page]),el('p','muted',route.page==='overview'?'A clear view of known twins, observed conditions and evidence quality.':'Read-only canonical data. Source time and receipt time remain separate.'));main.append(header);
  if(route.page==='overview'){view=overview();return;}chooser(main);if(!route.asset){main.append(notice('Select a known machine or enter a canonical asset ID to begin.'));view={update(){},destroy(){}};return;}
  if(route.page==='decision'){view=decisionView(main,route,()=>({twin:twins.find(t=>t.asset_id===route.asset),source,errors,lastRefresh}));return;}
  if(route.page==='machines'){view=machine();return;}
  if(route.page==='health'){const scores=el('div');scores.append(sourceScores(twins.find(t=>t.asset_id===route.asset)));main.append(scores);}
  if(route.page==='kpi'||route.page==='health'){view=analysisView(main,route,route.page==='health');return;}
  const evidence=evidenceView(main,route);view={update(){},destroy:evidence.destroy};
}
function overview(){const cards=el('div','stats'),toolbar=el('div','toolbar'),layout=el('div','fleet-layout'),fleet=panel('Fleet registry','Known twins only; not the complete installed factory inventory.'),inspection=panel('Machine inspection','Select a registry row to inspect canonical data.');layout.append(fleet,inspection);main.append(cards,toolbar,layout);
  const search=field('Search machines',route.search,'ID, type or line');const state=select('Observed state',[['','All states'],...['RUNNING','IDLE','FAULT','OFFLINE'].map(x=>[x,x])],route.state);const factory=field('Factory filter',route.factory,'All factories'),line=field('Line filter',route.line,'All lines');toolbar.append(search.wrap,state.wrap,factory.wrap,line.wrap,button('Export filtered twins',()=>exportJson('known-twins.json',{scope:'Currently loaded, filtered known twins',browser_refreshed_at:lastRefresh,twins:filterTwins(twins,route)}),'button secondary'));
  for(const [key,item] of [['search',search],['state',state],['factory',factory],['line',line]])item.input.addEventListener('input',()=>{route[key]=item.input.value;history.replaceState(null,'',routeUrl(route));renderShell();update();});
  function update(){const focusHref=layout.contains(document.activeElement)?document.activeElement.getAttribute('href'):null;const states=[...new Set([...twins.map(t=>t.state),...(route.state?[route.state]:[])])].sort();if(state.input.dataset.states!==JSON.stringify(states)){state.input.replaceChildren();for(const value of ['',...states]){const o=el('option','',value||'All states');o.value=value;state.input.append(o);}state.input.value=route.state;state.input.dataset.states=JSON.stringify(states);}patchDisplay(cards,stat('Known machines',twins.length,'Registry observations'),stat('Observed running',twins.filter(t=>t.state==='RUNNING').length,'Not proof of live operation'),stat('Reported faults',twins.filter(t=>t.active_fault).length,'Last observed fault codes'),stat('Quality attention',twins.filter(t=>!t.quality?.valid||!t.quality?.fresh||!connected()).length,'Invalid, stale or source unconfirmed'));
    const oldTable=fleet.querySelector('.table-scroll');const scroll={top:oldTable?.scrollTop||0,left:oldTable?.scrollLeft||0};const filtered=filterTwins(twins,route);const registryTable=table(['Machine / type','Factory / line','Observed state','Reported fault','Data quality'],filtered.map(t=>[link(t.asset_id,{...route,asset:t.asset_id}),`${t.asset_type} · ${t.factory_id} / ${t.line_id}`,badge(t.state),valueText(t.active_fault),qualityLabel(t,connected(),!!errors.twins)]));patchDisplay(fleet,fleet.firstChild,registryTable,...(!filtered.length?[notice(busy?'Loading known twins...':'No known twins match this selection.')]:[]));const retainedTable=fleet.querySelector('.table-scroll');retainedTable.scrollTop=scroll.top;retainedTable.scrollLeft=scroll.left;
    const details=el('div');const t=twins.find(t=>t.asset_id===route.asset);if(t){details.append(badge(qualityLabel(t,connected(),!!errors.twins)),twinFacts(t));const links=el('div','actions');for(const page of ['machines','decision','kpi','health','history'])links.append(link(titles[page],{...route,page,run:route.run||source?.run_id||''},'button secondary'));details.append(links);}else details.append(notice('Choose a machine to see its state, telemetry context and related views.'));patchDisplay(inspection,inspection.firstChild,...details.childNodes);
    if(focusHref)[...layout.querySelectorAll('a')].find(a=>a.getAttribute('href')===focusHref)?.focus({preventScroll:true});
  }update();return {update,destroy(){}};
}
function machine(){const region=el('div');main.append(link('Open decision support',{...route,page:'decision',run:route.run||source?.run_id||''},'button secondary'),region);let detail=null,dead=false;const request=new AbortController();const evidence=evidenceView(main,route);
  function update(){const t=twins.find(t=>t.asset_id===route.asset)||detail;region.replaceChildren();if(!t){region.append(notice('Loading machine details…'));return;}const grid=el('div','two-column');const identity=panel(t.asset_id,t.asset_type);identity.append(badge(qualityLabel(t,connected(),!!errors.twins)),twinFacts(t));grid.append(identity,sourceScores(t));region.append(grid);const telemetry=el('div','metric-grid');for(const [name,value] of Object.entries(t.telemetry?.values||{})){const m=measurement(name,t.quality?.source);telemetry.append(stat(m.label,value,m.unit||'Unit not supplied'));}if(!telemetry.children.length)telemetry.append(notice('No telemetry available.'));region.append(telemetry);}
  let detailError=null;
  api.twin(route.asset,request.signal).then(t=>{if(!dead){detail=t;update();}}).catch(e=>{if(!dead){detailError=e.message;region.replaceChildren(notice(e.message,'error'));}});update();return {update(){if(!detail&&!twins.some(t=>t.asset_id===route.asset)&&detailError)return;update();},destroy(){dead=true;request.abort();evidence.destroy();}};
}
async function refresh(signal){busy=true;const refreshButton=document.querySelector('#refresh');refreshButton.disabled=true;const oldRun=source?.run_id;
  try{
    const results=await Promise.allSettled([api.twins(signal),api.source(signal),api.persistence(signal)]);
    if(signal.aborted)return;
    results.forEach((r,i)=>{const key=['twins','source','persistence'][i];if(r.status==='fulfilled'){delete errors[key];if(i===0)twins=r.value;if(i===1)source=r.value;if(i===2)persistence=r.value;}else errors[key]=r.reason.message;});lastRefresh=new Date().toISOString();busy=false;
    if(oldRun&&source?.run_id&&oldRun!==source.run_id){document.querySelector('#run-warning').textContent='Source run changed. Previous analysis/history was invalidated; select and reload the intended recorded run.';if(route.page!=='overview')mount();}
    renderShell();view?.update();
  }finally{busy=false;refreshButton.disabled=false;}
}
const listeners=new AbortController();
const polling=createPolling(refresh,{onError:error=>{document.querySelector('#refresh-status').textContent=`Data check failed: ${error.message}`;}});
function dispose(){polling.dispose();listeners.abort();view?.destroy();}
window.__twinforgeDispose=dispose;
function listen(target,event,callback){target.addEventListener(event,callback,{signal:listeners.signal});}
listen(document.querySelector('#refresh'),'click',()=>polling.refresh());
listen(document.querySelector('#menu'),'click',()=>{const open=document.body.classList.toggle('menu-open');document.querySelector('#menu').setAttribute('aria-expanded',String(open));});
listen(window,'hashchange',()=>{document.body.classList.remove('menu-open');mount();});
listen(document,'visibilitychange',()=>polling.visibility());
// Preserve the mounted view during back/forward-cache suspension; resume on return.
listen(window,'pagehide',event=>{if(!event.persisted)dispose();else polling.pause();});
listen(window,'pageshow',()=>polling.resume());
mount();polling.refresh();
