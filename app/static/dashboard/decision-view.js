import {api} from './client.js';
import {valueText,qualityLabel} from './data.js';
import {el,panel,field,button,notice,stat,table,facts,badge,raw} from './components.js';
import {riskText,decisionTone,actionLabel,decisionError,maintenanceInputs} from './decision-data.js';

function messages(title,items){const section=el('details');section.append(el('summary','',`${title} (${items.length})`));const list=el('ul');for(const text of items)list.append(el('li','',text));section.append(list);return section;}
function riskCard(label,value){const card=stat(label,riskText(value),'Statistical deviation score');if(typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=1){const meter=el('meter','risk-meter');meter.min=0;meter.max=1;meter.value=value;meter.setAttribute('aria-label',`${label}: ${riskText(value)}`);card.append(meter);}return card;}

export function renderPredictive(data){
  const p=el('div','decision-result');
  if(!data){p.append(notice('Independent predictive evidence unavailable. Review the recommendation’s missing evidence.'));return p;}
  p.append(badge(data.status,decisionTone(data.status)),notice('Risk is a statistical deviation score, not failure probability. No historical predictive series is available.'));
  const cards=el('div','decision-risks');cards.append(riskCard('Combined risk',data.risk_score),riskCard('Z-score risk',data.z_score_risk),riskCard('EWMA risk',data.ewma_risk));p.append(cards);
  p.append(facts({'Asset / run':`${data.asset_id} / ${data.run_id}`,'Dominant signal':data.dominant_signal,'Dominant detector':data.dominant_method,'Observations used':data.observations_used,'Latest evidence — database receipt time':data.latest_observed_at,Method:data.method}));
  p.append(notice(data.explanation||data.reason||'See contributing signals for calculated evidence.'),notice(data.reason||'No partial-evidence reason returned. Coverage is limited to assessed signals.'));
  p.append(table(['Signal','Current','Rolling baseline mean / std','Z-score','Z-score risk','EWMA risk','Combined signal risk','Evidence / reason'],data.top_signals.map(s=>[s.signal,s.current_value,`${valueText(s.baseline_mean)} / ${valueText(s.baseline_std)}`,valueText(s.z_score),riskText(s.z_score_risk),riskText(s.ewma?.risk),riskText(s.risk),s.reason||`${s.observations_used} observations`])));
  p.append(raw('Predictive calculation details',data));return p;
}
const timingLabels={projected_maintenance_downtime_seconds:'Maintenance downtime',maintenance_start_offset_seconds:'Maintenance start',maintenance_end_offset_seconds:'Maintenance completion',current_batch_completion_offset_seconds:'Batch completion',current_batch_delay_seconds:'Batch delay',scenario_duration_seconds:'Total scenario duration',good_unit_impact:'Good-unit impact',throughput_impact:'Throughput impact',energy_impact:'Energy impact'};
function metricCell(m){const cell=el('div');cell.append(el('strong','mono',m?.value==null?'Unavailable':`${valueText(m.value)} ${m.unit}`),el('p','muted',m?.reason||'Metric unavailable'));return cell;}
export function renderComparison(data){
  const p=el('div','decision-result');p.append(notice('What-if estimates • offsets from hypothetical time zero, not wall-clock completion times.'));
  p.append(facts({'Frozen asset / run':`${data.baseline.asset_id} / ${data.baseline.run_id}`,'Frozen sequence':data.baseline.sequence,'Observed job label':data.baseline.current_job_id,'Source timestamp':data.baseline.source_timestamp,'Context captured at':data.baseline.captured_at,'Caller maintenance duration (seconds)':data.inputs.maintenance_duration_seconds,'Caller remaining batch duration (seconds)':data.inputs.remaining_batch_seconds,'Expected sequence':data.inputs.expected_sequence}));
  p.append(badge(`Now: ${data.scenario_a.status}`,data.scenario_a.status==='partial'?'warning':''),badge(`After batch: ${data.scenario_b.status}`,data.scenario_b.status==='partial'?'warning':''));
  p.append(table(['Operational metric','Maintenance now','After current batch','Difference: after − now'],Object.entries(timingLabels).map(([key,label])=>[label,metricCell(data.scenario_a.metrics[key]),metricCell(data.scenario_b.metrics[key]),metricCell(data.deltas_b_minus_a[key])])));
  p.append(facts({'Jobs considered — now':data.scenario_a.affected_jobs.join(', ')||'Unavailable','Jobs considered — after batch':data.scenario_b.affected_jobs.join(', ')||'Unavailable'}),notice('Job lists are incomplete; downstream effects are not modeled.'),notice(data.comparison_rule));
  p.append(messages('Assumptions',data.assumptions),messages('Data-quality findings',data.data_quality),messages('Unavailable outcomes',[...new Set([...data.scenario_a.unavailable,...data.scenario_b.unavailable])]),raw('Complete what-if estimate',data));return p;
}
export function renderRecommendation(data){
  const p=el('div',`decision-result decision-action ${decisionTone(data.recommended_action)}`);
  p.append(el('h3','',actionLabel(data.recommended_action)),badge(data.recommendation_status),notice(data.explanation));
  if(data.human_approval_required)p.append(notice('Operator approval required. This dashboard cannot approve or execute maintenance.','approval'));
  p.append(facts({'Predictive status considered':data.predictive_status_used,'Predictive risk considered':riskText(data.predictive_risk_used),'Rule ID':data.rule_id,'Policy version':data.policy_version,'Evidence quality':data.data_quality.classification,'Human approval required':data.human_approval_required?'Yes':'No — monitoring advice only','Automatic execution allowed':data.automatic_execution_allowed===false?'No':'Unexpected backend value — operator review required','Recommendation generated at':data.generated_at,'Evidence receipt time':data.predictive_evidence_reference.latest_observed_at,'Evidence receipt age (seconds)':data.predictive_evidence_reference.receipt_age_seconds,'Decision sequence':data.sequence}));
  p.append(notice(data.data_quality.meaning),messages('Evidence-quality findings',data.data_quality.findings),messages('Assumptions',data.assumptions),messages('Missing / unavailable evidence',data.missing_evidence),raw('Policy parameters',data.policy_parameters),raw('Complete recommendation and evidence',data));
  p.append(notice('Human decision: review the evidence and use your approved maintenance procedure. Approval recording and execution are not available here.'));
  return p;
}

