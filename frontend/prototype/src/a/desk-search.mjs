// Match the words readers type without requiring accented letters or punctuation.
export function normalizedBookSearch(value){
 return value.normalize('NFKD').replace(/\p{M}/gu,'').toLowerCase().replace(/['’‘]/gu,'').replace(/[^\p{L}\p{N}]+/gu,' ').trim();
}
export function matchesBookSearch(book,query){
 return normalizedBookSearch(`${book.title} ${book.author}`).includes(normalizedBookSearch(query));
}
