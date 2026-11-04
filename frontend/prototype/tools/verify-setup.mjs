import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readdirSync,readFileSync,existsSync,rmSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {inspectSetup,parseArgs,resolveConfiguration} from '../scripts/check-setup.mjs';
import {standaloneConfig} from '../scripts/serve.mjs';

function fixture(t){
 const repo=mkdtempSync(join(tmpdir(),'tastebridge-setup-'));
 t.after(()=>rmSync(repo,{recursive:true,force:true}));
 const backend=join(repo,'src/backend');
 mkdirSync(join(backend,'app'),{recursive:true});
 writeFileSync(join(backend,'app/main.py'),'');writeFileSync(join(backend,'uv.lock'),'');
 artifacts(join(backend,'sample_artifacts'));
 return {repo,backend,env:{},nodeVersion:'24.3.0',checkUv:()=>true};
}
function artifacts(path){
 mkdirSync(path,{recursive:true});
 for(const file of ['books.json','item_embeddings.npy','coords_2d.npy','meta.json'])writeFileSync(join(path,file),'');
}
const check=(report,name)=>report.checks.find(item=>item.name===name);

test('a fresh checkout can use bundled samples without DVC access or writing runtime files',t=>{
 const options=fixture(t),before=readdirSync(options.repo,{recursive:true});
 const report=inspectSetup(options);
 assert.equal(report.ok,true);
 assert.match(check(report,'Selected artifacts').message,/Bundled toy sample/);
 assert.equal(check(report,'Real-model export').status,'info');
 assert.match(check(report,'Real-model export').message,/bucket read permission/);
 assert.deepEqual(readdirSync(options.repo,{recursive:true}),before);
});

test('missing uv and unsupported Node are actionable failures',t=>{
 const report=inspectSetup({...fixture(t),nodeVersion:'18.20.0',checkUv:()=>false});
 assert.equal(report.ok,false);
 assert.equal(check(report,'Node.js').status,'error');
 assert.equal(check(report,'uv').status,'error');
});

test('missing backend source fails instead of claiming the app can start',t=>{
 const report=inspectSetup({...fixture(t),backendArg:'missing'});
 assert.equal(report.ok,false);
 assert.equal(check(report,'Backend source').status,'error');
 assert.match(check(report,'Backend source').message,/--backend PATH/);
});

test('backend override follows the launcher precedence and repository-relative paths',t=>{
 const options=fixture(t);
 assert.equal(inspectSetup({...options,env:{TASTEBRIDGE_BACKEND_DIR:'src/backend'}}).ok,true);
 assert.equal(inspectSetup({...options,backendArg:'src/backend',env:{TASTEBRIDGE_BACKEND_DIR:'missing'}}).ok,true);
});

test('port checks reject equal, out-of-range, nonnumeric and fractional values',t=>{
 const options=fixture(t);
 for(const env of [
  {TASTEBRIDGE_UI_PORT:'9016'},
  {TASTEBRIDGE_UI_PORT:'65536'},
  {TASTEBRIDGE_API_PORT:'0'},
  {TASTEBRIDGE_API_PORT:'hello'},
  {TASTEBRIDGE_UI_PORT:'4176.5'},
 ]){
  const report=inspectSetup({...options,env});
  assert.equal(report.ok,false);
  assert.equal(check(report,'Port configuration').status,'error');
 }
 assert.equal(inspectSetup({...options,env:{TASTEBRIDGE_UI_PORT:'65535',TASTEBRIDGE_API_PORT:'1'}}).ok,true);
});

test('custom artifacts use backend-relative paths and cloud URLs cannot pass as local folders',t=>{
 const options=fixture(t),real=join(options.repo,'data/artifacts/current');
 artifacts(real);
 const report=inspectSetup({...options,env:{ARTIFACT_DIR:'../../data/artifacts/current'}});
 assert.equal(report.ok,true);
 assert.match(check(report,'Selected artifacts').message,/Custom local export/);
 assert.match(check(report,'Real-model export').message,/required files/);
 for(const value of ['', 'missing','gs://example-bucket/artifacts']){
  const failed=inspectSetup({...options,env:{ARTIFACT_DIR:value}});
  assert.equal(failed.ok,false);
  assert.equal(check(failed,'Selected artifacts').status,'error');
 }
});

