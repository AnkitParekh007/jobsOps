import React,{useEffect,useState} from 'react';
import {Link,useLocation,useNavigate} from 'react-router-dom';
import Brand from './Brand.jsx';
import NavIcon from './NavIcon.jsx';
import ThemeSwitcher from './ThemeSwitcher.jsx';
import {menu,repo} from '../data/legacyContent.js';
import {pathFor} from '../data/seo.js';
export default function Header(){
 const location=useLocation(),navigate=useNavigate(),[open,setOpen]=useState(false);
 useEffect(()=>{setOpen(false)},[location.pathname]);
 useEffect(()=>{
   const onKey=e=>{
     if(e.key==='Escape'){setOpen(false);return}
     if(/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName||''))return;
     if((e.key==='/'&&!e.ctrlKey&&!e.metaKey&&!e.altKey)||((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k')){
       e.preventDefault();navigate('/search/');
     }
   };
   const onResize=()=>{if(window.innerWidth>900)setOpen(false)};
   window.addEventListener('keydown',onKey);window.addEventListener('resize',onResize);
   return()=>{window.removeEventListener('keydown',onKey);window.removeEventListener('resize',onResize)};
 },[navigate]);
 return <header className="header"><div className="wrap nav"><Brand/>
  <nav id="links" className={'links'+(open?' open':'')} aria-label="Main navigation">
    {menu.map(([path,label])=><Link key={path} to={pathFor(path)} aria-current={location.pathname===pathFor(path)||location.pathname===pathFor(path).replace(/\/$/,'')?'page':undefined} onClick={()=>setOpen(false)}>{label}</Link>)}
    <Link className="nav-support" to="/#support" onClick={()=>{setOpen(false);if(location.pathname==='/'&&location.hash==='#support'){document.getElementById('support')?.scrollIntoView({block:'start'});}}}>Support</Link>
  </nav>
  <div className="right">
    <Link className="nav-search" to="/search/" title="Search documentation (/ or Ctrl+K)" aria-label="Search documentation"><NavIcon name="search"/><span>Search</span><kbd>⌘ K</kbd></Link>
    <ThemeSwitcher/>
    <a className="nav-github" href={repo} target="_blank" rel="noopener noreferrer"><NavIcon name="github"/><span>GitHub</span></a>
    <button className="nav-menu" id="menu" type="button" aria-label={open?'Close navigation':'Open navigation'} aria-expanded={open} aria-controls="links" onClick={()=>setOpen(!open)}><NavIcon name="menu"/></button>
  </div>
 </div></header>;
}
