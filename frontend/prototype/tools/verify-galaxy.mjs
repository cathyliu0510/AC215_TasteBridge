import test from 'node:test';
import assert from 'node:assert/strict';
import {DeskGalaxy,bookConnectionsHTML,galaxyLayout,galaxySelection,mapBookRole,neighboringBook,packMapCallouts} from '../src/a/desk-galaxy.mjs';
import {enableApiCatalogue,cacheApiBooks} from '../src/a/shared/catalog.mjs';

test('coincident API books remain separately addressable without altering their coordinates',()=>{
 const galaxy={a:[{id:'first',x:0,y:0}],b:[{id:'second',x:0,y:0}],bridges:[{id:'result',x:0,y:0}]};
 const layout=galaxyLayout(['first'],['second'],[{book:{id:'result'}}],galaxy);
 assert.deepEqual(layout.ids,['result','first','second']);
 assert.deepEqual(layout.positions.get('first'),layout.positions.get('second'));
 assert.deepEqual(layout.positions.get('result'),{x:380,y:197.5});
});

test('map roles distinguish ranked recommendations, separate favorites and shared favorites',()=>{
 const results=[{book:{id:'result'}}];
 assert.deepEqual(mapBookRole('result',['first','shared'],['second','shared'],results),{kind:'recommendation',label:'Recommendation 1',rank:1});
 assert.deepEqual(mapBookRole('first',['first','shared'],['second','shared'],results),{kind:'favorite',reader:'a',label:'Reader 1 favorite'});
 assert.deepEqual(mapBookRole('second',['first','shared'],['second','shared'],results),{kind:'favorite',reader:'b',label:'Reader 2 favorite'});
 assert.deepEqual(mapBookRole('shared',['first','shared'],['second','shared'],results),{kind:'favorite',reader:'both',label:'Both readers’ favorite'});
});

test('directional map navigation prefers a nearby book along the intended direction',()=>{
 const positions=new Map([['origin',{x:0,y:0}],['right',{x:20,y:0}],['diagonal',{x:2,y:25}],['left',{x:-10,y:0}],['same',{x:0,y:0}]]);
 assert.equal(neighboringBook(positions,'origin','ArrowRight'),'right');
 assert.equal(neighboringBook(positions,'origin','ArrowLeft'),'left');
 assert.equal(neighboringBook(positions,'origin','ArrowUp'),null);
 assert.equal(neighboringBook(positions,'missing','ArrowDown'),null);
});

test('a favorite stays selected through a vote refresh but explicit result changes take priority',()=>{
 const ids=['result','next','favorite'],results=[{book:{id:'result'}},{book:{id:'next'}}];
 assert.equal(galaxySelection(ids,results,'favorite','result','result'),'favorite');
 assert.equal(galaxySelection(ids,results,'favorite','next','result'),'next');
 assert.equal(galaxySelection(ids,results,'removed','result','result'),'result');
 assert.equal(galaxySelection(ids,results,'favorite','removed','result'),'result');
 assert.equal(galaxySelection([],[],null,null,null),null);
});

test('map selection shows context without opening a dialog or claiming a joint choice',()=>{
 const calls=[];
 const map=Object.assign(Object.create(DeskGalaxy.prototype),{
  positions:new Map([['result',{x:1,y:2}],['favorite',{x:1,y:2}]]),
  a:['favorite'],b:[],results:[{book:{id:'result'}}],resultLookup:new Map([['result',{}]]),
  status:{textContent:''},book:id=>({title:id}),hideHover(){},ensureVisible(){},paintHighlight(){},renderInspector(){calls.push('context');},syncNavigator(){},
  onSelect:id=>calls.push(`selected:${id}`),onInspect:()=>calls.push('dialog'),onFavorite:()=>calls.push('favorite-dialog')
 });
 map.selectBook('result');assert.equal(map.selected,'result');
 assert.deepEqual(calls,['context','selected:result']);
 map.selectBook('favorite');assert.equal(map.selected,'favorite');
 assert.deepEqual(calls,['context','selected:result','context']);
 assert.equal(galaxySelection(['result','favorite'],map.results,map.selected,'result',map.externalSelected),'favorite');
 map.selectBook('missing');assert.equal(map.selected,'favorite');
});

test('only an inspector link moves focus to the replacement heading',()=>{
 const focus=[];
 const map=Object.assign(Object.create(DeskGalaxy.prototype),{
  positions:new Map([['favorite',{x:1,y:2}]]),a:['favorite'],b:[],results:[],resultLookup:new Map(),
  status:{textContent:''},book:id=>({title:id}),hideHover(){},ensureVisible(){},paintHighlight(){},renderInspector(){},syncNavigator(){},
  inspector:{querySelector:()=>({focus:options=>focus.push(options)})}
 });
 map.selectBook('favorite');assert.equal(focus.length,0);
 map.selectBook('favorite',{fromInspector:true});assert.deepEqual(focus,[{preventScroll:true}]);
});

