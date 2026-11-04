import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {readingShelf,shortlistCardHTML} from '../src/a/desk-presentation.mjs';
import {bothWilling} from '../src/a/desk-decision.mjs';
import {LatestRequests} from '../src/a/desk-api.mjs';

// Exercise the real page handlers with small view doubles. The doubles model
// only focus/scroll/control state; these tests do not claim visual browser QA.
const appSource=readFileSync(new URL('../src/a/app.mjs',import.meta.url),'utf8');
function handlers(start,end){
 const from=appSource.indexOf(start),to=appSource.indexOf(end,from);
 assert(from>=0&&to>from,'Page handlers moved; update the UX harness.');
 return appSource.slice(from,to);
}
function control(id,attributes=[]){
 return {id,attributes:new Set(attributes),disabled:false,toggleAttribute(name,enabled){this[name]=enabled;}};
}
function busyView({picking=false,pending=false,connecting=false,ready=false}={}){
 const controls=[control('pick',['data-book']),control('remove',['data-remove']),control('empty',['data-add-reader']),
  control('clear',['data-clear-reader']),control('reader',['data-reader']),control('step',['data-step']),
  control('filter',['data-filter']),control('nav-results'),control('nav-select'),control('undo-selection'),
  control('demo'),control('sample-inline'),control('pair-next'),control('search'),control('clear-query'),
  control('author',['data-search-author']),control('retry-search'),control('clear-search')];
 const byId=new Map(controls.map(button=>[button.id,button]));
 const context={state:{picking,pending,a:Array.from({length:ready?5:1},(_,index)=>`reader-a-${index}`),b:Array.from({length:ready?5:0},(_,index)=>`reader-b-${index}`)},apiConnection:{pending:connecting},
  $:selector=>byId.get(selector.slice(1))||null,
  $$:selector=>controls.filter(button=>selector.split(',').some(part=>part.startsWith('#')?button.id===part.slice(1):button.attributes.has(part.slice(1,-1))))};
 runInNewContext(handlers('function applyBusyState(){','async function connectApi(){'),context);
 return {...context,controls,byId};
}

test('connection, recommendation and pick loading each lock reader navigation while keeping cancellation available',()=>{
 for(const flags of [{connecting:true},{pending:true},{picking:true}]){
  const page=busyView({...flags,ready:true});page.applyBusyState();
  for(const id of ['pick','remove','empty','clear','reader','step','filter','nav-results','undo-selection','demo','sample-inline','pair-next','search','clear-query','author','retry-search','clear-search'])
   assert.equal(page.byId.get(id).disabled,true,`${id} must not change context during ${JSON.stringify(flags)}`);
  assert.equal(page.byId.get('nav-select').disabled,false,'Pick books must remain available to cancel and recover.');
 }
});

test('clearing an API search cancels a late result, restores the catalogue and keeps both shelves',async()=>{
 const requests=new LatestRequests(),renders=[],events=[],a=['first-pick'],b=['second-pick'];
 let resolveOld;
 const state={stage:'select',query:'Tolkien',filter:'mystery',searchResults:[],searchBusy:false,searchError:'',a,b};
 const search={value:state.query,focus:()=>events.push('focus-search')},clear={hidden:false};
 const render=()=>renders.push({query:state.query,busy:state.searchBusy,results:[...state.searchResults]});
 const context={state,api:{requests,search:()=>requests.run('search',()=>new Promise(resolve=>{resolveOld=resolve;}))},
  $:selector=>selector==='#search'?search:selector==='#clear-query'?clear:null,
  searchTimer:42,clearTimeout:timer=>events.push(`cancel-timer:${timer}`),syncFilters:()=>events.push('filters'),
  renderBooks:render,renderApiBooks:render};
 runInNewContext(handlers('function clearCatalogueSearch(','function syncFilters(){'),context);
 const pending=context.performSearch();
 assert.equal(renders.at(-1).busy,true);
 context.clearCatalogueSearch();resolveOld([{id:'stale-book'}]);await pending;
 assert.equal(state.query,'');assert.equal(search.value,'');assert.equal(clear.hidden,true);
 assert.equal(state.searchBusy,false);assert.equal(state.searchError,'');assert.equal(state.searchResults.length,0);
 assert.equal(state.filter,'mystery','Clearing text preserves the selected category.');
 assert.strictEqual(state.a,a);assert.strictEqual(state.b,b);
 assert.equal(renders.length,2,'A cancelled response must not redraw stale results.');
 assert.deepEqual(events,['cancel-timer:42','focus-search']);
 context.clearCatalogueSearch({resetFilter:true});assert.equal(state.filter,'all');assert(events.includes('filters'));
});

