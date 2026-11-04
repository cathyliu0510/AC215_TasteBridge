import {byId,profile,project} from './shared/engine.mjs';
import {escape,svg,bookTile} from './shared/ui.mjs';
import {bothWilling,voteLabel} from './desk-decision.mjs';

const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
const stableJitter=id=>[...id].reduce((sum,letter)=>sum+letter.charCodeAt(0),0);

export function galaxyLayout(a,b,results,galaxy=null){
 const ids=[...new Set([...results.map(result=>result.book.id),...a,...b])];
 const supplied=new Map();
 if(galaxy)for(const point of [...galaxy.a,...galaxy.b,...galaxy.bridges]){
  const old=supplied.get(point.id);
  if(old&&(old.x!==point.x||old.y!==point.y))throw new Error('Conflicting galaxy coordinates.');
  supplied.set(point.id,{x:point.x,y:point.y});
 }
 const raw=ids.map(id=>({id,p:galaxy?supplied.get(id):project(byId(id).vector)}));
 if(raw.some(({p})=>!p||!Number.isFinite(p.x)||!Number.isFinite(p.y)))throw new Error('Missing galaxy coordinates.');
 const xs=raw.map(book=>book.p.x),ys=raw.map(book=>book.p.y);
 const xmin=Math.min(-1,...xs),xmax=Math.max(1,...xs),ymin=Math.min(-1,...ys),ymax=Math.max(1,...ys);
 const convert=point=>({x:85+(point.x-xmin)/(xmax-xmin)*590,y:70+(point.y-ymin)/(ymax-ymin)*255});
 const positions=new Map(raw.map(({id,p})=>{
  const point=convert(p),jitter=galaxy?0:stableJitter(id);
  return [id,galaxy?point:{x:point.x+(jitter%5-2)*7,y:point.y+(Math.floor(jitter/5)%5-2)*6}];
 }));
 // API cluster centers are visual centroids of the displayed favorites. Their
 // coordinates are never treated as reader embeddings or used for scoring.
 const centroid=seeds=>({x:seeds.reduce((sum,id)=>sum+supplied.get(id).x,0)/(seeds.length||1),y:seeds.reduce((sum,id)=>sum+supplied.get(id).y,0)/(seeds.length||1)});
 const centers=galaxy?[convert(centroid(a)),convert(centroid(b))]:[convert(project(profile(a))),convert(project(profile(b)))];
 return {ids,positions,centers};
}

// Geometry remains a view of the ranking vectors, never a second ranking.
export function neighboringBook(positions,id,direction){
 const origin=positions.get(id);if(!origin)return null;
 const axis=['ArrowLeft','ArrowRight'].includes(direction)?'x':'y',other=axis==='x'?'y':'x';
 const sign=['ArrowLeft','ArrowUp'].includes(direction)?-1:1;
 return [...positions].filter(([candidate,point])=>candidate!==id&&(point[axis]-origin[axis])*sign>.01)
  .map(([candidate,point])=>({id:candidate,distance:Math.hypot(point.x-origin.x,point.y-origin.y)+Math.abs(point[other]-origin[other])*.7}))
  .sort((a,b)=>a.distance-b.distance||a.id.localeCompare(b.id))[0]?.id??null;
}
export function mapBookRole(id,a,b,results){
 const rank=results.findIndex(result=>result.book.id===id);
 if(rank>=0)return {kind:'recommendation',label:`Recommendation ${rank+1}`,rank:rank+1};
 const shared=a.includes(id)&&b.includes(id),reader=a.includes(id)?'a':'b';
 return {kind:'favorite',reader:shared?'both':reader,label:shared?'Both readers’ favorite':`Reader ${reader==='a'?'1':'2'} favorite`};
}
export function galaxySelection(ids,results,previous,selected,priorExternal){
 const wasFavorite=ids.includes(previous)&&!results.some(result=>result.book.id===previous);
 return wasFavorite&&selected===priorExternal?previous:ids.includes(selected)?selected:ids[0]??null;
}
// Only numbered annotations move. The dots and evidence paths remain at the
// original projected coordinates, joined to a displaced badge by a leader.
export function packMapCallouts(points,{width,height,gap=40,padding=24}={}){
 const placed=new Map(),angles=[0,-Math.PI/2,Math.PI/2,Math.PI,Math.PI/4,-Math.PI/4,Math.PI*3/4,-Math.PI*3/4];
 const fits=point=>point.x>=padding&&point.x<=width-padding&&point.y>=padding&&point.y<=height-padding&&
  [...placed.values()].every(other=>Math.hypot(other.x-point.x,other.y-point.y)>=gap-.001);
 for(const point of points){
  let chosen=fits(point)?{x:point.x,y:point.y}:null;
  for(let radius=8;!chosen&&radius<=160;radius+=8)for(const angle of angles){
   const candidate={x:point.x+Math.cos(angle)*radius,y:point.y+Math.sin(angle)*radius};
   if(fits(candidate)){chosen=candidate;break;}
  }
  placed.set(point.id,chosen||{x:point.x,y:point.y});
 }
 return placed;
}

