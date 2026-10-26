// @ts-check
/** @param {unknown} value */
export function riskText(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
    ? `${Number(value.toFixed(3))} / 1` : 'Unavailable';
}
/** @param {string} status */
export function decisionTone(status) {
  return ({NORMAL:'success',WARNING:'warning',CRITICAL:'critical',INSUFFICIENT_DATA:'neutral',
    continue_monitoring:'success',maintenance_after_current_batch:'warning',maintenance_now:'critical',manual_review_required:'review'})[status] || 'neutral';
}
/** @param {string} action */
export function actionLabel(action) {
  return ({continue_monitoring:'Continue monitoring',maintenance_after_current_batch:'Maintenance after current batch',maintenance_now:'Maintenance now',manual_review_required:'Operator review required'})[action] || 'Operator review required';
}
/** @param {{status?:number;message?:string}} error */
export function decisionError(error) {
  if(error.status===409)return 'Context changed. Refresh observed state, verify the selected run and sequence, then calculate again. Previous results are not current advice.';
  if(error.status===422)return 'Invalid assumptions. Use a positive maintenance duration, a nonnegative remaining duration (or leave it blank), and an optional whole-number sequence.';
  if(error.status===503)return 'Persistence or historical evidence is unavailable. Check connection status and retry.';
  if(error.status===404)return 'Machine is not available in the selected current context. Refresh and select a known machine.';
  return error.message || 'Request failed. Retry when the service is available.';
}
/** @param {import('./contracts').Selection} selection @param {string} duration @param {string} remaining @param {string} sequence @returns {import('./contracts').MaintenanceRequest} */
export function maintenanceInputs(selection,duration,remaining,sequence) {
  const number=(text,optional,min,max,integer=false)=>{
    if(!text.trim()){if(optional)return null;throw Error('Maintenance duration is required.');}
    const n=Number(text);
    if(!Number.isFinite(n)||n<min||n>max||(integer&&!Number.isSafeInteger(n)))throw Error('Check durations (maximum 604800 seconds) and the optional nonnegative integer sequence.');
    return n;
  };
  const d=number(duration,false,0,604800);
  if(d===0)throw Error('Maintenance duration must be greater than zero.');
  return {asset_id:selection.asset,run_id:selection.run,maintenance_duration_seconds:d,
    remaining_batch_seconds:number(remaining,true,0,604800),expected_sequence:number(sequence,true,0,Number.MAX_SAFE_INTEGER,true)};
}