test('numbered annotations separate dense phone clusters while the source points stay exact',()=>{
 for(const anchor of [{x:140,y:150},{x:28,y:28}]){
  const points=Array.from({length:5},(_,index)=>({id:String(index),...anchor})),before=structuredClone(points);
  const placed=packMapCallouts(points,{width:280,height:300}),positions=[...placed.values()];
  assert.deepEqual(points,before);
  assert.deepEqual(placed,packMapCallouts(points,{width:280,height:300}));
  for(let index=0;index<positions.length;index++){
   const point=positions[index];assert(point.x>=24&&point.x<=256&&point.y>=24&&point.y<=276);
   for(const other of positions.slice(index+1))assert(Math.hypot(point.x-other.x,point.y-other.y)>=39.999);
  }
 }
 const points=[{id:'a',x:60,y:60},{id:'b',x:180,y:180}];
 assert.deepEqual([...packMapCallouts(points,{width:280,height:300}).values()],points.map(({x,y})=>({x,y})));
});

test('map inspector escapes API titles, authors and reason references',()=>{
 enableApiCatalogue();
 cacheApiBooks([{id:'seed',title:'<Seed>',author:'Author',tags:['<theme>'],year:null,coverUrl:null}],{full:true});
 const result={book:{id:'result',title:'<script>bad</script>',author:'A & B',source:'api',color:'#123456',coverUrl:null},index:0,
  reasons:{a:{seedId:'seed',seedTitle:'<Seed>',tags:['<theme>']},b:{seedId:'seed',seedTitle:'<Seed>',tags:[]}}};
 const map=Object.assign(Object.create(DeskGalaxy.prototype),{selected:'result',a:['seed'],b:['seed'],results:[result],resultLookup:new Map([['result',result]]),inspector:{innerHTML:''}});
 map.renderInspector();
 assert.doesNotMatch(map.inspector.innerHTML,/<script>|<Seed>|<theme>/);
 assert.match(map.inspector.innerHTML,/&lt;script&gt;bad&lt;\/script&gt;/);
 assert.match(map.inspector.innerHTML,/A &amp; B/);
 assert.match(map.inspector.innerHTML,/data-map-inspect="result"/);
});

test('named connections use each returned reference and themes without turning projection coordinates into claims',()=>{
 const seed={id:'shared',title:'A shared favorite',author:'Author',source:'api',coverUrl:null,color:'#123456'};
 const result={book:{id:'result',title:'A new book',author:'Writer',source:'api',coverUrl:null,color:'#123456'},
  reasons:{a:{seedId:'shared',seedTitle:'A shared favorite',tags:['Magic']},b:{seedId:'shared',seedTitle:'A shared favorite',tags:['Mystery']}},
  x:41619.372,y:-72737.128,fitA:-.3,fitB:.9};
 const before=JSON.stringify(result),html=bookConnectionsHTML(result,2,5,()=>seed);
 assert.match(html,/Recommendation 3 of 5/);
 assert.match(html,/Reader 1 connection/);assert.match(html,/Reader 2 connection/);
 assert.equal((html.match(/data-map-inspect="shared"/g)||[]).length,2,'Both readers can reference the same favorite.');
 assert.match(html,/Magic/);assert.match(html,/Mystery/);assert.match(html,/Review &amp; respond|Review & respond/);
 assert.doesNotMatch(html,/41619\.372|-72737\.128|kilomet|latitude|longitude/);
 assert.equal(JSON.stringify(result),before,'Presentation must not modify the evidence or model values.');
});

test('connections expose missing shared themes and escape untrusted API text',()=>{
 const result={book:{id:'new"><img src=x>',title:'<script>Title</script>',author:'A & B',source:'api',coverUrl:null,color:'#123456'},
  reasons:{a:{seedId:'seed"><img>',seedTitle:'<Seed>',tags:[]},b:{seedId:'other',seedTitle:'Other',tags:['<theme>']}}};
 const html=bookConnectionsHTML(result,0,1,()=>undefined);
 assert.match(html,/No shared themes in this explanation/);
 assert.match(html,/&lt;Seed&gt;/);assert.match(html,/&lt;theme&gt;/);
 assert.match(html,/&lt;script&gt;Title&lt;\/script&gt;/);assert.match(html,/A &amp; B/);
 assert.doesNotMatch(html,/<script>|<img|<theme>|<Seed>/);
});

test('connection responses distinguish interest from an explicit shared choice and revoke stale confirmation',()=>{
 const result={book:{id:'book',title:'Book',author:'Writer',source:'api',coverUrl:null,color:'#123456'},
  reasons:{a:{seedId:'one',seedTitle:'One',tags:[]},b:{seedId:'two',seedTitle:'Two',tags:[]}}};
 const render=decision=>bookConnectionsHTML(result,0,1,()=>null,decision);
 const interested=render({votes:{book:{a:'yes',b:'yes'}},choice:null});
 assert.match(interested,/Reader 1: Interested/);assert.match(interested,/Reader 2: Interested/);
 assert.match(interested,/Review & choose/);assert.doesNotMatch(interested,/Chosen together/);
 const chosen=render({votes:{book:{a:'yes',b:'yes'}},choice:'book'});
 assert.match(chosen,/Chosen together/);assert.match(chosen,/Review choice/);
 const changed=render({votes:{book:{a:'yes',b:'no'}},choice:'book'});
 assert.match(changed,/Reader 2: Pass/);assert.doesNotMatch(changed,/Chosen together|Review choice/);
});
