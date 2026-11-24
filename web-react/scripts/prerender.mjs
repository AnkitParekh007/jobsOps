import {readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {createServer} from 'vite';
import {ROUTES} from '../src/data/seo.js';
const root=resolve(process.cwd());
const vite=await createServer({root,server:{middlewareMode:true},appType:'custom',logLevel:'error'});
try{
  const {render}=await vite.ssrLoadModule('/src/entry-server.jsx');
  const shell=await readFile(resolve(root,'dist/index.html'),'utf8');
  if(!shell.includes('<div id="root"></div>'))throw new Error('Vite shell missing root');
  for(const route of ROUTES){
    const {html,helmet}=render(route);
    if(!html.includes('<h1'))throw new Error('Server render missing h1 on '+route);
    const markup=[
      helmet.title.toString(),helmet.meta.toString(),helmet.link.toString(),
      helmet.script.toString()
    ].join('\n');
    const final=shell.replace(/<title>[^<]*<\/title>/,'').replace('</head>',markup+'\n</head>')
      .replace('<div id="root"></div>','<div id="root">'+html+'</div>');
    await writeFile(resolve(root,'dist',route),final,'utf8');
  }
  // GitHub Pages should serve existing HTML pages directly; unknown paths use
  // the dedicated status-404 page copied from public/404.html.
  console.log('Pre-rendered '+ROUTES.length+' crawlable HTML documents');
}finally{await vite.close()}
