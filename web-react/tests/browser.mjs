import {chromium} from 'playwright';
import {mkdir} from 'node:fs/promises';
import {ROUTES} from '../src/data/seo.js';
const origin='http://127.0.0.1:4173/jobsOps/';
await mkdir('browser-evidence',{recursive:true});
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 for(const width of [1440,390,320]){
  const context=await browser.newContext({viewport:{width,height:850},colorScheme:'dark',reducedMotion:'reduce'});
  const page=await context.newPage(), errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  for(const route of ROUTES){
   const response=await page.goto(origin+(route==='index.html'?'':route),{waitUntil:'networkidle'});
   if(!response||response.status()!==200)throw Error('HTTP error '+route);
   if(await page.locator('main h1').count()!==1)throw Error('heading '+route);
   const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth);
   if(overflow>1)throw Error('horizontal overflow '+route+' '+width+' '+overflow);
   if(errors.length)throw Error('JS console errors '+errors.join('; '));
   if(route==='index.html')await page.screenshot({path:'browser-evidence/home-'+width+'.png',fullPage:true});
  }
  await page.goto(origin);
  await page.locator('[data-mode="dark"]').click();
  if(await page.locator('html').getAttribute('data-theme')!=='dark')throw Error('dark theme');
  await page.reload();
  if(await page.locator('html').getAttribute('data-theme')!=='dark')throw Error('persisted theme');
  await page.locator('[data-mode="auto"]').click();
  if(await page.locator('html').getAttribute('data-theme')!=='dark')throw Error('system mode');
  await page.locator('[data-mode="light"]').click();
  if(width<=900){
   const m=page.locator('#menu');await m.click();
   if(await m.getAttribute('aria-expanded')!=='true')throw Error('mobile menu');
   await page.keyboard.press('Escape');
   if(await m.getAttribute('aria-expanded')!=='false')throw Error('escape');
  }
  await page.locator('#hero-query').fill('security');
  await page.locator('.hero-search button').click();
  await page.waitForURL('**/search.html?q=security');
  if(await page.locator('.result').count()<1)throw Error('search results');
  await page.goto(origin);
  await page.keyboard.press('/');
  await page.waitForURL('**/search.html');
  await context.close();
 }
 const res=await browser.newPage();
 const unknown=await res.goto(origin+'an-unknown-route');
 if(!unknown||unknown.status()!==404)throw Error('Unknown route did not serve HTTP 404');
 console.log('PASS all pages, three viewport widths, theme/menu/search, direct navigation and HTTP 404');
}finally{await browser.close()}
