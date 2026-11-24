import React from 'react';
import {Routes,Route} from 'react-router-dom';
import SEO from './components/SEO.jsx';
import SiteLayout from './layouts/SiteLayout.jsx';
import LegacyPage from './pages/LegacyPage.jsx';
import SearchPage from './pages/SearchPage.jsx';
import NotFound from './pages/NotFound.jsx';
import {ROUTES} from './data/seo.js';
function Page({name}){return <><SEO page={name}/>{name==='search.html'?<SearchPage/>:<LegacyPage name={name}/>}</>;}
export default function App(){
 return <Routes><Route element={<SiteLayout/>}>
  <Route index element={<Page name="index.html"/>}/>
  {ROUTES.map(name=><Route key={name} path={name} element={<Page name={name}/>}/>)}
  <Route path="*" element={<><SEO page="404.html"/><NotFound/></>}/>
 </Route></Routes>;
}
