import React,{useEffect} from 'react';
import {Outlet,useLocation} from 'react-router-dom';
import Header from '../components/Header.jsx';
import Footer from '../components/Footer.jsx';
export default function SiteLayout(){
 const {pathname,hash}=useLocation();
 useEffect(()=>{document.documentElement.dataset.reactReady="true";return()=>{delete document.documentElement.dataset.reactReady}},[]);
 useEffect(()=>{
  let first,second;
  if(hash){
    // Let React hydrate or commit the destination route before scrolling.
    // Using a pair of animation frames also handles direct external #support URLs.
    first=requestAnimationFrame(()=>{
      second=requestAnimationFrame(()=>{
        const id=decodeURIComponent(hash.slice(1));
        document.getElementById(id)?.scrollIntoView({block:'start'});
      });
    });
  }else{
    window.scrollTo(0,0);
  }
  return()=>{cancelAnimationFrame(first);cancelAnimationFrame(second)};
 },[pathname,hash]);
 useEffect(()=>{
  const handleHash=()=>{
    const id=decodeURIComponent(window.location.hash.slice(1));
    if(id)document.getElementById(id)?.scrollIntoView({block:'start'});
  };
  window.addEventListener('hashchange',handleHash);
  return()=>window.removeEventListener('hashchange',handleHash);
 },[]);
 return <><a className="skip" href="#app">Skip to content</a><Header/><main id="app"><Outlet/></main><Footer/></>;
}
