"use strict";
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(v);
function validRequest(p){
  if(!p||typeof p!=='object'||Array.isArray(p))return false;
  const keys=Object.keys(p);
  return p.op==='check'?keys.length===2&&typeof p.force==='boolean':p.op==='status'?keys.length===1:p.op==='install'&&keys.length===2&&uuid(p.ticket);
}
function request(p,resourcesPath,run=spawn){
  return new Promise(resolve=>{
    let config;
    try{
      const raw=fs.readFileSync(path.join(resourcesPath,'codex-marks/update-config.json'),'utf8');
      if(raw.length>16000)throw Error();config=JSON.parse(raw);
      if(!path.isAbsolute(config.state)||!path.isAbsolute(config.source_app)||!/^[0-9a-f]{16}$/.test(config.package_id)
         ||config.package!==path.join(config.state,'packages',config.package_id))throw Error();
    }catch{return resolve({ok:false,error:'请重新安装新版 mark 以启用更新入口'});}
    const args=['-B',path.join(config.package,'mark.py'),'--app',config.source_app,'--state-dir',config.state];
    if(p.op==='check')args.push('check-update',...(p.force?['--force']:[]));
    else if(p.op==='status')args.push('update-status');
    else args.push('update','--yes','--ticket',p.ticket,'--detached');
    let child;try{child=run('/usr/bin/python3',args,{stdio:['ignore','pipe','pipe'],shell:false});}catch{return resolve({ok:false,error:'暂时无法检查更新'});}
    let finished=false,size=0;const chunks=[];
    const done=value=>{if(!finished){finished=true;clearTimeout(timer);resolve(value);}};
    const timer=setTimeout(()=>{child.kill();done({ok:false,error:'检查更新超时，现有版本可继续使用'});},60000);
    child.on('error',()=>done({ok:false,error:'暂时无法检查更新'}));child.stderr.resume();
    child.stdout.on('data',chunk=>{size+=chunk.length;if(size>65536){child.kill();done({ok:false,error:'更新响应无效'});}else chunks.push(chunk);});
    child.on('close',code=>{try{if(code!==0)throw Error();const r=JSON.parse(Buffer.concat(chunks).toString('utf8'));if(typeof r.status!=='string')throw Error();done({ok:true,...r});}catch{done({ok:false,error:'更新未开始，请重新检查更新'});}});
  });
}
function registerUpdates({app,ipcMain},trustedSender){
  const pending=new Set();
  ipcMain.handle('local.codex-marks:updates:v1',async(event,p)=>{
    if(!trustedSender(event,app.getAppPath())||!validRequest(p))return {ok:false,error:'不允许的更新请求'};
    const id=event.sender.id;if(pending.has(id))return {ok:false,error:'正在处理更新请求，请稍候'};
    pending.add(id);try{return await request(p,process.resourcesPath);}finally{pending.delete(id);}
  });
}
module.exports={validRequest,request,registerUpdates};
