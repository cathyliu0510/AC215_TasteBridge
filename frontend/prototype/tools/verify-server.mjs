import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createFrontendServer} from '../scripts/serve.mjs';

test('same-origin API relay preserves IDs, JSON and backend validation without forwarding browser cookies',async()=>{
 let received;
 const backend=createServer(async(req,res)=>{
  let body='';for await(const chunk of req)body+=chunk;
  received={method:req.method,url:req.url,headers:req.headers,body};
  res.writeHead(req.url.startsWith('/books/missing')?404:200,{'Content-Type':'application/json'});
  res.end(JSON.stringify(req.method==='POST'?{ok:true}:{book_id:'w_opaque',title:'A book'}));
 });
 await new Promise(resolve=>backend.listen(0,'127.0.0.1',resolve));
 const frontend=createFrontendServer({apiBase:`http://127.0.0.1:${backend.address().port}`});
 await new Promise(resolve=>frontend.listen(0,'127.0.0.1',resolve));
 const base=`http://127.0.0.1:${frontend.address().port}`;
 try{
  assert.equal((await(await fetch(`${base}/api/books/search?q=A%26B`)).json()).book_id,'w_opaque');
  assert.equal(received.url,'/books/search?q=A%26B');
  const input={book_id:'w_opaque',vote:'would_read',model_version:'sample-v1'};
  await fetch(`${base}/api/feedback`,{method:'POST',headers:{'Content-Type':'application/json',Cookie:'private=secret'},body:JSON.stringify(input)});
  assert.deepEqual(JSON.parse(received.body),input);assert.equal(received.headers.cookie,undefined);
  assert.equal((await fetch(`${base}/api/books/missing`)).status,404);
  assert.equal((await fetch(`${base}/api/arbitrary`)).status,404);
 }finally{frontend.closeAllConnections();backend.closeAllConnections();await Promise.all([new Promise(resolve=>frontend.close(resolve)),new Promise(resolve=>backend.close(resolve))]);}
});

test('an unavailable API returns a recoverable JSON error',async()=>{
 const backend=createServer();await new Promise(resolve=>backend.listen(0,'127.0.0.1',resolve));
 const port=backend.address().port;await new Promise(resolve=>backend.close(resolve));
 const frontend=createFrontendServer({apiBase:`http://127.0.0.1:${port}`});await new Promise(resolve=>frontend.listen(0,'127.0.0.1',resolve));
 try{const reply=await fetch(`http://127.0.0.1:${frontend.address().port}/api/health`);assert.equal(reply.status,503);assert.deepEqual(await reply.json(),{detail:'API unavailable.'});}
 finally{frontend.closeAllConnections();await new Promise(resolve=>frontend.close(resolve));}
});

test('static serving defaults to connected A and never exposes files outside the built routes',async()=>{
 const root=await mkdtemp(join(tmpdir(),'tastebridge-server-'));await writeFile(join(root,'index.html'),'<h1>Offline demo</h1>');
 const frontend=createFrontendServer({root,apiBase:'http://127.0.0.1:9'});await new Promise(resolve=>frontend.listen(0,'127.0.0.1',resolve));
 const base=`http://127.0.0.1:${frontend.address().port}`;
 try{
  const home=await fetch(`${base}/`,{redirect:'manual'});assert.equal(home.headers.get('location'),'/a/?api=1');
  assert((await(await fetch(`${base}/?api=0`)).text()).includes('Offline demo'));
  assert.equal((await fetch(`${base}/.env`)).status,404);
  assert.equal((await fetch(`${base}/src/backend/sample_artifacts/books.json`)).status,404);
  assert.equal((await fetch(`${base}/api/recommend`,{method:'POST',body:'x'.repeat(65537)})).status,413);
 }finally{frontend.closeAllConnections();await new Promise(resolve=>frontend.close(resolve));await rm(root,{recursive:true,force:true});}
});


test('frontend health has a namespaced external route and retains the internal startup probe',async()=>{
 const frontend=createFrontendServer({apiBase:'http://127.0.0.1:9'});
 await new Promise(resolve=>frontend.listen(0,'127.0.0.1',resolve));
 const base=`http://127.0.0.1:${frontend.address().port}`;
 try{
  for(const path of ['/frontend/health','/healthz']){
   const reply=await fetch(base+path);
   assert.equal(reply.status,200);
   assert.equal(reply.headers.get('cache-control'),'no-store');
   assert.deepEqual(await reply.json(),{status:'ok',service:'frontend'});
  }
  assert.equal((await fetch(base+'/frontend/private')).status,404);
 }finally{frontend.closeAllConnections();await new Promise(resolve=>frontend.close(resolve));}
});
