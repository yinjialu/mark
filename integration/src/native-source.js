// Use the same registered source navigator as native message links.
export function __markUseRevealSource(){
  gTr();
  const store=zx(qv);
  return async mark=>{
    const messageId=mark.anchor?.message_id;
    if(!messageId)return false;
    const navigator=store.get(G8,mark.thread_id);
    if(!navigator?.revealItem)return false;
    await navigator.revealItem({conversationId:mark.thread_id,itemId:messageId,turnKey:mark.anchor?.turn_id});
    return true;
  };
}
