const entries = new Set();
const rootSelector = '[data-response-annotation-conversation][data-response-annotation-target]';
let timer, interval, observer, busy = false, again = false, force = false, cache = [], cacheScope = '', lastRead = 0;
const digest = async text => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), b => b.toString(16).padStart(2, '0')).join('');
const identity = item => JSON.stringify([item.thread_id, item.message_id]);

function schedule(refresh = false) {
  force ||= refresh; again = true;
  if (timer === undefined) timer = setTimeout(() => { timer = undefined; void update(); }, 180);
}
async function update() {
  if (busy) return;
  busy = true; again = false;
  try {
    const active = [];
    for (const entry of entries) entry.element()?.setAttribute('data-codex-mark-block-kind',entry.kind);
    for (const entry of entries) {
      const element = entry.element();
      const root = element?.closest(rootSelector);
      if (!root || !element.isConnected) { entry.meta = null; entry.update('unavailable'); continue; }
      element.setAttribute('data-codex-mark-block-kind', entry.kind);
      entry.node = element;
      const thread_id = root.getAttribute('data-response-annotation-conversation'), message_id = root.getAttribute('data-response-annotation-target');
      if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(thread_id) || !message_id) continue;
      const source = entry.source;
      if (typeof source !== 'string' || !source || (entry.kind !== 'image' && source.length > 100000)) continue;
      const source_hash = entry.lastSource === source ? entry.hash : await digest(source);
      entry.lastSource = source; entry.hash = source_hash;
      element.setAttribute('data-codex-mark-source-hash',source_hash);
      if (!entries.has(entry) || !element.isConnected) continue;
      // Include offscreen blocks whose action controls have not mounted yet.
      const blockSelector = entry.kind === 'image' ? 'img' : entry.kind === 'table' ? 'table' : '[data-codex-mark-block-kind="mermaid"]';
      const block_index = Array.from(root.querySelectorAll(blockSelector)).indexOf(element);
      entry.meta = {kind: entry.kind, thread_id, message_id, block_index, source_hash,
        source_text: entry.kind === 'image' ? '' : source, caption: (entry.caption || {image:'图片',mermaid:'Mermaid 图表',table:'表格'}[entry.kind]).slice(0,200)};
      entry.update('available');
      active.push(entry);
    }
    const messages = Array.from(new Map(active.map(entry => [identity(entry.meta), {thread_id:entry.meta.thread_id,message_id:entry.meta.message_id}])).values());
    messages.sort((a,b) => identity(a).localeCompare(identity(b)));
    const scope = JSON.stringify(messages);
    if (force || scope !== cacheScope || Date.now() - lastRead >= 10000) {
      force = false;
      const found = [];
      for (let i=0;i<messages.length;i+=100) {
        const result = await window.codexMarks.listUnderlines(messages.slice(i,i+100));
        if (!result?.ok) throw new Error('Position read failed');
        found.push(...result.marks);
      }
      cache = found; cacheScope = scope; lastRead = Date.now();
    }
    for (const entry of active) {
      if (!entries.has(entry) || !entry.node.isConnected) continue;
      const saved = cache.some(mark => identity(mark) === identity(entry.meta) && mark.block_kind === entry.kind
        && mark.block_index === entry.meta.block_index && mark.block_source_hash === entry.meta.source_hash);
      entry.node.toggleAttribute('data-codex-mark-saved-block', saved);
      entry.update(saved ? 'saved' : 'ready');
    }
  } catch (_) { lastRead = 0; }
  finally { busy = false; if (again) schedule(); }
}
function mount(entry) {
  entries.add(entry);
  if (!observer) {
    const style = new CSSStyleSheet();
    style.replaceSync('[data-codex-mark-saved-block]{outline:2px solid #d39620;outline-offset:3px}table[data-codex-mark-saved-block]{outline-offset:-2px;padding:8px 12px}');
    document.adoptedStyleSheets = [...document.adoptedStyleSheets,style];
    observer = new MutationObserver(records => {
      if (records.some(record => !record.target.parentElement?.closest('[data-codex-mark-button]'))) schedule();
    });
    observer.observe(document.documentElement,{childList:true,subtree:true,characterData:true});
    window.addEventListener('focus',()=>schedule(true));
    window.addEventListener('codex-marks-changed',()=>schedule(true));
    interval = setInterval(()=>{if(entries.size && !document.hidden) schedule(true);},10000);
  }
  schedule(true);
  return () => {entries.delete(entry);entry.node?.removeAttribute('data-codex-mark-saved-block');schedule(true);};
}
async function imagePNG(element, loader) {
  let bitmap;
  if (loader) {
    const src = await loader();
    if (typeof src !== 'string' || !src) throw new Error('图片尚未准备好');
    const response = await fetch(src, {credentials:'omit',referrerPolicy:'no-referrer'});
    if (!response.ok) throw new Error('图片暂时无法读取');
    const blob = await response.blob();
    if (blob.size > 24000000) throw new Error('图片过大，暂不能标记');
    bitmap = await createImageBitmap(blob);
  } else {
    if (!element.complete || !element.naturalWidth) throw new Error('请等图片加载完成再标记');
    bitmap = await createImageBitmap(element);
  }
  try {
    if (bitmap.width * bitmap.height > 40000000 || Math.max(bitmap.width,bitmap.height)>20000) throw new Error('图片尺寸过大');
    const canvas = document.createElement('canvas'); canvas.width=bitmap.width;canvas.height=bitmap.height;
    canvas.getContext('2d').drawImage(bitmap,0,0);
    return canvas.toDataURL('image/png');
  } finally {bitmap.close();}
}
export function renderMarkButton(React, jsx, Button, props) {
  const ref = React.useRef(null), stateRef = React.useRef('loading');
  const [state,setState] = React.useState('loading'), [error,setError] = React.useState('');
  const entryRef = React.useRef(null);
  React.useEffect(()=>{
    const entry = {kind:props.kind,source:props.source,caption:props.caption,
      element:()=>props.getElement(ref.current),update(value){if(value==='available'){if(!['loading','unavailable'].includes(stateRef.current))return;value='ready';}if(stateRef.current!=='saving'){stateRef.current=value;setState(value);}}};
    entryRef.current=entry;
    return mount(entry);
  },[props.kind,props.source]);
  if (!window.codexMarks?.beginBlockMark) return null;
  const click = async event => {
    event.stopPropagation();event.preventDefault();
    const entry=entryRef.current;
    if (!entry?.meta || stateRef.current==='saving') return;
    const selectedSource={...entry.meta}, selectedElement=entry.element(), imageSrc=selectedElement?.currentSrc;
    const existing=cache.find(mark=>identity(mark)===identity(selectedSource)&&mark.block_kind===entry.kind&&mark.block_index===selectedSource.block_index&&mark.block_source_hash===selectedSource.source_hash);
    // Only saving needs a ticket and asset capture; cancellation uses the existing mark ID.
    const ticketPromise=existing?null:window.codexMarks.beginBlockMark(selectedSource);
    stateRef.current='saving';setState('saving');setError('');
    try {
      if(existing){
        const result=await window.codexMarks.library({op:'delete',id:existing.mark_id});
        if(!result?.ok)throw new Error(result?.error||'取消失败，请重试');
        cache=cache.filter(mark=>mark.mark_id!==existing.mark_id);
        selectedElement?.removeAttribute('data-codex-mark-saved-block');
        stateRef.current='ready';setState('ready');schedule(true);
        window.dispatchEvent(new Event('codex-marks-changed'));
        return;
      }
      const ticket=await ticketPromise;
      if(!ticket?.ok) throw new Error('请重新点击 mark');
      const element=entry.element();
      if(!element?.isConnected) throw new Error('原文位置已变化，请重试');
      let content;
      if(props.kind==='mermaid') content=props.serialize(element);
      else if(props.kind==='table') content=JSON.stringify({rows:Array.from(element.rows,row=>Array.from(row.cells,cell=>({text:cell.innerText,header:cell.tagName==='TH',rowspan:cell.rowSpan||1,colspan:cell.colSpan||1})))});
      else content=await imagePNG(element,props.loadImage);
      if(element!==selectedElement || !element.isConnected || entry.meta.source_hash!==selectedSource.source_hash
          || identity(entry.meta)!==identity(selectedSource) || element.currentSrc!==imageSrc) throw new Error('原文位置已变化，请重试');
      const result=await window.codexMarks.saveBlock(ticket.token,content);
      if(!result?.ok) throw new Error(result?.error||'保存失败，请重试');
      cache.push({mark_id:result.mark_id,thread_id:selectedSource.thread_id,message_id:selectedSource.message_id,block_kind:entry.kind,block_index:selectedSource.block_index,block_source_hash:selectedSource.source_hash});
      element.setAttribute('data-codex-mark-saved-block','');
      stateRef.current='saved';setState('saved');schedule(true);
      window.dispatchEvent(new Event('codex-marks-changed'));
    } catch(err) {const restored=existing?'saved':'error';stateRef.current=restored;setState(restored);setError(err?.message||'操作失败，请重试');}
  };
  const saved=state==='saved', title=error || (saved?'取消 mark':state==='saving'?'正在 mark…':state==='loading'?'正在读取标记位置':state==='unavailable'?'无法确认来源位置':'mark');
  return jsx.jsx('span',{ref,'data-codex-mark-button':'','data-markdown-copy':'exclude',style:{display:'inline-flex'},title,
    children:jsx.jsx(Button,{type:'button',color:'ghost',size:'icon',onClick:click,disabled:state==='saving'||state==='loading'||state==='unavailable',
      'aria-label':title,'aria-pressed':saved,title,style:{width:28,height:28,padding:5,border:0,borderRadius:6,background:typeof Button==='string'?'transparent':undefined,color:saved?'#d39620':'inherit',cursor:'pointer'},
      children:jsx.jsx('svg',{viewBox:'0 0 24 24',width:16,height:16,fill:saved?'currentColor':'none',stroke:'currentColor',strokeWidth:1.6,'aria-hidden':true,
        children:jsx.jsx('path',{d:'M6 3.5h12v17l-6-4-6 4z'})})})});
}
