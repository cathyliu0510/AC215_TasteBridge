import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {LatestRequests} from '../src/a/desk-api.mjs';
import {enableApiCatalogue,cacheApiBooks,byId} from '../src/a/shared/catalog.mjs';
import {galaxyLayout} from '../src/a/desk-galaxy.mjs';
import {bookTile} from '../src/a/shared/ui.mjs';
import {shortlistText,readerConnection} from '../src/a/desk-interactions.mjs';
import {voteFor} from '../src/a/desk-decision.mjs';

// Run the real page handlers with a small view port, without introducing a
// browser dependency into the existing Node tests.
const appSource=readFileSync(new URL('../src/a/app.mjs',import.meta.url),'utf8');
function handlerSource(start,end){
 const from=appSource.indexOf(start),to=appSource.indexOf(end,from);
 assert(from>=0&&to>from,'Page handlers moved; update this view harness.');
 return appSource.slice(from,to);
}
function readerHandoff({executeSearch=async()=>[],searchTimer}={}){
 const state={reader:'a',stage:'select',query:'Potter',filter:'all',a:['a1','a2','a3','a4','a5'],b:[],searchResults:[{id:'previous-match'}],searchBusy:false,searchError:''};
 const requests=new LatestRequests(),renders=[],input={value:state.query,focus(){}};
 const render=()=>renders.push({query:state.query,results:Array.from(state.searchResults,book=>book.id),busy:state.searchBusy,error:state.searchError});
 const context={state,searchTimer,clearTimeout,api:{requests,search:query=>requests.run('search',signal=>executeSearch(query,signal))},
  compactViewport:{matches:false},readerName:reader=>reader==='a'?'Reader 1':'Reader 2',
  $:()=>input,syncFilters(){},syncSelectionChrome(){},syncCatalogueSelection(){},
  renderBooks:render,renderApiBooks:render,recorder:{record(){}}};
 runInNewContext(handlerSource('async function performSearch(){','function syncFilters()')+'\n'+handlerSource('function switchReader(','function bindShelf('),context);
 return {...context,renders,input};
}

test('reader handoff cancels an in-flight search and keeps the next reader idle after its late response',async()=>{
 let finish,searchSignal;
 const page=readerHandoff({executeSearch:(_query,signal)=>{searchSignal=signal;return new Promise(resolve=>{finish=resolve;});}});
 const pending=page.performSearch();
 assert.equal(page.state.searchBusy,true);
 page.switchReader('b',{handoff:true});
 assert.equal(searchSignal.aborted,true);
 assert.equal(page.state.reader,'b');
 assert.equal(page.input.value,'');
 assert.deepEqual(page.state.a,['a1','a2','a3','a4','a5']);
 assert.deepEqual(page.state.b,[]);
 assert.deepEqual(page.renders.at(-1),{query:'',results:[],busy:false,error:''});
 const renderCount=page.renders.length;
 finish([{id:'late-match'}]);await pending;
 assert.equal(page.renders.length,renderCount);
 assert.equal(page.state.searchBusy,false);
 assert.equal(page.state.searchResults.length,0);
});

test('reader handoff clears old search errors and prevents a queued search from starting',async()=>{
 let searches=0;
 const searchTimer=setTimeout(()=>{searches++;},5);
 const page=readerHandoff({searchTimer});
 page.state.searchError='Cannot reach the API.';
 page.switchReader('b',{handoff:true});
 await new Promise(resolve=>setTimeout(resolve,15));
 assert.equal(searches,0);
 assert.deepEqual(page.renders.at(-1),{query:'',results:[],busy:false,error:''});
});

test('a late response cannot replace a newer search even when its transport ignores abort',async()=>{
 const requests=new LatestRequests();let resolveOld;
 const old=requests.run('search',()=>new Promise(resolve=>{resolveOld=resolve;}));
 const rejected=assert.rejects(old,error=>error.name==='AbortError');
 assert.deepEqual(await requests.run('search',async()=>['new']),['new']);
 resolveOld(['old']);await rejected;
});

test('changing favorites cancels an outstanding recommendation',async()=>{
 const requests=new LatestRequests();let resolve;
 const pending=requests.run('recommend',()=>new Promise(done=>{resolve=done;}));
 const rejected=assert.rejects(pending,error=>error.name==='AbortError');
 requests.cancel('recommend');resolve(['stale book']);await rejected;
});

test('API metadata uses opaque IDs and a later search summary preserves full evidence',()=>{
 enableApiCatalogue();
 const [book]=cacheApiBooks([{id:'w_real',title:'Mistborn',author:'Author',year:null,coverUrl:null,tags:['heist']}],{full:true});
 assert.equal(byId('mistborn'),undefined);
 cacheApiBooks([{id:book.id,title:book.title,author:book.author,year:null,coverUrl:null,tags:[]}]);
 assert.deepEqual(byId(book.id).tags,['heist']);assert.equal(byId(book.id).detailsLoaded,true);
});

test('the API galaxy applies only viewport scaling and works without browser vectors',()=>{
 const results=[{book:{id:'bridge'}}];
 const galaxy={a:[{id:'a',x:-1,y:0}],b:[{id:'b',x:1,y:0}],bridges:[{id:'bridge',x:0,y:1}]};
 const {positions}=galaxyLayout(['a'],['b'],results,galaxy);
 assert.deepEqual(positions.get('a'),{x:85,y:197.5});
 assert.deepEqual(positions.get('b'),{x:675,y:197.5});
 assert.deepEqual(positions.get('bridge'),{x:380,y:325});
});

test('shared favorites draw one star and inconsistent coordinates are rejected',()=>{
 const galaxy={a:[{id:'shared',x:0,y:0}],b:[{id:'shared',x:0,y:0}],bridges:[]};
 assert.equal(galaxyLayout(['shared'],['shared'],[],galaxy).positions.size,1);
 galaxy.b[0].x=1;assert.throws(()=>galaxyLayout(['shared'],['shared'],[],galaxy),/Conflicting/);
});

test('API books render safely without years/covers or fixture cover requests',()=>{
 const [book]=cacheApiBooks([{id:'w_"><script>',title:'<script>bad</script>',author:'Author',year:null,coverUrl:null,tags:[]}],{full:true});
 const html=bookTile(book);
 assert(!html.includes('<script>'));assert(!html.includes('null'));assert(!html.includes('covers/'));
 assert(html.includes('&lt;script&gt;'));assert(html.includes('--cover-art:none'));
});

test('negative scores stay signed and partial shortlists can be shared',()=>{
 cacheApiBooks([{id:'seed',title:'Seed',author:'Author',tags:['heist'],year:null,coverUrl:null}],{full:true});
 const result={book:{id:'bridge',title:'Bridge',author:'Author',source:'api',tags:['heist']},fitA:-.12,fitB:.5,reasons:{a:{seedId:'seed',tags:['heist']}}};
 assert.equal(readerConnection(result,'a',['seed']).fit.label,'Similarity -0.12');
 assert(shortlistText([result]).includes('1. Bridge'));assert.throws(()=>shortlistText([]),/Find/);
});

test('opaque IDs named __proto__ remain ordinary per-book votes',()=>{
 const state={results:[{book:{id:'__proto__'}}],votes:{},choice:null};
 voteFor(state,'__proto__','a','yes');
 assert.equal(Object.hasOwn(state.votes,'__proto__'),true);
 assert.equal(state.votes.__proto__.a,'yes');assert.equal(Object.prototype.a,undefined);
});
