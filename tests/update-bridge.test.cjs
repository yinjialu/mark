const {test}=require('node:test'),assert=require('node:assert/strict');
const {validRequest}=require('../integration/src/update-bridge.cjs');
test('update IPC only accepts fixed operations and opaque tickets',()=>{
 assert(validRequest({op:'check',force:false}));assert(validRequest({op:'status'}));assert(validRequest({op:'install',ticket:'11111111-2222-3333-4444-555555555555'}));
 for(const p of [{op:'install',url:'https://evil.test'}, {op:'check',force:true,path:'/tmp/code'}, {op:'install',ticket:'../code'}, {op:'status',force:true}, {op:'check'}])assert.equal(validRequest(p),false);
});
