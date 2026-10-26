import test from 'node:test';
import assert from 'node:assert/strict';
import {patchDisplay,createPolling} from '../../app/static/dashboard/refresh.js';

function clock(){let next=0;const timers=new Map();return {timers,schedule(fn,delay){const id=++next;timers.set(id,{fn,delay});return id;},cancel(id){timers.delete(id);}};}
test('manual refresh and visibility events cannot overlap a polling batch',async()=>{
  const c=clock();let finish,calls=0;const poll=createPolling(()=>{calls++;return new Promise(r=>finish=r);},{...c,hidden:()=>false});
  const first=poll.refresh();await poll.refresh();await poll.visibility();assert.equal(calls,1);finish();await first;
  assert.equal(c.timers.size,1);assert.equal([...c.timers.values()][0].delay,3000);
  const second=poll.refresh();assert.equal(c.timers.size,0);finish();await second;assert.equal(c.timers.size,1);poll.dispose();assert.equal(c.timers.size,0);
});
test('failed requests are reported and retry only after the normal delay',async()=>{
  const c=clock();const errors=[];let calls=0;const poll=createPolling(async()=>{calls++;throw Error('offline');},{...c,hidden:()=>false,onError:e=>errors.push(e.message)});
  await poll.refresh();assert.equal(calls,1);assert.deepEqual(errors,['offline']);assert.equal(c.timers.size,1);assert.equal([...c.timers.values()][0].delay,3000);poll.dispose();
});
test('disposing an in-flight batch aborts it and prevents timer resurrection',async()=>{
  const c=clock();let signal,finish;const poll=createPolling(s=>{signal=s;return new Promise(r=>finish=r);},{...c,hidden:()=>false});
  const pending=poll.refresh();poll.dispose();assert.equal(signal.aborted,true);finish();await pending;assert.equal(c.timers.size,0);await poll.refresh();assert.equal(c.timers.size,0);
});
test('hidden and cached pages pause polling; resume schedules only one batch',async()=>{
  const c=clock();let hidden=false,calls=0;const poll=createPolling(async()=>calls++,{...c,hidden:()=>hidden});
  await poll.refresh();hidden=true;await poll.visibility();assert.equal(c.timers.size,0);await poll.refresh();assert.equal(calls,1);
  hidden=false;poll.pause();await poll.refresh();assert.equal(calls,1);await poll.resume();assert.equal(calls,2);assert.equal(c.timers.size,1);poll.dispose();
});

// Minimal display DOM double: verifies node identity, not browser layout.
class DisplayNode{
  constructor(name,text=null){this.nodeName=name;this.nodeType=text===null?1:3;this.nodeValue=text;this.childNodes=[];this.attrs=new Map();this.scrollTop=0;}
  get attributes(){return [...this.attrs].map(([name,value])=>({name,value}));}
  hasAttribute(k){return this.attrs.has(k);}getAttribute(k){return this.attrs.get(k)??null;}
  setAttribute(k,v){this.attrs.set(k,v);}removeAttribute(k){this.attrs.delete(k);}
  append(...nodes){for(const n of nodes){n.parent=this;this.childNodes.push(n);}}
  remove(){this.parent.childNodes.splice(this.parent.childNodes.indexOf(this),1);}
  replaceWith(n){const i=this.parent.childNodes.indexOf(this);n.parent=this.parent;this.parent.childNodes[i]=n;}
  isEqualNode(n){return this.nodeName===n.nodeName&&this.nodeValue===n.nodeValue&&JSON.stringify(this.attributes)===JSON.stringify(n.attributes)&&this.childNodes.length===n.childNodes.length&&this.childNodes.every((c,i)=>c.isEqualNode(n.childNodes[i]));}
}
function display(value){const table=new DisplayNode('TABLE'),cell=new DisplayNode('TD');cell.append(new DisplayNode('#text',value));table.append(cell);return table;}
test('unchanged data and changed measurements preserve the table and focused cell nodes',()=>{
  const host=new DisplayNode('DIV'),table=display('IDLE');host.append(table);table.scrollTop=75;const focusedCell=table.childNodes[0];
  patchDisplay(host,display('IDLE'));assert.equal(host.childNodes[0],table);
  patchDisplay(host,display('RUNNING'));assert.equal(host.childNodes[0],table);assert.equal(table.childNodes[0],focusedCell);assert.equal(focusedCell.childNodes[0].nodeValue,'RUNNING');assert.equal(table.scrollTop,75);
});
test('display changes update status attributes and remove obsolete rows without remounting host',()=>{
  const host=new DisplayNode('DIV'),before=display('Unavailable');before.setAttribute('class','error');host.append(before,new DisplayNode('P'));
  const next=display('Ready');next.setAttribute('class','success');patchDisplay(host,next);
  assert.equal(host.childNodes.length,1);assert.equal(host.childNodes[0],before);assert.equal(before.getAttribute('class'),'success');
});
