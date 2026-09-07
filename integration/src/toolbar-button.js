// Runs as a React child of Codex's existing selectedTextOverlay component.
async function __codexMarksFindSelection(source) {
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(source.text))), b => b.toString(16).padStart(2, '0')).join('');
  const result = await window.codexMarks.listUnderlines([{thread_id:source.thread_id,message_id:source.message_id}]);
  if (!result?.ok) throw new Error('无法读取标记状态，请重试');
  return result.marks.find(m => !m.block_kind && m.thread_id === source.thread_id && m.message_id === source.message_id
    && m.text_sha256 === hash && m.start_utf16 === source.start_utf16 && m.end_utf16 === source.end_utf16);
}
function __codexMarksNativeButton({selectedText, selectionSource}) {
  const [state,setState] = xlr.useState('loading'), [failure,setFailure] = xlr.useState('');
  const busy = xlr.useRef(false), version = xlr.useRef(0), reads = xlr.useRef(0);
  xlr.useEffect(() => {
    const revision=++version.current;let alive=true;
    busy.current=false;setState('loading');setFailure('');
    const refresh=async()=>{
      const read=++reads.current;
      if(!selectionSource){setState('ready');return;}
      try{const saved=await __codexMarksFindSelection(selectionSource);if(alive&&read===reads.current&&!busy.current){setState(saved?'saved':'ready');setFailure('');}}
      catch(e){if(alive&&read===reads.current&&!busy.current){setState('error');setFailure(e.message);}}
    };
    void refresh();window.addEventListener('codex-marks-changed',refresh);window.addEventListener('focus',refresh);
    return()=>{alive=false;if(version.current===revision)version.current++;window.removeEventListener('codex-marks-changed',refresh);window.removeEventListener('focus',refresh);};
  },[selectedText,selectionSource?.thread_id,selectionSource?.message_id,selectionSource?.text,selectionSource?.start_utf16,selectionSource?.end_utf16]);
  if(!window.codexMarks||typeof selectedText!=='string'||!selectedText.trim())return null;
  const toggle=async()=>{
    if(busy.current||state==='loading')return;
    busy.current=true;reads.current++;const revision=version.current;setState('saving');setFailure('');
    try{
      if(!selectionSource)throw new Error('无法读取这处原文的位置，请重新划词');
      const saved=await __codexMarksFindSelection(selectionSource);
      if(version.current!==revision)return;
      const result=saved?await window.codexMarks.library({op:'delete',id:saved.mark_id}):await window.codexMarks.saveSelectedText(selectedText,selectionSource);
      if(!result?.ok)throw new Error(result?.error||'操作失败，请重试');
      if(version.current===revision)setState(saved?'ready':'saved');
      window.dispatchEvent(new Event('codex-marks-changed'));
      if(typeof __codexMarksUnderlines!=='undefined')__codexMarksUnderlines?.refresh();
    }catch(e){if(version.current===revision){setState('error');setFailure(e?.message||'操作失败，请重试');}}
    finally{if(version.current===revision)busy.current=false;}
  };
  const saved=state==='saved',title=failure||(saved?'取消 mark':'保存选中文字到 mark 收藏库');
  return (0,g3.jsx)(zH,{onClick:toggle,disabled:state==='saving'||state==='loading',title,'aria-label':title,'aria-pressed':saved,
    children:state==='saving'||state==='loading'?'mark…':saved?'✓ mark':'mark'});
}
