import React from 'react';
import parse,{attributesToProps,domToReact} from 'html-react-parser';
import {Link} from 'react-router-dom';
/* Every literal is from committed, trusted site source. No user HTML is parsed. */
export function ContentSection({children,...props}){return <section {...props}>{children}</section>}
export function ToolCard({children,...props}){return <article {...props}>{children}</article>}
export default function LegacyMarkup({html}){
 const options={replace(node){
   if(node.type!=='tag')return;
   const props=attributesToProps(node.attribs||{});
   const children=()=>domToReact(node.children||[],options);
   if(node.name==='a'&&props.href&&/^(?:index|features|docs|about|contact|search)\.html(?:[?#].*)?$/.test(String(props.href))){
     const {href,...rest}=props;
     return <Link to={'/'+href} {...rest}>{children()}</Link>;
   }
   if(node.name==='section')return <ContentSection {...props}>{children()}</ContentSection>;
   if(node.name==='article')return <ToolCard {...props}>{children()}</ToolCard>;
 }};
 return <>{parse(html,options)}</>;
}
