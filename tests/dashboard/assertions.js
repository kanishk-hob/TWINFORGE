// Serve the repository root with http.server; never mounted in production.
import {segments,mergePage} from '../../app/static/dashboard/history.js';
import {renderKpi} from '../../app/static/dashboard/kpi.js';
import {display,get} from '../../app/static/dashboard/api.js';
const results=[];
function check(name,test){try{if(!test())throw Error('assertion failed');results.push(`PASS ${name}`);}catch(e){results.push(`FAIL ${name}: ${e.message}`);}}
const row=(id,extra={})=>({id,run_id:'fixture',source:'test',sequence:id,valid:true,fresh:true,source_timestamp:`2024-01-01T00:00:0${id}Z`,telemetry_values:{reading:id},...extra});
check('null is not zero',()=>display(null)==='Unavailable'&&display(0)==='0');
check('page retry deduplicates',()=>mergePage([row(1),row(2)],[row(2),row(3)]).length===3);
check('contiguous samples join',()=>segments([row(1),row(2)],'reading')[0].length===2);
for(const [label,extra] of Object.entries({run:{run_id:'other'},gap:{sequence:4},stale:{fresh:false},invalid:{valid:false},time:{source_timestamp:null},null:{telemetry_values:{reading:null}},string:{telemetry_values:{reading:'2'}}}))check(`trend breaks: ${label}`,()=>segments([row(1),row(2,extra),row(3)],'reading').every(p=>p.length===1));
const target=document.getElementById('fixture');
renderKpi({asset_id:'<img src=x onerror=alert(1)>',coverage:0,metrics:{oee:{value:null,unit:'fraction',status:'unknown',reason:'Missing schedule'},energy:{value:0,unit:'kWh',status:'estimated',reason:null}},downtime_reasons_seconds:null},target);
check('KPI null, zero, units, reason and estimate',()=>['Unavailable fraction','0 kWh','Missing schedule','Estimated'].every(t=>target.textContent.includes(t)));
check('source strings are text',()=>!target.querySelector('img'));
const original=globalThis.fetch;
for(const code of [404,422,503]){globalThis.fetch=async()=>({ok:false,status:code,json:async()=>({detail:'fixture error'})});try{await get('/fixture');results.push(`FAIL HTTP ${code}`);}catch(e){check(`HTTP ${code} visible`,()=>e.message.includes(`HTTP ${code}`));}}
globalThis.fetch=original;
document.getElementById('results').textContent=results.join('\n');
