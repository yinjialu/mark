const {test}=require('node:test'),assert=require('node:assert/strict'),{pathToFileURL}=require('node:url'),path=require('node:path');

const modulePromise=import(pathToFileURL(path.join(__dirname,'../integration/src/library-ui.mjs')).href);

test('message fallback is not an exact block location',async()=>{
 const {isExactLocation}=await modulePromise;
 const mark={anchor:{coordinate_space:'rendered_block'}};
 assert.equal(isExactLocation(mark,{precision:'message'}),false);
 assert.equal(isExactLocation(mark,{precision:'block'}),true);
});

test('navigation waits for a delayed exact block instead of stopping at its message',async()=>{
 const {waitForExactLocation}=await modulePromise;
 const element={isConnected:true,getAttribute:name=>name==='data-codex-mark-source-hash'?'hash':null};
 let reads=0;
 const root={
  getAttribute:name=>name==='data-response-annotation-conversation'?'thread':name==='data-response-annotation-target'?'message':null,
  querySelectorAll:selector=>selector==='[data-codex-mark-block-kind="mermaid"]'&&++reads>1?[element]:[]
 };
 const scroll={querySelectorAll:()=>[root]};
 const mark={thread_id:'thread',anchor:{coordinate_space:'rendered_block',message_id:'message',block_kind:'mermaid',block_index:0,block_source_hash:'hash'}};
 const result=await waitForExactLocation(mark,()=>scroll,()=>true,{root,element:root,precision:'message'},{attempts:3,interval:0});
 assert.equal(result.exact,true);assert.equal(result.found.element,element);assert.equal(result.found.precision,'block');
});
