/* Shared presentation only. Data, routes and settlement controls stay authoritative. */
(()=>{
 const base=new URL('.',document.currentScript.src);
 const sports={
  mlb:['MLB','EVERY PITCH.','THE FULL PICTURE.','Matchups · pitchers · player props'],
  nfl:['NFL','EVERY DOWN.','THE FULL PICTURE.','Game lines · player props · touchdowns'],
  cfb:['COLLEGE FOOTBALL','SATURDAY','STARTS HERE.','Game lines · totals · model comparison'],
  nhl:['NHL','ON THE ICE.','ON THE BOARD.','Game lines · player props · research'],
  soccer:['SOCCER','EVERY MATCH.','EVERY ANGLE.','Match results · goals · player props'],
  mma:['MMA','INSIDE','THE OCTAGON.','Fight card · projections · research'],
  ncaam:['COLLEGE BASKETBALL','EVERY POSSESSION','COUNTS.','Game lines · totals · the record']
 };
 function boot(){
  const key=window.SHELL?.sport,config=sports[key],shell=document.getElementById('shell');
  if(!config||!shell||document.getElementById('premium-hero'))return;
  document.body.classList.add('board-premium');
  const hero=document.createElement('section');hero.id='premium-hero';hero.className='premium-hero';
  hero.setAttribute('aria-label',config[0]+' board');
  const img=document.createElement('img');img.className='premium-hero-art';img.alt='';img.setAttribute('aria-hidden','true');img.src=new URL('assets/sport-heroes/'+key+'.png',base).href;img.decoding='async';img.onerror=()=>{img.hidden=true;};
  const copy=document.createElement('div');copy.className='premium-hero-copy';
  const label=document.createElement('p');label.className='premium-sport';label.textContent=config[0]+' / THE BOARD';
  const title=document.createElement('h2');title.append(document.createTextNode(config[1]),document.createElement('br'),document.createTextNode(config[2]));
  const sub=document.createElement('p');sub.className='premium-hero-sub';sub.textContent=config[3];
  const credit=document.createElement('small');credit.className='premium-art-credit';credit.textContent='AI-generated sports illustration';
  copy.append(label,title,sub);hero.append(img,copy,credit);
  const anchor=shell.querySelector('.vegas-pageheading,.vegas-markets');
  if(anchor)anchor.before(hero);else shell.append(hero);
  if(key==='cfb'){
   const head=document.querySelector('.cfb-head'),tabs=document.querySelector('.cfb-tabs');
   if(head&&tabs)head.after(tabs);
  }
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
 window.addEventListener('board-ready',boot,{once:true});
})();
