import {byId} from './shared/engine.mjs';
import {bookTile,svg,escape} from './shared/ui.mjs';
import {readerConnection,sampleFit} from './desk-interactions.mjs';
import {reasonHTML} from './shared/ui.mjs';
import {voteLabel,bothWilling} from './desk-decision.mjs';

export const readerName=reader=>reader==='a'?'Reader 1':'Reader 2';
export function readingShelf(ids,reader){
 return Array.from({length:5},(_,index)=>{
  const book=byId(ids[index]);
  return book?`<button class="seed-slot filled" data-remove="${escape(book.id)}" aria-label="Remove ${escape(book.title)} from ${readerName(reader)} favorites">${bookTile(book,{compact:true})}<span class="slot-remove">${svg('close')}</span></button>`:`<button class="seed-slot vacant" data-add-reader="${reader}" aria-label="Choose favorite ${index+1} for ${readerName(reader)}"><span>${index+1}</span>${svg('plus')}</button>`;
 }).join('');
}
export function catalogueSelection(book,a,b,reader){
 const current=reader==='a'?a:b,other=reader==='a'?b:a,selected=current.includes(book.id),otherSelected=other.includes(book.id);
 const otherReader=reader==='a'?'b':'a';
 return {selected,label:selected?'Selected':otherSelected?`${readerName(otherReader)} picked this`:book.source==='api'?'Pick this book':book.kind==='mystery'?'Mystery':book.kind==='fantasy'?'Fantasy':'Fantasy / Mystery',ariaLabel:`${selected?'Remove':'Add'} ${book.title} ${selected?'from':'to'} ${readerName(reader)} favorites${otherSelected?`; also picked by ${readerName(otherReader)}`:''}`};
}
export function shortlistCardHTML(result,index,{votes={},selected=false,chosen=false,api=false}={}){
 const responses=['a','b'].filter(reader=>votes[reader]);
 return `<button class="result-card ${selected?'selected':''} ${chosen?'joint-choice':''}" data-result="${escape(result.book.id)}" aria-label="View ${escape(result.book.title)} and both readers' reasons${chosen?'; chosen together':''}"><span class="rank-number" aria-hidden="true">${index+1}</span>${bookTile(result.book)}<div class="result-info"><div class="result-title-line"><h2>${escape(result.book.title)}</h2><span class="detail-cue" aria-hidden="true">↗</span></div><p>${escape(result.book.author)}</p><div class="result-evidence-preview">${['a','b'].map(reader=>{
  const fit=sampleFit(reader==='a'?result.fitA:result.fitB,{api});
  return `<div class="result-reason-preview reader-${reader}"><span class="reason-preview-label">${readerName(reader)}<span class="preview-fit">${escape(fit.label)}</span></span><span class="reference-prefix">From your pick </span><strong>${escape(result.reasons[reader].seedTitle)}</strong><span class="reason-preview-tags">${result.reasons[reader].tags.slice(0,2).map(escape).join(' · ')||'No shared themes'}</span></div>`;
 }).join('')}</div><div class="card-vote-row">${responses.map(reader=>`<span class="reader-${reader}">${readerName(reader)}: ${voteLabel(votes[reader])}</span>`).join('')}${chosen?'<strong class="card-outcome">Chosen together</strong>':bothWilling(votes)?'<span class="card-outcome">Both interested</span>':''}<span class="card-open-label">${chosen?'Review choice':bothWilling(votes)?'Review & choose':'View reasons & respond'} <span aria-hidden="true">→</span></span></div></div></button>`;
}
export function readerEvidenceHTML(result,reader,favorites,exploration,{includeReason=true}={}){
 const connection=readerConnection(result,reader,favorites),fit=connection.fit;
 return `<section class="reader-evidence reader-${reader}" aria-label="Evidence for ${readerName(reader)}">${includeReason?reasonHTML(result,reader):''}<button class="evidence-seed" data-seed="${escape(connection.seed.id)}" data-reader="${reader}"><span>From your five</span><strong>${escape(connection.seed.title)}</strong><span aria-hidden="true">↗</span></button><div class="evidence-tags">${connection.sharedTags.map(theme=>`<button data-theme="${escape(theme)}" data-reader="${reader}" aria-pressed="${exploration?.kind==='theme'&&exploration.reader===reader&&exploration.theme===theme}">${escape(theme)}</button>`).join('')}</div><div class="reader-fit" data-fit="${fit.level}"><span class="fit-label">${fit.label}</span><span class="fit-track" aria-hidden="true">${Array.from({length:3},(_,index)=>`<i class="${index<fit.filled?'active':''}"></i>`).join('')}</span><small>${result.book.source==='api'?'Model similarity':'Approximate sample-theme fit'}</small></div></section>`;
}
