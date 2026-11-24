import React from 'react';
export default function DocCard({title,summary,url}){
 return <article className="docitem"><h3>{title}</h3><p>{summary}</p><a href={url} target="_blank" rel="noopener noreferrer">Read on GitHub ↗</a></article>;
}
