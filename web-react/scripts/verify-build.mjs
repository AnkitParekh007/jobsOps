import {readFile,stat} from 'node:fs/promises';
import {resolve} from 'node:path';
import {ROUTES,metadataFor,SITE} from '../src/data/seo.js';
const paths=new Set(),titles=new Set();
for(const route of ROUTES){
 const content=await readFile(resolve('dist',route),'utf8');
 const m=metadataFor(route);
 const title=content.match(/<title[^>]*>(.*?)<\/title>/s)?.[1];
 if(!title||!title.includes('JobOps'))throw new Error(route+': title');
 if(titles.has(title))throw new Error(route+': duplicate title');
 titles.add(title);
 if(!content.includes('name="description"')||!content.includes('rel="canonical"'))throw new Error(route+': missing SEO');
 if(!content.includes(m.canonical))throw new Error(route+': wrong canonical');
 for(const tag of ['og:title','og:description','og:type','og:url','og:image','twitter:card','twitter:title','twitter:description','twitter:image']){
   if(!content.includes(tag))throw new Error(route+': missing '+tag);
 }
 if(!content.includes('application/ld+json')||!content.includes('schema.org'))throw new Error(route+': missing schema');
 const h1=(content.match(/<h1(?:\s|>)/g)||[]).length;
 if(h1!==1)throw new Error(route+': expected 1 heading, found '+h1);
 if(!content.includes('id="app"')||!content.includes('<main'))throw new Error(route+': missing pre-rendered body');
 if(!content.includes('JobOps')&&!content.includes('Job'))throw new Error(route+': content missing');
 paths.add(m.canonical);
}
const sitemap=await readFile(resolve('dist/sitemap.xml'),'utf8');
for(const path of paths){if(!sitemap.includes('<loc>'+path+'</loc>'))throw new Error('Sitemap missing '+path)}
const robots=await readFile(resolve('dist/robots.txt'),'utf8');
if(!robots.includes('Sitemap: '+SITE+'sitemap.xml'))throw new Error('robots.txt sitemap');
const notfound=await readFile(resolve('dist/404.html'),'utf8');
if(!notfound.includes('That route doesn'))throw new Error('404 missing');
await stat(resolve('dist/assets/jobops-mark.svg'));
await stat(resolve('dist/assets/social-preview.svg'));
console.log('PASS six HTML pages, unique SEO, JSON-LD, OG/Twitter tags, assets, sitemap, robots and 404');
