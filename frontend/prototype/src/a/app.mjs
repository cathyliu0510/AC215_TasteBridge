import {CATALOG,DEMO,byId,recommend,sessionFromURL,seedQuery} from './shared/engine.mjs';
import {enableApiCatalogue} from './shared/catalog.mjs';
import {ApiDesk,API_SAMPLE} from './desk-api.mjs';
import {$,$$,escape,brand,svg,bookTile,reasonHTML,bindDialog,toast,makeRecorder} from './shared/ui.mjs';
import {DeskGalaxy} from './desk-galaxy.mjs';
import {reconcileRanking} from './desk-ranking.mjs';
import {installBridge} from './shared/bridge.mjs';
import {VOTE_OPTIONS,voteLabel,bothWilling,clearDecision,voteFor,confirmChoice,deferChoice} from './desk-decision.mjs';
import {readingShelf,readerName,catalogueSelection,readerEvidenceHTML,shortlistCardHTML} from './desk-presentation.mjs';
import {themeFavorites,favoriteReferences,shortlistText,copyShortlistText,sampleFit} from './desk-interactions.mjs';

document.documentElement.dataset.embedded=String(window.parent!==window);
const apiMode=new URLSearchParams(location.search).get('api')==='1';
if(apiMode)enableApiCatalogue();
const api=apiMode&&/^https?:$/.test(location.protocol)?new ApiDesk(new URL('/api',location.href).href):null;
const apiConnection={pending:apiMode,health:null,error:''};
const input=sessionFromURL({api:apiMode});
const findData=(attribute,value,root=document)=>$$(`[${attribute}]`,root).find(node=>node.getAttribute(attribute)===value)||null;
let searchTimer,connectionEpoch=0;
const state={...input,reader:'a',stage:'select',view:new URLSearchParams(location.search).get('view')==='map'?'map':'shortlist',query:'',filter:'all',mode:input.mode,results:[],selected:null,votes:{},choice:null,deferred:false,undo:null,handoff:'',exploration:null,samplePair:false,pending:false,picking:false,searchBusy:false,searchError:'',searchResults:[],requestError:'',requestedMode:input.mode,galaxy:null,topShelves:null,modelVersion:null,feedback:{}};
const recorder=makeRecorder('reading-desk');
const seenReveals=new Set();
const compactViewport=matchMedia('(max-width: 760px)');
const motionTimers=new WeakMap();
let shelvesOpen=!compactViewport.matches;
let resultMap,pageObserver,detailObserver,lastDetailTrigger,explorerTrigger,shelfObserver,sampleTrigger;
let detailMode='recommendation';
compactViewport.addEventListener('change',event=>{shelvesOpen=!event.matches;const shelves=$('#selected-shelves');if(shelves)shelves.open=shelvesOpen;const options=$('#result-options');if(options)options.open=!event.matches;});
if(!apiMode&&state.a.length===5&&state.b.length===5){state.stage='results';state.results=recommend(state.a,state.b,state.mode);state.selected=state.results[0].book.id;}

