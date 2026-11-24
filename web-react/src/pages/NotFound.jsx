import React from 'react';
import {Link} from 'react-router-dom';
export default function NotFound(){
 return <div className="wrap" style={{minHeight:'60vh',display:'flex',flexDirection:'column',justifyContent:'center',alignItems:'flex-start'}}><span className="pill">404 · Page not found</span><h1 style={{margin:'24px 0'}}>That route doesn't exist.</h1><p className="lead">The page may have moved. Head to the homepage or read the documentation.</p><div className="actions"><Link className="btn primary" to="/">Back to JobOps</Link><Link className="btn" to="/docs.html">Browse documentation</Link></div></div>;
}
