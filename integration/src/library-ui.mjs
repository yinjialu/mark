// Rendered inside the existing thread tree with the host's native components.
const rootSelector='[data-response-annotation-conversation][data-response-annotation-target]';
const uuid=/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
let pendingJump=null;
const sha=async text=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),v=>v.toString(16).padStart(2,'0')).join('');
const changed=()=>window.dispatchEvent(new Event('codex-marks-changed'));
const kind=m=>({image:'图片',mermaid:'图表',table:'表格'}[m.anchor?.block_kind]||'文字');
const heading=m=>m.title||m.quote||kind(m);
const textOf=node=>{const r=document.createRange();r.selectNodeContents(node);return r.toString();};
function rangeAt(body,start,end){
  if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||end<=start)return null;
  const walker=document.createTreeWalker(body,NodeFilter.SHOW_TEXT),r=document.createRange();let node,offset=0,began=false;
  while((node=walker.nextNode())){const next=offset+node.length;if(!began&&start<next){r.setStart(node,start-offset);began=true;}if(began&&end<=next){r.setEnd(node,end-offset);return r;}offset=next;}return null;
}
export async function locateMark(mark,scroll){
  if(!scroll)return null;
  const a=mark.anchor||{},root=Array.from(scroll.querySelectorAll(rootSelector)).find(el=>el.getAttribute('data-response-annotation-conversation')===mark.thread_id&&el.getAttribute('data-response-annotation-target')===a.message_id);
  if(!root)return null;
  if(a.coordinate_space==='rendered_message_text'){
    const candidate=root.querySelector('[data-selected-text-overlay-target]');
    for(const body of candidate?[candidate,root]:[root]){
      const text=textOf(body);if(text.length>1000000||await sha(text)!==a.text_sha256)continue;
      if(!body.isConnected||textOf(body)!==text)continue;
      const range=rangeAt(body,a.dom_start_offset,a.dom_end_offset);if(range)return {root,range,element:range.startContainer.parentElement,precision:'selection'};
    }
  }
  if(a.coordinate_space==='rendered_block'){
    const selector=a.block_kind==='image'?'img':a.block_kind==='table'?'table':'[data-codex-mark-block-kind="mermaid"]';
    const element=root.querySelectorAll(selector)[a.block_index];
    if(element?.getAttribute('data-codex-mark-source-hash')===a.block_source_hash)return {root,element,precision:'block'};
  }
  // Exact message identity is still useful when a source snapshot no longer matches.
  return {root,element:root,precision:'message'};
}
function reveal(found,scroll){
  const rect=found.range?.getBoundingClientRect()||found.element.getBoundingClientRect(),box=scroll.getBoundingClientRect();
  scroll.scrollBy({top:rect.top-box.top-scroll.clientHeight*.3,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  if(found.range&&CSS.highlights&&window.Highlight){
    CSS.highlights.set('codex-mark-jump',new Highlight(found.range));setTimeout(()=>CSS.highlights.delete('codex-mark-jump'),2200);
  }else found.element.animate?.([{outline:'3px solid #d39620'},{outline:'3px solid transparent'}],{duration:1600});
}
export function createMarksUI(React,jsx,ui){
  const {Button,PageLayout,Input,Marker,Preview,Tooltip,Icon,createPortal}=ui;
  const h=(type,props,...children)=>jsx.jsx(type,{...props,...(children.length?{children:children.length===1?children[0]:children}:{})});
  const button=(text,onClick,props={})=>h(Button,{color:'ghost',size:'sm',onClick,...props},text);
  const call=async payload=>{const r=await window.codexMarks.library(payload);if(!r?.ok)throw Error(r?.error||'操作失败，请重试');return r;};
  function Detail({id,onChange,onJump}){
    const [data,setData]=React.useState(null),[error,setError]=React.useState(''),[busy,setBusy]=React.useState(false),[title,setTitle]=React.useState(''),[tags,setTags]=React.useState(''),[note,setNote]=React.useState(''),[notice,setNotice]=React.useState('');
    const previewRef=React.useRef(null),version=React.useRef(0);
    React.useEffect(()=>{let alive=true;version.current++;setData(null);setError('');setNotice('');call({op:'get',id}).then(r=>{if(!alive)return;setData(r);setTitle(r.mark.title||'');setTags((r.mark.tags||[]).join(', '));setNote(r.mark.note||'');}).catch(e=>alive&&setError(e.message));return()=>{alive=false;};},[id]);
    React.useEffect(()=>{const mark=previewRef.current?.querySelector('mark');if(mark)previewRef.current.scrollTop=Math.max(0,mark.offsetTop-previewRef.current.offsetTop-100);},[data]);
    async function mutate(op){
      const revision=version.current;
      setBusy(true);setError('');
      try{await call(op==='update'?{op,id,title,note,tags:tags.split(/[,，]/).map(t=>t.trim()).filter(Boolean)}:{op,id});changed();onChange();if(revision===version.current){setNotice(op==='update'?'已保存':op==='delete'?'已移到回收站':'已恢复');if(op!=='update')setData(null);}}
      catch(e){if(revision===version.current)setError(e.message);}finally{if(revision===version.current)setBusy(false);}
    }
    if(!data)return h('div',{className:'mark-detail-empty',role:'status'},error||notice||'正在读取收藏…');
    const {mark,context}=data,c=context||{},text=c.text||mark.quote,chars=Array.from(text),exact=c.status==='snapshot_verified';
    const dark=getComputedStyle(document.documentElement).colorScheme.includes('dark');
    const snapshot=(c.html||'')+`<style>body{background:${dark?'#202020':'#fff'};color:${dark?'#ececec':'#222'};font:14px/1.6 system-ui;margin:16px}th{background:${dark?'#303030':'#f3f3f3'}}td,th{border-color:${dark?'#484848':'#ccc'}}</style>`;
    const preview=c.status==='block_verified'?h('iframe',{title:kind(mark)+'收藏快照',sandbox:'',referrerPolicy:'no-referrer',srcDoc:snapshot,style:{width:'100%',height:'100%',border:0}}):h('div',{ref:previewRef,className:'mark-text-preview'},exact?[chars.slice(0,c.start_offset).join(''),h('mark',{key:'saved'},chars.slice(c.start_offset,c.end_offset).join('')),chars.slice(c.end_offset).join('')]:text);
    return h('div',{className:'mark-detail'},
      h('div',{className:'mark-detail-heading'},h('div',{className:'text-tertiary text-xs'},kind(mark)+' · '+(mark.thread_title||'来源任务')),h('div',{className:'font-medium'},mark.anchor?.turn_title||heading(mark))),
      h('div',{className:'mark-preview'},preview),
      h('div',{className:'mark-detail-actions'},button('定位原文',()=>onJump(mark),{disabled:!mark.thread_id||busy}),button('复制原文',()=>navigator.clipboard.writeText(mark.quote).then(()=>setNotice('已复制')).catch(()=>setError('复制失败，请重试')))),
      h('details',{className:'mark-edit'},h('summary',{},'标题、标签与备注'),
        h('label',{},'标题',h(Input,{'aria-label':'标题',value:title,maxLength:200,autoFocus:false,onChange:e=>setTitle(e.target.value),className:'mark-input'})),
        h('label',{},'标签',h(Input,{'aria-label':'标签',value:tags,autoFocus:false,onChange:e=>setTags(e.target.value),placeholder:'用逗号分隔',className:'mark-input'})),
        h('label',{},'备注',h('textarea',{'aria-label':'备注',value:note,maxLength:10000,onChange:e=>setNote(e.target.value),className:'mark-input',rows:3})),
        button('保存修改',()=>mutate('update'),{disabled:busy||!!mark.deleted_at})),
      h('div',{className:'mark-detail-actions'},button(mark.deleted_at?'恢复收藏':'移到回收站',()=>mutate(mark.deleted_at?'restore':'delete'),{disabled:busy}),h('span',{className:'text-tertiary text-xs',role:'status'},error||notice||new Date(mark.created_at).toLocaleDateString())));
  }
  function Library({threadId,onJump,selected,onSelect,revision,query}){
    const [scope,setScope]=React.useState('all'),[rows,setRows]=React.useState([]),[total,setTotal]=React.useState(0),[offset,setOffset]=React.useState(0),[busy,setBusy]=React.useState(true),[error,setError]=React.useState(''),[localRev,setLocalRev]=React.useState(0);
    React.useEffect(()=>{let alive=true;setBusy(true);setError('');setRows([]);const timer=setTimeout(()=>{call({op:'search',query,thread_id:scope==='task'?threadId:'',deleted:scope==='trash',offset,limit:50}).then(r=>{if(!alive)return;setRows(r.marks);setTotal(r.total);}).catch(e=>alive&&setError(e.message)).finally(()=>alive&&setBusy(false));},180);return()=>{alive=false;clearTimeout(timer);};},[query,scope,threadId,offset,revision,localRev]);
    React.useEffect(()=>{setOffset(0);},[query]);
    return h('div',{className:'mark-library-grid'},h('section',{className:'mark-library-list'},
      h('div',{className:'mark-library-filters'},...['all','task','trash'].map(s=>button({all:'全部',task:'当前任务',trash:'回收站'}[s],()=>{setScope(s);setOffset(0);onSelect(null);},{key:s,color:scope===s?'ghostActive':'ghost',disabled:s==='task'&&!threadId,'aria-pressed':scope===s}))),
      h('div',{className:'text-tertiary text-xs',role:'status'},busy?'正在读取…':error||`${total} 条收藏`),
      h('div',{className:'mark-library-rows'},...rows.map(m=>h('button',{key:m.id,type:'button',className:'mark-library-row','aria-pressed':selected===m.id,onClick:()=>onSelect(m.id)},h('div',{className:'mark-row-title'},heading(m)),h('div',{className:'mark-row-excerpt'},m.quote),h('div',{className:'text-tertiary text-xs'},kind(m)+' · '+(m.thread_title||new Date(m.created_at).toLocaleDateString())))),!busy&&!error&&!rows.length?h('p',{className:'text-tertiary'},query?'没有找到匹配的收藏':'还没有收藏。在原文上点击 mark 即可保存。'):null),
      h('div',{className:'mark-detail-actions'},button('上一页',()=>setOffset(Math.max(0,offset-50)),{disabled:busy||offset===0}),button('下一页',()=>setOffset(offset+50),{disabled:busy||offset+50>=total}))),
      selected?h(Detail,{key:selected,id:selected,onChange:()=>{setLocalRev(v=>v+1);},onJump}):h('div',{className:'mark-detail-empty'},'选择一条收藏，查看内容和来源'));
  }
  function Page({navigate,sourceThreadId='',selectedId=null,initialNotice=''}){
    const [selected,setSelected]=React.useState(selectedId),[query,setQuery]=React.useState(''),[revision,setRevision]=React.useState(0);
    const threadId=uuid.test(sourceThreadId)?sourceThreadId:'';
    React.useEffect(()=>{setSelected(selectedId);},[selectedId]);
    React.useEffect(()=>{const update=()=>setRevision(v=>v+1);window.addEventListener('codex-marks-changed',update);window.addEventListener('focus',update);return()=>{window.removeEventListener('codex-marks-changed',update);window.removeEventListener('focus',update);};},[]);
    function jump(mark){if(!uuid.test(mark.thread_id||''))return;pendingJump=mark;navigate('/local/'+mark.thread_id);}
    return h('main',{className:'mark-page','data-codex-mark-page':'','aria-label':'mark 收藏库'},h('style',{},styles),
      h(PageLayout,{title:'mark',subtitle:'收藏与原文',headerVariant:'inset',contentWidth:'extraWide',contentClassName:'mark-page-content',animateContentLayout:false,
        search:{id:'mark-page-search',label:'搜索收藏',placeholder:'搜索原文、任务、标签或备注',searchQuery:query,onSearchQueryChange:value=>setQuery(value.slice(0,500)),autoFocus:false}},
        initialNotice?h('p',{role:'status',className:'text-secondary text-sm'},initialNotice):null,
        window.codexMarks?.library?h(Library,{threadId,onJump:jump,selected,onSelect:setSelected,revision,query}):h('p',{role:'status'},'mark 暂不可用，请通过 mark 启动器打开适配后的客户端。')));
  }
  function Marks({items,onRevealItem,getScrollElement,navigate,pathname}){
    const [marks,setMarks]=React.useState([]),[total,setTotal]=React.useState(0),[revision,setRevision]=React.useState(0),[threadId,setThreadId]=React.useState(''),[container,setContainer]=React.useState(null),[hover,setHover]=React.useState(null),[active,setActive]=React.useState(null),[notice,setNotice]=React.useState('');
    const ref=React.useRef({});ref.current={items,onRevealItem,getScrollElement,navigate,threadId};
    const disposed=React.useRef(false),jumpSequence=React.useRef(0);
    React.useEffect(()=>{disposed.current=false;return()=>{disposed.current=true;jumpSequence.current++;};},[]);
    React.useEffect(()=>{
      const scroll=getScrollElement();setContainer(scroll?.parentElement||null);
      const pathId=pathname.match(/\/local\/([0-9a-f-]{36})(?:\/|$)/i)?.[1];
      const id=pathId||scroll?.querySelector(rootSelector)?.getAttribute('data-response-annotation-conversation')||'';
      setThreadId(uuid.test(id)?id:'');setHover(null);setMarks([]);setTotal(0);setNotice('');
    },[pathname,getScrollElement]);
    React.useEffect(()=>{const update=()=>setRevision(v=>v+1);window.addEventListener('codex-marks-changed',update);window.addEventListener('focus',update);const timer=setInterval(()=>{if(!document.hidden)update();},10000);return()=>{window.removeEventListener('codex-marks-changed',update);window.removeEventListener('focus',update);clearInterval(timer);};},[]);
    React.useEffect(()=>{
      if(!threadId)return;let alive=true;
      (async()=>{const found=[];let offset=0,count=0;do{const r=await call({op:'search',query:'',thread_id:threadId,deleted:false,offset,limit:100});if(!alive)return;count=r.total;found.push(...r.marks);offset+=100;}while(offset<count&&offset<1000);
        const order=new Map(items.map((item,i)=>[item.turnKey,i]));
        const rank=m=>{const t=m.anchor?.turn_id;for(const [key,index] of order)if(key===t||key.endsWith(':'+t))return index;return 100000;};
        found.sort((a,b)=>rank(a)-rank(b)||a.created_at.localeCompare(b.created_at)||(a.anchor?.dom_start_offset||0)-(b.anchor?.dom_start_offset||0));
        if(alive){setMarks(found);setTotal(count);setNotice('');}
      })().catch(e=>alive&&setNotice(e.message));return()=>{alive=false;};
    },[threadId,revision,items]);
    React.useEffect(()=>{
      const scroll=getScrollElement();if(!scroll)return;let frame;
      const update=()=>{if(frame)return;frame=requestAnimationFrame(()=>{frame=null;const center=scroll.getBoundingClientRect().top+scroll.clientHeight*.35;let best=null,distance=Infinity;for(const root of scroll.querySelectorAll(rootSelector)){const candidates=marks.filter(m=>m.anchor?.message_id===root.getAttribute('data-response-annotation-target')&&m.thread_id===root.getAttribute('data-response-annotation-conversation'));if(!candidates.length)continue;const d=Math.abs(root.getBoundingClientRect().top-center);if(d<distance){best=candidates[0].id;distance=d;}}setActive(best);});};
      scroll.addEventListener('scroll',update,{passive:true});const observer=new MutationObserver(update);observer.observe(scroll,{childList:true,subtree:true});update();return()=>{scroll.removeEventListener('scroll',update);observer.disconnect();cancelAnimationFrame(frame);};
    },[getScrollElement,marks]);
    async function jump(mark){
      if(!uuid.test(mark.thread_id||'')){setNotice('这条收藏没有来源任务');return;}
      if(mark.thread_id!==ref.current.threadId){pendingJump=mark;navigate('/local/'+mark.thread_id);return;}
      const seq=++jumpSequence.current;setNotice('正在定位…');
      const current=()=>!disposed.current&&seq===jumpSequence.current&&ref.current.threadId===mark.thread_id;
      const scroll=getScrollElement();let found=await locateMark(mark,scroll);
      if(!current())return;
      if(!found){
        const turn=mark.anchor?.turn_id;
        const item=turn&&ref.current.items.find(i=>i.turnKey===turn||i.turnKey?.endsWith(':'+turn));
        if(item&&ref.current.onRevealItem){try{await ref.current.onRevealItem(item);}catch{}}
        for(let i=0;i<15&&current();i++){found=await locateMark(mark,getScrollElement());if(found)break;await new Promise(r=>setTimeout(r,100));}
        if(!found&&item&&current()){
          const unit=Array.from(getScrollElement()?.querySelectorAll('[data-content-search-unit-key]')||[]).find(el=>el.getAttribute('data-content-search-unit-key')===item.id);
          if(unit)found={element:unit,precision:'turn'};
        }
      }
      if(!current())return;
      if(found){setHover(null);setActive(mark.id);requestAnimationFrame(()=>reveal(found,getScrollElement()));setNotice(found.precision==='message'?'已定位到对应消息':found.precision==='turn'?'已定位到所属轮次':'');}
      else{navigate('/mark',{state:{markSourceThreadId:threadId,markSelectedId:mark.id,markNotice:'原文暂未加载，已打开保存的快照'}});}
    }
    React.useEffect(()=>{if(pendingJump?.thread_id===threadId&&items.length){const m=pendingJump;pendingJump=null;void jump(m);}},[threadId,items]);
    if(!window.codexMarks?.library||!container)return null;
    const markButtons=marks.map(m=>h('button',{key:m.id,type:'button','data-codex-mark-nav-id':m.id,'aria-label':'定位 mark：'+heading(m).slice(0,100),'aria-current':active===m.id?'true':undefined,'aria-describedby':hover?.mark.id===m.id?'codex-mark-preview':undefined,className:'mark-rail-line',onPointerEnter:e=>setHover({mark:m,element:e.currentTarget}),onFocus:e=>setHover({mark:m,element:e.currentTarget}),onBlur:()=>setHover(null),onClick:()=>void jump(m)},h(Marker,{bookmarked:false})));
    const preview=hover?h(Preview,{},h('div',{className:'font-medium truncate'},hover.mark.anchor?.turn_title||heading(hover.mark)),h('div',{className:'mark-hover-excerpt'},hover.mark.quote),h('div',{className:'text-tertiary text-xs'},kind(hover.mark)+' · 点击定位')):null;
    const rail=h('nav',{'aria-label':'mark 导航','data-codex-mark-rail':'',className:'mark-rail'},
      h(Tooltip,{open:!!hover,onOpenChange:value=>{if(!value)setHover(null);},positioningElement:hover?.element,side:'left',sideOffset:4,align:'center',variant:'floating-navigation-rail',tooltipContent:preview,tooltipId:'codex-mark-preview',tooltipMaxWidth:'min(20rem, calc(100vw - 16px))'},h('div',{'data-floating-navigation-rail-list':true,className:'mark-rail-lines',onPointerLeave:()=>setHover(null)},...markButtons)),
      total>marks.length?button('+',()=>navigate('/mark',{state:{markSourceThreadId:threadId}}),{'aria-label':'在收藏库查看其余标记'}):null);
    return h(jsx.Fragment,{},h('style',{},styles),createPortal(rail,container),
      notice?createPortal(h('div',{className:'mark-nav-notice',role:'status'},notice),container):null);
  }
  // A failed optional panel must not take down the host's thread view.
  return class SafeMarks extends React.Component {
    constructor(props){super(props);this.state={failed:false};}
    static getDerivedStateFromError(){return {failed:true};}
    render(){return this.state.failed?h('div',{style:this.props.page?{padding:24}:{position:'absolute',right:12,top:80,zIndex:20}},button('重试 mark',()=>this.setState({failed:false}))):h(this.props.page?Page:Marks,this.props);}
  };
}
const styles=`
::highlight(codex-mark-jump){background-color:#d3962040;color:inherit}
.mark-rail{position:absolute;right:12px;top:50%;transform:translateY(-50%);z-index:20;display:flex;flex-direction:column;align-items:center;gap:8px;color:var(--color-text-tertiary,var(--color-text));-webkit-app-region:no-drag}
.mark-rail-lines{max-height:60vh;overflow-y:auto;scrollbar-width:none;display:flex;flex-direction:column;align-items:flex-end}
.mark-rail-line{height:calc(var(--spacing,4px)*2.5);min-height:calc(var(--spacing,4px)*2.5);width:36px;display:flex;align-items:center;justify-content:flex-end;cursor:pointer;border:0;background:transparent;outline-offset:2px}
.mark-rail-line [class*='_Marker_']{margin-left:auto;transform:scaleX(-1)}
.mark-hover-excerpt{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;margin:6px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.mark-nav-notice{position:absolute;right:58px;bottom:90px;z-index:30;background:var(--color-surface-elevated-secondary);color:var(--color-text);border-radius:8px;padding:8px 12px;font-size:12px}
.mark-page{display:flex;flex:1;flex-direction:column;height:100%;min-height:0;min-width:0;overflow:hidden;color:var(--color-text);background:var(--color-surface)}
.mark-page-content{min-width:0}.mark-page .mark-library-grid{min-height:440px;align-items:start;gap:28px}.mark-page .mark-library-list{min-width:0}.mark-page .mark-detail{min-width:0;position:sticky;top:88px;height:calc(100dvh - 240px);min-height:340px}.mark-page .mark-detail-empty{min-height:440px}.mark-page .mark-preview{min-height:180px}
.mark-library-grid{display:grid;grid-template-columns:minmax(220px,32%) minmax(0,1fr);gap:20px;flex:1;min-height:0}
.mark-library-list{display:flex;flex-direction:column;gap:12px;min-height:0}.mark-input{width:100%;border:1px solid var(--color-border)!important;border-radius:8px!important;padding:8px 10px!important;background:var(--color-surface)!important;color:var(--color-text);font:inherit;box-sizing:border-box;outline-offset:2px}
.mark-library-filters,.mark-detail-actions{display:flex;align-items:center;flex-wrap:wrap;gap:6px;flex:none}.mark-library-rows{flex:1;min-height:0;overflow:auto}
.mark-library-row{display:block;width:100%;text-align:left;border:0;border-radius:10px;background:transparent;color:inherit;padding:12px;cursor:pointer;margin-bottom:4px}.mark-library-row:hover{background:color-mix(in srgb,var(--color-text) 5%,transparent)}.mark-library-row[aria-pressed=true]{background:color-mix(in srgb,var(--color-text) 9%,transparent)}
.mark-row-title{font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mark-row-excerpt{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:13px;line-height:1.5;margin:6px 0;opacity:.7;overflow-wrap:anywhere}
.mark-detail{display:flex;flex-direction:column;gap:12px;min-height:0;overflow:auto}.mark-detail-heading{overflow-wrap:anywhere}.mark-preview{min-height:180px;flex:1;overflow:hidden;border:1px solid var(--color-border);border-radius:10px;background:var(--color-surface)}
.mark-text-preview{height:100%;overflow:auto;padding:18px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;box-sizing:border-box}.mark-text-preview mark{background:#d3962030;color:inherit;text-decoration:underline;text-decoration-color:#d39620;text-underline-offset:3px;border-radius:2px}
.mark-detail-empty{display:flex;align-items:center;justify-content:center;color:var(--color-text-tertiary);font-size:14px;padding:24px}.mark-edit{flex:none;font-size:13px}.mark-edit summary{cursor:pointer}.mark-edit label{display:block;margin:10px 0}.mark-edit input,.mark-edit textarea{margin-top:4px}
@media(max-width:700px){.mark-library-grid{grid-template-columns:minmax(160px,35%) minmax(0,1fr);gap:10px}.mark-rail{right:4px}}
`;
