import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {SESSION_TTL_MS,parseDeskSession,deskSessionSnapshot,restoreDeskDecision,createDeskSessionStore} from '../src/a/desk-session.mjs';
import {matchesBookSearch,normalizedBookSearch} from '../src/a/desk-search.mjs';
import {DEMO,byId,recommend} from '../src/a/shared/engine.mjs';
import {reconcileRanking} from '../src/a/desk-ranking.mjs';
import {clearDecision,bothWilling} from '../src/a/desk-decision.mjs';

const now=1900000000000;
const fingerprintOne='a'.repeat(64),fingerprintTwo='b'.repeat(64);
const stateWith=changes=>({a:['a1','a2','a3','a4','a5'],b:['b1','b2','b3','b4','b5'],mode:'least-misery',reader:'b',stage:'results',view:'map',results:[{book:{id:'c1'}},{book:{id:'c2'}}],votes:{c1:{a:'yes',b:'yes'},c2:{a:'unsure'}},choice:'c1',selected:'c1',deferred:false,...changes});
const rawWith=(changes={},api=false)=>JSON.stringify({...deskSessionSnapshot(stateWith(),{api,modelVersion:api?'model-one':null,artifactFingerprint:api?fingerprintOne:null,now}),...changes});
function memoryStorage(){const entries=new Map();return {entries,getItem:key=>entries.get(key)??null,setItem:(key,value)=>entries.set(key,value),removeItem:key=>entries.delete(key)};}

test('stores only bounded selection and decision fields, never query, catalogue data or feedback',()=>{
 const raw=JSON.stringify(deskSessionSnapshot(stateWith({query:'private search',searchError:'private error',feedback:{private:'feedback'},credentials:'secret',results:[{book:{id:'c1',title:'Private metadata',vector:[1,2,3]}}]}),{now}));
 for(const privateText of ['private search','private error','feedback','secret','Private metadata','vector','title'])assert(!raw.includes(privateText),privateText);
 const parsed=parseDeskSession(raw,{now});
 assert.equal(parsed.reason,'restored');assert.equal(parsed.snapshot.choice,'c1');
 assert.equal(parsed.snapshot.reader,'b');assert.equal(parsed.snapshot.view,'map');
});

test('restores an explicit choice only for surviving candidates with both readers Interested',()=>{
 const saved=parseDeskSession(rawWith(),{now}).snapshot;
 const state=stateWith({votes:{},choice:null,results:[{book:{id:'c2'}},{book:{id:'c1'}}]});
 assert.deepEqual(restoreDeskDecision(state,saved),{restored:true,changed:false});
 assert.equal(state.choice,'c1');assert.deepEqual(state.votes,saved.votes);
 state.votes.c1.a='no';assert.equal(saved.votes.c1.a,'yes','Restored answers must be copied.');
 const next=stateWith({votes:{},choice:null,results:[{book:{id:'c2'}},{book:{id:'new'}}]});
 assert.deepEqual(restoreDeskDecision(next,saved),{restored:true,changed:true});
 assert.equal(next.choice,null);assert.deepEqual(next.votes,{c2:{a:'unsure'}});
});

test('two Interested responses alone never restore an unconfirmed joint choice',()=>{
 const saved=parseDeskSession(rawWith({choice:null}),{now}).snapshot,state=stateWith({choice:null});
 restoreDeskDecision(state,saved);assert.equal(state.choice,null);
});

test('changed seeds, ranking or API model discard stale opinions and shared choice',()=>{
 const saved=parseDeskSession(rawWith({},true),{api:true,now}).snapshot;
 for(const [changes,modelVersion] of [[{a:['other']},'model-one'],[{mode:'average'},'model-one'],[{},'model-two'],[{},null]]){
  const state=stateWith(changes);
  assert.deepEqual(restoreDeskDecision(state,saved,{api:true,modelVersion,artifactFingerprint:fingerprintOne}),{restored:false,changed:true});
  assert.deepEqual(state.votes,{});assert.equal(state.choice,null);assert.equal(state.deferred,false);
 }
 const matching=stateWith({votes:{},choice:null});
 restoreDeskDecision(matching,saved,{api:true,modelVersion:'model-one',artifactFingerprint:fingerprintOne});assert.equal(matching.choice,'c1');
});