test('an idle render keeps intentionally unavailable actions disabled and restores editable search',()=>{
 for(const ready of [false,true]){
  const page=busyView({ready});page.byId.get('pair-next').disabled=!ready;
  page.byId.get('search').disabled=true;page.byId.get('clear-query').disabled=true;
  page.applyBusyState();
  assert.equal(page.byId.get('pair-next').disabled,!ready,'Shelf readiness is retained.');
  assert.equal(page.byId.get('nav-results').disabled,!ready,'Results become actionable only when both shelves are complete.');
  assert.equal(page.byId.get('search').disabled,false);
  assert.equal(page.byId.get('clear-query').disabled,false);
  assert.equal(page.byId.get('step').disabled,false);
 }
});

function readerView({mobile=false}={}){
 const events=[],state={reader:'a',pending:false,picking:false,query:'The Hobbit',filter:'all',a:['first-pick'],b:[],handoff:''};
 const search={value:state.query,focus:()=>events.push('focus'),scrollIntoView:()=>events.push('scroll-search')};
 const shelves={open:true},clearQuery={hidden:false};
 const context={state,apiConnection:{pending:false},compactViewport:{matches:mobile},shelvesOpen:true,
  $:selector=>({'#search':search,'#selected-shelves':shelves,'#clear-query':clearQuery}[selector]||null),
  readerName:reader=>reader==='a'?'Reader 1':'Reader 2',api:{requests:{cancel:lane=>events.push(`cancel:${lane}`)}},clearTimeout(){},searchTimer:null,
  syncFilters:()=>events.push('filters'),renderBooks:()=>events.push('books'),syncSelectionChrome:()=>events.push('chrome'),syncCatalogueSelection:()=>events.push('selection'),
  recorder:{record:()=>events.push('record')}};
 runInNewContext(handlers('function switchReader(','function bindShelf('),context);
 return Object.assign(context,{events,search,shelves,clearQuery});
}

test('reader switching is guarded during hydration, recommendation and connection, including calls outside disabled buttons',()=>{
 for(const flag of ['picking','pending','connecting']){
  const page=readerView({mobile:true});
  if(flag==='connecting')page.apiConnection.pending=true;else page.state[flag]=true;
  page.switchReader('b',{handoff:true});
  assert.equal(page.state.reader,'a');assert.equal(page.search.value,'The Hobbit');
  assert.deepEqual(page.events,[]);assert.equal(page.shelves.open,true);
 }
});

test('editing an empty shelf slot selects its reader and reveals search without losing the other shelf',()=>{
 const page=readerView({mobile:true}),empty={dataset:{addReader:'b'}};
 page.$$=selector=>selector==='[data-add-reader]'?[empty]:[];
 runInNewContext(handlers('function bindShelf(','function bindSelect(){'),page);
 page.bindShelf({});empty.onclick();
 assert.equal(page.state.reader,'b');assert.deepEqual(page.state.a,['first-pick']);
 assert.equal(page.state.query,'The Hobbit','Manual switching can find a book shared by both readers.');
 assert.equal(page.shelves.open,false);assert.equal(page.shelvesOpen,false);
 assert.deepEqual(page.events.slice(-3),['focus','scroll-search','record']);
});

test('editing the already active reader also closes a phone shelf and reveals search',()=>{
 const page=readerView({mobile:true});page.switchReader('a');
 assert.equal(page.shelves.open,false);assert.deepEqual(page.events,['focus','scroll-search']);
 assert.equal(page.state.query,'The Hobbit');
});

