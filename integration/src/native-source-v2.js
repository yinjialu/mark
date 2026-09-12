// Ask the current client navigation registry to materialize the saved response,
// then let library-ui verify and scroll to the exact saved range or block.
export function __markUseRevealSource(){
  M6n();
  const store=Of(se);
  return async mark=>{
    const messageId=mark.anchor?.message_id;
    if(!messageId)return false;
    const escape=value=>typeof CSS<'u'&&CSS.escape?CSS.escape(value):String(value).replace(/"/g,'\\"');
    const selector=`[data-response-annotation-conversation="${escape(mark.thread_id)}"][data-response-annotation-target="${escape(messageId)}"]`;
    await C6n(store,mark.thread_id,selector,()=>document.querySelector(selector));
    return true;
  };
}