test('the same model label with different artifact bytes never restores opinions or a joint choice',()=>{
 const saved=parseDeskSession(rawWith({},true),{api:true,now}).snapshot,state=stateWith();
 restoreDeskDecision(state,saved,{api:true,modelVersion:'model-one',artifactFingerprint:fingerprintTwo});
 assert.equal(state.choice,null);assert.deepEqual(state.votes,{});
});

test('older sessions and responses without a fingerprint keep favorites but cannot verify opinions',()=>{
 const old=JSON.parse(rawWith({},true));delete old.artifactFingerprint;
 const saved=parseDeskSession(JSON.stringify(old),{api:true,now}).snapshot;
 assert.deepEqual(saved.a,stateWith().a);assert.equal(saved.artifactFingerprint,null);
 for(const artifactFingerprint of [null,undefined,fingerprintOne]){
  const state=stateWith();restoreDeskDecision(state,saved,{api:true,modelVersion:'model-one',artifactFingerprint});
  assert.equal(state.choice,null);assert.deepEqual(state.votes,{});
 }
 const verified=parseDeskSession(rawWith({},true),{api:true,now}).snapshot,state=stateWith();
 restoreDeskDecision(state,verified,{api:true,modelVersion:'model-one'});assert.equal(state.choice,null);
 for(const artifactFingerprint of ['x',fingerprintOne.toUpperCase(),{hashes:{}}])assert.equal(parseDeskSession(rawWith({artifactFingerprint},true),{api:true,now}).snapshot,null);
});

test('malformed, oversized and unknown-schema saved sessions cannot enter application state',()=>{
 for(const raw of ['{','null','[]','x'.repeat(12001),rawWith({schema:2}),rawWith({a:['a1','a1']}),rawWith({mode:'invented'}),rawWith({stage:'checkout'}),rawWith({view:'invented'}),rawWith({votes:{c1:{a:'maybe'}}}),rawWith({votes:{c1:{admin:'yes'}}}),rawWith({votes:{absent:{a:'yes'}}}),rawWith({choice:'c2'}),rawWith({a:['x'.repeat(65)]})]){
  assert.equal(parseDeskSession(raw,{now}).snapshot,null);
 }
 const loaded=parseDeskSession(rawWith({query:'must not enter state',credentials:'never'}),{now}).snapshot;
 assert(!Object.hasOwn(loaded,'query'));assert(!Object.hasOwn(loaded,'credentials'));
});

test('expires after 24 idle hours and rejects future timestamps',()=>{
 assert.equal(parseDeskSession(rawWith({savedAt:now-SESSION_TTL_MS}),{now}).reason,'restored');
 assert.equal(parseDeskSession(rawWith({savedAt:now-SESSION_TTL_MS-1}),{now}).reason,'expired');
 assert.equal(parseDeskSession(rawWith({savedAt:now+60001}),{now}).reason,'invalid');
});

test('missing static catalogue books preserve other favorites and discard saved decisions',()=>{
 const {snapshot,reason}=parseDeskSession(rawWith(),{now,knownId:id=>id!=='a1'});
 assert.equal(reason,'missing');assert.deepEqual(snapshot.a,['a2','a3','a4','a5']);
 assert.deepEqual(snapshot.votes,{});assert.equal(snapshot.choice,null);
});

test('explicit URL shelves take priority even when empty, and do not read saved data',()=>{
 let reads=0;
 const store=createDeskSessionStore({storage:()=>({getItem(){reads++;throw Error('must not read');}})});
 for(const search of ['?a=','?b=b1','?api=1&a=%5B%22a1%22%5D'])assert.equal(store.load({search}).reason,'url');
 assert.equal(reads,0);
});

