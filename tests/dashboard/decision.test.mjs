import test from 'node:test';
import assert from 'node:assert/strict';
import {renderPredictive,renderComparison,renderRecommendation,decisionView} from '../../app/static/dashboard/decision-view.js';
import {decisionError,maintenanceInputs,riskText} from '../../app/static/dashboard/decision-data.js';
import {parseRoute,routeUrl} from '../../app/static/dashboard/data.js';
import {api,ApiError} from '../../app/static/dashboard/client.js';

// Minimal DOM tree for safe-text/rendering and event lifecycle tests. Not a layout emulator.
class TestNode {
  constructor(tag='text'){this.tagName=tag;this.children=[];this.attributes={};this.listeners={};this.className='';this.value='';this.disabled=false;this.text='';}
  set textContent(v){this.text=String(v);this.children=[];}
  get textContent(){return this.text+this.children.map(c=>c.textContent).join(' ');}
  append(...nodes){for(const n of nodes)this.children.push(n instanceof TestNode?n:Object.assign(new TestNode(),{text:String(n)}));}
  replaceChildren(...nodes){this.text='';this.children=[];this.append(...nodes);}
  setAttribute(k,v){this.attributes[k]=v;}
  addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
  async fire(k){for(const fn of this.listeners[k]||[])await fn({target:this});}
  async click(){if(!this.disabled)await this.fire('click');}
}
globalThis.Node=TestNode;
globalThis.document={createElement:tag=>new TestNode(tag),createTextNode:text=>Object.assign(new TestNode(),{text:String(text)})};
const nodes=root=>[root,...root.children.flatMap(nodes)];
const btn=(root,label)=>nodes(root).find(n=>n.tagName==='button'&&n.textContent===label);
const inputs=root=>nodes(root).filter(n=>n.tagName==='input');
const predictive=(status='WARNING')=>({status,asset_id:'A',run_id:'R',method:'z_score_ewma',risk_score:status==='INSUFFICIENT_DATA'?null:.5,z_score_risk:.5,ewma_risk:.2,dominant_signal:'temperature',dominant_method:'rolling_z_score',observations_used:60,latest_observed_at:'2026-01-01T00:00:00Z',reason:status==='INSUFFICIENT_DATA'?'No useful evidence':null,explanation:'Calculated deviation',top_signals:[]});
const metric=(value)=>({value,unit:'seconds',status:value===null?'unknown':'estimated',reason:value===null?'Missing evidence':'Modeled timing'});
const comparison=()=>({baseline:{asset_id:'A',run_id:'R',sequence:4,current_job_id:'J',source_timestamp:'2025-01-01T00:00:00Z',captured_at:'2026-01-01T00:00:00Z'},inputs:{maintenance_duration_seconds:10,remaining_batch_seconds:30,expected_sequence:4},scenario_a:{status:'estimated',metrics:{current_batch_delay_seconds:metric(10),energy_impact:metric(null)},affected_jobs:['J'],unavailable:['Energy unavailable']},scenario_b:{status:'partial',metrics:{current_batch_delay_seconds:metric(0)},affected_jobs:['J'],unavailable:[]},deltas_b_minus_a:{current_batch_delay_seconds:metric(-10)},comparison_rule:'No overall preference',assumptions:['Pause and resume'],data_quality:['Partial timing']});
const recommendation=(action='maintenance_after_current_batch')=>({recommended_action:action,recommendation_status:'recommended',explanation:'Explicit policy',human_approval_required:action!=='continue_monitoring',automatic_execution_allowed:false,predictive_status_used:'WARNING',predictive_risk_used:.5,rule_id:'R4',policy_version:'maintenance_policy.v1',data_quality:{classification:'adequate',meaning:'Not statistical confidence',findings:[]},generated_at:'2026-01-01T00:00:01Z',predictive_evidence_reference:{latest_observed_at:'2026-01-01T00:00:00Z',receipt_age_seconds:1},sequence:4,assumptions:['Policy assumption'],missing_evidence:['Energy unknown'],policy_parameters:{max_warning_deferral_seconds:300},calculated_predictive_evidence:predictive(),estimated_scenario_evidence:comparison()});
const route={asset:'A',run:'R',source:'factory_simulator',page:'decision'};
function context(){return {twin:{asset_id:'A',sequence:4,state:'RUNNING',current_job_id:'J',active_fault:null,quality:{valid:true,fresh:true},telemetry:{timestamp:'2025-01-01T00:00:00Z'}},source:{run_id:'R',connected:true},errors:{},lastRefresh:'2026-01-01T00:00:00Z'};}