test('CLI options reject incomplete or unknown arguments',()=>{
 assert.deepEqual(parseArgs(['--backend','src/backend','--json']),{json:true,backendArg:'src/backend'});
 assert.deepEqual(parseArgs(['--help']),{json:false,help:true});
 assert.throws(()=>parseArgs(['--backend']),/needs a path/);
 assert.throws(()=>parseArgs(['--backend','--json']),/needs a path/);
 assert.throws(()=>parseArgs(['--deploy']),/Unknown option/);
});


test('connected launcher rejects bad input before building or creating runtime files',t=>{
 const {repo}=fixture(t),frontend=join(repo,'frontend/prototype'),scripts=join(frontend,'scripts');
 mkdirSync(scripts,{recursive:true});
 for(const name of ['dev.mjs','serve.mjs','check-setup.mjs'])writeFileSync(join(scripts,name),readFileSync(new URL(`../scripts/${name}`,import.meta.url)));
 writeFileSync(join(scripts,'build-prototype.mjs'),"import {writeFileSync} from 'node:fs';writeFileSync('build-attempt','unexpected build');");
 const run=(args,env={})=>spawnSync(process.execPath,[join(scripts,'dev.mjs'),...args],{encoding:'utf8',env:{...process.env,ARTIFACT_DIR:join(repo,'src/backend/sample_artifacts'),TASTEBRIDGE_BACKEND_DIR:join(repo,'src/backend'),TASTEBRIDGE_UI_PORT:'4176',TASTEBRIDGE_API_PORT:'9016',...env},timeout:5000});
 const help=run(['--help']);
 assert.equal(help.status,0);assert.match(help.stdout,/Usage: node scripts\/dev.mjs/);
 for(const [args,env,message] of [
  [['--backend'],{},/needs a path/],
  [['--backend','--help'],{},/needs a path/],
  [['--unknown'],{},/Unknown option/],
  [['--json'],{},/Unknown option/],
  [[],{TASTEBRIDGE_UI_PORT:'65536'},/Port configuration/],
  [[],{TASTEBRIDGE_UI_PORT:'9016'},/Port configuration/],
  [['--backend','missing'],{},/Backend source/],
 ]){
  const result=run(args,env);
  assert.equal(result.status,1,result.stderr);assert.match(result.stderr,message);
  assert.equal(existsSync(join(frontend,'build-attempt')),false);
  assert.equal(existsSync(join(repo,'.integration-runtime')),false);
 }
});

test('preflight and launcher resolve the same bounded ports and backend configuration',t=>{
 const options=fixture(t);
 for(const env of [{},{TASTEBRIDGE_UI_PORT:'65535',TASTEBRIDGE_API_PORT:'1'},{TASTEBRIDGE_API_PORT:'65536'},{TASTEBRIDGE_UI_PORT:'9016'}]){
  const config=resolveConfiguration({...options,env});
  assert.equal(config.backend,options.backend);
  assert.equal(config.portsValid,check(inspectSetup({...options,env}),'Port configuration').status==='ok');
 }
});

test('standalone preview ignores ambient HOST while Docker explicitly binds to its network interface',()=>{
 assert.equal(standaloneConfig({HOST:'machine-name.invalid'}).host,'127.0.0.1');
 const dockerfile=readFileSync(new URL('../Dockerfile',import.meta.url),'utf8');
 const host=dockerfile.match(/\bTASTEBRIDGE_HOST=(\S+)/)?.[1],port=dockerfile.match(/\bPORT=(\d+)/)?.[1];
 assert.equal(host,'0.0.0.0');
 assert.deepEqual(standaloneConfig({HOST:'machine-name.invalid',TASTEBRIDGE_HOST:host,PORT:port}),{host:'0.0.0.0',port:8080,apiBase:'http://127.0.0.1:9000'});
 for(const PORT of ['0','65536','8080.5','invalid'])assert.throws(()=>standaloneConfig({PORT}),/PORT must be/);
});