// This is a diagram of the returned explanation references, not a new score,
// geographical position or inference about either reader.
function connectionResponse(result,decision={}){
 const votes=decision.votes?.[result.book.id]||{},ready=bothWilling(votes);
 return {votes,ready,chosen:ready&&decision.choice===result.book.id};
}
function connectionRecommendationHTML(result,index,total,decision={}){
 const {votes,chosen}=connectionResponse(result,decision),responded=Boolean(votes.a||votes.b);
 return `<section class="connection-recommendation" aria-label="Current recommendation"><div class="connection-result-cover" aria-hidden="true">${bookTile(result.book,{compact:true})}</div><div><p class="connection-position">Recommendation ${index+1} of ${total}${chosen?'<strong class="connection-outcome">Chosen together</strong>':''}</p><h3 tabindex="-1" data-connection-title>${escape(result.book.title)}</h3><p class="connection-author">${escape(result.book.author)}</p>${responded?`<p class="connection-responses">${['a','b'].map(reader=>`<span class="reader-${reader}">Reader ${reader==='a'?1:2}: ${voteLabel(votes[reader])}</span>`).join('')}</p>`:''}</div></section>`;
}
export function bookConnectionsHTML(result,index,total,lookup=byId,decision={}){
 const source=reader=>{
  const reason=result.reasons[reader],book=lookup(reason.seedId),number=reader==='a'?1:2;
  const title=reason.seedTitle||book?.title||'Your favorite';
  return `<section class="connection-source reader-${reader}" aria-label="Reader ${number} connection"><p class="connection-reader"><i>${number}</i>Reader ${number}</p><span class="connection-source-label">From your favorite</span><button class="connection-favorite" data-map-inspect="${escape(reason.seedId)}" aria-label="Explore Reader ${number} favorite: ${escape(title)}">${book?`<span class="connection-source-cover" aria-hidden="true">${bookTile(book,{compact:true})}</span>`:''}<span><strong>${escape(title)}</strong>${book?.author?`<small>${escape(book.author)}</small>`:''}</span><span class="connection-open" aria-hidden="true">↗</span></button><p class="connection-theme-label">Shared themes</p><p class="connection-themes">${reason.tags.length?reason.tags.slice(0,3).map(escape).join(' · '):'No shared themes in this explanation'}</p><span class="connection-arrow" aria-hidden="true">${reader==='a'?'→':'←'}</span></section>`;
 };
 const response=connectionResponse(result,decision);
 return `<div class="connection-diagram">${source('a')}${connectionRecommendationHTML(result,index,total,decision)}${source('b')}</div><div class="connection-action"><button class="primary" data-map-inspect="${escape(result.book.id)}">${response.chosen?'Review choice':response.ready?'Review & choose':'Review & respond'} <span aria-hidden="true">→</span></button><p>See the reasons and mark what each reader would read.</p></div>`;
}

