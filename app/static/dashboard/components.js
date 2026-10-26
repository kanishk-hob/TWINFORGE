import {valueText,routeUrl} from './data.js';
export function el(tag,cls='',text) {const n=document.createElement(tag);n.className=cls;if(text!==undefined)n.textContent=valueText(text);return n;}
export function box(...children){const n=el('div');n.append(...children);return n;}
export function badge(text,tone='neutral'){return el('span','badge '+tone,text);}
export function button(text,fn,cls='button'){const n=el('button',cls,text);n.type='button';n.addEventListener('click',fn);return n;}
export function link(text,route,cls='text-link'){const n=el('a',cls,text);n.href=routeUrl(route);return n;}
export function panel(title,subtitle){const n=el('section','panel');const h=el('header','panel-heading');h.append(el('h2','',title));if(subtitle)h.append(el('p','muted',subtitle));n.append(h);return n;}
export function notice(text,tone=''){return el('p','notice '+tone,text);}
export function stat(label,value,detail){const n=el('div','stat');n.append(el('span','eyebrow',label),el('strong','metric mono',valueText(value)));if(detail)n.append(el('span','muted',detail));return n;}
export function field(label,value='',placeholder=''){const wrap=el('label','field');const input=el('input');input.value=value;input.placeholder=placeholder;wrap.append(el('span','',label),input);return {wrap,input};}
export function select(label,values,current=''){const wrap=el('label','field');const input=el('select');for(const [v,t] of values){const o=el('option','',t);o.value=v;input.append(o);}input.value=current;wrap.append(el('span','',label),input);return {wrap,input};}
export function table(headers,rows){const wrap=el('div','table-scroll');const t=el('table');const head=el('thead');const tr=el('tr');headers.forEach(h=>tr.append(el('th','',h)));head.append(tr);t.append(head);const body=el('tbody');for(const row of rows){const r=el('tr');for(const cell of row){const td=el('td');td.append(cell instanceof Node?cell:document.createTextNode(valueText(cell)));r.append(td);}body.append(r);}t.append(body);wrap.append(t);return wrap;}
export function facts(values){const dl=el('dl','facts');for(const [name,value] of Object.entries(values)){dl.append(el('dt','',name),el('dd','mono',valueText(value)));}return dl;}
export function raw(title,value){const d=el('details');d.append(el('summary','',title),el('pre','raw',JSON.stringify(value,null,2)));return d;}
export function eventList(events){if(!events.length)return notice('No events in the loaded selection. This is not evidence that no faults occurred.');return table(['Receipt time (UTC offset shown)','Observed event','Previous → recorded value','Sequence / ID'],events.map(e=>[e.observed_at,e.kind,`${valueText(e.previous_value)} → ${valueText(e.value)}`,`${e.sequence} / ${e.id}`]));}
