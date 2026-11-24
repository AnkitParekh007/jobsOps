import React from 'react';
import {renderToString} from 'react-dom/server';
import {StaticRouter} from 'react-router-dom/server.js';
import HelmetAsync from 'react-helmet-async';
const {HelmetProvider}=HelmetAsync;
import App from './App.jsx';
export function render(path){
 const context={};
 const html=renderToString(<HelmetProvider context={context}><StaticRouter basename="/jobsOps" location={'/jobsOps/'+(path==='index.html'?'':path)}><App/></StaticRouter></HelmetProvider>);
 return {html,helmet:context.helmet};
}