function header(){return `<header class="site-header"><a class="brand" href="./?v=20261104.4&api=${apiMode?1:0}" aria-label="TasteBridge home">${brand}</a><nav class="site-nav" aria-label="Main navigation"><button id="nav-select" class="${state.stage==='select'?'active':''}">Pick books</button><button id="nav-results" class="${state.stage==='results'?'active':''}">Recommendations</button><a class="project-link" href="/project/">Project</a></nav></header>`;}
function footer(){return `<footer class="footer-line"><span>${apiMode?`Connected demo · ${apiConnection.health?.numBooks??'…'} books${apiConnection.health?.modelVersion==='sample-shelf-toy-v1'?' · Sample model':''}`:`Frontend prototype · ${CATALOG.length} sample books`}</span><div class="footer-actions"><a class="project-link" href="/project/">About the project</a><a id="other-version" class="other-version" href="../b/?v=20261104.4&${apiMode?'':seedQuery(state.a,state.b,state.mode)}">Compare version B</a>${apiMode?'<a href="./?api=0">Use offline demo</a>':''}</div></footer>`;}
function connectionHTML(){
 if(!apiMode)return '';
 if(apiConnection.pending)return '<div class="api-status" role="status"><span class="loading-dot" aria-hidden="true"></span>Connecting to the book catalogue…</div>';
 if(apiConnection.error)return `<div class="api-status api-error" role="status"><p>${escape(apiConnection.error)}</p><button id="retry-api" class="secondary">Retry connection</button></div>`;
 return '';
}
function requestStatusHTML(){
 if(state.pending)return '<div class="api-status" role="status"><span class="loading-dot" aria-hidden="true"></span>Finding books for both of you…</div>';
 return state.requestError?`<div class="api-status api-error" role="status"><p>${escape(state.requestError)}</p><button id="retry-recommend" class="secondary">Try again</button><button id="replace-picks" class="quiet">Change books</button></div>`:'';
}
function applyBusyState(){
 const busy=apiConnection.pending||state.pending||state.picking;
 $$('[data-book],[data-remove],[data-add-reader],[data-clear-reader],[data-reader],[data-step],[data-filter],[data-search-author],#retry-search,#clear-search,#nav-results,#undo-selection,#demo,#sample-inline,#pair-next').forEach(button=>{if(busy)button.disabled=true;});
 $('#search')?.toggleAttribute('disabled',busy);
 if($('#nav-results'))$('#nav-results').disabled=busy||state.a.length!==5||state.b.length!==5;
 if($('#clear-query'))$('#clear-query').disabled=busy;
 if($('#retry-api'))$('#retry-api').onclick=connectApi;
 if($('#retry-recommend'))$('#retry-recommend').onclick=()=>showResults({mode:state.requestedMode});
 if($('#replace-picks'))$('#replace-picks').onclick=editPicks;
}
async function connectApi(){
 const epoch=++connectionEpoch;apiConnection.pending=true;apiConnection.error='';render();
 try{
  if(!api)throw new Error('Open the connected demo through the local app server.');
  const health=await api.health();if(epoch!==connectionEpoch)return;
  if(apiConnection.health&&apiConnection.health.modelVersion!==health.modelVersion){enableApiCatalogue();invalidateInput();}
  apiConnection.health=health;
  const ids=[...new Set([...state.a,...state.b])];
  const metadata=await Promise.allSettled(ids.map(id=>api.book(id)));if(epoch!==connectionEpoch)return;
  const missing=ids.filter((id,index)=>metadata[index].status==='rejected'&&metadata[index].reason?.status===404);
  const failed=metadata.find(item=>item.status==='rejected'&&item.reason?.status!==404);if(failed)throw failed.reason;
  if(missing.length){state.a=state.a.filter(id=>!missing.includes(id));state.b=state.b.filter(id=>!missing.includes(id));state.handoff='Some books in this link are unavailable. Your other favorites are kept.';}
  apiConnection.pending=false;render();
  if(state.a.length===5&&state.b.length===5)await showResults();
 }catch(error){if(epoch!==connectionEpoch||error.name==='AbortError')return;apiConnection.pending=false;apiConnection.error=error.message;render();}
}
function revealItems(nodes,context,root=null){
 if(typeof IntersectionObserver!=='function'||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
 const observer=new IntersectionObserver(entries=>{for(const entry of entries){if(!entry.isIntersecting)continue;entry.target.classList.add('is-revealed');seenReveals.add(entry.target.dataset.revealKey);observer.unobserve(entry.target);}},{root,threshold:.08,rootMargin:'0px 0px 24px 0px'});
 nodes.forEach((node,index)=>{const key=`${context}:${node.dataset.book||node.dataset.result||index}`;if(seenReveals.has(key))return;node.dataset.revealKey=key;node.classList.add('reveal-item');node.style.setProperty('--reveal-delay',`${index%4*35}ms`);observer.observe(node);});
 return observer;
}
function render(){
 pageObserver?.disconnect();detailObserver?.disconnect();shelfObserver?.disconnect();resultMap?.destroy();resultMap=null;
 $('#app').innerHTML=header()+`<main class="desk-main"><nav class="journey-progress" aria-label="Your shared reading journey">${journeyProgressHTML()}</nav>${connectionHTML()}${requestStatusHTML()}${state.stage==='select'?selectHTML():resultsHTML()}${footer()}</main><dialog id="detail-dialog" class="detail-dialog" aria-labelledby="detail-title"><button class="close-dialog" aria-label="Close book details">${svg('close')}</button><div id="detail-body"></div></dialog><dialog id="sample-dialog" class="flow-dialog" aria-labelledby="sample-title"><h2 id="sample-title">Try a sample pair?</h2><p>This replaces the favorites you have chosen with an example pair for exploring the demo.</p><div class="flow-actions"><button id="keep-favorites" class="secondary">Keep my books</button><button id="use-sample-pair" class="primary">Use sample pair</button></div></dialog>`;
 $$('a.project-link').forEach(link=>link.addEventListener('click',()=>{link.href=`/project/?${seedQuery(state.a,state.b,state.mode,{api:apiMode})}`;}));
 $('#nav-select').onclick=editPicks;
 $('#nav-results').onclick=()=>{if(state.stage==='results'){window.scrollTo({top:0,behavior:'instant'});titleFocus();return;}if(state.a.length!==5||state.b.length!==5)return;showResults();};
 const dialog=$('#detail-dialog');bindDialog(dialog);$('.close-dialog').onclick=()=>dialog.close();
 dialog.addEventListener('close',()=>{const trigger=lastDetailTrigger;state.exploration=null;requestAnimationFrame(()=>restoreDetailFocus(trigger));});
 dialog.addEventListener('cancel',event=>{if(detailMode==='recommendation'&&state.exploration){event.preventDefault();closeExplorer();}});
 dialog.addEventListener('keydown',event=>{if(detailMode!=='recommendation'||state.exploration||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey||event.target.closest('input,textarea,select,button,a,summary,[contenteditable]'))return;if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();navigateCandidate(event.key==='ArrowLeft'?-1:1);}});
 bindJourneyProgress();
 const sampleDialog=$('#sample-dialog');bindDialog(sampleDialog);$('#keep-favorites').onclick=()=>sampleDialog.close();$('#use-sample-pair').onclick=loadSamplePair;sampleDialog.addEventListener('close',()=>{if(sampleTrigger?.isConnected)sampleTrigger.focus({preventScroll:true});});
 if(state.stage==='select')bindSelect();else bindResults();
 trackShelfHeight();applyBusyState();
}
function journeyProgressHTML(){
 const current=state.stage==='results'?'results':state.reader;
 return [['a','Reader 1'],['b','Reader 2'],['results','Choose together']].map(([step,label],index)=>`<button data-step="${step}" ${current===step?'aria-current="step"':''} ${step==='results'&&(state.a.length!==5||state.b.length!==5)?'disabled':''}><span class="step-index">${String(index+1).padStart(2,'0')}</span><span class="step-label">${label}${step==='results'?'':` <small>${state[step].length}/5</small>`}</span></button>`).join('');
}
function bindJourneyProgress(){
 $$('[data-step]').forEach(button=>button.onclick=()=>{const step=button.dataset.step;if(step==='results'){if(state.a.length===5&&state.b.length===5)showResults();return;}if(state.stage==='select'){switchReader(step);return;}state.reader=step;editPicks();});
}
function updateJourneyProgress(){const progress=$('.journey-progress');if(!progress)return;progress.innerHTML=journeyProgressHTML();bindJourneyProgress();}
function trackShelfHeight(){
 const panel=$('.pair-panel');document.documentElement.style.removeProperty('--shelf-height');if(!panel)return;
 const measure=()=>document.documentElement.style.setProperty('--shelf-height',`${compactViewport.matches?Math.ceil(panel.getBoundingClientRect().height):0}px`);
 measure();if(typeof ResizeObserver==='function'){shelfObserver=new ResizeObserver(measure);shelfObserver.observe(panel);}
}
function requestSamplePair(trigger){
 if(state.a.length||state.b.length){sampleTrigger=trigger;$('#sample-dialog').showModal();$('#keep-favorites').focus();return;}
 loadSamplePair();
}
async function loadSamplePair(){
 if(apiMode){
  if(apiConnection.health?.modelVersion!=='sample-shelf-toy-v1')return;
  state.picking=true;state.searchError='';render();
  try{await api.favorites(API_SAMPLE.a,API_SAMPLE.b);}
  catch(error){if(error.name==='AbortError')return;state.picking=false;state.searchError=error.message;render();return;}
  state.picking=false;
 }
 const sample=apiMode?API_SAMPLE:DEMO;
 state.a=[...sample.a];state.b=[...sample.b];state.samplePair=true;state.undo=null;state.exploration=null;state.handoff='';clearDecision(state);recorder.record('use_demo');await showResults();
}

function titleFocus(){$('#page-title')?.focus({preventScroll:true});}
function editPicks(){const changedStage=state.stage!=='select';api?.requests.cancel('recommend');api?.requests.cancel('search');api?.requests.cancel('favorites');api?.requests.cancel('pick');state.picking=false;clearTimeout(searchTimer);state.pending=false;state.requestError='';state.stage='select';state.query='';state.searchResults=[];state.searchBusy=false;state.searchError='';state.filter='all';state.exploration=null;render();if(changedStage)window.scrollTo({top:0,behavior:'instant'});titleFocus();}
function selectionStatus(){if(state.a.length===5&&state.b.length===5)return 'Both shelves are ready. Find your shared reads.';const count=state[state.reader].length;return count===5?`${readerName(state.reader)}’s shelf is ready.`:`Choose ${5-count} more ${count===4?'favorite':'favorites'} for ${readerName(state.reader)}.`;}

function continueLabel(){if(state.a.length===5&&state.b.length===5)return 'Find our shared reads';if(state[state.reader].length<5){const remaining=5-state[state.reader].length;return `Choose ${remaining} more ${remaining===1?'book':'books'}`;}return `Continue to ${readerName(state.reader==='a'?'b':'a')}`;}

