const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const template=fs.readFileSync(path.join(__dirname,'../integration/src/toolbar-button.js'),'utf8');
const source={thread_id:'11111111-2222-3333-4444-555555555555',message_id:'message',text:'same same',start_utf16:0,end_utf16:4};
const hash=require('node:crypto').createHash('sha256').update(source.text).digest('hex');
function setup(generation=1){
 const slots=[],effects=[],records=[],calls=[];let index=0,props={selectedText:'same',selectionSource:source},fail=false;
 const win=new EventTarget();win.Event=Event;win.codexMarks={
  async listUnderlines(){return {ok:true,marks:records.map(r=>({...r}))};},
  async saveSelectedText(text,s){calls.push('save');const mark_id=String(calls.length);records.push({mark_id,...s,start_utf16:s.start_utf16,end_utf16:s.end_utf16,text_sha256:hash});return {ok:true,mark_id};},
  async library({op,id}){calls.push(op);if(fail)return {ok:false,error:'cancel failed'};const i=records.findIndex(r=>r.mark_id===id);if(i>=0)records.splice(i,1);return {ok:true};}
 };
 const R={useState(initial){const i=index++;if(!(i in slots))slots[i]=initial;return [slots[i],v=>slots[i]=v];},useRef(initial){const i=index++;return slots[i]??(slots[i]={current:initial});},useEffect(fn,deps){const i=index++,old=slots[i];if(!old||deps.some((v,n)=>v!==old.deps[n])){old?.cleanup?.();slots[i]={deps};effects.push(()=>slots[i].cleanup=fn());}}};
 const context={window:win,Event,crypto:webcrypto,TextEncoder,Uint8Array};
 const names=generation===1?['xlr','g3','zH']:['f4n','q3','Gh'];context[names[0]]=R;context[names[1]]={jsx:(type,p)=>p};context[names[2]]='Button';
 const code=template.replaceAll('__MARK_REACT__',names[0]).replaceAll('__MARK_JSX__',names[1]).replaceAll('__MARK_BUTTON__',names[2]);
 vm.createContext(context);vm.runInContext(code,context);
 const render=p=>{if(p)props=p;index=0;const v=context.__codexMarksNativeButton(props);for(const fn of effects.splice(0))fn();return v;};
 return {render,records,calls,setFail:v=>fail=v,win};
}
async function ready(h){for(let i=0;i<100;i++){await new Promise(r=>setTimeout(r,2));const v=h.render();if(!v.disabled)return v;}throw Error('not ready');}
test('text mark toggles off and on, including a reopened exact selection',async()=>{
 const h=setup();h.render();let v=await ready(h);await v.onClick();v=h.render();assert.equal(v['aria-pressed'],true);assert.equal(v.disabled,false);
 await v.onClick();assert.equal(h.records.length,0);assert.equal(h.render()['aria-pressed'],false);
 await h.render().onClick();assert.equal(h.records.length,1);
 h.render({selectedText:'same',selectionSource:{...source,start_utf16:5,end_utf16:9}});v=await ready(h);assert.equal(v['aria-pressed'],false,'same words at another position are not the same mark');
 h.render({selectedText:'same',selectionSource:source});v=await ready(h);assert.equal(v['aria-pressed'],true);await v.onClick();assert.equal(h.records.length,0);
});
test('double click does not save twice and cancellation errors can be retried',async()=>{
 const h=setup();h.render();const v=await ready(h);await Promise.all([v.onClick(),v.onClick()]);assert.equal(h.records.length,1);assert.equal(h.calls.filter(c=>c==='save').length,1);
 h.setFail(true);await h.render().onClick();assert.equal(h.records.length,1);assert.equal(h.render().title,'cancel failed');
 h.setFail(false);await h.render().onClick();assert.equal(h.records.length,0);
});
test('new client aliases survive repeated native toolbar mounts',async()=>{
 const h=setup(2);h.render();let v=await ready(h);assert.equal(v.disabled,false);await v.onClick();
 for(let i=0;i<5;i++)v=h.render();assert.equal(v['aria-pressed'],true);assert.equal(h.records.length,1);
});
