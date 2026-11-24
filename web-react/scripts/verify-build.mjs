import {readFile,stat} from 'node:fs/promises';
import {resolve} from 'node:path';
import {ROUTES,metadataFor,SITE,pathFor,BASE} from '../src/data/seo.js';

const canonicals=new Set(),titles=new Set();
for(const page of ROUTES){
 const clean=pathFor(page);
 const file=clean==='/'?'dist/index.html':'dist/'+clean.slice(1)+'index.html';
 const content=await readFile(resolve(file),'utf8');
 const m=metadataFor(page);
 const title=content.match(/<title[^>]*>(.*?)<\/title>/s)?.[1];
 if(!title||!title.includes('JobOps')||titles.has(title))throw new Error(page+': missing or repeated title');
 titles.add(title);
 if(!content.includes('name="description"')||!content.includes('rel="canonical"')||!content.includes(m.canonical))throw new Error(page+': missing or incorrect SEO');
 for(const tag of ['og:title','og:description','og:type','og:url','og:image','twitter:card','twitter:title','twitter:description','twitter:image']){
   if(!content.includes(tag))throw new Error(page+': missing '+tag);
 }
 if(!content.includes('application/ld+json')||!content.includes('schema.org'))throw new Error(page+': missing JSON-LD');
 const headings=(content.match(/<h1(?:\s|>)/g)||[]).length;
 if(headings!==1)throw new Error(page+': expected exactly one H1, got '+headings);
 if(!content.includes('id="app"')||!content.includes('<main'))throw new Error(page+': missing pre-rendered content');
 if(page!=='index.html'){
   const redirect=await readFile(resolve('dist',page),'utf8');
   if(!redirect.includes('noindex,follow')||!redirect.includes('location.replace')||!redirect.includes(BASE+clean.slice(1)))throw new Error(page+': missing legacy redirect');
 }
 canonicals.add(m.canonical);
}
const sitemap=await readFile(resolve('dist/sitemap.xml'),'utf8');
for(const url of canonicals)if(!sitemap.includes('<loc>'+url+'</loc>'))throw new Error('sitemap missing '+url);
for(const page of ROUTES.filter(x=>x!=='index.html'))if(sitemap.includes('/'+page+'</loc>'))throw new Error('old .html URL in sitemap: '+page);
const robots=await readFile(resolve('dist/robots.txt'),'utf8');
if(!robots.includes('Sitemap: '+SITE+'sitemap.xml'))throw new Error('robots.txt sitemap');
const notFound=await readFile(resolve('dist/404.html'),'utf8');
if(!notFound.includes('That route doesn'))throw new Error('404 missing');
await stat(resolve('dist/assets/jobops-mark.svg'));
await stat(resolve('dist/assets/social-preview.svg'));
console.log('PASS: clean pre-rendered routes, old URL redirects, SEO, sitemap, robots, and assets');