function readerShelfHTML(reader){return `<section class="reader-summary reader-${reader} ${state.reader===reader?'active':''}"><div class="summary-head"><strong>${readerName(reader)} <span>${state[reader].length}/5</span></strong><button data-reader="${reader}" aria-label="Edit ${readerName(reader)} favorites">${state.reader===reader?'Editing':'Edit'}</button></div><div class="seed-slots">${readingShelf(state[reader],reader)}</div><div class="shelf-actions"><button class="quiet" data-clear-reader="${reader}" ${state[reader].length?'':'disabled'}>Clear ${readerName(reader)}</button></div></section>`;}
function selectHTML(){
 return `<section class="intro"><div><h1 id="page-title" tabindex="-1">A book for both of you.</h1><p>Choose five favorites each to build your shared shortlist.</p></div><button id="demo" class="sample-button" ${apiMode&&apiConnection.health?.modelVersion!=='sample-shelf-toy-v1'?'hidden':''}>Try a sample pair ${svg('reset')}</button></section>
 <div class="desk-workspace"><section class="catalogue reader-${state.reader}" aria-labelledby="pick-title">
 <div class="section-top"><h2 id="pick-title">${readerName(state.reader)}’s favorites</h2><div class="reader-tabs" role="group" aria-label="Reader choosing books">${['a','b'].map(reader=>`<button class="reader-${reader} ${state.reader===reader?'active':''}" data-reader="${reader}" aria-pressed="${state.reader===reader}">${readerName(reader)} <span>${state[reader].length}/5</span></button>`).join('')}</div></div>
 <p id="selection-status" class="selection-status" role="status">${selectionStatus()}</p><p id="handoff-note" class="handoff-note" role="status">${escape(state.handoff)}</p>
 <div class="search-shell"><label class="search-field">${svg('search')}<span class="sr-only">Search by book title or author</span><input id="search" maxlength="100" type="search" placeholder="Search titles or authors" autocomplete="off" value="${escape(state.query)}"></label><button id="clear-query" class="search-clear" aria-label="Clear search" ${state.query?'':'hidden'}>${svg('close')}</button></div>
 <div class="catalogue-toolbar"><div class="filter-list" role="group" aria-label="Book category" ${apiMode?'hidden':''}>${[['all','All books'],['fantasy','Fantasy'],['mystery','Mystery'],['bridge','Fantasy & mystery']].map(([id,name])=>`<button data-filter="${id}" class="${state.filter===id?'active':''}" aria-pressed="${state.filter===id}">${name}</button>`).join('')}</div><span id="catalogue-count" class="catalogue-count"></span></div>
 <p id="catalogue-feedback" role="status"></p><div id="book-grid" class="book-grid"></div><p class="catalogue-footnote">${apiMode?'':'23-book sample catalogue. '}Both readers can choose the same book.</p>
 </section><aside class="pair-panel" aria-label="Selected favorites"><details id="selected-shelves" class="shelf-disclosure" ${shelvesOpen?'open':''}><summary><span>Your books</span><span class="shelf-counts">${shelfCountsHTML()}</span></summary><div class="shelf-content">${['a','b'].map(readerShelfHTML).join('')}<button id="undo-selection" class="quiet" ${state.undo?'':'hidden'}>Undo last change</button></div></details><button id="pair-next" class="pair-next" ${state[state.reader].length<5?'disabled':''}>${continueLabel()} <span aria-hidden="true">→</span></button></aside></div>`;
}
function shelfCountsHTML(){return ['a','b'].map((reader,index)=>`<span aria-label="${readerName(reader)} ${state[reader].length} of 5 books"><i aria-hidden="true">${index+1}</i>${state[reader].length}/5</span>`).join('');}
function bookPickHTML(book){const view=catalogueSelection(book,state.a,state.b,state.reader);return `<button class="book-pick ${view.selected?'is-picked':''}" data-book="${escape(book.id)}" aria-label="${escape(view.ariaLabel)}" aria-pressed="${view.selected}">${bookTile(book,{selected:view.selected})}<span class="book-pick-note">${escape(view.label)}</span></button>`;}
function renderBooks(){
 pageObserver?.disconnect();
 if(apiMode){renderApiBooks();return;}
 const books=CATALOG.filter(book=>(state.filter==='all'||book.kind===state.filter)&&`${book.title} ${book.author}`.toLowerCase().includes(state.query.toLowerCase().trim()));
 $('#catalogue-count').textContent=`${books.length} ${books.length===1?'book':'books'}`;
 const category={fantasy:'Fantasy',mystery:'Mystery',bridge:'Fantasy / Mystery'}[state.filter],query=state.query.trim();
 $('#catalogue-feedback').textContent=query?`${books.length} ${books.length===1?'match':'matches'} for “${query}”${category?` in ${category}`:''}.`:category?`${books.length} ${category} books.`:'';
 $('#book-grid').innerHTML=books.length?books.map(bookPickHTML).join(''):`<div class="empty-message"><p>That book is not in this sample catalogue.</p><p>You can browse the 23 sample books or try an example pair.</p><div class="empty-actions"><button id="clear-search" class="secondary">Browse sample books</button><button id="empty-sample" class="primary">Try a sample pair</button></div></div>`;
 $$('[data-book]').forEach(button=>button.onclick=()=>toggleBook(button.dataset.book));
 $('#clear-search')?.addEventListener('click',()=>clearCatalogueSearch({resetFilter:true}));
 $('#empty-sample')?.addEventListener('click',event=>requestSamplePair(event.currentTarget));
 pageObserver=revealItems($$('[data-book]'),'catalogue');
}
function renderApiBooks(){
 const grid=$('#book-grid');if(!grid)return;
 const books=state.searchResults;
 $('#catalogue-count').textContent=state.query.trim()?`${books.length} ${books.length===1?'match':'matches'}${books.length===25?' shown':''}`:'';
 $('#catalogue-feedback').textContent=state.picking?'Adding your favorite…':'';
 grid.setAttribute('aria-busy',String(state.searchBusy));
 grid.innerHTML=state.searchBusy?'<div class="empty-message" role="status"><span class="loading-dot" aria-hidden="true"></span> Searching the catalogue…</div>':state.searchError?`<div class="empty-message api-error" role="status"><p>${escape(state.searchError)}</p><button id="retry-search" class="secondary">Retry search</button></div>`:books.length?books.map(bookPickHTML).join(''):state.query.trim()?'<div class="empty-message"><p>No books match that title or author.</p><button id="clear-search" class="secondary">Clear search</button></div>':`<div class="catalogue-start">${svg('search')}<h3>${state[state.reader].length?'Find another favorite':'Start with a favorite'}</h3><p>Search a title or author to add to your shelf.</p>${apiConnection.health?.modelVersion==='sample-shelf-toy-v1'?`<div class="search-suggestions"><span>Try an author</span>${['Tolkien','Agatha Christie','Neil Gaiman'].map(author=>`<button data-search-author="${escape(author)}">${escape(author)}</button>`).join('')}</div>`:''}</div>`;
 $$('[data-book]').forEach(button=>{button.disabled=state.picking||apiConnection.pending;button.onclick=()=>toggleBook(button.dataset.book);});
 $$('[data-search-author]').forEach(button=>button.onclick=()=>{state.query=button.dataset.searchAuthor;$('#search').value=state.query;$('#clear-query').hidden=false;performSearch();$('#search').focus({preventScroll:true});});
 $('#retry-search')?.addEventListener('click',performSearch);
 $('#clear-search')?.addEventListener('click',()=>clearCatalogueSearch());
 pageObserver=revealItems($$('[data-book]'),'api-catalogue');
 applyBusyState();
}
function clearCatalogueSearch({resetFilter=false}={}){
 api?.requests.cancel('search');clearTimeout(searchTimer);
 state.query='';state.searchResults=[];state.searchBusy=false;state.searchError='';
 if(resetFilter){state.filter='all';syncFilters();}
 $('#search').value='';if($('#clear-query'))$('#clear-query').hidden=true;
 renderBooks();$('#search').focus({preventScroll:true});
}
async function performSearch(){
 const query=state.query;state.searchBusy=true;state.searchError='';renderApiBooks();
 try{const books=await api.search(query);if(state.stage!=='select'||query!==state.query)return;state.searchResults=books;state.searchBusy=false;renderApiBooks();}
 catch(error){if(error.name==='AbortError')return;if(query!==state.query||state.stage!=='select')return;state.searchBusy=false;state.searchError=error.message;renderApiBooks();}
}
function syncFilters(){$$('[data-filter]').forEach(button=>{button.classList.toggle('active',button.dataset.filter===state.filter);button.setAttribute('aria-pressed',String(button.dataset.filter===state.filter));});}
function syncCatalogueSelection(){
 $$('[data-book]').forEach(button=>{
  const book=byId(button.dataset.book),view=catalogueSelection(book,state.a,state.b,state.reader);
  button.classList.toggle('is-picked',view.selected);button.setAttribute('aria-pressed',String(view.selected));button.setAttribute('aria-label',view.ariaLabel);$('.book-pick-note',button).textContent=view.label;
  const check=$('.book-check',button);if(view.selected&&!check)$('.book-object',button).insertAdjacentHTML('beforeend',`<span class="book-check">${svg('check')}</span>`);else if(!view.selected)check?.remove();
 });
}
function syncSelectionChrome(){
 updateJourneyProgress();
 $('#pick-title').textContent=`${readerName(state.reader)}’s favorites`;
 $('.catalogue').classList.toggle('reader-a',state.reader==='a');$('.catalogue').classList.toggle('reader-b',state.reader==='b');
 $$('[data-reader]').forEach(button=>{const reader=button.dataset.reader;if(button.closest('.reader-tabs')){button.innerHTML=`${readerName(reader)} <span>${state[reader].length}/5</span>`;button.classList.toggle('active',state.reader===reader);button.setAttribute('aria-pressed',String(state.reader===reader));}else button.textContent=state.reader===reader?'Editing':'Edit';});
 ['a','b'].forEach(reader=>{const summary=$(`.reader-summary.reader-${reader}`);summary.classList.toggle('active',state.reader===reader);$('.summary-head strong',summary).innerHTML=`${readerName(reader)} <span>${state[reader].length}/5</span>`;$('[data-clear-reader]',summary).disabled=state[reader].length===0;});
 $('.shelf-counts').innerHTML=shelfCountsHTML();$('#selection-status').textContent=selectionStatus();$('#handoff-note').textContent=state.handoff;
 $('#nav-results').disabled=state.a.length!==5||state.b.length!==5;
 $('#pair-next').disabled=state[state.reader].length<5;$('#pair-next').innerHTML=`${continueLabel()} <span aria-hidden="true">→</span>`;$('#undo-selection').hidden=!state.undo;
 $('#other-version').href=`../b/?v=20261104.4&${apiMode?'':seedQuery(state.a,state.b,state.mode)}`;
}
function updateShelf(reader){const summary=$(`.reader-summary.reader-${reader}`);$('.seed-slots',summary).innerHTML=readingShelf(state[reader],reader);bindShelf(summary);}
function motionHook(node,name,duration=450){
 if(!node||matchMedia('(prefers-reduced-motion: reduce)').matches||document.documentElement.classList.contains('reduce-motion'))return;
 clearTimeout(motionTimers.get(node));node.classList.remove('just-added','just-removed','detail-browse-next','detail-browse-prev','choice-arrived');
 void node.offsetWidth;node.classList.add(name);motionTimers.set(node,setTimeout(()=>{if(node.isConnected)node.classList.remove(name);motionTimers.delete(node);},duration));
}
function switchReader(reader,{handoff=false}={}){
 if(state.pending||state.picking||apiConnection.pending)return;
 if(state.reader===reader){focusCatalogueSearch();return;}
 state.reader=reader;state.handoff=handoff?`${readerName(reader)}, your turn. The first five are kept.`:`Now editing ${readerName(reader)}.`;
 if(handoff){
  api?.requests.cancel('search');clearTimeout(searchTimer);
  state.query='';state.filter='all';state.searchResults=[];state.searchBusy=false;state.searchError='';
  $('#search').value='';if($('#clear-query'))$('#clear-query').hidden=true;syncFilters();renderBooks();
 }
 syncSelectionChrome();syncCatalogueSelection();focusCatalogueSearch({handoff});recorder.record('switch_reader',{reader});
}
function focusCatalogueSearch({handoff=false}={}){
 const search=$('#search');
 if(compactViewport.matches){
  shelvesOpen=false;$('#selected-shelves').open=false;
  search.focus({preventScroll:true});search.scrollIntoView({block:'center',behavior:'instant'});
 }else search.focus({preventScroll:!handoff});
}
function bindShelf(container){
 $$('[data-add-reader]',container).forEach(button=>button.onclick=()=>switchReader(button.dataset.addReader));
 $$('[data-remove]',container).forEach(button=>button.onclick=()=>{
  const reader=button.closest('.reader-summary').classList.contains('reader-a')?'a':'b',id=button.dataset.remove,index=state[reader].indexOf(id);
  changeFavorites(reader,state[reader].filter(bookId=>bookId!==id));motionHook(findData('data-book',id),'just-removed');
  const remaining=$$(`.reader-summary.reader-${reader} [data-remove]`);(remaining[Math.min(index,remaining.length-1)]||$(`.reader-summary.reader-${reader} [data-reader]`))?.focus({preventScroll:true});recorder.record('remove_seed',{reader});
 });
 const clear=$('[data-clear-reader]',container);if(clear)clear.onclick=()=>{const reader=container.classList.contains('reader-a')?'a':'b';if(!state[reader].length)return;changeFavorites(reader,[]);toast(`${readerName(reader)} cleared. Undo is available.`);};
}
function bindSelect(){
 renderBooks();
 const shelves=$('#selected-shelves');shelves.addEventListener('toggle',()=>{if(shelves.isConnected)shelvesOpen=shelves.open;});
 $('#search').addEventListener('input',event=>{state.query=event.target.value;$('#clear-query').hidden=!state.query;if(!apiMode){renderBooks();return;}api.requests.cancel('search');clearTimeout(searchTimer);state.searchResults=[];state.searchError='';state.searchBusy=Boolean(state.query.trim());renderApiBooks();if(state.query.trim())searchTimer=setTimeout(performSearch,180);});
 $$('[data-reader]').forEach(button=>button.onclick=()=>switchReader(button.dataset.reader));
 $$('[data-filter]').forEach(button=>button.onclick=()=>{state.filter=button.dataset.filter;syncFilters();renderBooks();});
 $$('.reader-summary').forEach(bindShelf);
 $('#undo-selection').onclick=()=>{const change=state.undo;if(!change)return;state[change.reader]=[...change.before];state.undo=null;invalidateInput();updateShelf(change.reader);syncSelectionChrome();syncCatalogueSelection();$('#selected-shelves summary').focus({preventScroll:true});toast('Last selection change undone.');};
 $('#pair-next').onclick=()=>{if(state.a.length===5&&state.b.length===5)showResults();else switchReader(state.reader==='a'?'b':'a',{handoff:true});};
 $('#demo').onclick=event=>requestSamplePair(event.currentTarget);
 $('#clear-query').onclick=()=>clearCatalogueSearch();
}
function invalidateInput(){api?.requests.cancel('recommend');state.pending=false;state.requestError='';state.samplePair=false;clearDecision(state);state.results=[];state.selected=null;state.exploration=null;state.galaxy=null;state.topShelves=null;}
function changeFavorites(reader,ids){state.undo={reader,before:[...state[reader]]};state[reader]=[...ids];state.handoff='';invalidateInput();updateShelf(reader);syncSelectionChrome();syncCatalogueSelection();}
async function toggleBook(id){
 if(state.picking)return;
 const ids=state[state.reader],wasSelected=ids.includes(id);
 if(apiMode&&!wasSelected){
  if(ids.length>=5){toast('You picked 5 books. Remove one to choose another.');return;}
  const reader=state.reader;state.picking=true;renderApiBooks();applyBusyState();
  try{await api.requests.run('pick',signal=>api.book(id,{signal}));}catch(error){if(error.name==='AbortError')return;state.picking=false;state.searchError=error.message;render();return;}
  state.picking=false;if(state.reader!==reader)return;render();
 }
 if(!wasSelected&&ids.length>=5){toast('You picked 5 books. Remove one to choose another.');return;}
 changeFavorites(state.reader,wasSelected?ids.filter(bookId=>bookId!==id):[...ids,id]);
 motionHook(findData('data-book',id),wasSelected?'just-removed':'just-added');
 if(!wasSelected)motionHook(findData('data-remove',id,$(`.reader-summary.reader-${state.reader}`)),'just-added');
 if(apiMode)findData('data-book',id)?.focus({preventScroll:true});
 recorder.record(wasSelected?'remove_seed':'add_seed',{reader:state.reader,count:state[state.reader].length});
}
async function showResults({mode=state.mode,rerank=false}={}){
 if(state.picking||apiConnection.pending)return;
 if(state.a.length!==5||state.b.length!==5){toast('Each reader needs 5 books.');return;}
 const previous=new Map($$('.result-card[data-result]').map(card=>[card.dataset.result,card.getBoundingClientRect()]));
 if(!apiMode){
  const next=recommend(state.a,state.b,mode);
  if(rerank)reconcileRanking(state,next,mode);else{state.results=next;state.selected=next[0]?.book.id??null;}
 }else{
  state.pending=true;state.requestError='';state.requestedMode=mode;render();
  try{
   const reply=await api.recommend([...state.a],[...state.b],mode);
   const summary=reconcileRanking(state,reply.results,reply.mode);
   state.galaxy=reply.galaxy;state.topShelves=reply.topShelves;state.modelVersion=reply.modelVersion;
   if(rerank&&summary.choiceChanged)toast('The shortlist changed. Your previous choice is no longer available.');
  }catch(error){
   if(error.name==='AbortError')return;
   state.pending=false;state.requestError=error.status===404?`${error.message} Change books to replace unavailable favorites.`:rerank?`${error.message} Your previous shortlist is kept.`:error.message;render();return;
  }
  state.pending=false;
 }
 state.stage='results';state.query='';state.searchResults=[];state.exploration=null;recorder.record('show_results',{aggregation:state.mode});render();
 if(rerank){animateRanking(previous);$('#aggregation').focus({preventScroll:true});}else{window.scrollTo({top:0,behavior:'instant'});titleFocus();}
}

