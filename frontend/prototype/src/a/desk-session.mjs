// A Reading Desk session belongs to this origin and tab, never to an account.
// Browser-restored tabs may retain sessionStorage, so expire after 24 idle hours.
// Only allowlisted IDs and decision state are stored; no queries or book data.
export const SESSION_TTL_MS=24*60*60*1000;
const SESSION_SCHEMA=1;
const MAX_SESSION_BYTES=12000;
const isRecord=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const validId=value=>typeof value==='string'&&value.length>0&&[...value].length<=64;
const validIds=value=>Array.isArray(value)&&value.length<=5&&value.every(validId)&&new Set(value).size===value.length;
const samePicks=(left,right)=>JSON.stringify([left.a,left.b])===JSON.stringify([right.a,right.b]);
const validModel=value=>value===null||typeof value==='string'&&value.length>0&&[...value].length<=128;
const verifiedFingerprint=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);

export function parseDeskSession(raw,{api=false,now=Date.now(),knownId=()=>true}={}){
 if(typeof raw!=='string'||raw.length>MAX_SESSION_BYTES)return {snapshot:null,reason:'invalid'};
 let saved;try{saved=JSON.parse(raw);}catch{return {snapshot:null,reason:'invalid'};}
 if(!isRecord(saved)||saved.schema!==SESSION_SCHEMA||saved.scope!==(api?'api':'static')||
  !Number.isFinite(saved.savedAt)||saved.savedAt>now+60000||!validIds(saved.a)||!validIds(saved.b)||
  !['least-misery','average'].includes(saved.mode)||!['a','b'].includes(saved.reader)||
  !['select','results'].includes(saved.stage)||!['shortlist','map'].includes(saved.view)||
  !validModel(saved.modelVersion)||!(saved.artifactFingerprint==null||verifiedFingerprint(saved.artifactFingerprint))||!validIds(saved.candidates)||!isRecord(saved.votes)||
  Object.keys(saved.votes).length>5||typeof saved.deferred!=='boolean'||typeof saved.samplePair!=='boolean'||
  !(saved.selected===null||validId(saved.selected))||!(saved.choice===null||validId(saved.choice)))return {snapshot:null,reason:'invalid'};
 if(now-saved.savedAt>SESSION_TTL_MS)return {snapshot:null,reason:'expired'};
 const votes=[];
 for(const [id,answers] of Object.entries(saved.votes)){
  if(!saved.candidates.includes(id)||!isRecord(answers)||Object.keys(answers).some(reader=>!['a','b'].includes(reader))||
   Object.values(answers).some(vote=>!['yes','no','unsure'].includes(vote)))return {snapshot:null,reason:'invalid'};
  votes.push([id,{...answers}]);
 }
 const safeVotes=Object.fromEntries(votes);
 if(saved.choice!==null&&(!saved.candidates.includes(saved.choice)||safeVotes[saved.choice]?.a!=='yes'||safeVotes[saved.choice]?.b!=='yes'))return {snapshot:null,reason:'invalid'};
 const a=api?saved.a:saved.a.filter(knownId),b=api?saved.b:saved.b.filter(knownId);
 const changed=a.length!==saved.a.length||b.length!==saved.b.length;
 // Rebuild explicitly: unexpected stored fields never enter application state.
 const snapshot={a:[...a],b:[...b],mode:saved.mode,reader:saved.reader,stage:saved.stage,view:saved.view,
  modelVersion:saved.modelVersion,artifactFingerprint:api?saved.artifactFingerprint??null:null,candidates:[...saved.candidates],votes:changed?{}:safeVotes,
  choice:changed?null:saved.choice,selected:saved.selected,deferred:changed?false:saved.deferred,samplePair:saved.samplePair};
 return {snapshot,reason:changed?'missing':'restored'};
}

export function deskSessionSnapshot(state,{api=false,modelVersion=null,artifactFingerprint=null,now=Date.now()}={}){
 const candidates=state.results.slice(0,5).map(result=>result.book.id);
 const votes=Object.fromEntries(Object.entries(state.votes).filter(([id])=>candidates.includes(id))
  .map(([id,answers])=>[id,Object.fromEntries(['a','b'].filter(reader=>['yes','no','unsure'].includes(answers[reader])).map(reader=>[reader,answers[reader]]))]));
 const choice=candidates.includes(state.choice)&&votes[state.choice]?.a==='yes'&&votes[state.choice]?.b==='yes'?state.choice:null;
 return {schema:SESSION_SCHEMA,scope:api?'api':'static',savedAt:now,a:[...state.a],b:[...state.b],
  mode:state.mode,reader:state.reader,stage:state.stage,view:state.view,modelVersion:api?modelVersion:null,artifactFingerprint:api&&verifiedFingerprint(artifactFingerprint)?artifactFingerprint:null,
  candidates,votes,choice,selected:candidates.includes(state.selected)?state.selected:null,deferred:state.deferred===true,samplePair:state.samplePair===true};
}

export function restoreDeskDecision(state,snapshot,{api=false,modelVersion=null,artifactFingerprint=null}={}){
 const verifiedModel=snapshot.modelVersion!==null&&snapshot.modelVersion===modelVersion&&verifiedFingerprint(snapshot.artifactFingerprint)&&verifiedFingerprint(artifactFingerprint)&&snapshot.artifactFingerprint===artifactFingerprint;
 const compatible=samePicks(state,snapshot)&&state.mode===snapshot.mode&&(!api||verifiedModel);
 if(!compatible){state.votes={};state.choice=null;state.deferred=false;return {restored:false,changed:true};}
 const ids=new Set(state.results.map(result=>result.book.id));
 state.votes=Object.fromEntries(Object.entries(snapshot.votes).filter(([id])=>ids.has(id)).map(([id,answers])=>[id,{...answers}]));
 state.choice=ids.has(snapshot.choice)&&state.votes[snapshot.choice]?.a==='yes'&&state.votes[snapshot.choice]?.b==='yes'?snapshot.choice:null;
 state.deferred=state.choice===null&&snapshot.deferred;
 if(ids.has(snapshot.selected))state.selected=snapshot.selected;
 return {restored:true,changed:snapshot.choice!==state.choice||Object.keys(snapshot.votes).some(id=>!ids.has(id))};
}

export function createDeskSessionStore({storage,api=false,now=()=>Date.now()}={}){
 const key=`tastebridge:reading-desk:v${SESSION_SCHEMA}:${api?'api':'static'}`;
 const store={available:true,
  load({search='',knownId}={}){
   const query=new URLSearchParams(search);
   // A shared/project link always wins, including an explicitly empty shelf.
   if(query.has('a')||query.has('b'))return {snapshot:null,reason:'url'};
   try{
    const source=storage(),raw=source.getItem(key);
    if(raw===null)return {snapshot:null,reason:'empty'};
    const result=parseDeskSession(raw,{api,now:now(),knownId});
    if(!result.snapshot)source.removeItem(key);
    return result;
   }catch{store.available=false;return {snapshot:null,reason:'unavailable'};}
  },
  save(state,modelVersion=null,artifactFingerprint=null){
   try{
    const target=storage();
    if(!state.a.length&&!state.b.length)target.removeItem(key);
    else target.setItem(key,JSON.stringify(deskSessionSnapshot(state,{api,modelVersion,artifactFingerprint,now:now()})));
    store.available=true;return true;
   }catch{
    // A failed write must not leave an older choice available for recovery.
    try{storage().removeItem(key);}catch{}
    store.available=false;return false;
   }
  },
  clear(){try{storage().removeItem(key);return true;}catch{store.available=false;return false;}}
 };
 return store;
}
