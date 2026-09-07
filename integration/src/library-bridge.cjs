"use strict";
const path = require('node:path');
const {spawn} = require('node:child_process');
const uuid = v => typeof v === 'string' && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(v);
function validLibraryRequest(p) {
  if (!p || typeof p !== 'object' || Array.isArray(p)) return false;
  const exact = keys => Object.keys(p).length === keys.length && keys.every(k => Object.hasOwn(p,k));
  if (p.op === 'search') return exact(['op','query','thread_id','deleted','offset','limit'])
    && typeof p.query === 'string' && p.query.length <= 500 && (p.thread_id === '' || uuid(p.thread_id))
    && typeof p.deleted === 'boolean' && Number.isSafeInteger(p.offset) && p.offset >= 0 && p.offset <= 1000000
    && Number.isSafeInteger(p.limit) && p.limit >= 1 && p.limit <= 100;
  if (!uuid(p.id)) return false;
  if (['get','delete','restore'].includes(p.op)) return exact(['op','id']);
  return p.op === 'update' && exact(['op','id','title','note','tags'])
    && typeof p.title === 'string' && p.title.length <= 200 && typeof p.note === 'string' && p.note.length <= 10000
    && Array.isArray(p.tags) && p.tags.length <= 30 && p.tags.every(t => typeof t === 'string' && t.length <= 50);
}
function libraryRequest(payload, resourcesPath, run = spawn) {
  return new Promise(resolve => {
    const child=run('/usr/bin/python3',['-B',path.join(resourcesPath,'codex-marks/library.py')],{stdio:['pipe','pipe','pipe'],shell:false,windowsHide:true});
    let finished=false,bytes=0;const chunks=[];
    const done=value=>{if(!finished){finished=true;clearTimeout(timer);resolve(value);}};
    const timer=setTimeout(()=>{child.kill();done({ok:false,error:'读取超时，请重试'});},30000);
    child.on('error',()=>done({ok:false,error:'无法打开收藏库'}));
    child.stdin.on('error',()=>done({ok:false,error:'无法读取收藏'}));
    child.stdout.on('data',chunk=>{bytes+=chunk.length;if(bytes>48000000){child.kill();done({ok:false,error:'收藏内容过大'});}else chunks.push(chunk);});
    child.stderr.resume();
    child.on('close',code=>{try{if(code!==0)throw Error();const result=JSON.parse(Buffer.concat(chunks).toString('utf8'));if(typeof result.ok!=='boolean')throw Error();done(result);}catch{done({ok:false,error:'无法读取收藏'});}});
    child.stdin.end(JSON.stringify(payload));
  });
}
function registerLibrary({app,ipcMain}, trustedSender) {
  const pending=new Map();
  ipcMain.handle('local.codex-marks:library:v1',async(event,payload)=>{
    if(!trustedSender(event,app.getAppPath())||!validLibraryRequest(payload))return {ok:false,error:'不允许的收藏请求'};
    const id=event.sender.id,count=pending.get(id)||0;
    if(count>=4)return {ok:false,error:'正在读取，请稍候'};
    pending.set(id,count+1);
    try{return await libraryRequest(payload,process.resourcesPath);}
    catch{return {ok:false,error:'无法打开收藏库'};}
    finally{const count=pending.get(id)-1;if(count)pending.set(id,count);else pending.delete(id);}
  });
}
module.exports={registerLibrary,libraryRequest,validLibraryRequest};