for(const status of ['NORMAL','WARNING','CRITICAL','INSUFFICIENT_DATA'])test('predictive rendering '+status,()=>{const tree=renderPredictive(predictive(status));assert.match(tree.textContent,new RegExp(status));assert.match(tree.textContent,/not failure probability/);assert.match(tree.textContent,/database receipt time/);if(status==='INSUFFICIENT_DATA')assert.match(tree.textContent,/Unavailable/);const tones={NORMAL:'success',WARNING:'warning',CRITICAL:'critical',INSUFFICIENT_DATA:'neutral'};assert.ok(nodes(tree).some(n=>n.className==='badge '+tones[status]));});
test('risk zero is distinct from unknown',()=>{assert.equal(riskText(0),'0 / 1');assert.equal(riskText(null),'Unavailable');assert.equal(riskText(NaN),'Unavailable');});
test('what-if renders both timings, zero and missing outcomes separately',()=>{const tree=renderComparison(comparison());assert.match(tree.textContent,/10 seconds/);assert.match(tree.textContent,/0 seconds/);assert.match(tree.textContent,/Unavailable/);assert.match(tree.textContent,/After current batch/);assert.match(tree.textContent,/offsets from hypothetical time zero/);assert.match(tree.textContent,/Partial timing/);});
for(const [action,label] of Object.entries({continue_monitoring:'Continue monitoring',maintenance_after_current_batch:'Maintenance after current batch',maintenance_now:'Maintenance now',manual_review_required:'Operator review required'}))test('recommendation action '+action,()=>{const tree=renderRecommendation(recommendation(action));assert.match(tree.textContent,new RegExp(label));assert.match(tree.textContent,/Automatic execution allowed No/);if(action!=='continue_monitoring')assert.match(tree.textContent,/Operator approval required/);assert.equal(nodes(tree).filter(n=>n.tagName==='button').length,0);});
test('backend text is rendered as literal text, never markup',()=>{const attack='<img src=x onerror=alert(1)>';const data=recommendation();data.explanation=attack;data.missing_evidence=[attack];const tree=renderRecommendation(data);assert.ok(tree.textContent.includes(attack));assert.ok(!nodes(tree).some(n=>n.tagName==='img'||n.tagName==='script'));});
test('decision route round trips escaped selection',()=>{const r=parseRoute(routeUrl({...route,asset:'A/B #'}));assert.equal(r.page,'decision');assert.equal(r.asset,'A/B #');assert.equal(r.run,'R');});
test('assumption parsing preserves blank, zero and valid sequence',()=>{assert.equal(maintenanceInputs(route,'10','','').remaining_batch_seconds,null);assert.equal(maintenanceInputs(route,'10','0','0').remaining_batch_seconds,0);for(const args of [['0','',''],['10','-1',''],['10','0','1.5'],['Infinity','','']])assert.throws(()=>maintenanceInputs(route,...args));});
test('operator error guidance for 409, 422 and 503',()=>{assert.match(decisionError(new ApiError(409,'context')),/Context changed/);assert.match(decisionError(new ApiError(422,'query')),/Invalid assumptions/);assert.match(decisionError(new ApiError(503,'db')),/Persistence/);});
test('client sends only explicit calculation endpoints with JSON POST',async()=>{const old=globalThis.fetch,calls=[];globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({})};};try{await api.predictive(route);const body=maintenanceInputs(route,'10','0','4');await api.compareMaintenance(body);await api.recommendMaintenance(body);assert.equal(calls[0].options.method,'GET');assert.match(calls[0].url,/method=z_score_ewma/);assert.equal(calls[1].url,'/api/scenarios/maintenance/compare');assert.equal(calls[2].url,'/api/recommendations/maintenance');assert.equal(calls[1].options.method,'POST');assert.equal(JSON.parse(calls[1].options.body).remaining_batch_seconds,0);assert.equal(JSON.parse(calls[2].options.body).predictive_method,'z_score_ewma');}finally{globalThis.fetch=old;}});
test('409 retains but invalidates last-known recommendation',async()=>{const host=new TestNode(),live=context();let fail=false;const client={recommendMaintenance:async()=>{if(fail)throw new ApiError(409,'changed');return recommendation();}};const view=decisionView(host,route,()=>live,client);inputs(host)[0].value='10';inputs(host)[1].value='30';await btn(host,'Generate maintenance recommendation').click();fail=true;await btn(host,'Generate maintenance recommendation').click();assert.match(host.textContent,/Context changed/);assert.match(host.textContent,/Previous result/);assert.match(host.textContent,/Explicit policy/);view.destroy();});
test('temporary predictive error retains previous calculation',async()=>{const host=new TestNode();let fail=false;const client={predictive:async()=>{if(fail)throw new ApiError(503,'db');return predictive();}};const view=decisionView(host,route,context,client);await btn(host,'Calculate predictive condition').click();fail=true;await btn(host,'Calculate predictive condition').click();assert.match(host.textContent,/Calculated deviation/);assert.match(host.textContent,/last-known evidence retained/);view.destroy();});
test('input edits and destroy suppress late requests',async()=>{const host=new TestNode();let resolve;const client={compareMaintenance:()=>new Promise(r=>{resolve=r;})};const view=decisionView(host,route,context,client);inputs(host)[0].value='10';const pending=btn(host,'Compare maintenance timings').click();inputs(host)[0].value='20';await inputs(host)[0].fire('input');resolve(comparison());await pending;assert.doesNotMatch(host.textContent,/No overall preference/);const pending2=btn(host,'Compare maintenance timings').click();view.destroy();resolve(comparison());await pending2;assert.doesNotMatch(host.textContent,/No overall preference/);});
test('canonical sequence changes mark old results and suppress requests in flight',async()=>{const host=new TestNode(),live=context();const view=decisionView(host,route,()=>live,{predictive:async()=>predictive()});await btn(host,'Calculate predictive condition').click();live.twin.sequence=5;view.update();assert.match(host.textContent,/observed context changed/);assert.match(host.textContent,/Calculated deviation/);view.destroy();});

