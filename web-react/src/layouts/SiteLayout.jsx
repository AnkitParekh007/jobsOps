import React,{useEffect} from 'react';
import {Outlet,useLocation} from 'react-router-dom';
import Header from '../components/Header.jsx';
import Footer from '../components/Footer.jsx';
export default function SiteLayout(){
 const {pathname,hash}=useLocation();
 useEffect(()=>{document.documentElement.dataset.reactReady="true";return()=>{delete document.documentElement.dataset.reactReady}},[]);
 useEffect(()=>{if(hash){const el=document.getElementById(decodeURIComponent(hash.slice(1)));el?.scrollIntoView();}else{window.scrollTo(0,0)}},[pathname,hash]);
 return <><a className="skip" href="#app">Skip to content</a><Header/><main id="app"><Outlet/></main><Footer/></>;
}
