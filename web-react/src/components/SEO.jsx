import React from 'react';
import HelmetAsync from 'react-helmet-async';
const {Helmet}=HelmetAsync;
import {metadataFor,schemaFor} from '../data/seo.js';
export default function SEO({page}) {
 const m=metadataFor(page);
 return <Helmet>
   <title>{m.title}</title><meta name="description" content={m.description}/>
   <link rel="canonical" href={m.canonical}/>
   <meta property="og:title" content={m.title}/><meta property="og:description" content={m.description}/>
   <meta property="og:type" content="website"/><meta property="og:url" content={m.canonical}/>
   <meta property="og:image" content={m.image}/><meta name="twitter:card" content="summary_large_image"/>
   <meta name="twitter:title" content={m.title}/><meta name="twitter:description" content={m.description}/>
   <meta name="twitter:image" content={m.image}/>
   {page==='404.html'&&<meta name="robots" content="noindex,nofollow"/>}
   <script type="application/ld+json">{JSON.stringify(schemaFor(page)).replace(/</g,'\\u003c')}</script>
 </Helmet>;
}
