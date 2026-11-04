import {spawnSync} from 'node:child_process';
import {statSync} from 'node:fs';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

const frontend=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const repository=resolve(frontend,'../..');
const artifactFiles=['books.json','item_embeddings.npy','coords_2d.npy','meta.json'];
const isFile=path=>{try{return statSync(path).isFile();}catch{return false;}};

function probeUv(){
 const result=spawnSync('uv',['--version'],{encoding:'utf8',timeout:3000,windowsHide:true});
 return !result.error&&result.status===0;
}

export function parseArgs(args,{allowJson=true}={}){
 const options={json:false};
 for(let index=0;index<args.length;index++){
  const option=args[index];
  if(option==='--json'&&allowJson)options.json=true;
  else if(option==='--help')options.help=true;
  else if(option==='--backend'){
   const path=args[++index];
   if(!path||path.startsWith('--'))throw new Error('--backend needs a path.');
   options.backendArg=path;
  }else throw new Error('Unknown option. Use --help for usage.');
 }
 return options;
}

export function resolveConfiguration({repo=repository,backendArg,env=process.env}={}){
 const supplied=backendArg||env.TASTEBRIDGE_BACKEND_DIR;
 const candidates=supplied?[resolve(repo,supplied)]:[join(repo,'src/backend'),resolve(repo,'../TasteBridge-backend-review/src/backend')];
 const backend=candidates.find(path=>isFile(join(path,'uv.lock'))&&isFile(join(path,'app/main.py')));
 const uiPort=Number(env.TASTEBRIDGE_UI_PORT||4176),apiPort=Number(env.TASTEBRIDGE_API_PORT||9016);
 const validPort=port=>Number.isInteger(port)&&port>=1&&port<=65535;
 return {backend,uiPort,apiPort,portsValid:validPort(uiPort)&&validPort(apiPort)&&uiPort!==apiPort};
}

export function inspectSetup({repo=repository,backendArg,env=process.env,nodeVersion=process.versions.node,checkUv=probeUv}={}){
 const checks=[];
 const add=(status,name,message)=>checks.push({status,name,message});
 const nodeMajor=Number(nodeVersion.split('.')[0]);
 add(Number.isInteger(nodeMajor)&&nodeMajor>=20?'ok':'error','Node.js',`Node ${nodeVersion}; this workflow requires Node 20 or newer.`);
 const uvAvailable=checkUv();
 add(uvAvailable?'ok':'error','uv',uvAvailable?'uv is available on PATH (uv --version succeeded).':'uv was not found or could not run. Install it separately before starting the connected app.');

 const {backend,uiPort,apiPort,portsValid}=resolveConfiguration({repo,backendArg,env});
 add(backend?'ok':'error','Backend source',backend||'No backend with uv.lock and app/main.py found. Pass --backend PATH (relative to the repository root), as with dev.mjs.');

 add(portsValid?'ok':'error','Port configuration',portsValid?`UI ${uiPort}; API ${apiPort}. Availability is checked when the app starts.`:'Set distinct TASTEBRIDGE_UI_PORT and TASTEBRIDGE_API_PORT integers between 1 and 65535.');

 if(backend){
  const raw=env.ARTIFACT_DIR;
  if(raw&&/^[a-z][a-z\d+.-]*:\/\//i.test(raw)){
   add('error','Selected artifacts','ARTIFACT_DIR must be a local folder. The current backend cannot load cloud URLs; obtain an authorized local export first.');
  }else{
   // uv runs from the backend directory; match its relative-path semantics.
   const selected=raw!==undefined?resolve(backend,raw):join(backend,'sample_artifacts');
   const bundled=selected===join(backend,'sample_artifacts');
   const missing=artifactFiles.filter(file=>!isFile(join(selected,file)));
   add(missing.length?'error':'ok','Selected artifacts',`${bundled?'Bundled toy sample':'Custom local export'}: ${selected}.${missing.length?` Missing: ${missing.join(', ')}.`:' Required files are present; the backend validates their contents at startup.'}`);
  }
 }
 const realExport=join(repo,'data/artifacts/current');
 const realPresent=artifactFiles.every(file=>isFile(join(realExport,file)));
 add('info','Real-model export',realPresent?'data/artifacts/current has the required files. Select it with ARTIFACT_DIR=../../data/artifacts/current for dev.mjs. Contents and provenance are not validated here.':'data/artifacts/current is absent or incomplete. The bundled sample is sufficient for local UI work. Retrieving the DVC export separately needs the team bucket read permission; no account or bucket access was checked.');

 return {ok:!checks.some(check=>check.status==='error'),checks,note:'Read-only prerequisite check. No servers, installs, downloads, credentials, cloud calls or artifact-content validation. This does not prove M3 deployment or training completion.'};
}

const help=`Usage: node scripts/check-setup.mjs [--backend PATH] [--json]

Run from frontend/prototype. Uses the same backend lookup and environment
variables as scripts/dev.mjs. It does not read .env files or start the app.
`;

if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href){
 try{
  const options=parseArgs(process.argv.slice(2));
  if(options.help)console.log(help);
  else{
   const report=inspectSetup(options);
   if(options.json)console.log(JSON.stringify(report,null,2));
   else{
    console.log('TasteBridge local setup');
    for(const {status,name,message} of report.checks)console.log(`[${status.toUpperCase()}] ${name}: ${message}`);
    console.log(`\n${report.note}`);
    console.log(report.ok?'\nPrerequisites found. Next: node scripts/dev.mjs (uv may synchronize packages at launch).':'\nFix the errors above before starting the connected app.');
   }
   process.exitCode=report.ok?0:1;
  }
 }catch(error){console.error(error.message);process.exitCode=1;}
}