test('receipt-age expiry marks retained recommendation outdated without a sequence change',async()=>{const host=new TestNode(),live=context();const data=recommendation();const view=decisionView(host,route,()=>live,{recommendMaintenance:async()=>data});inputs(host)[0].value='10';await btn(host,'Generate maintenance recommendation').click();data.policy_parameters.max_predictive_receipt_age_seconds=60;view.update();assert.match(host.textContent,/exceeded the policy receipt-age limit/);view.destroy();});

for(const [label,method] of [['Compare maintenance timings','compareMaintenance'],['Generate maintenance recommendation','recommendMaintenance']]) {
  const section=host=>nodes(host).find(n=>n.tagName==='section'&&nodes(n).includes(btn(host,label)));
  test(label+' explains historical run locally without sending a request',async()=>{
    const host=new TestNode();let calls=0;
    const view=decisionView(host,{...route,run:'OLD'},context,{[method]:async()=>{calls++;}});
    inputs(host)[0].value='60';await btn(host,label).click();
    assert.equal(calls,0);assert.match(section(host).textContent,/Selected run OLD is historical; current source run is R/);
    assert.match(section(host).textContent,/Open selection/);assert.doesNotMatch(section(host).textContent,/No result loaded/);view.destroy();
  });
  test(label+' reports required duration beside the action',async()=>{
    const host=new TestNode();let calls=0;
    const view=decisionView(host,route,context,{[method]:async()=>{calls++;}});
    await btn(host,label).click();assert.equal(calls,0);
    assert.match(section(host).textContent,/Maintenance duration is required/);view.destroy();
  });
  test(label+' shows loading and server failure locally and permits retry',async()=>{
    const host=new TestNode();let reject;
    const view=decisionView(host,route,context,{[method]:()=>new Promise((_,r)=>{reject=r;})});
    inputs(host)[0].value='60';const pending=btn(host,label).click();
    assert.match(section(host).textContent,/Reading evidence and calculating/);assert.equal(btn(host,label).disabled,true);
    reject(new ApiError(503,'unavailable'));await pending;
    assert.match(section(host).textContent,/Persistence or historical evidence is unavailable/);
    assert.doesNotMatch(section(host).textContent,/No result loaded/);assert.equal(btn(host,label).disabled,false);view.destroy();
  });
  test(label+' renders a successful calculation and local completion feedback',async()=>{
    const host=new TestNode();const view=decisionView(host,route,context,{[method]:async()=>method==='compareMaintenance'?comparison():recommendation()});
    inputs(host)[0].value='60';await btn(host,label).click();
    assert.match(section(host).textContent,method==='compareMaintenance'?/Calculation loaded/:/No action was executed/);
    assert.match(section(host).textContent,method==='compareMaintenance'?/No overall preference/:/Operator approval required/);view.destroy();
  });
}