function resultsHTML(){
 return `<section class="result-top"><div><h1 id="page-title" tabindex="-1">Your shared shortlist.</h1><p>${state.results.length?`${state.results.length} new ${state.results.length===1?'book':'books'}. `:''}Compare the reasons and mark what you’d read.</p></div><details class="result-options" id="result-options" ${compactViewport.matches?'':'open'}><summary>More options</summary><div class="result-actions"><details class="shortlist-options" id="shortlist-options"><summary>Copy shortlist</summary><div><button id="copy-shortlist" class="secondary" ${state.pending||!state.results.length?'disabled':''}>Copy titles</button><button id="show-shortlist" class="quiet" ${state.pending||!state.results.length?'disabled':''}>Show text to copy</button></div></details><button id="edit-picks" class="secondary">Change favorites</button></div></details></section>
 ${state.samplePair?'<p class="sample-pair-note">You’re exploring an example pair.</p>':''}<p id="copy-status" class="sr-only" role="status"></p><section id="copy-fallback" class="copy-fallback" hidden aria-label="Manual shortlist copy"><p id="copy-help">Select this text and copy it.</p><textarea id="shortlist-text" readonly rows="8" aria-label="Shortlist text to copy"></textarea><div><button id="select-copy-text" class="secondary">Select text</button><button id="close-copy-fallback" class="quiet">Close</button></div></section>
 ${state.topShelves?`<div class="reader-taste-summary">${['a','b'].map(reader=>`<p class="reader-${reader}"><strong>${readerName(reader)}</strong><span>${state.topShelves[reader].map(escape).join(' · ')}</span></p>`).join('')}</div>`:''}<div id="decision-panel"></div>
 <section class="results-layout" aria-label="Recommendations" aria-busy="${state.pending}"><div class="results-toolbar"><div class="results-views" role="tablist" aria-label="Explore recommendations"><button id="view-shortlist" role="tab" data-results-view="shortlist" aria-controls="result-list" aria-selected="${state.view==='shortlist'}" tabindex="${state.view==='shortlist'?0:-1}">Shortlist <span>${state.results.length}</span></button><button id="view-map" role="tab" data-results-view="map" aria-controls="taste-map-panel" aria-selected="${state.view==='map'}" tabindex="${state.view==='map'?0:-1}" ${state.pending||!state.results.length?'disabled':''}><span aria-hidden="true">↔</span>Book connections</button></div>
 <div class="mode-control"><label for="aggregation">Rank by</label><select id="aggregation" aria-describedby="ranking-note" ${state.pending?'disabled':''}><option value="least-misery" ${state.mode==='least-misery'?'selected':''}>Balance both readers</option><option value="average" ${state.mode==='average'?'selected':''}>Highest average match</option></select><details class="ranking-help"><summary aria-label="How ranking works">?</summary><p>${rankingNote()}</p></details></div></div><p class="ranking-note" id="ranking-note" role="status">${rankingNote()}</p>
 <div id="result-list" class="result-list" role="tabpanel" aria-labelledby="view-shortlist" ${state.view==='shortlist'?'':'hidden'}></div><section id="taste-map-panel" class="taste-map-panel" role="tabpanel" aria-labelledby="view-map" ${state.view==='map'&&!state.pending&&state.results.length?'':'hidden'}><div id="large-map" class="large-map"></div></section></section>`;
}
function setResultsView(view,{focus=false}={}){
 if(!['shortlist','map'].includes(view)||state.pending||view==='map'&&!state.results.length)return;
 state.view=view;
 $$('[data-results-view]').forEach(button=>{const active=button.dataset.resultsView===view;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;if(active&&focus)button.focus({preventScroll:true});});
 $('#result-list').hidden=view!=='shortlist';$('#taste-map-panel').hidden=view!=='map';
 if(view==='map')resultMap.update(state.a,state.b,state.results,state.selected,state.galaxy,{votes:state.votes,choice:state.choice});
 recorder.record('change_results_view',{view});
}
function rankingNote(){return state.mode==='average'?'Ranks by the average of both readers’ matches.':'Ranks by the lower of the two readers’ matches.';}
function animateRanking(previous){
 if(matchMedia('(prefers-reduced-motion: reduce)').matches||document.documentElement.classList.contains('reduce-motion'))return;
 $$('.result-card[data-result]').forEach(card=>{const before=previous.get(card.dataset.result),after=card.getBoundingClientRect();if(!before||Math.abs(before.top-after.top)<1||before.bottom<0&&after.bottom<0||before.top>innerHeight&&after.top>innerHeight||typeof card.animate!=='function')return;card.animate([{transform:`translateY(${before.top-after.top}px)`},{transform:'translateY(0)'}],{duration:460,easing:'cubic-bezier(.22,1,.36,1)'});});
}

