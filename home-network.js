/* Read-only public news. No model jobs, paid feeds or writes. */
const sports=[['NFL','football/nfl'],['MLB','baseball/mlb'],['SOCCER','soccer/eng.1']];
async function news(){const results=await Promise.allSettled(sports.map(async([sport,path])=>{
 const r=await fetch('https://site.api.espn.com/apis/site/v2/sports/'+path+'/news?limit=1');if(!r.ok)throw Error('News unavailable');const j=await r.json();return {sport,a:j.articles?.[0]};}));
 const box=document.querySelector('#news');box.replaceChildren();let count=0;
 for(const r of results){if(r.status!=='fulfilled'||!r.value.a)continue;const {sport,a}=r.value;const href=a.links?.web?.href;if(!href||!href.startsWith('https://'))continue;
 const card=document.createElement('a');card.href=href;card.target='_blank';card.rel='noopener';const src=a.images?.[0]?.url;if(src?.startsWith('https://')){const img=document.createElement('img');img.src=src;img.alt='';img.loading='lazy';card.append(img)}const tag=document.createElement('small');tag.textContent=sport+' · ESPN';const h=document.createElement('h3');h.textContent=a.headline;card.append(tag,h);box.append(card);count++}
 if(!count){const p=document.createElement('p');p.className='empty';p.textContent='News is temporarily unavailable. Open a sport board to continue.';box.append(p)}document.querySelector('#news-time').textContent='Publisher feed fetched '+new Date().toLocaleString()+'. Story images come from the same article, not stock substitutions.';
}news().catch(()=>{document.querySelector('#news').textContent='News temporarily unavailable.'});
fetch('https://myles00price.github.io/baseball-model/board_stats.json', {cache:'no-store'}).then(r=>r.json()).then(s=>{document.querySelector('#record').textContent=s.record||'—';document.querySelector('#record-detail').textContent='Published MLB record · '+s.win_pct+'% wins · source updated '+s.updated+'.';}).catch(()=>{document.querySelector('#record-detail').textContent='Record unavailable; visit the full ledger.'});