export function decisionView(host,route,getContext,client=api){
  let dead=false,controller=null,contextKey=null;
  const observed=panel('1 · Observed machine state','Source-reported canonical state. Independent from the calculations below.');
  const observedBody=el('div');observed.append(observedBody);host.append(observed);
  const controls=panel('Operator assumptions','Explicit inputs for the timing model. Blank remaining duration means unknown, not zero.');
  const duration=field('Maintenance duration (seconds)','','Required, greater than zero');
  const remaining=field('Remaining batch duration (seconds)','','Optional — unknown if blank');
  const sequence=field('Expected sequence (optional)','','Guard against context changes');
  for(const f of [duration,remaining]){f.input.type='number';f.input.min='0';f.input.max='604800';f.input.step='any';}
  sequence.input.type='number';sequence.input.min='0';sequence.input.step='1';
  const useSequence=button('Use observed sequence',()=>{const t=getContext().twin;if(t){sequence.input.value=String(t.sequence);assumptionsChanged();}},'button secondary');
  const form=el('div','toolbar');form.append(duration.wrap,remaining.wrap,sequence.wrap,useSequence);controls.append(form,notice('Calculations are read-only with respect to machine control. Changing inputs makes previous estimates and advice outdated.'));host.append(controls);
  const status=el('div');status.setAttribute('role','status');status.setAttribute('aria-live','polite');host.append(status);
  const sections={};
  for(const [key,title,subtitle] of [['predictive','2 · Predictive calculation','Persisted raw telemetry · rolling Z-score + EWMA'],['comparison','3 · What-if estimate','Compare two maintenance timings under your assumptions'],['recommendation','4 · Recommendation policy decision','Advisory policy with human review; no machine commands']]){
    const p=panel(title,subtitle),message=el('div'),body=el('div');p.append(message,body);host.append(p);sections[key]={p,message,body,result:null};body.append(notice('No result loaded. Calculate explicitly for this selection.'));
  }
  const actions={predictive:button('Calculate predictive condition',()=>calculate('predictive')),comparison:button('Compare maintenance timings',()=>calculate('comparison')),recommendation:button('Generate maintenance recommendation',()=>calculate('recommendation'))};
  for(const key of Object.keys(actions))sections[key].p.append(actions[key]);
  function busy(value){for(const action of Object.values(actions))action.disabled=value;}
  function stop(){controller?.abort();controller=null;busy(false);}
  function previous(keys,why){for(const key of keys)if(sections[key].result!==null)sections[key].message.replaceChildren(notice(`Previous result — ${why} Not current advice.`,'previous'));}
  function assumptionsChanged(){stop();previous(['comparison','recommendation'],'assumptions changed.');status.replaceChildren(notice('Assumptions changed. Recalculate the comparison and recommendation.'));}
  for(const f of [duration,remaining,sequence])f.input.addEventListener('input',assumptionsChanged);
  function display(key,data,renderer){sections[key].result=data;sections[key].body.replaceChildren(renderer(data));sections[key].message.replaceChildren(notice(`Browser received this calculation: ${new Date().toISOString()}. Recalculate after context or assumption changes.`));}
  function feedback(kind,text,tone=''){
    status.replaceChildren(notice(text,tone));
    sections[kind].message.replaceChildren(notice(text,tone));
    if(sections[kind].result===null)sections[kind].body.replaceChildren();
  }
  async function calculate(kind){
    stop();const live=getContext();
    if(!route.asset||!route.run||route.source!=='factory_simulator'){feedback(kind,'Select a machine, run and factory_simulator source, then click Open selection. These decision APIs support that source only.','error');return;}
    let body;
    if(kind!=='predictive'){
      if(!live.twin||live.errors?.twins||live.errors?.source||!live.source?.run_id){feedback(kind,'Current machine/source context is unavailable. Refresh observed state before comparing or recommending.','error');return;}
      if(live.source.run_id!==route.run){feedback(kind,`Selected run ${route.run} is historical; current source run is ${live.source.run_id}. These actions require current context. Click Use current source run, then Open selection. Historical predictive evidence alone cannot be used for a current maintenance decision.`,'error');return;}
      try{body=maintenanceInputs(route,duration.input.value,remaining.input.value,sequence.input.value);}catch(error){feedback(kind,error.message,'error');return;}
    }
    const request=new AbortController();controller=request;busy(true);
    previous(kind==='recommendation'?Object.keys(sections):[kind,'recommendation'],'refresh in progress.');
    feedback(kind,'Reading evidence and calculating...');
    try{
      const result=kind==='predictive'?await client.predictive(route,request.signal):kind==='comparison'?await client.compareMaintenance(body,request.signal):await client.recommendMaintenance(body,request.signal);
      if(dead||controller!==request)return;
      if(kind==='recommendation'){
        display('predictive',result.calculated_predictive_evidence,renderPredictive);
        display('comparison',result.estimated_scenario_evidence,renderComparison);
        display('recommendation',result,renderRecommendation);
      }else display(kind,result,kind==='predictive'?renderPredictive:renderComparison);
      feedback(kind,kind==='recommendation'?'Recommendation and its exact predictive/scenario evidence loaded together. No action was executed.':'Calculation loaded. Recommendation must be generated separately and may use newer evidence.');
    }catch(error){if(!dead&&controller===request){previous(error.status===409?Object.keys(sections):[kind],'request failed; last-known evidence retained.');feedback(kind,`${decisionError(error)}${sections[kind].result!==null?' Previous result: last-known evidence retained; not current advice.':''}`,'error');}}
    finally{if(controller===request){controller=null;busy(false);}}
  }
  function update(){
    const live=getContext(),t=live.twin,s=live.source;
    const advice=sections.recommendation.result;
    if(advice){const receipt=Date.parse(advice.predictive_evidence_reference.latest_observed_at||'');const limit=advice.policy_parameters.max_predictive_receipt_age_seconds;if(Number.isFinite(receipt)&&typeof limit==='number'&&(Date.now()-receipt)/1000>limit)previous(['recommendation'],'predictive evidence has exceeded the policy receipt-age limit.');}
    const key=JSON.stringify([s?.run_id,t?.sequence,t?.current_job_id,t?.state,t?.active_fault,t?.quality?.valid,t?.quality?.fresh,s?.connected,!!live.errors?.twins,!!live.errors?.source]);
    if(contextKey!==null&&contextKey!==key){stop();previous(Object.keys(sections),'observed context changed.');status.replaceChildren(notice('Observed context changed. Verify assumptions and sequence before recalculating.'));}contextKey=key;
    observedBody.replaceChildren();
    if(!t){observedBody.append(notice('Selected machine is not in the loaded registry. Refresh or select a known machine.'));return;}
    observedBody.append(badge(qualityLabel(t,s?.connected===true&&!live.errors?.source,!!live.errors?.twins)),facts({Asset:t.asset_id,'Selected run':route.run,'Current source run':s?.run_id,'Observed state':t.state,'Current job':t.current_job_id,'Reported fault':t.active_fault,Sequence:t.sequence,'Source telemetry time':t.telemetry?.timestamp,'Last successful synchronization time':s?.last_sync_at,'Browser registry refresh time':live.lastRefresh}));
    if(route.run!==s?.run_id)observedBody.append(notice('Selected run is not the current source run. What-if and recommendation require current context.'));
  }
  update();return {update,destroy(){dead=true;stop();}};
}