test('leaving results cancels requests and restores the top of selection while same-stage editing preserves position',()=>{
 for(const stage of ['results','select']){
  const events=[],a=['opaque,first'],b=['__proto__'];
  const context={state:{stage,a,b,query:'old query',pending:true,picking:true,requestError:'old error',searchBusy:true,searchError:'old search error',searchResults:['old'],filter:'mystery'},
   api:{requests:{cancel:lane=>events.push(`cancel:${lane}`)}},clearTimeout:()=>events.push('clear-timer'),searchTimer:123,
   render:()=>events.push('render'),window:{scrollTo:options=>events.push(`scroll:${options.top}`)},titleFocus:()=>events.push('focus-title')};
  runInNewContext(handlers('function editPicks(){','function selectionStatus(){'),context);context.editPicks();
  assert.deepEqual(events.slice(0,4),['cancel:recommend','cancel:search','cancel:favorites','cancel:pick']);
  assert.equal(context.state.stage,'select');assert.equal(context.state.pending,false);assert.equal(context.state.picking,false);
  assert.equal(context.state.query,'');assert.equal(context.state.searchBusy,false);assert.equal(context.state.searchError,'');
  assert.strictEqual(context.state.a,a);assert.strictEqual(context.state.b,b);
  assert.equal(events.includes('scroll:0'),stage==='results');
  assert.equal(events.at(-1),'focus-title');
  if(stage==='results')assert(events.indexOf('render')<events.indexOf('scroll:0'));
 }
});

function detailView(){
 const events=[],dialog={dataset:{bookId:'first'},scrollTop:580,open:true};
 let evidence={open:true};
 const body={set innerHTML(value){this.value=value;evidence={open:false};},get innerHTML(){return this.value;}};
 const focus={focus:()=>events.push('focus')};
 const context={state:{results:[{book:{id:'first'}},{book:{id:'second'}}]},detailObserver:{disconnect:()=>events.push('disconnect')},detailMode:'recommendation',
  $:selector=>selector==='#detail-dialog'?dialog:selector==='#detail-body'?body:selector==='#detail-evidence-panel'?evidence:focus,
  $$:()=>[],detailHTML:result=>result.book.id,bindDetail:id=>events.push(`bind:${id}`),renderExplorer:()=>events.push('explorer'),revealItems:()=>null};
 runInNewContext(handlers('function refreshDetail(','function openDetail('),context);
 return {...context,dialog,body,events,evidence:()=>evidence};
}

test('browsing a different book resets dialog position and does not carry the previous evidence disclosure',()=>{
 const page=detailView();page.refreshDetail('second','#detail-title');
 assert.equal(page.dialog.scrollTop,0);assert.equal(page.dialog.dataset.bookId,'second');
 assert.equal(page.body.innerHTML,'second');assert.equal(page.evidence().open,false);
 assert(page.events.includes('bind:second'));assert.equal(page.events.at(-1),'focus');
});

test('responding to the same book preserves dialog position and an expanded evidence disclosure',()=>{
 const page=detailView();page.refreshDetail('first','[data-vote="a:yes"]');
 assert.equal(page.dialog.scrollTop,580);assert.equal(page.evidence().open,true);
 assert.equal(page.body.innerHTML,'first');assert.equal(page.events.at(-1),'focus');
});

test('an empty recommendation response from map view reveals the shortlist recovery message and selects its tab',()=>{
 const list={hidden:true,innerHTML:''},map={hidden:false},decision={innerHTML:'old decision'};
 const tabs=['shortlist','map'].map(view=>({dataset:{resultsView:view},attributes:{},setAttribute(name,value){this.attributes[name]=value;}}));
 const context={state:{view:'map',pending:false,results:[]},
  $:selector=>({'#result-list':list,'#taste-map-panel':map,'#decision-panel':decision}[selector]||null),
  $$:selector=>selector==='[data-results-view]'?tabs:[],recorder:{record(){}},
  resultMap:{update(){assert.fail('An empty response must not initialize map geometry.');}}};
 runInNewContext(handlers('function setResultsView(','function rankingNote(){')+'\n'+handlers('function renderResultsContent(){','function mapNode('),context);
 context.renderResultsContent();
 assert.equal(context.state.view,'shortlist');assert.equal(list.hidden,false);assert.equal(map.hidden,true);
 assert.match(list.innerHTML,/No new books/);assert.match(list.innerHTML,/Your favorites are kept/);
 assert.equal(decision.innerHTML,'');
 assert.equal(tabs[0].attributes['aria-selected'],'true');assert.equal(tabs[0].tabIndex,0);
 assert.equal(tabs[1].attributes['aria-selected'],'false');assert.equal(tabs[1].tabIndex,-1);
});

