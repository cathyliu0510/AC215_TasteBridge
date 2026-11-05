// A keeps opinions and the explicit joint decision in the current tab only.
export const VOTE_OPTIONS=[['yes','Interested'],['no','Pass'],['unsure','Not sure']];
export const voteLabel=value=>VOTE_OPTIONS.find(([key])=>key===value)?.[1]||'No response yet';
export const bothWilling=(votes={})=>votes.a==='yes'&&votes.b==='yes';

export function clearDecision(state){
 state.votes={};state.choice=null;state.deferred=false;
}
export function voteFor(state,id,reader,value){
 if(!['a','b'].includes(reader)||!VOTE_OPTIONS.some(([key])=>key===value))throw new Error('Invalid reader or interest.');
 if(!state.results.some(result=>result.book.id===id))throw new Error('Choose from the current five recommendations.');
 if(!Object.hasOwn(state.votes,id))Object.defineProperty(state.votes,id,{value:{},writable:true,enumerable:true,configurable:true});
 state.votes[id][reader]=value;state.deferred=false;
 const revoked=state.choice===id&&!bothWilling(state.votes[id]);
 if(revoked)state.choice=null;
 return revoked;
}
export function confirmChoice(state,id){
 if(!state.results.some(result=>result.book.id===id)||!bothWilling(state.votes[id]))return false;
 state.choice=id;state.deferred=false;return true;
}
export function deferChoice(state){state.choice=null;state.deferred=true;}
