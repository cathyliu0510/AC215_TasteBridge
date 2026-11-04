import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,symlinkSync,rmSync} from 'node:fs';
import {join,dirname,delimiter} from 'node:path';
import {tmpdir} from 'node:os';

// The fake uv uses the existing Node executable: `uv --version` succeeds,
// while `uv run ...` executes the fixture's backend/run script. No packages
// are installed and the frontend/health doubles never open network sockets.
function launch(t,{health=false,race=false,backend='setInterval(()=>{},1000);'}={}){
 const repo=mkdtempSync(join(tmpdir(),'tastebridge-launcher-'));
 const frontend=join(repo,'frontend/prototype'),scripts=join(frontend,'scripts'),backendDir=join(repo,'src/backend'),bin=join(repo,'bin');
 for(const dir of [scripts,join(backendDir,'app'),join(backendDir,'sample_artifacts'),bin])mkdirSync(dir,{recursive:true});
 for(const name of ['dev.mjs','check-setup.mjs'])writeFileSync(join(scripts,name),readFileSync(new URL(`../scripts/${name}`,import.meta.url)));
 writeFileSync(join(scripts,'build-prototype.mjs'),'');
 writeFileSync(join(backendDir,'uv.lock'),'');writeFileSync(join(backendDir,'app/main.py'),'');
 for(const name of ['books.json','item_embeddings.npy','coords_2d.npy','meta.json'])writeFileSync(join(backendDir,'sample_artifacts',name),'');
 symlinkSync(process.execPath,join(bin,'uv'));
 writeFileSync(join(backendDir,'run'),`console.log('fixture-backend-started');${backend}`);
 writeFileSync(join(scripts,'serve.mjs'),`
 import {EventEmitter} from 'node:events';
 globalThis.fetch=async(_url,{signal})=>${health?'({ok:true})':"new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('Aborted')),{once:true}))"};
 export function createFrontendServer(){
  return new class extends EventEmitter{
   listening=false;
   closeAllConnections(){}
   listen(_port,_host,ready){
    ${race?"process.emit('SIGTERM');":''}
    setImmediate(()=>{this.listening=true;this.keepAlive=setInterval(()=>{},1000);console.log('fixture-frontend-listening');ready();});
    return this;
   }
   close(){clearInterval(this.keepAlive);this.listening=false;console.log('fixture-frontend-closed');}
  };
 }
 `);
 const child=spawn(process.execPath,[join(scripts,'dev.mjs')],{cwd:frontend,env:{...process.env,PATH:[bin,dirname(process.execPath),process.env.PATH].join(delimiter),TASTEBRIDGE_BACKEND_DIR:backendDir,ARTIFACT_DIR:join(backendDir,'sample_artifacts'),TASTEBRIDGE_UI_PORT:'4176',TASTEBRIDGE_API_PORT:'9016'}});
 let stdout='',stderr='';
 child.stdout.on('data',chunk=>{stdout+=chunk;});child.stderr.on('data',chunk=>{stderr+=chunk;});
 const exited=new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',(code,signal)=>resolve({code,signal}));});
 const within=async(promise,ms=2500)=>{
  let timer;
  try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(`Launcher did not finish promptly. ${stdout} ${stderr}`)),ms);})]);}
  finally{clearTimeout(timer);}
 };
 t.after(async()=>{
  if(child.exitCode===null&&child.signalCode===null){child.kill('SIGTERM');const timer=setTimeout(()=>child.kill('SIGKILL'),3500);try{await exited;}finally{clearTimeout(timer);}}
  rmSync(repo,{recursive:true,force:true});
 });
 return {child,exited:()=>within(exited),output:()=>({stdout,stderr}),waitFor:async text=>{
  if(stdout.includes(text))return;
  await within(new Promise(resolve=>{const listener=()=>{if(stdout.includes(text)){child.stdout.off('data',listener);resolve();}};child.stdout.on('data',listener);}));
 }};
}

const options={skip:process.platform==='win32'?'Fake uv symlinks use POSIX executable lookup.':false};

test('SIGINT during API readiness aborts startup promptly without opening the frontend',options,async t=>{
 const run=launch(t);
 await run.waitFor('fixture-backend-started');run.child.kill('SIGINT');
 const result=await run.exited();
 assert.equal(result.code,0,run.output().stderr);
 assert.doesNotMatch(run.output().stdout,/fixture-frontend-listening|Connected A:/);
 assert.equal(run.output().stderr,'');
});

test('a backend terminated by a signal aborts readiness promptly and reports failure',options,async t=>{
 const run=launch(t,{backend:"setTimeout(()=>process.kill(process.pid,'SIGTERM'),80);setInterval(()=>{},1000);"});
 const result=await run.exited();
 assert.equal(result.code,1);
 assert.match(run.output().stderr,/Backend stopped \(SIGTERM\)/);
 assert.doesNotMatch(run.output().stdout,/fixture-frontend-listening|Connected A:/);
});

test('a backend exit after startup closes the frontend and fails the launcher',options,async t=>{
 const run=launch(t,{health:true,backend:'setTimeout(()=>process.exit(7),150);'});
 const result=await run.exited();
 assert.equal(result.code,1);
 assert.match(run.output().stdout,/Connected A:/);assert.match(run.output().stdout,/fixture-frontend-closed/);
 assert.match(run.output().stderr,/Backend stopped \(exit 7\)/);
});

test('shutdown during a pending frontend listen closes it without reporting a connected app',options,async t=>{
 const run=launch(t,{health:true,race:true});
 const result=await run.exited();
 assert.equal(result.code,0,run.output().stderr);
 assert.match(run.output().stdout,/fixture-frontend-closed/);
 assert.doesNotMatch(run.output().stdout,/Connected A:/);
});
