import React from 'react';
import {hydrateRoot,createRoot} from 'react-dom/client';
import {BrowserRouter} from 'react-router-dom';
import {HelmetProvider} from 'react-helmet-async';
import App from './App.jsx';
import './styles/site.css';
const element=<React.StrictMode><HelmetProvider><BrowserRouter basename="/jobsOps"><App/></BrowserRouter></HelmetProvider></React.StrictMode>;
const root=document.getElementById('root');
if(root.hasChildNodes())hydrateRoot(root,element);else createRoot(root).render(element);