function bindResults(){
 $('#edit-picks').onclick=editPicks;
 $('#aggregation').onchange=event=>showResults({mode:event.target.value,rerank:true});
 resultMap=new DeskGalaxy($('#large-map'),{
  onSelect:id=>{state.selected=id;$$('.result-card[data-result]').forEach(card=>card.classList.toggle('selected',card.dataset.result===id));},
  onInspect:id=>openDetail(id,{kind:'map',id}),onFavorite:id=>openFavorite(id,{kind:'favorite-map',id})
 });
 $$('[data-results-view]').forEach(button=>{
  button.onclick=()=>setResultsView(button.dataset.resultsView);
  button.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();setResultsView(event.key==='Home'?'shortlist':event.key==='End'?'map':state.view==='map'?'shortlist':'map',{focus:true});};
 });
 $('#copy-shortlist').onclick=async()=>{
  const status=$('#copy-status'),text=shortlistText(state.results,state.choice),copied=await copyShortlistText(text);
  if(!status.isConnected||$('#copy-status')!==status||state.stage!=='results')return;
  if(shortlistText(state.results,state.choice)!==text){status.textContent='The shortlist changed. Copy it again.';toast('The shortlist changed. Please copy again.');return;}
  status.textContent=copied?'Shortlist copied.':'Clipboard unavailable. Copy the text manually.';
  if(copied){toast('Shortlist copied.');if(!$('#copy-fallback').hidden)$('#copy-help').textContent='This shortlist is also available to copy manually.';}
  else showShortlistText(true);
  $('#shortlist-options').open=false;if(copied)$('#shortlist-options summary').focus({preventScroll:true});
  recorder.record('copy_shortlist',{outcome:copied?'copied':'manual'});
 };
 $('#show-shortlist').onclick=()=>{showShortlistText(false);$('#shortlist-options').open=false;};
 $('#select-copy-text').onclick=()=>{$('#shortlist-text').focus();$('#shortlist-text').select();};
 $('#close-copy-fallback').onclick=()=>{$('#copy-fallback').hidden=true;$('#shortlist-options summary').focus({preventScroll:true});};
 $('#shortlist-text').onkeydown=event=>{if(event.key==='Escape'){$('#copy-fallback').hidden=true;$('#shortlist-options summary').focus({preventScroll:true});}};
 renderResultsContent();
}
function showShortlistText(failed=false){
 const text=shortlistText(state.results,state.choice);$('#copy-fallback').hidden=false;$('#copy-help').textContent=failed?'Clipboard unavailable. Select this text and copy it.':'Select this text and use your copy shortcut.';$('#shortlist-text').value=text;$('#shortlist-text').focus();$('#shortlist-text').select();
}
function decisionHTML(){
 const choice=state.results.find(result=>result.book.id===state.choice),count=state.results.filter(result=>bothWilling(state.votes[result.book.id])).length;
 if(choice)return `<section class="decision-strip confirmed" aria-labelledby="decision-heading"><div class="decision-copy"><h2 id="decision-heading" tabindex="-1">Your next read</h2><p><strong>${escape(choice.book.title)}</strong><span>${escape(choice.book.author)}</span></p></div><div class="decision-actions"><button id="review-choice" class="primary">View reasons</button><button id="revoke-choice" class="secondary">Undo choice</button></div>${apiMode?feedbackHTML(choice.book.id):''}</section>`;
 if(state.deferred)return `<section class="decision-strip deferred" aria-labelledby="decision-heading"><div class="decision-copy"><h2 id="decision-heading" tabindex="-1">No book chosen yet</h2><p>Your shortlist is still here.</p></div><button id="reopen-choice" class="secondary">Keep looking</button></section>`;
 if(!count)return '';
 return `<section class="decision-strip open" aria-labelledby="decision-heading"><div class="decision-copy"><h2 id="decision-heading" tabindex="-1">Choose one together</h2>${count?`<p>${count} ${count===1?'book you both want':'books you both want'} to read.</p>`:''}</div><button id="defer-choice" class="quiet">Decide later</button></section>`;
}
function feedbackKey(id){return JSON.stringify([state.modelVersion,id]);}
function feedbackHTML(id){
 const status=state.feedback[feedbackKey(id)];
 return `<div class="anonymous-feedback"><p>${status==='sent'?'Thanks. Anonymous feedback sent.':status==='pending'?'Sending anonymous feedback…':status==='unknown'?'Delivery could not be confirmed. Your choice is kept here.':'Your choice stays on this page. You can also send it as anonymous feedback.'}</p><button id="send-feedback" class="quiet" ${status?'disabled':''}>${status==='sent'?'Feedback sent':'Send anonymous feedback'}</button></div>`;
}
async function sendFeedback(){
 const id=state.choice;if(!id||!bothWilling(state.votes[id])||!state.modelVersion)return;
 const key=feedbackKey(id);if(state.feedback[key])return;
 state.feedback[key]='pending';renderResultsContent();
 try{await api.feedback({bookId:id,vote:'would_read',modelVersion:state.modelVersion});state.feedback[key]='sent';}
 catch{state.feedback[key]='unknown';}
 if(state.stage==='results'&&!state.pending)renderResultsContent();
}
function bindDecision(){
 $('#send-feedback')?.addEventListener('click',sendFeedback);
 $('#review-choice')?.addEventListener('click',()=>openDetail(state.choice));
 $('#revoke-choice')?.addEventListener('click',()=>{recorder.record('revoke_choice',{rank:state.results.findIndex(result=>result.book.id===state.choice)+1});state.choice=null;renderResultsContent();$('#decision-heading').focus({preventScroll:true});toast('Choice undone. Your interests are kept.');});
 $('#defer-choice')?.addEventListener('click',()=>{deferChoice(state);renderResultsContent();$('#decision-heading').focus({preventScroll:true});recorder.record('defer_choice');});
 $('#reopen-choice')?.addEventListener('click',()=>{state.deferred=false;renderResultsContent();const target=state.view==='map'?mapNode(state.selected):findData('data-result',state.selected,$('#result-list'));(target||$('#view-map'))?.focus({preventScroll:true});});
}
function renderResultsContent(){
 if(state.pending){$('#result-list').innerHTML='<div class="empty-message">Updating your shortlist…</div>';$('#decision-panel').innerHTML='';return;}
 if(!state.results.length){setResultsView('shortlist');$('#result-list').innerHTML='<div class="empty-message"><p>No new books are available for this pair.</p><p>Your favorites are kept. Try another set of books.</p></div>';$('#decision-panel').innerHTML='';$('#taste-map-panel').hidden=true;return;}
 pageObserver?.disconnect();$('#decision-panel').innerHTML=decisionHTML();bindDecision();
 $('#result-list').innerHTML=state.results.map((result,index)=>shortlistCardHTML(result,index,{votes:state.votes[result.book.id]||{},selected:state.selected===result.book.id,chosen:state.choice===result.book.id,api:apiMode})).join('');
 $$('.result-card[data-result]',$('#result-list')).forEach(button=>button.onclick=()=>openDetail(button.dataset.result));
 $$('a[href^="../b/"]').forEach(link=>link.href=`../b/?v=20261104.4&${apiMode?'':seedQuery(state.a,state.b,state.mode)}`);
 resultMap.update(state.a,state.b,state.results,state.selected,state.galaxy,{votes:state.votes,choice:state.choice});pageObserver=revealItems($$('.result-card[data-result]',$('#result-list')),'recommendation');
 if(!$('#copy-fallback').hidden)$('#shortlist-text').value=shortlistText(state.results,state.choice);
}
function mapNode(id){const container=$('#large-map');return container?(findData('data-map-inspect',id,container)||findData('data-map-pick',id,container)||findData('data-id',id,container)):null;}
function restoreDetailFocus(trigger){
 let target;if(trigger?.kind==='favorite-map'||trigger?.kind==='map'||state.view==='map')target=mapNode(trigger?.id||state.selected);else target=findData('data-result',trigger?.id||state.selected);
 (target||$('#view-map')||$('#page-title'))?.focus({preventScroll:true});
}
function opinionNote(votes={}){if(bothWilling(votes))return 'Both interested. Confirm to choose it together.';if(votes.a==='no'||votes.b==='no')return 'Keep exploring the other books.';if(votes.a==='unsure'||votes.b==='unsure')return 'Not sure yet? You can come back to this one.';if(votes.a||votes.b)return 'Waiting for the other reader.';return 'Mark Interested for each reader to enable a shared choice.';}
function detailHTML(result,index){
 const id=result.book.id,votes=state.votes[id]||{},chosen=state.choice===id,previous=state.results[(index+state.results.length-1)%state.results.length],next=state.results[(index+1)%state.results.length];
 return `<div class="detail-header detail-header-cover"><div class="detail-cover" aria-hidden="true">${bookTile(result.book,{compact:true})}</div><div class="detail-header-copy"><span class="book-position">Book ${index+1} of ${state.results.length}</span><h2 id="detail-title" tabindex="-1">${escape(result.book.title)}</h2><p>${escape(result.book.author)}${result.book.year==null?'':` · ${result.book.year}`}</p></div></div><nav class="detail-pagination" aria-label="Browse recommendations"><button id="prev-candidate" class="secondary" aria-label="Previous book: ${escape(previous.book.title)}">← Previous</button><span class="candidate-position">${index+1} / ${state.results.length}</span><button id="next-candidate" class="secondary" aria-label="Next book: ${escape(next.book.title)}">Next →</button></nav><div class="reasons">${['a','b'].map(reader=>reasonHTML(result,reader)).join('')}</div><div class="votes-block"><h3>Would you each read this?</h3><div class="desk-vote-columns">${['a','b'].map(reader=>`<section class="desk-vote-reader reader-${reader}" aria-label="${readerName(reader)} interest"><strong>${readerName(reader)}</strong><div class="desk-vote-options">${VOTE_OPTIONS.map(([value,label])=>`<button data-vote="${reader}:${value}" aria-label="${readerName(reader)}: ${label}" aria-pressed="${votes[reader]===value}" class="${votes[reader]===value?'chosen':''}">${label}</button>`).join('')}</div></section>`).join('')}</div><p id="opinion-note" class="vote-state" role="status">${chosen?'Chosen together. You can change your mind.':opinionNote(votes)}</p></div><div class="detail-choice-actions"><button id="confirm-choice" class="primary" ${!bothWilling(votes)||chosen?'disabled':''}>${chosen?'Chosen together':'Choose this book together'}</button></div><details class="detail-evidence" id="detail-evidence-panel" ${state.exploration?'open':''}><summary>Explore the connections</summary><div class="reasons">${['a','b'].map(reader=>readerEvidenceHTML(result,reader,state[reader],state.exploration,{includeReason:false})).join('')}</div><section id="evidence-explorer" class="evidence-explorer" hidden></section></details>`;
}

