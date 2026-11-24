import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {sections,docs,menu} from '../src/data/legacyContent.js';
import {ROUTES,metadataFor,BASE,CANONICAL} from '../src/data/seo.js';
test('every previous page and documentation entry is preserved',async()=>{
 const old=await readFile(new URL('../../website/assets/app.js',import.meta.url),'utf8');
 const original=old.slice(old.indexOf('const sections='),old.indexOf('const navGlyph')).replace(/const header=document\.getElementById\("header"\),footer=document\.getElementById\("footer"\);\s*$/,'').trimEnd();
 const migrated=await readFile(new URL('../src/data/legacyContent.js',import.meta.url),'utf8');
 assert.ok(migrated.includes(original),'Original page HTML templates must remain byte-for-byte intact');
 assert.deepEqual(Object.keys(sections),ROUTES);
 assert.equal(docs.length,14);
 assert.equal(menu.length,5);
 for(const route of ROUTES){assert.match(sections[route],/<h1[\s>]/);}
 assert.ok(sections['index.html'].includes('buymeacoffee.com/ankitparekh'));
 assert.ok(sections['docs.html'].includes('review-live'));
});
test('correct GitHub Pages base, canonical and unique SEO',()=>{
 assert.equal(BASE,'/jobsOps/');
 const titles=new Set();
 for(const route of ROUTES){
  const m=metadataFor(route);
  assert.ok(m.title&&m.description&&m.canonical);
  assert.ok(m.canonical.startsWith('https://ankitparekh007.github.io/jobsOps/'));
  assert.ok(m.description.length>=125 && m.description.length<=190,[route,m.description.length]);
  assert.equal(CANONICAL[route],m.canonical);
  assert.ok(!titles.has(m.title));titles.add(m.title);
 }
});