test('static and API sessions use separate keys and reject the opposite saved scope',()=>{
 const storage=memoryStorage(),offline=createDeskSessionStore({storage:()=>storage,now:()=>now}),api=createDeskSessionStore({storage:()=>storage,api:true,now:()=>now});
 offline.save(stateWith());api.save(stateWith({mode:'average'}),'model-one');
 assert.equal(storage.entries.size,2);assert.equal(offline.load().snapshot.mode,'least-misery');assert.equal(api.load().snapshot.mode,'average');
 assert.equal(parseDeskSession(rawWith({},true),{now}).reason,'invalid');
 assert.equal(parseDeskSession(rawWith(),{api:true,now}).reason,'invalid');
});

test('damaged or expired storage is removed and unsupported storage never crashes',()=>{
 for(const raw of ['{',rawWith({savedAt:now-SESSION_TTL_MS-1})]){
  const storage=memoryStorage(),store=createDeskSessionStore({storage:()=>storage,now:()=>now});
  store.save(stateWith());const key=[...storage.entries.keys()][0];storage.entries.set(key,raw);
  assert.equal(store.load().snapshot,null);assert.equal(storage.entries.size,0);
 }
 const inaccessible=createDeskSessionStore({storage:()=>{throw Error('Blocked storage');}});
 assert.equal(inaccessible.load().reason,'unavailable');assert.equal(inaccessible.save(stateWith()),false);assert.equal(inaccessible.clear(),false);
 let removed=false;
 const full=createDeskSessionStore({storage:()=>({getItem:()=>null,setItem(){throw Error('Quota');},removeItem(){removed=true;}})});
 assert.equal(full.save(stateWith()),false);assert.equal(full.available,false);
 assert.equal(removed,true,'A failed save must remove the older recoverable choice.');
});

test('Start over removes this scope without changing another mode session',()=>{
 const storage=memoryStorage(),offline=createDeskSessionStore({storage:()=>storage}),api=createDeskSessionStore({storage:()=>storage,api:true});
 offline.save(stateWith());api.save(stateWith(),'model-one');offline.clear();
 assert.equal(offline.load().snapshot,null);assert.equal(api.load().snapshot.choice,'c1');
 offline.save(stateWith({a:[],b:[]}));assert.equal(storage.entries.size,1);
});

test('opaque __proto__ candidate IDs stay ordinary stored votes without prototype pollution',()=>{
 const state=stateWith({results:[{book:{id:'__proto__'}}],votes:Object.fromEntries([['__proto__',{a:'yes',b:'yes'}]]),choice:'__proto__',selected:'__proto__'});
 const parsed=parseDeskSession(JSON.stringify(deskSessionSnapshot(state,{now})),{now});
 const next=stateWith({results:state.results,votes:{},choice:null});restoreDeskDecision(next,parsed.snapshot);
 assert.equal(next.choice,'__proto__');assert.equal(Object.hasOwn(next.votes,'__proto__'),true);assert.equal(Object.prototype.a,undefined);
});

const appSource=readFileSync(new URL('../src/a/app.mjs',import.meta.url),'utf8');
function boot(savedState,{apiMode=false,search='',urlInput,fingerprint=fingerprintOne}={}){
 const storage=memoryStorage(),store=createDeskSessionStore({storage:()=>storage,api:apiMode});store.save(savedState,apiMode?'model-one':null,apiMode?fingerprint:null);
 const context={apiMode,apiConnection:{pending:apiMode,health:null,error:''},window:{sessionStorage:storage,scrollTo(){}},location:{search,href:`https://tastebridge.test/a/${search}`},URL,URLSearchParams,
  createDeskSessionStore,restoreDeskDecision,reconcileRanking,clearDecision,byId,recommend,sessionFromURL:()=>urlInput||({a:[],b:[],mode:'least-misery'}),makeRecorder:()=>({record(){}}),toast(){},
  matchMedia:()=>({matches:false,addEventListener(){}}),$:()=>null,$$:()=>[],api:null,clearTimeout,
  history:{state:null,replaceState(_state,_title,url){context.location.search=url.search;context.location.href=url.href;}},render(){},titleFocus(){}};
 const start=appSource.indexOf('const sessionStore='),end=appSource.indexOf('function header(){');
 assert(start>=0&&end>start);
 const recommendationHandler=appSource.slice(appSource.indexOf('async function showResults('),appSource.indexOf('function resultsHTML(){'));
 runInNewContext(appSource.slice(start,end)+'\n'+recommendationHandler+'\nglobalThis.page={state,persistSession,startOver,showResults,sessionStatus,pending:()=>pendingRecovery};',context);
 return Object.assign(context,{storage});
}

