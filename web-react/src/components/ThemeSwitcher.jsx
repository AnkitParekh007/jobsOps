import React,{useEffect,useState} from 'react';
import NavIcon from './NavIcon.jsx';
const choices=[['auto','monitor','System theme'],['light','sun','Light theme'],['dark','moon','Dark theme']];
export default function ThemeSwitcher(){
 const [mode,setMode]=useState('light');
 useEffect(()=>{setMode(document.documentElement.dataset.mode||'light')},[]);
 useEffect(()=>{
  const media=window.matchMedia('(prefers-color-scheme: dark)');
  const sync=()=>{document.documentElement.dataset.mode=mode;document.documentElement.dataset.theme=mode==='auto'?(media.matches?'dark':'light'):mode};
  sync();media.addEventListener('change',sync);return()=>media.removeEventListener('change',sync);
 },[mode]);
 function choose(value){setMode(value);try{localStorage.setItem('jobops-theme',value)}catch{}}
 return <div className="theme-modes" role="group" aria-label="Color theme">{choices.map(([value,icon,label])=><button key={value} className="theme-mode" type="button" data-mode={value} aria-label={label} title={label} aria-pressed={mode===value} onClick={()=>choose(value)}><NavIcon name={icon}/></button>)}</div>;
}
