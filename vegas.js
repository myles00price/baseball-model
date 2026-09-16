/* Vegas After Dark: presentation only. Original data/renderers remain authoritative. */
(() => {
  'use strict';
  const assetBase = new URL('.', document.currentScript.src);
  const boot = () => {
    const frame = document.querySelector('.frame'), shell = document.querySelector('#shell');
    if (!frame || !shell) return;
    const sport = document.body.dataset.boardSport || 'mlb';
    const make = (tag, cls, text) => {const e=document.createElement(tag);e.className=cls||'';if(text)e.textContent=text;return e;};
    document.body.classList.add('vegas');
    const header=shell.querySelector('.marquee');
    if(header) shell.prepend(header);
    const title=shell.querySelector('h1');
    if(title){title.textContent='THE BOARD';title.append(make('small','','SPORTS ANALYTICS'));}
    const routes = sport==='mlb' ? [['overview','Overview'],['moneyline','Moneyline'],['first5','First 5'],['runline','Run Line'],['props','Player Props'],['record','Record'],['research','Research']]
      : sport==='nfl' ? [['overview','Overview'],['games','Game Lines'],['props','Player Props'],['touchdowns','Touchdowns'],['record','Record'],['research','Research']]
      : sport==='soccer' ? [['overview','Overview'],['games','Match Markets'],['props','Player Props'],['corners','Corners'],['record','Record'],['research','Research']]
      : sport==='cfb' ? [['overview','Overview'],['games','Spreads & Totals'],['record','Record'],['research','Research']]
      : sport==='mma' ? [['overview','Overview'],['games','Fight Card'],['research','Research']] : [];
    if(!routes.length) return;
    const subs=sport==='mlb' ? [['hits','Hits'],['homers','Home Runs'],['strikeouts','Strikeouts']] : sport==='soccer' ? [['goals','Goal Scorers'],['shots','Shots on Target']] : [];
    let current='overview', sub=subs[0]?.[0]||'';
    const nav=make('nav','vegas-markets');nav.setAttribute('aria-label','Market categories');
    const subnav=make('nav','vegas-subtabs');subnav.setAttribute('aria-label','Prop categories');
    const heading=make('div','vegas-pageheading');
    const headingText=make('div');headingText.append(make('p','vegas-eyebrow',sport.toUpperCase()+' / THE BOARD'));
    const h=make('h2','','Today’s board');const desc=make('p','vegas-description','Every matchup. Every price. Your numbers in focus.');headingText.append(h,desc);
    heading.append(headingText,make('span','vegas-disclosure',sport==='mlb'?'LOCKED PICKS · TRACKED RECORD':'PAPER · REFERENCE ONLY'));
    shell.append(nav,subnav,heading);
    const empty=make('div','vegas-empty','No published data is available in this category yet. Check the board’s update time.');empty.hidden=true;
    frame.append(empty);
    const nodes=[];
    const classify = el => {
      const id=el.id,cl=el.classList,heading=(el.querySelector('h2')?.textContent||'').toUpperCase();
      if(['SCRIPT','STYLE','LINK'].includes(el.tagName)||id==='shell'||el===empty) return;
      if(cl.contains('duo')){el.classList.add('vegas-group');Array.from(el.children).forEach(classify);return;}
      let cats=[];
      if(cl.contains('stats')||cl.contains('recbox'))cats=['overview','record'];
      else if(cl.contains('statusline')||cl.contains('paper')||cl.contains('evt')||cl.contains('banner'))cats=['all'];
      else if(id==='hrwatch')cats=['homers'];
      else if(id==='hitwatch')cats=['hits'];
      else if(id==='kwatch')cats=['strikeouts'];
      else if(id==='props'||id==='ledger'||heading.includes('LEDGER'))cats=['record'];
      else if(id==='tdsect')cats=['touchdowns'];
      else if(heading.includes('GOAL WATCH'))cats=['goals'];
      else if(heading.includes('SOT WATCH'))cats=['shots'];
      else if(heading.includes('CORNER WATCH'))cats=['corners'];
      else if(/ENGINE|MODEL UPDATES|PATCHED LEAKS|ARCHIVE|IDEA BOX|STANDINGS|LEADERS|BULLPEN/.test(heading)||id==='news'||cl.contains('foot'))cats=['research'];
      else if(heading.includes('EDGE SCANNER'))cats=['props'];
      else if(sport==='nfl'&&cl.contains('grid'))cats=['overview','games','props'];
      else if(cl.contains('showcase'))cats=['overview',sport==='mlb'?'moneyline':'props'];
      else if(cl.contains('teambar')||id==='gamefocus')cats=['overview','games','props','touchdowns'];
      else cats=['overview',sport==='mlb'?'moneyline':'games'];
      nodes.push({el,cats});
    };
    Array.from(frame.children).forEach(classify);
    if(sport==='mlb'){
      const f5=document.querySelector('#lg-f5-box');
      if(f5){frame.insertBefore(f5,empty);nodes.push({el:f5,cats:['first5','record']});}
    }
    let runline=null,rlSignature='';
    if(sport==='mlb'){runline=make('section','sect vegas-hidden');frame.insertBefore(runline,empty);nodes.push({el:runline,cats:['runline']});}
    function renderRunline(){
      if(!runline||typeof picks==='undefined')return;
      const rows=picks.map(r=>[r.Away,r.Home,r['Game#'],r['DK RL Away'],r['DK RL Home'],r['MGM RL Away'],r['MGM RL Home']]);
      const signature=JSON.stringify(rows);if(signature===rlSignature)return;rlSignature=signature;
      runline.replaceChildren(make('h2','','Run line prices'),make('p','vegas-description','Captured book lines · reference only, not official plays. Each price belongs to the exact team and handicap shown.'));
      const grid=make('div','vegas-runlines');
      rows.forEach(([away,home,game,da,dh,ma,mh])=>{
        const card=make('article','vegas-runline');card.append(make('h3','',away+' at '+home+(Number(game)>1?' · Game '+game:'')));
        [[away,da,ma],[home,dh,mh]].forEach(([team,dk,mgm])=>{
          const groups=new Map();[['DK',dk],['MGM',mgm]].forEach(([book,value])=>{const m=String(value||'').match(/^([+-]?\d+(?:\.\d+)?)@([+-]?\d+(?:\.\d+)?)$/);if(!m)return;const handicap=m[1],odds=Number(m[2]);if(Math.abs(odds)<100)return;if(!groups.has(handicap))groups.set(handicap,[]);groups.get(handicap).push({book,odds});});
          groups.forEach((list,line)=>{card.append(make('p','',team+' '+line),tiles(list));});
          if(!groups.size)card.append(make('p','vegas-description',team+' · No captured line'));
        });grid.append(card);
      });runline.append(grid);
    }
    function select(key,child,write=true){
      current=routes.some(x=>x[0]===key)?key:'overview';
      if(child&&subs.some(x=>x[0]===child))sub=child;
      const chosen=current==='props'&&subs.length?sub:current;
      for(const {el,cats} of nodes)el.classList.toggle('vegas-hidden',!cats.includes('all')&&!cats.includes(chosen));
      nav.querySelectorAll('button').forEach(b=>b.setAttribute('aria-current',b.dataset.route===current?'page':'false'));
      subnav.hidden=current!=='props'||!subs.length;
      subnav.querySelectorAll('button').forEach(b=>b.setAttribute('aria-current',b.dataset.route===sub?'page':'false'));
      const label=(subs.find(x=>x[0]===chosen)||routes.find(x=>x[0]===current))[1];
      h.textContent=current==='overview'?'Today’s board':label;
      desc.textContent=current==='research'?'The models, the evidence, and every published correction.':current==='record'?'Results and provenance, preserved exactly as published.':current==='first5'?'First-five shadow ledger · paper only.':current==='props'?'Player projections and book prices · display only.':'Compare the market. Open a card for the full picture.';
      if(sport==='nfl'&&current==='props')desc.textContent='Player projections and locked shadow picks · paper only.';
      const disclosure=heading.querySelector('.vegas-disclosure');
      disclosure.textContent=sport!=='mlb'?'PAPER · REFERENCE ONLY':['props','first5','runline'].includes(current)?'DISPLAY ONLY · NOT OFFICIAL PLAYS':'LOCKED PICKS · TRACKED RECORD';
      syncProvenance();
      if(write)history.replaceState(null,'','#market='+current+(current==='props'&&sub?'&prop='+sub:''));
      window.dispatchEvent(new Event('resize'));
      updateEmpty();
    }
    function updateEmpty(){
      const chosen=current==='props'&&subs.length?sub:current;
      empty.hidden=nodes.some(({el,cats})=>cats.includes(chosen)&&el.textContent.trim()&&getComputedStyle(el).display!=='none');
      const loading=/LOADING/i.test(document.querySelector('#mq-sub')?.textContent||'');
      const message=loading?'Loading published Board data…':'No published data is available in this category yet. Check the board’s update time.';
      if(empty.textContent!==message)empty.textContent=message;
    }
    function syncProvenance(){Array.from(frame.children).filter(e=>/^RECORD = TEXTED/.test(e.textContent.trim())).forEach(e=>e.classList.toggle('vegas-hidden',!['overview','record'].includes(current)));}
    function tabButton(key,label,target){const b=make('button','',label);b.type='button';b.dataset.route=key;b.onclick=()=>target(key);return b;}
    routes.forEach(([k,l])=>nav.append(tabButton(k,l,k=>select(k))));
    subs.forEach(([k,l])=>subnav.append(tabButton(k,l,k=>select('props',k))));
    function readHash(){const q=new URLSearchParams(location.hash.slice(1));select(q.get('market')||'overview',q.get('prop'),false);}
    window.addEventListener('hashchange',readHash);readHash();
    document.addEventListener('board-reveal',e=>{const match=nodes.find(x=>x.el.contains(e.detail));if(!match)return;const key=match.cats.find(x=>x!=='all');if(subs.some(x=>x[0]===key))select('props',key);else if(key)select(key);});
    // Price comparison is valid only within one side and one market/line.
    function prices(text){const result=[];for(const m of text.matchAll(/\b(DK|MGM|CZR|FD)\s+([+-]\d+(?:\.\d+)?)/g)){const odds=Number(m[2]);if(Math.abs(odds)>=100&&!result.some(x=>x.book===m[1]))result.push({book:m[1],odds});}return result;}
    function tiles(list){const box=make('div','vegas-prices');const payout=o=>o>0?o:10000/-o;const best=Math.max(...list.map(x=>payout(x.odds)));
      list.forEach(x=>{const win=list.length>1&&payout(x.odds)===best;const tile=make('div','vegas-price'+(win?' best':''));tile.append(make('span','',x.book),make('strong','',(x.odds>0?'+':'')+x.odds));if(win)tile.append(make('small','','BEST PRICE'));box.append(tile);});return box;}
    let playerArt = {};
    function portrait(row) {
      const img=row.querySelector(':scope > img:not(.vegas-team-watermark)');
      if(!img)return;
      const id=row.dataset.playerId||img.src.match(/people\/(\d+)\//)?.[1];
      if(!id)return;
      row.dataset.playerId=id;
      const data=row.closest('#hr-body')?(typeof hrData!=='undefined'?hrData:null):row.closest('#k-body')?(typeof kData!=='undefined'?kData:null):(typeof hitData!=='undefined'?hitData:null);
      const player=(row.closest('#hit2-body')?(data?.players2||[]):(data?.players||data?.pitchers||[])).find(p=>String(p.id)===id);
      const source=playerArt[id];
      if(!img.dataset.original)img.dataset.original=img.src;
      if(!img.dataset.fallback)img.dataset.fallback=img.src.replace(/w_\d+,q_\d+/, 'w_426,q_90');
      img.alt='';img.loading='lazy';img.decoding='async';
      const custom=source?.approved===true&&(!player||source.team===player.team)&&typeof source.src==='string'&&source.src.startsWith('assets/player-art/')&&!source.src.includes('..');
      const target=custom?new URL(source.src,assetBase).href:img.dataset.fallback;
      if(img.src!==target){
        const fallbacks=[img.dataset.fallback,img.dataset.original].filter(url=>url!==target);
        img.onerror=()=>{row.classList.remove('vegas-action');const next=fallbacks.shift();if(next)img.src=next;else {img.onerror=null;img.style.visibility='hidden';}};
        img.style.visibility='';row.classList.toggle('vegas-action',custom);img.src=target;
      }
      if(player&&typeof logo==='function'){
        const info=row.querySelector('.vegas-player-info')||Array.from(row.children).find(x=>x.tagName==='DIV');
        if(info&&!info.querySelector('.vegas-team-badge')){
          const badge=make('span','vegas-team-badge');
          const icon=make('img');icon.src=logo(player.team);icon.alt='';icon.onerror=()=>{icon.hidden=true;};
          badge.append(icon,document.createTextNode(typeof AB!=='undefined'?(AB[player.team]||player.team):player.team));
          badge.title=player.team;info.append(badge);
        }
        if(row.classList.contains('vegas-player')&&!row.querySelector('.vegas-team-watermark')){
          const mark=make('img','vegas-team-watermark');mark.src=logo(player.team);mark.alt='';mark.setAttribute('aria-hidden','true');mark.onerror=()=>{mark.hidden=true;};row.prepend(mark);
        }
      }
    }
    fetch(new URL('player-art.json?v=locked-20260915',assetBase)).then(r=>r.ok?r.json():{}).then(data=>{playerArt=data.players||{};renderFeaturedPlays();renderFeaturedPlays();document.querySelectorAll('.vegas-player,#k-body>.ldr').forEach(portrait);}).catch(()=>{});
    const credits=make('a','vegas-photo-credits','Player photo credits');credits.href=new URL('photo-credits.html',assetBase).href;frame.append(credits);
    // A notified key alone is not a bet: the notifier also records skipped games.
    let featuredSignature='';
    function renderFeaturedPlays(){
      if(sport!=='mlb'||typeof picks==='undefined'||typeof locked==='undefined')return;
      const grid=document.getElementById('sc-grid');if(!grid)return;
      const rows=picks.filter(r=>String(r.Flag||'').includes('BET')&&flagged_side_js(r));
      const hitters=typeof hitData!=='undefined'?(hitData?.players||[]):[];
      const signature=JSON.stringify([rows,Array.from(locked),liveMap,playerArt,typeof roster!=='undefined'?roster:null,hitters.map(p=>[p.id,p.team,p.p])]);
      if(signature===featuredSignature&&grid.querySelector('.vegas-lock-card'))return;
      if(!rows.length)return;
      featuredSignature=signature;
      const fragment=document.createDocumentFragment();
      const money=n=>n.toLocaleString('en-US',{style:'currency',currency:'USD'});
      rows.forEach(r=>{
        const side=flagged_side_js(r),label=side==='away'?'Away':'Home',team=r[label];
        const gn=parseInt(r['Game#']||'1')||1,key=r.Away+'@'+r.Home+(gn>1?'#'+gn:'');
        const isLocked=locked.has(key),odds=Number(r['DK '+label+' Odds']);
        const valid=Number.isFinite(odds)&&Math.abs(odds)>=100;
        const lv=r.GamePk?Object.values(liveMap).find(v=>String(v.pk)===String(r.GamePk))||{}:liveMap[key]||{};
        const final=isLocked&&lv.state==='Final'&&lv.as!=null&&lv.hs!=null&&lv.as!==lv.hs;
        const won=final&&(side==='away'?lv.as>lv.hs:lv.hs>lv.as);
        const card=make('article','vegas-lock-card'+(isLocked?' is-locked':' is-lean'));
        const badge=make('div','vegas-lock-status',final?(won?'✓ LOCKED · CASHED':'LOCKED · LOST'):isLocked?'▣ LOCKED · OFFICIAL PLAY':'LEAN · NOT LOCKED');
        card.append(badge);
        const main=make('div','vegas-lock-main'),art=make('div','vegas-lock-art');
        const mark=make('img','vegas-lock-watermark');mark.src=logo(team);mark.alt='';mark.onerror=()=>mark.hidden=true;art.append(mark);
        // Current roster membership prevents old-uniform artwork representing a new team.
        const candidate=Object.entries(playerArt).filter(([id,a])=>a.approved===true&&a.team===team&&a.src?.startsWith('assets/player-art/')&&!a.src.includes('..')&&typeof roster!=='undefined'&&roster?.some(p=>String(p.id)===id&&Number(p.t)===Number(TID[team]))).sort((a,b)=>(a[1].featurePriority||99)-(b[1].featurePriority||99))[0];
        if(candidate){
          const [id,a]=candidate,img=make('img','vegas-lock-player');img.src=new URL(a.src,assetBase).href;img.alt=a.name;img.decoding='async';
          img.onerror=()=>{img.hidden=true;caption.hidden=true;};
          art.append(img);const caption=make('span','vegas-lock-caption','FEATURED · '+a.name);art.append(caption);
        }else if(typeof roster!=='undefined'&&roster){
          const belongs=id=>roster.some(p=>String(p.id)===String(id)&&Number(p.t)===Number(TID[team]));
          const hitter=hitters.filter(p=>p.team===team&&belongs(p.id)).sort((a,b)=>Number(b.p)-Number(a.p))[0];
          const starter=roster.find(p=>r[label+' SP']&&p.n===r[label+' SP']&&Number(p.t)===Number(TID[team]));
          const person=hitter||starter;
          if(person){const img=make('img','vegas-lock-player vegas-lock-headshot');img.src=mug(person.id).replace(/w_\d+,q_\d+/,'w_426,q_90');img.alt=person.name||person.n;img.decoding='async';const caption=make('span','vegas-lock-caption',(hitter?'FEATURED · ':'STARTER · ')+(person.name||person.n));img.onerror=()=>{img.hidden=true;caption.hidden=true;};art.append(img,caption);}
        }
        const info=make('div','vegas-lock-info'),teamBadge=make('img','vegas-lock-team');teamBadge.src=logo(team);teamBadge.alt='';teamBadge.onerror=()=>teamBadge.hidden=true;
        info.append(teamBadge,make('small','vegas-lock-market','MLB · MONEYLINE'),make('h3','',team),make('p','vegas-lock-matchup',r.Away+' @ '+r.Home+(gn>1?' · Game '+gn:'')));
        const price=make('div','vegas-lock-price');price.append(make('strong','',valid?(odds>0?'+':'')+odds:'Unavailable'),make('span','',isLocked?'SAVED DRAFTKINGS PRICE':'DRAFTKINGS SNAPSHOT'));info.append(price);
        const probability=parseFloat(r['Model '+label+'%']);if(Number.isFinite(probability))info.append(make('p','vegas-lock-model','Model probability '+probability.toFixed(1)+'%'));
        main.append(art,info);card.append(main);
        const stats=make('div','vegas-lock-stats');
        const stat=(title,value)=>{const e=make('div');e.append(make('small','',title),make('strong','',value));return e;};
        const win=valid?(odds>0?odds:10000/-odds):null;
        stats.append(stat(isLocked?'MODEL TRACKED STAKE':'ILLUSTRATIVE STAKE','$100.00'),stat(final?'TRACKED RESULT':'POTENTIAL PROFIT',win===null?'Unavailable':final?(won?'+'+money(win):'−$100.00'):'+'+money(win)));card.append(stats);
        const details=make('details','vegas-lock-details');details.append(make('summary','','View play details'));
        details.append(make('p','',whyText(r,team,side)),make('p','',r.Away+' starter: '+(r['Away SP']||'TBD')+' · '+r.Home+' starter: '+(r['Home SP']||'TBD')),make('p','vegas-lock-note','Model tracking uses a flat $100 stake. This is not a wager receipt. '+(isLocked?'The DraftKings price is preserved with the official pick.':'This lean has not been locked as an official play.')));card.append(details);
        fragment.append(card);
      });
      grid.replaceChildren(fragment);
    }

    function enhance(){
      renderFeaturedPlays();
      renderRunline();
      syncProvenance();
      document.querySelectorAll('.sc-bar').forEach(b=>{if(b.textContent==="TONIGHT'S LEAN")b.textContent='LEAN · NOT LOCKED';});
      [['hrwatch','Home run projections ⓘ'],['hitwatch','Hit projections ⓘ'],['kwatch','Strikeout projections ⓘ']].forEach(([id,label])=>{const t=document.querySelector('#'+id+'>h2');if(t&&t.textContent!==label)t.textContent=label;});
      document.querySelectorAll('.sc-why:not([data-vegas])').forEach(el=>{el.dataset.vegas='1';const details=make('details','vegas-why');const summary=make('summary','','Why the model likes it');details.append(summary);while(el.firstChild)details.append(el.firstChild);el.append(details);});
      document.querySelectorAll('#hr-body>.ldr:not([data-vegas]),#hit-body>.ldr:not([data-vegas]),#hit2-body>.ldr:not([data-vegas])').forEach(row=>{
        row.dataset.vegas='1';row.classList.add('vegas-player');
        const info=Array.from(row.children).find(x=>x.tagName==='DIV');if(info)info.classList.add('vegas-player-info');
        const odds=row.querySelector('.hr-odds');const list=prices(odds?.textContent||'');
        if(list.length){row.append(tiles(list));odds.classList.add('vegas-odds-detail');Array.from(odds.childNodes).filter(n=>n.nodeType===3).forEach(n=>{n.textContent=n.textContent.replace(/\b(DK|MGM|CZR|FD)\s+[+-]\d+(?:\.\d+)?/g,'').replace(/(?:\s*·\s*){2,}/g,' · ').replace(/^\s*·\s*$/,' ');});}
        const label=row.closest('#hr-body')?'MODEL HR PROBABILITY':row.closest('#hit2-body')?'MODEL 2+ HITS PROBABILITY':'MODEL 1+ HIT PROBABILITY';
        row.querySelector('.v')?.append(make('small','vegas-prob-label',label));
        const more=make('span','vegas-more','Player analysis ↗');row.append(more);
        portrait(row);
        row.tabIndex=0;row.setAttribute('role','button');row.setAttribute('aria-expanded',row.querySelector('.hd-caret')?.textContent==='▴'?'true':'false');row.setAttribute('aria-label',(info?.firstElementChild?.textContent||'Player')+' — view analysis');row.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();row.click();}});
      });
      document.querySelectorAll('#k-body>.ldr:not([data-portrait])').forEach(row=>{row.dataset.portrait='1';portrait(row);});
      document.querySelectorAll('.sc-line:not([data-vegas])').forEach(el=>{
        el.dataset.vegas='1';const list=prices(el.textContent);if(!list.length)return;
        const text=el.textContent;el.textContent=text.split(/\s*·\s*DK\s/)[0];el.after(tiles(list));
      });
      updateEmpty();
    }
    enhance();
    let scheduled=false;
    new MutationObserver(()=>{if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;enhance();});}).observe(frame,{subtree:true,childList:true});
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
