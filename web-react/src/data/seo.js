export const SITE='https://ankitparekh007.github.io/jobsOps/';
export const REPO='https://github.com/AnkitParekh007/jobsOps';
export const BASE='/jobsOps/';
export const ROUTES=['index.html','features.html','docs.html','about.html','contact.html','search.html'];
export const CLEAN_ROUTES=Object.fromEntries(ROUTES.map(page=>[page,page==='index.html'?'/':'/'+page.replace(/\.html$/,'/')]));
export const pathFor=page=>CLEAN_ROUTES[page]||'/';
export const CANONICAL=Object.fromEntries(ROUTES.map(page=>[page,SITE+pathFor(page).slice(1)]));
export const META={
'index.html':{title:'JobOps — Evidence-based job discovery and human review',description:'Explore JobOps, the open-source review-first toolkit for discovering public ATS jobs, preserving source evidence, detecting duplicates and making informed decisions.'},
'features.html':{title:'JobOps Features — Discovery, Provenance and Review',description:'See which JobOps capabilities are implemented, experimental or disabled, including public ATS discovery, evidence capture, deduplication and human review controls.'},
'docs.html':{title:'JobOps Documentation — Installation, Discovery and Security',description:'Read JobOps setup instructions, public Greenhouse and Lever discovery guides, review-first workflows, architecture references, security practices and release requirements.'},
'about.html':{title:'About JobOps — Open-source, Policy-governed Job Search',description:'Discover the principles behind JobOps: transparent job-search research, candidate privacy, source evidence, explicit human approvals and responsible open-source development.'},
'contact.html':{title:'Contact JobOps — Community Support and Contributions',description:'Find the official JobOps GitHub Issues, Discussions, contribution guidelines and responsible security-reporting policy for questions, feedback and open-source collaboration.'},
'search.html':{title:'Search JobOps — Documentation and Guides',description:'Search JobOps documentation topics, installation instructions, public ATS discovery, security boundaries, product features and the open-source development roadmap.'},
'404.html':{title:'Page Not Found — JobOps',description:'The requested JobOps page could not be found. Browse the documentation or return to the official open-source JobOps homepage.'}
};
export function metadataFor(route){const key=META[route]?route:'404.html';return {...META[key],canonical:CANONICAL[key]||SITE,image:SITE+'assets/social-preview.svg'};}
export function schemaFor(route){
 const m=metadataFor(route);
 const website={'@type':'WebSite','@id':SITE+'#website',name:'JobOps',url:SITE,description:META['index.html'].description};
 const page={'@type':'WebPage','@id':m.canonical+'#webpage',url:m.canonical,name:m.title,description:m.description,isPartOf:{'@id':SITE+'#website'},breadcrumb:{'@id':m.canonical+'#breadcrumb'}};
 const items=route==='index.html'?[{'@type':'ListItem',position:1,name:'Home',item:SITE}]:[{'@type':'ListItem',position:1,name:'Home',item:SITE},{'@type':'ListItem',position:2,name:route.replace('.html','').replace(/^./,x=>x.toUpperCase()),item:m.canonical}];
 return {'@context':'https://schema.org','@graph':[website,page,{'@type':'BreadcrumbList','@id':m.canonical+'#breadcrumb',itemListElement:items}]};
}
