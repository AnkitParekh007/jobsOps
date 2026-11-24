import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Link,useLocation} from 'react-router-dom';
import {docs,menu} from '../data/legacyContent.js';
import {pathFor} from '../data/seo.js';
function ResultLink({item}){
 const inner=<><small>{item.kind}</small><strong>{item.title}</strong><span>{item.summary}</span></>;
 return item.url.startsWith('http')?<a className="result" href={item.url} target="_blank" rel="noopener noreferrer">{inner}</a>:<Link className="result" to={pathFor(item.url)}>{inner}</Link>;
}
export default function SearchPage(){
 const loc=useLocation(),[value,setValue]=useState(''),ref=useRef(null);
 useEffect(()=>{setValue(new URLSearchParams(loc.search).get('q')||'');ref.current?.focus()},[loc.search]);
 const entries=useMemo(()=>docs.concat(menu.map(([url,title])=>({url,title,kind:'Site',summary:'Explore the '+title.toLowerCase()+' page of JobOps.',keywords:title.toLowerCase()}))),[]);
 const terms=value.toLowerCase().trim().split(/\s+/).filter(Boolean);
 const results=entries.map(x=>({...x,score:terms.reduce((score,t)=>score+(x.title.toLowerCase().includes(t)?5:0)+(x.summary.toLowerCase().includes(t)?1:0),0)})).filter(x=>terms.every(t=>(x.title+' '+x.summary+' '+x.keywords).toLowerCase().includes(t))).sort((a,b)=>b.score-a.score||a.title.localeCompare(b.title));
 return <div className="wrap"><div className="intro"><span className="pill">Site search</span><h1>Find what <span className="gradient">matters.</span></h1><p>Search across site pages and repository guide topics. Press <kbd>/</kbd> to open search from anywhere.</p></div>
 <label htmlFor="searchbox" className="sr">Search pages and documentation</label>
 <input ref={ref} id="searchbox" className="search" type="search" placeholder="Try discovery, installation, security, source evidence…" autoComplete="off" value={value} onChange={e=>setValue(e.target.value)}/>
 <p style={{fontSize:13,marginTop:10}} id="count" role="status" aria-live="polite">{results.length} results{terms.length?' for “'+value+'”':''}</p>
 <div id="results" className="results">{results.length?results.map(x=><ResultLink key={x.url} item={x}/>):<p>No matches. Try “discovery”, “security”, “installation”, or “review”.</p>}</div></div>;
}
