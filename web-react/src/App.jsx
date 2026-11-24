import React from 'react';
import {Routes,Route,Navigate,useLocation} from 'react-router-dom';
import SEO from './components/SEO.jsx';
import SiteLayout from './layouts/SiteLayout.jsx';
import LegacyPage from './pages/LegacyPage.jsx';
import SearchPage from './pages/SearchPage.jsx';
import NotFound from './pages/NotFound.jsx';
import {ROUTES,pathFor} from './data/seo.js';
function Page({name}){return <><SEO page={name}/>{name==='search.html'?<SearchPage/>:<LegacyPage name={name}/>}</>;}
function LegacyRedirect({page}){const l=useLocation();return <Navigate replace to={pathFor(page)+l.search+l.hash}/>;}
export default function App(){
 return <Routes><Route element={<SiteLayout/>}>
  <Route index element={<Page name="index.html"/>}/>
  {ROUTES.filter(name=>name!=='index.html').map(name=><Route key={name} path={pathFor(name)} element={<Page name={name}/>}/>)}
  {ROUTES.map(name=><Route key={'legacy-'+name} path={'/'+name} element={<LegacyRedirect page={name}/>}/>)} 
  <Route path="*" element={<><SEO page="404.html"/><NotFound/></>}/>
 </Route></Routes>;
}