test('actual static page boot recovers both shelves and a completed mutual choice after refresh',()=>{
 const results=recommend(DEMO.a,DEMO.b),id=results[0].book.id;
 for(const stage of ['results','select']){
  const source=stateWith({a:DEMO.a,b:DEMO.b,results,stage,votes:{[id]:{a:'yes',b:'yes'}},choice:id,selected:id});
  const {page}=boot(source);assert.equal(page.state.choice,id);assert.equal(page.state.stage,stage);
  assert.equal(page.state.a.join(','),DEMO.a.join(','));assert.equal(page.state.b.join(','),DEMO.b.join(','));
  assert.equal(page.pending(),null);
 }
});

test('actual API page boot keeps recovery pending and never overwrites it before model validation',()=>{
 const context=boot(stateWith(),{apiMode:true}),before=[...context.storage.entries.values()][0];
 context.page.persistSession();assert.equal([...context.storage.entries.values()][0],before);
 assert.equal(context.page.state.choice,null);assert(context.page.pending());
});

test('actual API recovery uses the recommendation label and fingerprint, including absence, ahead of health',async()=>{
 for(const [modelVersion,artifactFingerprint,healthFingerprint,expectedChoice] of [
  ['model-one',fingerprintOne,fingerprintTwo,'c1'],['model-two',fingerprintOne,fingerprintOne,null],
  ['model-one',fingerprintTwo,fingerprintOne,null],['model-one',undefined,fingerprintOne,null]]){
  const context=boot(stateWith({stage:'select'}),{apiMode:true});
  context.apiConnection.pending=false;context.apiConnection.health={modelVersion:'model-one',artifactFingerprint:healthFingerprint};
  context.api={recommend:async()=>({results:[{book:{id:'c1'}},{book:{id:'c2'}}],mode:'least-misery',galaxy:{},topShelves:{a:[],b:[]},modelVersion,artifactFingerprint})};
  await context.page.showResults();
  assert.equal(context.page.state.stage,'select','Refreshing while editing must keep the edit screen.');
  assert.equal(context.page.state.choice,expectedChoice);
  assert.equal(context.page.pending(),null);context.page.persistSession();
  const saved=JSON.parse([...context.storage.entries.values()][0]);
  assert.equal(saved.modelVersion,modelVersion,'Persist the recommendation model, even if health reported an older one.');
  assert.equal(saved.artifactFingerprint,artifactFingerprint??null,'Never fill a missing recommendation fingerprint from health.');
  if(!artifactFingerprint)assert.match(context.page.sessionStatus(),/model could not be verified/);
 }
});

test('a changed response fingerprint also clears an existing in-page choice with an unchanged label',async()=>{
 const context=boot(stateWith(),{apiMode:true});context.apiConnection.pending=false;
 let artifactFingerprint=fingerprintOne;
 context.api={recommend:async()=>({results:[{book:{id:'c1'}},{book:{id:'c2'}}],mode:'least-misery',galaxy:{},topShelves:{a:[],b:[]},modelVersion:'model-one',artifactFingerprint})};
 await context.page.showResults();assert.equal(context.page.state.choice,'c1');
 artifactFingerprint=fingerprintTwo;await context.page.showResults();
 assert.equal(context.page.state.choice,null);assert.equal(Object.keys(context.page.state.votes).length,0);
});