export class DeskGalaxy{
 constructor(container,{onSelect=()=>{},onInspect=()=>{},onFavorite=()=>{}}={}){
  this.container=container;this.onSelect=onSelect;this.onInspect=onInspect;this.onFavorite=onFavorite;
  this.zoom=1;this.offset={x:0,y:0};this.selected=null;this.focused=null;
  this.lifecycle=new AbortController();
  this.prefix=`${container.id||'taste-map'}-galaxy`;
  container.classList.add('galaxy-workbench');
  container.innerHTML=`<div class="connections-intro"><h2>Why these books connect</h2><p>Choose a recommendation to see the link to each reader’s favorite.</p></div><nav class="galaxy-shortlist" aria-label="Choose a recommendation"></nav><div class="book-connections-body"></div><details class="galaxy-projection"><summary>Explore similarity view <span>Optional</span></summary><div class="galaxy-layout"><div class="galaxy-map-column"><p class="galaxy-projection-note">Positions show approximate book similarity, not places. Use the reader reasons to compare matches.</p><div class="galaxy-key" aria-label="Similarity view legend"><span class="galaxy-key-a"><i></i>Reader 1 favorites</span><span class="galaxy-key-b"><i></i>Reader 2 favorites</span><span class="galaxy-key-bridge"><i>1</i>Recommendations</span></div><div class="galaxy-canvas"><svg class="map-svg galaxy-svg" viewBox="0 0 760 430" role="group" aria-label="Book similarity projection" aria-describedby="${this.prefix}-help"></svg><div class="galaxy-hover-title" role="tooltip" hidden></div><div class="galaxy-view-controls" role="group" aria-label="Similarity view controls"><button data-zoom="out" aria-label="Zoom out">−</button><output class="galaxy-zoom-level" aria-label="Zoom level">100%</output><button data-zoom="in" aria-label="Zoom in">+</button><button data-zoom="reset" class="galaxy-fit" aria-label="Fit all books">${svg('reset')}<span>Fit all</span></button></div></div><div class="galaxy-selection-summary"></div><p class="galaxy-help" id="${this.prefix}-help">Select a book to trace its explanation references.<span class="galaxy-mouse-help"> Drag to move; use + or − to zoom.</span></p><details class="galaxy-all-books"><summary>All books in this view <span>Choose by title</span></summary><div class="galaxy-book-groups"></div></details></div><aside class="galaxy-inspector" aria-label="Selected similarity-view book"><div class="galaxy-inspector-body"></div></aside></div></details><span class="galaxy-status sr-only" role="status" aria-live="polite"></span>`;
  container.querySelector('.galaxy-shortlist').insertAdjacentHTML('beforebegin','<div class="connections-current"></div>');
  this.svg=container.querySelector('.galaxy-svg');this.tooltip=container.querySelector('.galaxy-hover-title');
  this.inspector=container.querySelector('.galaxy-inspector-body');this.status=container.querySelector('.galaxy-status');
  const listen=(target,event,handler,options={})=>target.addEventListener(event,handler,{...options,signal:this.lifecycle.signal});
  listen(container.querySelector('.galaxy-projection'),'toggle',event=>{if(event.target.open)this.transform();});
  container.querySelectorAll('[data-zoom]').forEach(button=>listen(button,'click',()=>{
   if(button.dataset.zoom==='reset'){this.zoom=1;this.offset={x:0,y:0};this.transform();}
   else this.setZoom(this.zoom+(button.dataset.zoom==='in'?.25:-.25));
   this.status.textContent=`Map zoom ${Math.round(this.zoom*100)}%.`;
  }));
  listen(container,'click',event=>{
   const pick=event.target.closest('[data-map-pick]');
   if(pick){this.selectBook(pick.dataset.mapPick,{fromInspector:Boolean(pick.closest('.galaxy-inspector'))});return;}
   const showSelected=event.target.closest('[data-map-show-selected]');
   if(showSelected){
    this.inspector.querySelector('h3')?.focus({preventScroll:true});
    const reduced=globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches||this.container.ownerDocument.documentElement.classList.contains('reduce-motion');
    this.inspector.parentElement.scrollIntoView({block:'start',behavior:reduced?'auto':'smooth'});return;
   }
   const inspect=event.target.closest('[data-map-inspect]');
   if(inspect){const id=inspect.dataset.mapInspect;this.resultLookup.has(id)?this.onInspect(id):this.onFavorite(id);}
  });
  listen(this.svg,'pointerdown',event=>{
   // Keep one-finger page scrolling native. Panning is a mouse operation;
   // touch users have zoom controls and the full title navigator below.
   if(event.pointerType==='touch'||event.target.closest('.map-node')||event.button!==0)return;
   this.drag={x:event.clientX,y:event.clientY,ox:this.offset.x,oy:this.offset.y};
   this.svg.setPointerCapture(event.pointerId);this.svg.classList.add('is-dragging');
  });
  listen(this.svg,'pointermove',event=>{
   if(!this.drag)return;
   const rect=this.svg.getBoundingClientRect(),scale=Math.max(.01,Math.min(rect.width/760,rect.height/430));
   this.offset={x:clamp(this.drag.ox+(event.clientX-this.drag.x)/scale,-700,700),y:clamp(this.drag.oy+(event.clientY-this.drag.y)/scale,-380,380)};
   this.transform();
  });
  const release=()=>{this.drag=null;this.svg.classList.remove('is-dragging');};
  listen(this.svg,'pointerup',release);listen(this.svg,'pointercancel',release);listen(this.svg,'lostpointercapture',release);
  listen(this.svg,'pointerleave',()=>this.hideHover());
  listen(this.svg,'keydown',event=>{
   if(['+','=','-','0','Home'].includes(event.key)){
    event.preventDefault();const action=event.key==='-'?'out':['0','Home'].includes(event.key)?'reset':'in';
    container.querySelector(`[data-zoom="${action}"]`).click();
   }
  });
  listen(this.svg,'wheel',event=>{
   if(!event.ctrlKey&&!event.metaKey)return;
   event.preventDefault();this.setZoom(this.zoom+(event.deltaY<0?.12:-.12));
  },{passive:false});
  if(typeof ResizeObserver==='function'){
   this.resizeObserver=new ResizeObserver(()=>this.updateHitTargets());this.resizeObserver.observe(this.svg);
  }
 }
 book(id){return this.resultLookup?.get(id)?.book||byId(id);}
 update(a,b,results,selected=null,galaxy=null,decision={}){
  const previous=this.selected;
  this.hideHover();this.a=a;this.b=b;this.results=results;this.decision=decision;
  this.resultLookup=new Map(results.map((result,index)=>[result.book.id,{...result,index}]));
  const {ids,positions}=galaxyLayout(a,b,results,galaxy);this.positions=positions;
  this.selected=galaxySelection(ids,results,previous,selected,this.externalSelected);
  this.externalSelected=selected;
  const evidencePaths=results.map(result=>['a','b'].map(reader=>{
   const point=positions.get(result.book.id),seed=positions.get(result.reasons[reader].seedId);
   return `<path class="evidence-line" data-result="${escape(result.book.id)}" data-seed="${escape(result.reasons[reader].seedId)}" data-reader="${reader}" d="M${seed.x},${seed.y} Q${(seed.x+point.x)/2},${Math.min(seed.y,point.y)-35} ${point.x},${point.y}" fill="none" stroke="var(--${reader})" opacity="0"/>`;
  }).join('')).join('');
  const nodes=ids.map(id=>{
   const book=this.book(id),point=positions.get(id),role=mapBookRole(id,a,b,results),result=this.resultLookup.get(id);
   const color=result?'var(--gold)':role.reader==='b'?'var(--b)':'var(--a)';
   return `<g class="map-node ${result?'is-bridge':'is-favorite'}" data-id="${escape(id)}" data-reader="${role.reader||'bridge'}" data-selected="${id===this.selected}" data-hover="false" transform="translate(${point.x},${point.y})" tabindex="${id===this.selected?0:-1}" role="button" aria-label="Select ${escape(role.label.toLowerCase())}: ${escape(book.title)}" aria-pressed="${id===this.selected}"><title>${escape(book.title)}</title>${result?'<circle class="node-location" r="2.5" fill="var(--gold)"/><path class="node-leader" d="M0,0 L0,0" fill="none" stroke="var(--gold)"/>':''}<g class="node-badge"><circle class="node-hit" r="23" fill="transparent"/><circle class="node-halo" r="${result?21:13}" fill="${color}" fill-opacity=".13"/><circle class="node-core" r="${result?13:5}" fill="${result?'var(--surface)':color}" stroke="${color}"/>${role.reader==='both'?'<circle class="node-shared" r="8" fill="none" stroke="var(--b)"/>':''}<circle class="node-ring" r="22" fill="none" stroke="${color}" opacity="${id===this.selected?1:0}"/>${result?`<text class="node-number" dominant-baseline="central" text-anchor="middle" fill="var(--gold)">${result.index+1}</text>`:''}<text class="node-label" text-anchor="${point.x>580?'end':point.x<180?'start':'middle'}" fill="var(--ink)" opacity="${id===this.selected?1:0}">${escape(book.title.length>31?book.title.slice(0,28)+'…':book.title)}</text></g></g>`;
  }).join('');
  this.svg.innerHTML=`<desc>Approximate book similarity, without geographic locations or a distance scale. Numbered badges are recommendations; short leaders point to their exact projected locations when badges are close. Blue and purple dots are favorites. Lines trace the selected explanation references. Use arrow keys between books, then Enter to select.</desc><g class="map-content">${evidencePaths}${nodes}</g>`;
  this.group=this.svg.querySelector('.map-content');this.transform();
  this.svg.querySelectorAll('.map-node').forEach(node=>{
   const id=node.dataset.id;
   node.addEventListener('click',event=>{
    const target=event.detail>0?this.pointerBook(event,id):id;
    this.selectBook(target);this.node(target)?.focus({preventScroll:true});
   });
   node.addEventListener('keydown',event=>{
    if(event.key==='Enter'||event.key===' '){event.preventDefault();this.selectBook(id);}
    else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){
     event.preventDefault();const next=neighboringBook(this.hitPositions||this.positions,id,event.key);
     if(next){this.ensureVisible(next);this.node(next)?.focus({preventScroll:true});}
    }
   });
   node.addEventListener('pointerenter',event=>{if(event.pointerType!=='touch')this.showBook(this.pointerBook(event,id));});
   node.addEventListener('pointerleave',()=>this.hideHover());
   node.addEventListener('focus',()=>this.showBook(id));node.addEventListener('blur',()=>this.hideHover());
  });
  this.renderNavigator();this.renderInspector();this.paintHighlight(this.selected);
 }
 node(id){return [...this.svg.querySelectorAll('.map-node')].find(node=>node.dataset.id===id);}
 selectBook(id,{fromInspector=false}={}){
  if(!this.positions?.has(id))return;
  this.selected=id;this.focused=id;this.hideHover();this.ensureVisible(id);
  this.paintHighlight(id);this.renderInspector();this.syncNavigator();
  this.status.textContent=`Selected ${this.book(id).title}. ${mapBookRole(id,this.a,this.b,this.results).label}.`;
  if(fromInspector)this.inspector.querySelector('h3')?.focus({preventScroll:true});
  if(this.resultLookup.has(id)){this.externalSelected=id;this.onSelect(id);}
 }
 renderNavigator(){
  const selected=this.resultLookup.has(this.selected)?this.selected:this.externalSelected||this.results[0]?.book.id;
  this.container.querySelector('.galaxy-shortlist').innerHTML=this.results.map((result,index)=>`<button data-map-pick="${escape(result.book.id)}" aria-pressed="${selected===result.book.id}"><span class="galaxy-nav-rank">${index+1}</span><span>${escape(result.book.title)}</span></button>`).join('');
  const groups=[['a','Reader 1 favorites',this.a],['b','Reader 2 favorites',this.b]];
  this.container.querySelector('.galaxy-book-groups').innerHTML=groups.map(([reader,label,ids])=>`<section class="galaxy-title-group reader-${reader}"><h3>${label}</h3>${ids.map(id=>`<button data-map-pick="${escape(id)}" aria-pressed="${id===this.selected}"><i aria-hidden="true"></i><span>${escape(this.book(id).title)}</span>${this.a.includes(id)&&this.b.includes(id)?'<small>Both</small>':''}</button>`).join('')}</section>`).join('');
 }
 syncNavigator(){
  const recommendation=this.resultLookup.has(this.selected)?this.selected:this.externalSelected||this.results[0]?.book.id;
  this.container.querySelectorAll('[data-map-pick]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.mapPick===(button.closest('.galaxy-shortlist')?recommendation:this.selected))));
  this.svg.querySelectorAll('.map-node').forEach(node=>{const selected=node.dataset.id===this.selected;node.setAttribute('aria-pressed',String(selected));node.setAttribute('tabindex',selected?'0':'-1');});
 }
 renderInspector(){
  const id=this.selected,book=this.book(id);
  if(!book){this.inspector.innerHTML='<p class="galaxy-empty">Find recommendations to explore your map.</p>';return;}
  const result=this.resultLookup.get(id),role=mapBookRole(id,this.a,this.b,this.results);
  const connectionBody=this.container?.querySelector('.book-connections-body');
  if(connectionBody){
   const current=result||this.resultLookup.get(this.externalSelected)||this.results[0];
   const index=current?this.results.findIndex(item=>item.book.id===current.book.id):0;
   connectionBody.innerHTML=current?bookConnectionsHTML(current,index,this.results.length,id=>this.book(id),this.decision):'';
   this.container.querySelector('.connections-current').innerHTML=current?connectionRecommendationHTML(current,index,this.results.length,this.decision):'';
  }
  const summary=this.container?.querySelector('.galaxy-selection-summary');
  if(summary)summary.innerHTML=`<span><small>${escape(role.label)}</small><strong>${escape(book.title)}</strong></span><button data-map-show-selected>View selected book</button>`;
  const header=`<div class="galaxy-book-heading"><div class="galaxy-inspector-cover" aria-hidden="true">${bookTile(book,{compact:true})}</div><div><p class="galaxy-book-role">${escape(role.label)}</p><h3 tabindex="-1">${escape(book.title)}</h3><p class="galaxy-book-author">${escape(book.author)}</p></div></div>`;
  if(result){
   this.inspector.innerHTML=header+`<div class="galaxy-reference-list">${['a','b'].map(reader=>{const reason=result.reasons[reader];return `<section class="galaxy-reference reader-${reader}"><span class="galaxy-reference-reader"><i>${reader==='a'?'1':'2'}</i>Reader ${reader==='a'?'1':'2'}</span><span class="galaxy-reference-label">Connects with your favorite</span><button data-map-pick="${escape(reason.seedId)}">${escape(reason.seedTitle||this.book(reason.seedId)?.title||'Your favorite')}<span aria-hidden="true">↗</span></button><p>${reason.tags.slice(0,3).map(escape).join(' · ')||'No shared themes'}</p></section>`;}).join('')}</div><button class="primary galaxy-inspect-action" data-map-inspect="${escape(id)}">View reasons & choose</button><p class="galaxy-inspector-hint">The lines trace the references behind each reader’s reason.</p>`;
  }else{
   const references=this.results.filter(item=>['a','b'].some(reader=>item.reasons[reader].seedId===id));
   this.inspector.innerHTML=header+`<div class="galaxy-favorite-context"><h4>${references.length?`A reference for ${references.length} ${references.length===1?'recommendation':'recommendations'}`:'Your taste starts here'}</h4>${references.length?references.map(item=>`<button data-map-pick="${escape(item.book.id)}"><span>${this.resultLookup.get(item.book.id).index+1}</span>${escape(item.book.title)}</button>`).join(''):'<p>This favorite shapes your recommendations, even when it is not the direct reference in a reason.</p>'}</div><button class="secondary galaxy-inspect-action" data-map-inspect="${escape(id)}">Explore this favorite</button>`;
  }
 }
 showBook(id){
  const book=this.book(id);if(!book)return;
  this.focused=id;this.tooltip.textContent=book.title;this.tooltip.hidden=false;this.paintHighlight(id);
 }
 hideHover(){if(this.tooltip)this.tooltip.hidden=true;if(this.positions)this.paintHighlight(this.selected);}
 pointerBook(event,fallback=null){
  if(!Number.isFinite(event?.clientX)||!Number.isFinite(event?.clientY)||!this.positions)return fallback;
  const matrix=this.group?.getScreenCTM();if(!matrix)return fallback;
  const determinant=matrix.a*matrix.d-matrix.b*matrix.c;if(!determinant)return fallback;
  const dx=event.clientX-matrix.e,dy=event.clientY-matrix.f;
  const point={x:(matrix.d*dx-matrix.c*dy)/determinant,y:(matrix.a*dy-matrix.b*dx)/determinant};
  let nearest=null,distance=Infinity;
  for(const [id,position] of this.hitPositions||this.positions){const current=Math.hypot(position.x-point.x,position.y-point.y);if(current<distance){nearest=id;distance=current;}}
  return nearest||fallback;
 }
 paintHighlight(id){
  if(!this.resultLookup)return;
  const isBridge=this.resultLookup.has(id),related=new Set([id]);
  this.svg.querySelectorAll('.evidence-line').forEach(path=>{
   const active=isBridge?path.dataset.result===id:path.dataset.seed===id;
   path.classList.toggle('is-active',active);path.setAttribute('opacity',active?'.8':'0');
   if(active){related.add(path.dataset.seed);related.add(path.dataset.result);}
  });
  this.svg.querySelectorAll('.map-node').forEach(node=>{
   const active=node.dataset.id===id,selected=node.dataset.id===this.selected;
   node.dataset.hover=String(active);node.dataset.selected=String(selected);node.classList.toggle('is-connected',related.has(node.dataset.id));
   node.classList.toggle('is-dimmed',!related.has(node.dataset.id));
   node.querySelector('.node-label').setAttribute('opacity',active||selected?'1':'0');
   node.querySelector('.node-ring').setAttribute('opacity',active||selected?'1':'0');
  });
  this.syncNavigator();
 }
 setZoom(next){
  const value=clamp(next,1,3),point=this.positions?.get(this.selected)||{x:380,y:215};
  this.offset.x=clamp(this.offset.x+(point.x-380)*(this.zoom-value),-700,700);
  this.offset.y=clamp(this.offset.y+(point.y-215)*(this.zoom-value),-380,380);
  this.zoom=value;this.transform();
 }
 ensureVisible(id){
  if(this.zoom===1)return;
  const point=this.positions.get(id),x=380+this.offset.x+(point.x-380)*this.zoom,y=215+this.offset.y+(point.y-215)*this.zoom;
  if(x<50||x>710)this.offset.x=clamp((380-point.x)*this.zoom,-700,700);
  if(y<45||y>385)this.offset.y=clamp((215-point.y)*this.zoom,-380,380);
  this.transform();
 }
 transform(){
  this.group?.setAttribute('transform',`translate(${380+this.offset.x},${215+this.offset.y}) scale(${this.zoom}) translate(-380,-215)`);
  this.updateHitTargets();
  this.container.querySelector('.galaxy-zoom-level').textContent=`${Math.round(this.zoom*100)}%`;
  this.container.querySelector('[data-zoom="in"]').disabled=this.zoom>=3;
  this.container.querySelector('[data-zoom="out"]').disabled=this.zoom<=1;
 }
 updateHitTargets(){
  const rect=this.svg.getBoundingClientRect(),scale=Math.min(rect.width/760,rect.height/430)*this.zoom;
  if(scale<=0)return;
  this.svg.style.setProperty('--galaxy-scale',String(scale));
  this.svg.querySelectorAll('.map-node').forEach(node=>{
   const bridge=node.classList.contains('is-bridge');
   node.querySelector('.node-hit').setAttribute('r',String(23/scale));
   node.querySelector('.node-core').setAttribute('r',String((bridge?13:5)/scale));
   node.querySelector('.node-halo').setAttribute('r',String((bridge?21:12)/scale));
   node.querySelector('.node-ring').setAttribute('r',String((bridge?19:10)/scale));
   node.querySelector('.node-shared')?.setAttribute('r',String(8/scale));
   node.querySelector('.node-label').setAttribute('y',String((bridge?32:24)/scale));
   node.querySelector('.node-location')?.setAttribute('r',String(2.5/scale));
  });
  this.updateCallouts(rect);
 }
 updateCallouts(rect){
  const matrix=this.group?.getScreenCTM();if(!matrix)return;
  const determinant=matrix.a*matrix.d-matrix.b*matrix.c;if(!determinant)return;
  const anchors=this.results.map(result=>{
   const point=this.positions.get(result.book.id);
   return {id:result.book.id,x:matrix.a*point.x+matrix.c*point.y+matrix.e-rect.left,y:matrix.b*point.x+matrix.d*point.y+matrix.f-rect.top};
  });
  const visible=anchors.filter(point=>point.x>=24&&point.x<=rect.width-24&&point.y>=24&&point.y<=rect.height-24);
  const callouts=packMapCallouts(visible,{width:rect.width,height:rect.height});
  this.hitPositions=new Map(this.positions);
  for(const anchor of anchors){
   const callout=callouts.get(anchor.id)||anchor,dx=callout.x-anchor.x,dy=callout.y-anchor.y;
   const offset={x:(matrix.d*dx-matrix.c*dy)/determinant,y:(matrix.a*dy-matrix.b*dx)/determinant};
   const node=this.node(anchor.id),point=this.positions.get(anchor.id);
   node.querySelector('.node-badge').setAttribute('transform',`translate(${offset.x},${offset.y})`);
   node.querySelector('.node-leader').setAttribute('d',`M0,0 L${offset.x},${offset.y}`);
   node.querySelector('.node-leader').setAttribute('opacity',Math.hypot(dx,dy)>1?'.7':'0');
   this.hitPositions.set(anchor.id,{x:point.x+offset.x,y:point.y+offset.y});
  }
 }
 destroy(){this.lifecycle.abort();this.resizeObserver?.disconnect();}
}
