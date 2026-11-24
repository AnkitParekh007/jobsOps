import React from 'react';
const glyphs={
 search:<><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></>,
 monitor:<><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/></>,
 sun:<><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/></>,
 moon:<path d="M20 15A8 8 0 0 1 9 4a9 9 0 1 0 11 11Z"/>,
 menu:<path d="M4 7h16M4 12h16M4 17h16"/>,
 github:<path d="M9 19c-4 1-4-2-6-2m12 5v-4a3 3 0 0 0-1-2c4-.5 7-2 7-7a5 5 0 0 0-1-3 5 5 0 0 0 0-4s-2 0-4 2a14 14 0 0 0-8 0C6 2 4 2 4 2a5 5 0 0 0 0 4 5 5 0 0 0-1 3c0 5 3 6.5 7 7a3 3 0 0 0-1 2v4"/>
};
export default function NavIcon({name}){
 return <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{glyphs[name]||null}</svg>;
}
