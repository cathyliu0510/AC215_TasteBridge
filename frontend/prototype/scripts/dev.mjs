import {spawn,spawnSync} from 'node:child_process';
import {mkdirSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import {createFrontendServer} from './serve.mjs';
import {inspectSetup,parseArgs,resolveConfiguration} from './check-setup.mjs';

const frontend=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const repo=resolve(frontend,'../..');
async function main(){
 const options=parseArgs(process.argv.slice(2),{allowJson:false});
 if(options.help){
  console.log('Usage: node scripts/dev.mjs [--backend PATH]\n\nBuild and launch the local frontend and API. Backend paths resolve from the repository root.');
  return;
 }
 const report=inspectSetup(options);
 if(!report.ok)throw new Error(report.checks.filter(check=>check.status==='error').map(check=>`${check.name}: ${check.message}`).join('\n'));
 const {backend,uiPort,apiPort}=resolveConfiguration(options);
 const built=spawnSync(process.execPath,[join(frontend,'scripts/build-prototype.mjs')],{cwd:frontend,stdio:'inherit'});
 if(built.status!==0){process.exitCode=built.status||1;return;}
 const runtime=join(repo,'.integration-runtime');mkdirSync(runtime,{recursive:true});
 const apiBase=`http://127.0.0.1:${apiPort}`;
 const child=spawn('uv',['run','--frozen','uvicorn','app.main:app','--host','127.0.0.1','--port',String(apiPort)],{
  cwd:backend,stdio:'inherit',env:{...process.env,FEEDBACK_PATH:join(runtime,'feedback.jsonl')}
 });
 const shutdown=new AbortController();
 let stopping=false,killTimer;
 const exited=()=>child.exitCode!==null||child.signalCode!==null;
 const server=createFrontendServer({root:join(frontend,'dist'),apiBase,log:line=>console.log(`frontend ${line}`)});
 function stop(){
  if(stopping)return;stopping=true;shutdown.abort();
  server.closeAllConnections();if(server.listening)server.close();
  if(!exited()){
   child.kill('SIGTERM');
   killTimer=setTimeout(()=>{if(!exited())child.kill('SIGKILL');},3000);killTimer.unref();
  }
 }
 child.once('error',error=>{if(!stopping){console.error(error.message);process.exitCode=1;stop();}});
 child.once('exit',(code,signal)=>{
  clearTimeout(killTimer);
  if(!stopping){console.error(`Backend stopped (${signal||`exit ${code}`}).`);process.exitCode=1;stop();}
 });
 process.on('SIGINT',stop);process.on('SIGTERM',stop);
 try{
  let healthy=false;
  for(let attempt=0;attempt<120;attempt++){
   if(stopping)return;
   if(exited())throw new Error('Backend stopped during startup.');
   const request=new AbortController(),cancel=()=>request.abort();
   shutdown.signal.addEventListener('abort',cancel,{once:true});
   const timeout=setTimeout(cancel,500);
   try{
    const reply=await fetch(`${apiBase}/health`,{signal:request.signal});healthy=reply.ok;
   }catch{if(stopping)return;}
   finally{clearTimeout(timeout);shutdown.signal.removeEventListener('abort',cancel);}
   if(stopping)return;
   if(healthy)break;
   await delay(250,undefined,{signal:shutdown.signal});
  }
  if(stopping)return;
  if(!healthy)throw new Error('Backend did not become healthy.');
  if(exited())throw new Error('Backend stopped during startup.');
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(uiPort,'127.0.0.1',resolve);});
  // A signal can arrive after listen starts but before its callback runs.
  if(stopping){server.closeAllConnections();if(server.listening)server.close();return;}
  console.log(`Connected A: http://127.0.0.1:${uiPort}/a/?api=1`);
  console.log(`Offline A:   http://127.0.0.1:${uiPort}/a/?api=0`);
 }catch(error){if(!stopping){console.error(error.message);process.exitCode=1;}stop();}

}

try{await main();}catch(error){console.error(error.message);process.exitCode=1;}
