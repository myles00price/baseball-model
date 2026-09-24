/* Presentation only: preserve original nodes, data, grades and event handlers. */
(()=>{
 const init=()=>{
  if(document.body.dataset.boardSport!=='nfl'||document.body.classList.contains('nfl-facelift'))return;
  document.body.classList.add('nfl-facelift');
  const heading=document.querySelector('.vegas-pageheading'),nav=document.querySelector('.vegas-markets');
  if(heading&&nav)nav.before(heading);
  const title=document.createElement('div');title.className='nfl-title';title.textContent='PRO FOOTBALL';
  if(heading)heading.prepend(title);
  for(const card of document.querySelectorAll('.gl-game,#gamegrid>.card')){
   const head=card.querySelector('.gl-head,.ch');if(!head||head.querySelector('.nfl-art'))continue;
   const art=document.createElement('div');art.className='nfl-art';art.setAttribute('aria-hidden','true');
   [...head.querySelectorAll('img')].slice(0,2).forEach((img,i)=>{const copy=img.cloneNode();copy.className='nfl-art-logo logo-'+i;copy.removeAttribute('width');copy.removeAttribute('height');art.append(copy)});
   head.prepend(art);
  }
  const section=document.querySelector('#gamelines');
  if(section){
   const sub=document.createElement('nav');sub.className='nfl-market-tabs';sub.setAttribute('aria-label','Game line markets');
   const labels=['Spreads','Totals','Moneyline','All markets'];
   labels.forEach((label,i)=>{const button=document.createElement('button');button.type='button';button.textContent=label;
    button.onclick=()=>{section.dataset.nflMarket=String(i);sub.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)))};sub.append(button)});
   section.prepend(sub);sub.firstElementChild.click();
  }
  // Preserve explanations in a compact disclosure without replacing their contents.
  for(const note of document.querySelectorAll('.frame>.paper,#gamelines>.gl-hint,#gamelines>.gl-paper,#gamelines>.gl-pending')){
   const d=document.createElement('details'),s=document.createElement('summary');d.className='nfl-method';s.textContent=note.classList.contains('paper')?'Paper season · methodology':'Quote and market notes';
   note.before(d);d.append(s,note);
   if(section&&section.contains(d))section.append(d);
  }
  function view(){document.body.dataset.nflView=nav?.querySelector('[aria-current="page"]')?.dataset.route||'overview'}
  nav?.addEventListener('click',view);window.addEventListener('hashchange',view);view();
 };
 if(document.querySelector('.vegas-markets'))init();else window.addEventListener('board-ready',init,{once:true});
})();