function refreshDetail(id,focus){
 const evidenceOpen=$('#detail-evidence-panel')?.open;detailObserver?.disconnect();detailMode='recommendation';const index=state.results.findIndex(result=>result.book.id===id),dialog=$('#detail-dialog');
 const sameBook=dialog.dataset.bookId===id;dialog.dataset.bookId=id;$('#detail-body').innerHTML=detailHTML(state.results[index],index);if(sameBook&&evidenceOpen)$('#detail-evidence-panel').open=true;if(!sameBook)dialog.scrollTop=0;bindDetail(id);renderExplorer();if(focus)$(focus)?.focus({preventScroll:true});
 if(dialog.open)detailObserver=revealItems($$('.reason'),`reason-${id}`,dialog);
}
function openDetail(id,trigger={kind:'result',id}){
 if(!state.results.some(result=>result.book.id===id))return;
 const dialog=$('#detail-dialog');if(!dialog.open)lastDetailTrigger=trigger;
 state.selected=id;state.exploration=null;renderResultsContent();refreshDetail(id);recorder.record('open_explanation',{rank:state.results.findIndex(result=>result.book.id===id)+1});
 if(!dialog.open)dialog.showModal();$('#detail-title').focus({preventScroll:true});detailObserver=revealItems($$('.reason'),`reason-${id}`,dialog);
}
function navigateCandidate(direction){const index=state.results.findIndex(result=>result.book.id===state.selected),next=(index+direction+state.results.length)%state.results.length;state.selected=state.results[next].book.id;state.exploration=null;if(lastDetailTrigger&&['result','map','map-action'].includes(lastDetailTrigger.kind))lastDetailTrigger.id=state.selected;renderResultsContent();refreshDetail(state.selected,'#detail-title');motionHook($('#detail-body'),direction>0?'detail-browse-next':'detail-browse-prev',420);recorder.record('open_explanation',{rank:next+1});}
function bindDetail(id){
 $$('[data-vote]').forEach(button=>button.onclick=()=>{const [reader,vote]=button.dataset.vote.split(':'),revoked=voteFor(state,id,reader,vote);recorder.record('vote',{rank:state.results.findIndex(result=>result.book.id===id)+1,reader,vote});refreshDetail(id,`[data-vote="${reader}:${vote}"]`);renderResultsContent();if(revoked)toast('Interest changed. The shared choice was undone.');});
 $('#confirm-choice').onclick=()=>{if(!confirmChoice(state,id))return;refreshDetail(id,'#detail-title');renderResultsContent();motionHook($('.decision-strip.confirmed'),'choice-arrived',520);motionHook($('.detail-choice-actions'),'choice-arrived',520);recorder.record('confirm_choice',{rank:state.results.findIndex(result=>result.book.id===id)+1});toast('Chosen together.');};
 $('#prev-candidate').onclick=()=>navigateCandidate(-1);$('#next-candidate').onclick=()=>navigateCandidate(1);bindEvidence();
}
function bindEvidence(){
 $$('[data-seed]',$('#detail-body')).forEach(button=>button.onclick=()=>{const previous=state.exploration,fromTheme=previous?.kind==='theme'&&button.closest('.theme-favorites')&&button.dataset.reader===previous.reader;explorerTrigger=fromTheme?{kind:'theme',reader:previous.reader,theme:previous.theme}:{kind:'seed',reader:button.dataset.reader,id:button.dataset.seed};state.exploration={kind:'seed',reader:button.dataset.reader,id:button.dataset.seed,parentTheme:fromTheme?previous.theme:null};renderExplorer();$('#explorer-title').focus();});
 $$('[data-theme]',$('#detail-body')).forEach(button=>button.onclick=()=>{const reader=button.dataset.reader,theme=button.dataset.theme;if(state.exploration?.kind==='theme'&&state.exploration.reader===reader&&state.exploration.theme===theme){closeExplorer();return;}explorerTrigger={kind:'theme',reader,theme};state.exploration={kind:'theme',reader,theme};renderExplorer();$('#explorer-title').focus();});
}
function renderExplorer(){
 const region=$('#evidence-explorer');if(!region)return;const exploration=state.exploration,result=state.results.find(item=>item.book.id===state.selected);
 $$('[data-theme]',$('#detail-body')).forEach(button=>button.setAttribute('aria-pressed',String(exploration?.kind==='theme'&&button.dataset.reader===exploration.reader&&button.dataset.theme===exploration.theme)));
 region.hidden=!exploration;if(!exploration){region.innerHTML='';return;}
 const reader=exploration.reader;
 if(exploration.kind==='theme'){
  const matches=themeFavorites(state[reader],exploration.theme);
  region.innerHTML=`<div class="theme-inspector"><h3 id="explorer-title" tabindex="-1">${escape(exploration.theme)}</h3><p>${matches.length} of ${readerName(reader)}’s five favorites share this theme with ${escape(result.book.title)}.</p><div class="theme-favorites">${matches.map(book=>`<button class="evidence-seed" data-seed="${escape(book.id)}" data-reader="${reader}">${escape(book.title)} <span aria-hidden="true">↗</span></button>`).join('')}</div><button id="close-explorer" class="quiet">Back to reasons</button></div>`;
 }else{
  const book=byId(exploration.id),shared=book.tags.filter(theme=>result.book.tags.includes(theme));
  region.innerHTML=`<div class="seed-inspector"><div class="favorite-cover" aria-hidden="true">${bookTile(book,{compact:true})}</div><div class="favorite-info"><p>${readerName(reader)}’s favorite</p><h3 id="explorer-title" tabindex="-1">${escape(book.title)}</h3><p>${escape(book.author)}${book.year==null?'':` · ${book.year}`}</p><p>${shared.length?`Shared themes with ${escape(result.book.title)}: ${shared.map(escape).join(' · ')}.`:'No shared themes with this recommendation.'}</p>${exploration.parentTheme?'<button id="back-to-theme" class="secondary">Back to shared theme</button>':''}<button id="close-explorer" class="quiet">Back to reasons</button></div></div>`;
 }
 $('#close-explorer').onclick=closeExplorer;
 $('#back-to-theme')?.addEventListener('click',()=>{state.exploration={kind:'theme',reader,theme:exploration.parentTheme};renderExplorer();$('#explorer-title').focus();});bindEvidence();
}
function closeExplorer(){
 const trigger=explorerTrigger;state.exploration=null;renderExplorer();
 const target=trigger?.kind==='seed'?$$('[data-seed]',$('#detail-body')).find(node=>node.dataset.seed===trigger.id&&node.dataset.reader===trigger.reader):$$('[data-theme]',$('#detail-body')).find(button=>button.dataset.reader===trigger?.reader&&button.dataset.theme===trigger?.theme);
 (target||$('#detail-title'))?.focus({preventScroll:true});
}
function openFavorite(id,trigger){
 const book=byId(id);if(!book||!state.a.includes(id)&&!state.b.includes(id))return;
 const dialog=$('#detail-dialog'),readers=['a','b'].filter(reader=>state[reader].includes(id)),links=favoriteReferences(state.results,id);lastDetailTrigger=trigger;detailMode='favorite';state.exploration=null;detailObserver?.disconnect();delete dialog.dataset.bookId;
 $('#detail-body').innerHTML=`<section class="favorite-inspector"><div class="favorite-cover" aria-hidden="true">${bookTile(book)}</div><div class="favorite-info"><p>${readers.map(readerName).join(' and ')} favorite</p><h2 id="detail-title" tabindex="-1">${escape(book.title)}</h2><p>${escape(book.author)}${book.year==null?'':` · ${book.year}`}</p><div class="evidence-tags">${book.tags.map(theme=>`<span>${escape(theme)}</span>`).join('')}</div><h3>Connected recommendations</h3><div class="favorite-links">${links.length?links.map(item=>`<button class="evidence-seed" data-candidate="${escape(item.result.book.id)}"><strong>${escape(item.result.book.title)}</strong><span>Reference for ${item.readers.map(readerName).join(' and ')}</span></button>`).join(''):'<p>No current explanation uses this favorite as its direct reference.</p>'}</div><button id="close-favorite" class="secondary">Back to book connections</button></div></section>`;
 $$('[data-candidate]',$('#detail-body')).forEach(button=>button.onclick=()=>openDetail(button.dataset.candidate));$('#close-favorite').onclick=()=>dialog.close();
 if(!dialog.open)dialog.showModal();$('#detail-title').focus({preventScroll:true});
}

installBridge({
 read:()=>({a:[...state.a],b:[...state.b],mode:state.mode,stage:state.stage,fixture:apiMode?(state.modelVersion||apiConnection.health?.modelVersion||'api'):'manual-tags-v1',recommendations:state.results.map(result=>result.book.id)}),
 apply:async data=>{
  api?.requests.cancel('favorites');api?.requests.cancel('pick');api?.requests.cancel('search');clearTimeout(searchTimer);state.picking=false;state.searchBusy=false;state.searchError='';
  api?.requests.cancel('recommend');state.pending=false;state.a=data.a;state.b=data.b;state.mode=data.mode;state.samplePair=false;clearDecision(state);state.undo=null;state.handoff='';state.exploration=null;state.query='';state.searchResults=[];state.filter='all';state.reader='a';state.stage='select';state.results=[];state.selected=null;render();
  if(state.a.length===5&&state.b.length===5)await showResults();
 },
 find:()=>showResults()
});

recorder.record('start');render();if(apiMode)connectApi();
