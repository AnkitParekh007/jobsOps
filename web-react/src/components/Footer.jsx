import React from 'react';
import {Link} from 'react-router-dom';
import Brand from './Brand.jsx';
import {repo} from '../data/legacyContent.js';
import {pathFor} from '../data/seo.js';
const groups=[['Explore',['Features','features.html'],['Documentation','docs.html'],['Search','search.html']],['Project',['About','about.html'],['Releases',repo+'/releases'],['Source code',repo]],['Support',['Contact','contact.html'],['Issues',repo+'/issues'],['Discussions',repo+'/discussions']]];
export default function Footer(){
 return <footer className="footer"><div className="wrap"><div className="foot-grid">
  <div><Brand/><p style={{marginTop:15,fontSize:13,maxWidth:315}}>Open-source, policy-governed job-search operations. Built for evidence, human review and control.</p><span className="pill">Preview · submissions off</span></div>
  {groups.map(([heading,...links])=><div key={heading}><h4>{heading}</h4>{links.map(([label,url])=>url.startsWith('http')
     ? <a key={label} href={url} target="_blank" rel="noopener noreferrer">{label}</a>
     : <Link key={label} to={pathFor(url)}>{label}</Link>)}</div>)}
 </div><div className="copyright"><span>© {new Date().getFullYear()} jobOps contributors · MIT licensed</span><span>No guarantee of interviews or offers</span></div></div></footer>;
}
