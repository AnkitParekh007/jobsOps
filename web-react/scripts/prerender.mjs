import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {createServer} from 'vite';
import {ROUTES,pathFor,metadataFor,BASE} from '../src/data/seo.js';

const root=resolve(process.cwd());
const vite=await createServer({root,server:{middlewareMode:true},appType:'custom',logLevel:'error'});
try{
  const {render}=await vite.ssrLoadModule('/src/entry-server.jsx');
  const shell=await readFile(resolve(root,'dist/index.html'),'utf8');
  if(!shell.includes('<div id="root"></div>'))throw new Error('Vite shell missing root');
  for(const page of ROUTES){
    const {html,helmet}=render(page);
    if(!html.includes('<h1'))throw new Error('Missing pre-rendered heading: '+page);
    const markup=[helmet.title.toString(),helmet.meta.toString(),helmet.link.toString(),helmet.script.toString()].join('\n');
    const output=shell.replace(/<title>[^<]*<\/title>/,'')
      .replace('</head>',markup+'\n</head>')
      .replace('<div id="root"></div>','<div id="root">'+html+'</div>');
    const clean=pathFor(page);
    const path=clean==='/'?'index.html':clean.slice(1)+'index.html';
    const destination=resolve(root,'dist',path);
    await mkdir(dirname(destination),{recursive:true});
    await writeFile(destination,output,'utf8');

    if(page!=='index.html'){
      const target=BASE+clean.slice(1);
      const canonical=metadataFor(page).canonical;
      const redirect='<!doctype html><html lang="en"><head><meta charset="utf-8">'
        +'<meta name="robots" content="noindex,follow">'
        +'<link rel="canonical" href="'+canonical+'">'
        +'<meta http-equiv="refresh" content="0;url='+target+'">'
        +'<script>location.replace('+JSON.stringify(target)+'+location.search+location.hash);</script>'
        +'<title>Page moved · JobOps</title></head><body><main>'
        +'<h1>This page has moved</h1><p><a href="'+target+'">Continue to the new JobOps page</a></p>'
        +'</main></body></html>';
      await writeFile(resolve(root,'dist',page),redirect,'utf8');
    }
  }
  console.log('Pre-rendered '+ROUTES.length+' clean routes with legacy compatibility redirects');
}finally{await vite.close()}
