import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import {trendSegments,plotData,measurement} from './data.js';
import {el,notice,select} from './components.js';
export function chart(host,rows){
  let plot,observer;const fields=[...new Set(rows.flatMap(r=>Object.keys(r.telemetry_values||{})))].filter(k=>rows.some(r=>typeof r.telemetry_values?.[k]==='number'));
  const destroy=()=>{observer?.disconnect();plot?.destroy();plot=null;};
  if(!fields.length){host.append(notice('No numeric persisted telemetry in this loaded selection.'));return destroy;}
  const choice=select('Measurement',fields.map(f=>[f,f]),fields[0]);const area=el('div','chart');host.append(choice.wrap,area,el('p','muted','Source time axis • breaks mark unavailable or discontinuous observations. See the observation table for receipt timestamps.'));
  function draw(){destroy();area.replaceChildren();const data=plotData(trendSegments(rows,choice.input.value));
    if(!data||!data[0].length){area.append(notice('No continuous, valid numeric series can be plotted. Runs or source timestamps overlap; inspect the table.'));return;}
    const unit=measurement(choice.input.value,rows[0]?.source).unit;
    plot=new uPlot({width:Math.max(240,area.clientWidth),height:240,legend:{show:false},scales:{x:{time:true}},axes:[{stroke:'#64748b',grid:{stroke:'#e7edf4'}},{stroke:'#64748b',grid:{stroke:'#e7edf4'}}],series:[{}, {label:choice.input.value+(unit?' ('+unit+')':''),stroke:'#2563eb',width:2,spanGaps:false,points:{show:true,size:4}}]},[data[0].map(x=>x/1000),data[1]],area);
    observer=new ResizeObserver(()=>plot?.setSize({width:Math.max(240,area.clientWidth),height:240}));observer.observe(area);
  }choice.input.onchange=draw;draw();return destroy;
}
