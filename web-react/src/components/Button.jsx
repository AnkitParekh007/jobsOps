import React from 'react';
import {Link} from 'react-router-dom';
export default function Button({href,children,primary=false,className='',...rest}){
 const classes=['btn',primary?'primary':'',className].filter(Boolean).join(' ');
 if(/^https?:\/\//.test(href))return <a className={classes} href={href} target="_blank" rel="noopener noreferrer" {...rest}>{children}</a>;
 return <Link className={classes} to={href} {...rest}>{children}</Link>;
}
