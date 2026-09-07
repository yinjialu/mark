const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../integration/src/native-source.js'),'utf8').replace('export function','function');
test('native message navigation preserves source identity even without a turn ID',async()=>{
 const calls=[],G8={},qv={},context={G8,qv,gTr(){},zx(value){assert.equal(value,qv);return {get(registry,tid){assert.equal(registry,G8);assert.equal(tid,'task');return {async revealItem(p){calls.push(p);}};}};}};
 vm.createContext(context);vm.runInContext(source,context);
 await context.__markUseRevealSource()({thread_id:'task',anchor:{message_id:'message'}});
 assert.equal(calls[0].conversationId,'task');assert.equal(calls[0].itemId,'message');assert.equal(calls[0].turnKey,undefined);
});
test('missing source navigator does not navigate elsewhere',async()=>{
 const context={G8:{},qv:{},gTr(){},zx(){return {get(){return null;}};}};
 vm.createContext(context);vm.runInContext(source,context);
 assert.equal(await context.__markUseRevealSource()({thread_id:'task',anchor:{message_id:'message'}}),false);
});
