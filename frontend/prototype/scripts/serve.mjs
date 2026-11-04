import {createServer,request as httpRequest} from 'node:http';
import {request as httpsRequest} from 'node:https';
import {readFile} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

const here=dirname(fileURLToPath(import.meta.url));
const routes=new Map([['/','index.html'],['/a/','a/index.html'],['/b/','b/index.html'],['/project/','project/index.html']]);
const json=(res,status,value)=>{if(!res.headersSent)res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value));};

export function standaloneConfig(env=process.env){
 const port=Number(env.PORT||4176);
 if(!Number.isInteger(port)||port<1||port>65535)throw new Error('PORT must be an integer between 1 and 65535.');
 return {port,host:env.TASTEBRIDGE_HOST||'127.0.0.1',apiBase:env.API_BASE_URL||'http://127.0.0.1:9000'};
}

export function createFrontendServer({root=resolve(here,'../dist'),apiBase,log=()=>{}}){
 const backend=new URL(apiBase);
 if(!['http:','https:'].includes(backend.protocol)||backend.username||backend.password||backend.search||backend.hash)throw new Error('Invalid API base URL.');
 return createServer(async(req,res)=>{
  const started=Date.now(),url=new URL(req.url,'http://frontend.invalid');
  res.on('finish',()=>log(`${req.method} ${url.pathname} ${res.statusCode} ${Date.now()-started}ms`));
  if(url.pathname==='/healthz'){json(res,200,{status:'ok',service:'frontend'});return;}
  if(url.pathname.startsWith('/api/')){
   const path=url.pathname.slice(4);
   const allowed=(req.method==='GET'&&(path==='/health'||path==='/books/search'||/^\/books\/[^/]+$/.test(path)))||
    (req.method==='POST'&&(path==='/recommend'||path==='/feedback'));
   if(!allowed){json(res,404,{detail:'Unknown API route.'});return;}
   if(Number(req.headers['content-length']||0)>65536){json(res,413,{detail:'Request body too large.'});return;}
   const target=new URL(`${backend.href.replace(/\/$/,'')}${path}${url.search}`);
   const upstream=(backend.protocol==='https:'?httpsRequest:httpRequest)(target,{
    method:req.method,headers:{Accept:'application/json',...(req.headers['content-type']?{'Content-Type':req.headers['content-type']}:{})}
   },reply=>{
    res.writeHead(reply.statusCode||502,{'Content-Type':reply.headers['content-type']||'application/json','Cache-Control':'no-store'});
    reply.on('error',()=>res.destroy());reply.pipe(res);
   });
   upstream.setTimeout(15000,()=>upstream.destroy(new Error('API timeout')));
   upstream.on('error',()=>{if(!res.headersSent)json(res,503,{detail:'API unavailable.'});else res.destroy();});
   req.on('aborted',()=>upstream.destroy());
   res.on('close',()=>{if(!res.writableFinished)upstream.destroy();});
   let bytes=0;
   req.on('data',chunk=>{bytes+=chunk.length;if(bytes>65536){json(res,413,{detail:'Request body too large.'});upstream.destroy();}else if(!upstream.destroyed)upstream.write(chunk);});
   req.on('end',()=>upstream.end());return;
  }
  if(req.method!=='GET'&&req.method!=='HEAD'){json(res,405,{detail:'Method not allowed.'});return;}
  if((url.pathname==='/'||url.pathname==='/a/')&&!url.searchParams.has('api')){
   url.pathname='/a/';url.searchParams.set('api','1');res.writeHead(302,{Location:`${url.pathname}${url.search}`});res.end();return;
  }
  if(!routes.has(url.pathname)){
   if(routes.has(`${url.pathname}/`)){res.writeHead(302,{Location:`${url.pathname}/${url.search}`});res.end();return;}
   json(res,404,{detail:'Page not found.'});return;
  }
  try{
   const html=await readFile(resolve(root,routes.get(url.pathname)));
   res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
   res.end(req.method==='HEAD'?undefined:html);
  }catch{json(res,503,{detail:'Build the frontend before starting this server.'});}
 });
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const {port,host,apiBase}=standaloneConfig();
 const server=createFrontendServer({apiBase,log:line=>console.log(line)});
 server.listen(port,host,()=>console.log(`TasteBridge frontend ready on ${host}:${port}`));
 const stop=()=>{server.closeAllConnections();server.close();};
 process.on('SIGINT',stop);process.on('SIGTERM',stop);
}