test('Keep looking and closing a reviewed choice restore focus to the current visible results view',()=>{
 for(const view of ['shortlist','map']){
  const events=[],list={hidden:view!=='shortlist'},reopen={addEventListener(_type,listener){this.click=listener;}};
  const card={focus(){assert.equal(list.hidden,false,'A hidden shortlist card cannot receive focus.');events.push('focus:card');}};
  const node={focus(){assert.equal(view,'map');events.push('focus:map');}};
  const context={state:{view,selected:'opaque-book',deferred:true},
   $:selector=>selector==='#reopen-choice'?reopen:selector==='#result-list'?list:null,
   renderResultsContent:()=>events.push('render'),mapNode:id=>id==='opaque-book'?node:null,
   findData:(_attribute,id)=>id==='opaque-book'?card:null};
  runInNewContext(handlers('function bindDecision(){','function renderResultsContent(){')+'\n'+handlers('function restoreDetailFocus(','function opinionNote('),context);
  context.bindDecision();reopen.click();
  assert.equal(context.state.deferred,false);
  assert.deepEqual(events,['render',view==='map'?'focus:map':'focus:card']);
  events.length=0;context.restoreDetailFocus({kind:'result',id:'opaque-book'});
  assert.deepEqual(events,[view==='map'?'focus:map':'focus:card']);
 }
});

test('empty shelf slots expose five named actions for the correct reader',()=>{
 const html=readingShelf([],'b');
 assert.equal((html.match(/<button\b/g)||[]).length,5);
 assert.equal((html.match(/data-add-reader="b"/g)||[]).length,5);
 for(let index=1;index<=5;index++)assert(html.includes(`aria-label="Choose favorite ${index} for Reader 2"`));
 assert(!html.includes('data-remove='));
});

test('shortlist cards escape opaque IDs and all metadata while preserving signed model scores',()=>{
 const result={book:{id:'w_"><img src=x>',title:'<script>Title</script>',author:'A & "B"',source:'api',year:null,coverUrl:null,color:'#365781'},
  fitA:-.12,fitB:.71,reasons:{a:{seedTitle:'<img src=x onerror=bad>',tags:['<script>theme</script>']},b:{seedTitle:'Reader 2 & pick',tags:['mystery']}}};
 const before=JSON.stringify(result),html=shortlistCardHTML(result,0,{api:true});
 assert(!html.includes('<script>'));assert(!html.includes('<img'));
 assert(html.includes('data-result="w_&quot;&gt;&lt;img src=x&gt;"'));
 assert(html.includes('&lt;script&gt;Title&lt;/script&gt;'));assert(html.includes('A &amp; &quot;B&quot;'));
 assert(html.includes('&lt;script&gt;theme&lt;/script&gt;'));assert(html.includes('Similarity -0.12'));
 assert(html.includes('View reasons & respond'));assert(!html.includes('No response yet'));
 assert.equal(JSON.stringify(result),before,'Presentation must not modify server data.');
});

test('an initial or one-sided response does not push an empty decision banner ahead of the books',()=>{
 const context={state:{results:[{book:{id:'one',title:'One',author:'Author'}}],votes:{},choice:null,deferred:false},bothWilling,apiMode:false,escape:String};
 runInNewContext(handlers('function decisionHTML(){','function feedbackKey('),context);
 assert.equal(context.decisionHTML(),'');
 context.state.votes.one={a:'yes'};assert.equal(context.decisionHTML(),'');
 context.state.votes.one.b='yes';assert.match(context.decisionHTML(),/1 book you both want/);
 context.state.choice='one';assert.match(context.decisionHTML(),/Your next read/);
 context.state.choice=null;context.state.deferred=true;assert.match(context.decisionHTML(),/Keep looking/);
});

test('closing connection details prefers the visible relation action to a collapsed projection node',()=>{
 const action={id:'relation-action'},nav={id:'title-navigation'},node={id:'collapsed-node'},container={};
 const context={$:()=>container,findData:attribute=>({'data-map-inspect':action,'data-map-pick':nav,'data-id':node}[attribute])};
 runInNewContext(handlers('function mapNode(','function restoreDetailFocus('),context);
 assert.strictEqual(context.mapNode('book'),action);
 context.findData=attribute=>attribute==='data-map-pick'?nav:attribute==='data-id'?node:null;
 assert.strictEqual(context.mapNode('book'),nav);
});
