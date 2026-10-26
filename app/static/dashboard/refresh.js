// Patch display-only regions without replacing their scroll/focus-owning nodes.
// Forms and selected values remain owned by their views, not by this function.
export function patchDisplay(parent, ...children) {
  const current=[...parent.childNodes];
  children.forEach((next,index)=>{
    const old=current[index];
    if(!old){parent.append(next);return;}
    if(old.isEqualNode(next))return;
    if(old.nodeType!==next.nodeType || old.nodeName!==next.nodeName){old.replaceWith(next);return;}
    if(old.nodeType===3){old.nodeValue=next.nodeValue;return;}
    for(const attr of [...old.attributes])if(!next.hasAttribute(attr.name))old.removeAttribute(attr.name);
    for(const attr of [...next.attributes])if(old.getAttribute(attr.name)!==attr.value)old.setAttribute(attr.name,attr.value);
    patchDisplay(old,...next.childNodes);
  });
  current.slice(children.length).forEach(node=>node.remove());
}

// One serialized request batch and one timer, including manual/visibility refresh.
export function createPolling(run, {hidden=()=>document.hidden, delay=3000,
  schedule=setTimeout, cancel=clearTimeout, onError=()=>{}}={}) {
  let timer=null, controller=null, disposed=false, paused=false;
  function clear(){if(timer!==null)cancel(timer);timer=null;}
  async function refresh(){
    if(disposed||paused||hidden()||controller)return;
    clear();const request=new AbortController();controller=request;
    try{await run(request.signal);}catch(error){if(!request.signal.aborted)onError(error);}
    finally{controller=null;if(!disposed&&!paused&&!hidden())timer=schedule(refresh,delay);}
  }
  return {refresh,visibility(){clear();if(!hidden())return refresh();},
    pause(){paused=true;clear();controller?.abort();},resume(){paused=false;return refresh();},
    dispose(){disposed=true;clear();controller?.abort();}};
}