test('actual Start over cancels requests, clears URL shelves and saved choice, and resets readers',()=>{
 const results=recommend(DEMO.a,DEMO.b),id=results[0].book.id,context=boot(stateWith({a:DEMO.a,b:DEMO.b,results,votes:{[id]:{a:'yes',b:'yes'}},choice:id}));
 const canceled=[];context.api={requests:{cancel:lane=>canceled.push(lane)}};
 context.location.href='https://tastebridge.test/a/?a=old&b=old&mode=average&view=map&api=0';
 let replaced;context.history.replaceState=(_state,_title,url)=>{replaced=url;};
 // Context objects are shared with the actual handler; api is looked up in it.
 context.page.startOver();
 assert.equal(context.page.state.a.length,0);assert.equal(context.page.state.b.length,0);assert.equal(context.page.state.choice,null);
 assert.equal(context.page.state.reader,'a');assert.equal(context.storage.entries.size,0);
 assert.deepEqual(canceled,['health','recommend','search','favorites','pick']);
 assert(!replaced.searchParams.has('a'));assert(!replaced.searchParams.has('b'));assert.equal(replaced.searchParams.get('api'),'0');
});

test('actual linked page takes URL shelves first and consumes them so later refresh can recover edits',()=>{
 const context=boot(stateWith(),{search:'?a=linked&b=linked&mode=average&api=0',urlInput:{a:[DEMO.a[0]],b:[],mode:'average'}});
 assert.equal(context.page.state.a.join(','),DEMO.a[0]);assert.equal(context.page.state.choice,null);
 assert.equal(context.page.state.mode,'average');assert.equal(context.location.search,'?api=0');
 context.page.state.a=[DEMO.a[1]];context.page.persistSession();
 const stored=[...context.storage.entries.values()][0];assert.equal(parseDeskSession(stored).snapshot.a[0],DEMO.a[1]);
});

test('static title/author search tolerates accents, combining marks, apostrophes and dashes',()=>{
 assert(matchesBookSearch({title:'The City & the City',author:'China Miéville'},'Mieville'));
 assert(matchesBookSearch({title:'The City & the City',author:'China Miéville'},'Mie\u0301ville'));
 assert(matchesBookSearch({title:'Harry Potter and the Half-Blood Prince',author:'J. K. Rowling'},'half blood'));
 assert(matchesBookSearch({title:'The Hitchhiker’s Guide',author:'Douglas Adams'},'hitchhikers'));
 assert.equal(normalizedBookSearch('  M I É V I L L E —  '),'m i e v i l l e');
 assert(!matchesBookSearch({title:'The Hobbit',author:'J. R. R. Tolkien'},'Miéville'));
});

test('the real explicit feedback handler uses the current recommendation identity and sends once',async()=>{
 const source=appSource.slice(appSource.indexOf('function feedbackKey('),appSource.indexOf('function bindDecision(){'));
 const actions=[],context={state:stateWith({modelVersion:'same-label',artifactFingerprint:fingerprintTwo,feedback:{},pending:false}),bothWilling,
  api:{feedback:async action=>{actions.push(action);}},renderResultsContent(){}};
 runInNewContext(source,context);
 assert.equal(actions.length,0,'Installing the handler must never send feedback.');
 await context.sendFeedback();await context.sendFeedback();
 assert.equal(actions.length,1);assert.equal(actions[0].artifactFingerprint,fingerprintTwo);assert.equal(actions[0].modelVersion,'same-label');
 const saved=deskSessionSnapshot(context.state,{api:true,modelVersion:'same-label',artifactFingerprint:fingerprintTwo});
 assert(!Object.hasOwn(saved,'feedback'),'Sent-feedback state must remain outside saved sessions.');
});
