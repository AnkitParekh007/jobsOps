import React from 'react';
import {Link} from 'react-router-dom';
import {BASE} from '../data/seo.js';
export default function Brand(){
 return <Link className="brand" to="/" aria-label="JobOps home"><img className="brand-mark" src={BASE+'assets/jobops-mark.svg'} alt="" width="40" height="40" decoding="async"/><span className="brand-wordmark"><span className="brand-job">Job</span><span className="brand-ops">Ops</span></span></Link>;
}
