/* Site shell: renders the SAME top on every page -- sport nav + the MLB board's
   marquee (title / search / sub line / light-dark toggle), pixel-identical.
   Only the content under the shell differs per sport.

   Usage (before including this file):
     <div id="shell"></div>
     <script>window.SHELL={sport:'nfl',accent:'NFL',sub:'WEEK 1 · 2026',ownUI:true}</script>
     <script src="shell.js"></script>

   ownUI:false  -> page's own JS drives search/sub/modebtn (the MLB board).
   ownUI:true   -> shell binds them: theme toggle persisted in the same
                   localStorage key the MLB board uses ("boardMode"), and search
                   over any elements with a data-player attribute on the page.
   Theme therefore carries across pages, and cross-document view transitions
   (where the browser supports them) fade page swaps under a stable header. */
(function () {
  var cfg = window.SHELL || {};
  var sport = cfg.sport || "";
  document.body.dataset.boardSport = sport; document.body.classList.add("vegas");
  var shared = document.createElement("link");
  shared.rel = "stylesheet";
  shared.href = new URL("board-common.css", document.currentScript.src).href;
  if(!document.querySelector('link[href*="board-common.css"]'))document.head.appendChild(shared);
  var vegasStyle = document.createElement("link");
  vegasStyle.rel = "stylesheet";
  vegasStyle.href = new URL("vegas.css?v=unified-20260924b", document.currentScript.src).href;
  if(!document.querySelector('link[href*="vegas.css"]'))document.head.appendChild(vegasStyle);
  if(!document.querySelector('link[href*="site-unified.css"]')){var unified=document.createElement("link");unified.rel="stylesheet";unified.href=new URL("site-unified.css?v=unified-20260924b",document.currentScript.src);document.head.appendChild(unified);}
  var vegasScript = document.createElement("script");
  vegasScript.src = new URL("vegas.js?v=unified-20260924b", document.currentScript.src).href;
  document.head.appendChild(vegasScript);

  // Shared premium presentation persists across generated sport pages.
  if (["mlb","nfl","cfb","nhl","soccer","mma","ncaam"].includes(sport)) {
    document.body.classList.add("board-premium");
    var premiumStyle=document.createElement("link");premiumStyle.rel="stylesheet";
    premiumStyle.href=new URL("board-premium.css?v=20261002",document.currentScript.src).href;document.head.appendChild(premiumStyle);
    var premiumScript=document.createElement("script");premiumScript.src=new URL("board-premium.js?v=20261002",document.currentScript.src).href;document.head.appendChild(premiumScript);
  }

  var SPORTS = [
    { id: "agent-book", label: "AGENT BOOK", href: "agent-book.html", status: "paper" },
    { id: "agent-market", label: "AGENT MARKET", href: "agent-market.html", status: "paper" },
    { id: "hub",   label: "HOME",   href: "index.html", status: "live"  },
    { id: "mlb",   label: "MLB",    href: "board.html", status: "live"  },
    { id: "nfl",   label: "NFL",    href: "nfl.html",   status: "paper" },
    { id: "cfb",   label: "CFB",    href: "cfb.html",   status: "paper" },
    { id: "mma",   label: "MMA",    href: "mma.html",   status: "paper" },
    { id: "soccer",label: "SOCCER", href: "soccer.html",status: "paper" },
    { id: "nba",   label: "NBA",    href: "nba.html",   status: "paper" },
    { id: "ncaam", label: "NCAAM",  href: "ncaam.html", status: "paper" },
    { id: "nhl",   label: "NHL",    href: "nhl.html",   status: "paper" }
  ];

  /* ---- CSS: nav + the exact marquee rules from board.html (duplicating them
     on the MLB page is harmless -- identical values). ---- */
  var css = "" +
    "@view-transition{navigation:auto}" +
    "#shell .marquee{view-transition-name:board-marquee}" +
    "#sportnav{display:flex;gap:6px;flex-wrap:wrap;align-items:center;background:#050505;" +
      "border:1px solid #1c1c1c;padding:6px 10px;margin-bottom:10px;view-transition-name:board-nav}" +
    "#sportnav a,#sportnav span.soon{font-family:'VT323',monospace;font-size:17px;" +
      "letter-spacing:.08em;padding:3px 12px;text-decoration:none;border:1px solid transparent}" +
    "#sportnav a{color:#8a8a8a}#sportnav a:hover{color:#2bff64;border-color:#1f7a3d}" +
    "#sportnav a.active{color:#2bff64;border-color:#2bff64;text-shadow:0 0 8px rgba(43,255,100,.5)}" +
    "#sportnav .tag{font-size:11px;margin-left:5px;color:#ffb000}" +
    "#sportnav span.soon{color:#2e2e2e;cursor:default}#sportnav span.soon .tag{color:#2e2e2e}" +
    "body.light #sportnav{background:#f7f4ec;border-color:#d8d2c2}" +
    "body.light #sportnav a{color:#6b6355}" +
    "body.light #sportnav a:hover{color:#0d7a2e;border-color:#0d7a2e}" +
    "body.light #sportnav a.active{color:#0d7a2e;border-color:#0d7a2e;text-shadow:none}" +
    "body.light #sportnav span.soon,body.light #sportnav span.soon .tag{color:#c9c2b2}" +
    ".marquee{display:flex;justify-content:space-between;align-items:center;gap:14px;" +
      "background:#0a0a0a;border:1px solid var(--line);padding:8px 18px;margin-bottom:10px;flex-wrap:wrap}" +
    ".marquee h1{font-family:'Bebas Neue',sans-serif;font-size:32px;letter-spacing:.38em;font-weight:400}" +
    ".marquee h1 .accent{color:var(--amber)}" +
    ".marquee .sub{font-family:'VT323',monospace;font-size:18px;color:var(--phos);" +
      "text-shadow:0 0 8px rgba(43,255,100,.5)}" +
    ".searchbox{position:relative;flex:1;max-width:330px;min-width:220px}" +
    ".searchbox input{width:100%;background:#050505;border:1px solid #222;color:var(--phos);" +
      "font-family:'VT323',monospace;font-size:17px;padding:6px 12px;outline:none;letter-spacing:.05em}" +
    ".searchbox input::placeholder{color:#333}" +
    ".sr{position:absolute;top:100%;left:0;right:0;background:#0a0a0a;border:1px solid #222;" +
      "z-index:60;max-height:300px;overflow-y:auto}" +
    ".sr div{padding:6px 12px;font-size:13px;cursor:pointer;display:flex;" +
      "justify-content:space-between;border-bottom:1px solid #141414}" +
    ".sr div:hover{background:#141414}.sr .pos{color:var(--mut);font-family:'VT323',monospace}" +
    ".modebtn{font-family:'VT323',monospace;font-size:22px;color:var(--mut);cursor:pointer;" +
      "border:1px solid var(--line);padding:1px 10px;user-select:none}" +
    ".modebtn:hover{color:var(--amber)}" +
    "body.light .marquee{background:#f7f4ec;border-color:var(--line)}" +
    "body.light .marquee h1{color:#14171c}" +
    "body.light .searchbox input{background:#fdfcf8;border-color:var(--line);color:#0a6e30}" +
    "body.light .searchbox input::placeholder{color:#b5b0a2}" +
    "body.light .sr{background:#fdfcf8;border-color:var(--line)}" +
    "body.light .sr div{border-color:#eee9dd}body.light .sr div:hover{background:#efece0}" +
    ".shell-flash{animation:shellflash 1.6s}" +
    "@keyframes shellflash{0%,60%{background:#1a2a12}100%{background:transparent}}";
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  /* ---- markup: nav + marquee, same element ids the MLB board's JS expects ---- */
  var mount = document.getElementById("shell");
  if (!mount) return;
  var path = (location.pathname.split("/").pop() || "index.html").toLowerCase();
  SPORTS.push({ id: "weekly-review", label: "WEEKLY RESULTS", href: "weekly-review.html", status: "" });
  var nav = SPORTS.map(function (s) {
    var tag = s.status === "paper" ? "<span class='tag'>PAPER</span>"
            : s.status === "soon" ? "<span class='tag'>SOON</span>" : "";
    if (!s.href) return "<span class='soon'>" + s.label + tag + "</span>";
    var active = path === s.href.toLowerCase() ? " class='active' aria-current='page'" : "";
    return "<a href='" + s.href + "'" + active + ">" + s.label + tag + "</a>";
  }).join("");
  var accent = cfg.accent ? " <span class='accent'>" + cfg.accent + "</span>" : "";
  mount.innerHTML =
    "<div id='sportnav' role='navigation' aria-label='Sports'>" + nav + "</div>" +
    "<div class='marquee'>" +
      "<h1>THE BOARD" + accent + "</h1>" +
      "<div class='searchbox'><input id='psearch' placeholder='► SEARCH PLAYERS…' " +
        "autocomplete='off' aria-label='Search players'><div class='sr' id='sr' style='display:none'></div></div>" +
      "<span class='sub' id='mq-sub'>" + (cfg.sub || "") + "</span>" +
      "<button type='button' class='modebtn' id='modebtn' aria-label='Toggle light and dark theme' title='light/dark'>☀</button>" +
    "</div>";

  function fitTables() {
    document.querySelectorAll(".frame table").forEach(function (table) {
      if (table.closest(".board-table-scroll,.tw")) return;
      var wrap = document.createElement("div");
      wrap.className = "board-table-scroll";
      wrap.tabIndex = 0;
      wrap.setAttribute("role", "region");
      wrap.setAttribute("aria-label", "Data table, scroll horizontally for more columns");
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
    });
  }
  document.addEventListener("DOMContentLoaded", function () {
    fitTables();
    var frame=document.querySelector(".frame");if(frame)new MutationObserver(fitTables).observe(frame, {childList:true,subtree:true});
  });
  if (!cfg.ownUI) return;   /* the MLB board's own JS takes over from here */

  /* ---- theme: same localStorage key as the MLB board, so it follows you ---- */
  var btn = document.getElementById("modebtn");
  function applyTheme() {
    var light = document.body.classList.contains("light");
    try { light = localStorage.getItem("boardMode") === "light"; } catch (e) {}
    document.body.classList.toggle("light", light);
    btn.textContent = light ? "☾" : "☀";
  }
  applyTheme();
  btn.addEventListener("click", function () {
    var light = !document.body.classList.contains("light");
    document.body.classList.toggle("light", light);
    try { localStorage.setItem("boardMode", light ? "light" : "dark"); } catch (e) {}
    applyTheme();
  });

  /* ---- search over [data-player] elements on this page ----
     Shell runs at the top of the page, before the content below exists, so the
     row scan must wait for DOMContentLoaded. */
  var input = document.getElementById("psearch");
  var srBox = document.getElementById("sr");
  var rows = [];
  document.addEventListener("DOMContentLoaded", function () {
    rows = Array.prototype.slice.call(document.querySelectorAll("[data-player]"));
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") srBox.style.display = "none";
    if (e.key === "ArrowDown") {
      var first = srBox.querySelector("button");
      if (first) { e.preventDefault(); first.focus(); }
    }
  });
  input.addEventListener("input", function () {
    var q = input.value.trim().toLowerCase();
    if (q.length < 2) { srBox.style.display = "none"; return; }
    rows = Array.prototype.slice.call(document.querySelectorAll("[data-player]"));
    var hits = rows.filter(function (r) {
      return r.getAttribute("data-player").toLowerCase().indexOf(q) !== -1;
    }).slice(0, 12);
    srBox.innerHTML = hits.length
      ? hits.map(function (r, i) {
          var label = document.createElement("span");
          label.textContent = r.getAttribute("data-player");
          return "<button type='button' data-hit='" + i + "'>" + label.innerHTML + "</button>";
        }).join("")
      : "<div><span class='pos'>NO MATCHING PLAYERS</span></div>";
    srBox.style.display = "block";
    Array.prototype.forEach.call(srBox.querySelectorAll("[data-hit]"), function (el) {
      el.addEventListener("click", function () {
        var row = hits[+el.getAttribute("data-hit")];
        srBox.style.display = "none"; input.value = "";
        document.dispatchEvent(new CustomEvent("board-reveal", {detail:row}));
        row.scrollIntoView({ behavior: "smooth", block: "center" });
        row.classList.remove("shell-flash"); void row.offsetWidth;
        row.classList.add("shell-flash");
      });
    });
  });
  document.addEventListener("click", function (e) {
    if (!srBox.contains(e.target) && e.target !== input) srBox.style.display = "none";
  });
})();

/* NFL presentation assets persist across regenerated pages; other sports are untouched. */
(function(){if(!window.SHELL||window.SHELL.sport!=='nfl')return;var base=new URL('.',document.currentScript.src);var c=document.createElement('link');c.rel='stylesheet';c.href=new URL('nfl-facelift.css?v=unified-20260924b',base);if(!document.querySelector('link[href*="nfl-facelift.css"]'))document.head.appendChild(c);var s=document.createElement('script');s.src=new URL('nfl-facelift.js?v=unified-20260924b',base);document.head.appendChild(s);})();

/* BOARD_SPORTSBOOK_PICKS_START */
/* Two prospective paper competitions, fed by immutable locked tickets. */
(()=>{'use strict';if(window.BoardSportsbookUI)return;window.BoardSportsbookUI=true;
const E=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(Number(n||0)),pct=n=>Number.isFinite(n)?(n>0?'+':'')+n.toFixed(1)+'%':'—',odds=n=>(n>0?'+':'')+n,when=v=>v?new Date(v).toLocaleString():'';
const base='https://raw.githubusercontent.com/myles00price/baseball-model/agent-market-feed/';
let data=null,owner=null,ownerHistory=null,regime='owner_line',sport='',status='open',market='',selected=null,dialogRegime='sportsbook',page=0;
let host,dialog,bookGame='';const isMarket=()=>window.SHELL?.sport==='agent-market';
const pick=t=>t.bet_type==='player_prop'?String(t.player_name||t.player_id)+' '+String(t.side).toUpperCase()+' '+t.line+' '+String(t.stat_short||t.stat||'').toUpperCase():(t.market==='total'?t.side.toUpperCase():t.side==='draw'?'DRAW':t.side==='home'?t.home:t.away)+(t.market==='moneyline'?' ML':' '+(t.line>0?'+':'')+t.line);
function metrics(ts){const done=ts.filter(t=>['win','loss','push'].includes(t.result)),stakes=done.reduce((n,t)=>n+t.stake,0),profit=done.reduce((n,t)=>n+(t.payout-t.stake),0);return {wins:done.filter(t=>t.result==='win').length,losses:done.filter(t=>t.result==='loss').length,pushes:done.filter(t=>t.result==='push').length,profit,roi_percent:stakes?profit/stakes*100:null,games:new Set(done.map(t=>t.game_key)).size}}
function heat(id){if(Date.now()-Date.parse(data.as_of_utc)>600000)return '';const ts=data.tickets.filter(t=>t.agent_id===id&&t.result).sort((a,b)=>String(b.settled_utc).localeCompare(String(a.settled_utc))),games=new Map();for(const t of ts){if(!games.has(t.game_key)&&games.size>=10)continue;games.set(t.game_key,(games.get(t.game_key)||0)+t.profit)}const vals=[...games.values()],m=metrics(ts),profit=vals.reduce((a,b)=>a+b,0),rate=vals.filter(n=>n>0).length/vals.length;return vals.length>=5&&profit>0?(rate>=.7&&m.games>=10&&m.profit>0?'sb-red':rate>=.6?'sb-orange':''):''}
const title=a=>`${a.wins||0}–${a.losses||0}–${a.pushes||0} · ROI ${pct(a.roi_percent)} · ${money(a.profit)} paper profit · ${a.games||0} settled games`;
function button(a){return '<button class="sb-name '+heat(a.agent_id)+'" data-sb-agent="'+E(a.agent_id)+'" title="'+E(title(a))+'">'+E(a.name||a.agent_id)+' · '+E(a.agent_id)+'</button>'}
function bookHTML(){let qs=(data.book_lines||[]).filter(q=>(!sport||q.sport===sport)&&(!market||q.market===market)&&Date.parse(q.tip_utc)>Date.now()&&Date.now()-Date.parse(q.quote_utc)<=5400000&&Date.now()-Date.parse(q.observed_utc)<=5400000);const key=q=>q.sport+'|'+q.event_id+'|'+q.tip_utc;const games=[...new Map(qs.map(q=>[key(q),q])).entries()];if(bookGame&&!games.some(([k])=>k===bookGame))bookGame='';if(bookGame)qs=qs.filter(q=>key(q)===bookGame);const coverage=sport&&data.eligibility?.[sport]?'<p>'+E(data.eligibility[sport].reason)+' '+data.eligibility[sport].matched_games+' matched games / '+data.eligibility[sport].quoted_events+' quoted events.</p>':'';return coverage+'<details open><summary>Fresh sportsbook lines · '+qs.length+' quotes</summary><label>Book game <select id="sb-book-game"><option value="">All quoted games</option>'+games.map(([k,q])=>'<option value="'+E(k)+'"'+(bookGame===k?' selected':'')+'>'+E(q.away)+' @ '+E(q.home)+' · '+E(when(q.tip_utc))+'</option>').join('')+'</select></label><p>Current saved provider quotes. Agents evaluate these when a matching supported model forecast is available; they may pass or reach paper exposure limits.</p><div class="sb-scroll"><table><thead><tr><th>Game</th><th>Book</th><th>Market / selection</th><th>Line / odds</th><th>Book updated / captured</th></tr></thead><tbody>'+qs.slice(0,150).map(q=>'<tr><td>'+E(q.sport.toUpperCase())+' · '+E(q.away)+' @ '+E(q.home)+'<br>'+E(when(q.tip_utc))+'</td><td>'+E(q.book)+'</td><td>'+E(q.market)+' · '+E(q.side==='draw'?'DRAW':q.side==='home'?q.home:q.side==='away'?q.away:q.side.toUpperCase())+'</td><td>'+E(q.line==null?'ML':q.line)+' / '+E(odds(q.price))+'</td><td>'+E(when(q.quote_utc))+'<br>'+E(when(q.observed_utc))+'</td></tr>').join('')+'</tbody></table></div>'+(qs.length>150?'<p>Showing first 150. Select a game to see its book lines.</p>':'')+(qs.length?'':'<p>No fresh posted quotes for this filter. No stale prices are presented as current.</p>')+'</details>'}
function ticketTable(ts){return '<div class="sb-scroll sb-ticket-scroll"><table><thead><tr><th>Bettor / matchup</th><th>Locked pick</th><th>Book / odds</th><th>Paper stake</th><th>Result / profit</th><th>Time / evidence</th></tr></thead><tbody>'+ts.map(t=>{const a=data.agents.find(a=>a.agent_id===t.agent_id)||{agent_id:t.agent_id};return '<tr><td>'+button(a)+'<br>'+E(t.sport?.toUpperCase())+' · '+E(t.away)+' @ '+E(t.home)+'</td><td>'+E(pick(t))+'</td><td>'+E(t.book||'Model Lines')+'<br>'+E(odds(t.price))+'</td><td>'+E(money(t.stake))+'</td><td>'+E(t.result?.toUpperCase()||'OPEN')+'<br>'+E(t.result?money(t.payout-t.stake):'—')+'</td><td>Placed '+E(when(t.accepted_utc))+'<br>Starts '+E(when(t.tip_utc))+(t.quote_utc?'<br>Book updated '+E(when(t.quote_utc)):'')+'<details><summary>Why / source</summary><p>'+E(t.reason||'Recorded owner-market ticket.')+'</p>'+(t.bet_type==='player_prop'?'<p>Player prop: '+E(t.player_name)+' ('+E(t.player_team||'')+', id '+E(t.player_id)+') · '+E(t.stat_label||t.stat)+' · projected mean '+E(t.projected_mean)+' · '+E(t.model_version||'')+' snapshot '+E(when(t.projection_as_of_utc))+'</p>'+(t.settlement?'<p>Settled from '+E(t.settlement.source)+': '+E(t.settlement.actual??'did not play')+' in '+E(t.settlement.minutes)+' min · '+E(t.settlement.reason)+'</p>':'<p>Settles only from the official box score; no minutes = void (refund).</p>'):'')+(t.probability_gap!=null?'<p>Estimated probability gap '+E(pct(t.probability_gap*100))+'. Uncalibrated.</p>':'')+(t.latest_pregame_reference?'<p>Latest observed pregame: '+E(t.latest_pregame_reference.book)+' '+E(t.latest_pregame_reference.line??'ML')+' @ '+E(odds(t.latest_pregame_reference.price))+' · '+E(when(t.latest_pregame_reference.quote_utc))+'. Not a verified closing line.</p>':'')+'<small>Model '+E(t.model_sha256||'Saved owner offer')+'<br>Quote '+E(t.source_sha256||'Owner-line terms')+'</small></details></td></tr>'}).join('')+'</tbody></table></div>'}
function render(){if(!data||!host)return;const stale=Date.now()-Date.parse(data.as_of_utc)>600000;
 const allSports=[...new Set([...(owner?.sports||[]),...data.tickets.map(t=>t.sport)])].sort();
 const rows=data.tickets.filter(t=>(!sport||t.sport===sport)&&(!market||(market==='player_props'?t.bet_type==='player_prop':t.market===market))&&(status==='all'||(status==='open'?!t.result:!!t.result)));
 const owners=owner?.supervisor?.bettors||{};
 const leaders=(regime==='sportsbook'?data.agents:data.agents.map(a=>({...a,...owners[a.agent_id]?.lifetime}))).slice().sort((a,b)=>(b.profit||0)-(a.profit||0));
 const table=leaders.map(a=>'<tr><td>'+(regime==='sportsbook'?button(a):'<a href="agent-market.html" data-owner-agent="'+E(a.agent_id)+'">'+E(a.name)+' · '+E(a.agent_id)+'</a>')+'</td><td>'+(a.wins||0)+'–'+(a.losses||0)+'–'+(a.pushes||0)+'</td><td>'+E(pct(a.roi_percent))+'</td><td>'+E(money(a.profit))+'</td></tr>').join('');
 host.innerHTML='<h2>'+(isMarket()?'Two competitions':'Agent Picks · Sportsbook Lines')+'</h2><p class="sb-muted">'+(stale?'WORKER STALE / PC OFFLINE':'PAPER WORKER ACTIVE')+' · Updated '+E(when(data.as_of_utc))+' · '+data.agents.length+' rule-based fictional bettors</p>'+(isMarket()?'<div class="sb-tabs"><button data-sb-regime="owner_line" aria-pressed="'+(regime==='owner_line')+'">Model Lines</button><button data-sb-regime="sportsbook" aria-pressed="'+(regime==='sportsbook')+'">Sportsbook Lines</button></div>':'')+'<p>Separate paper bankrolls and records. Sportsbook tickets lock a real saved book quote. Model Lines tickets use the separate moving owner market. Agent picks do not change model projections.</p>'+(isMarket()?'<details '+(regime==='sportsbook'?'open':'')+'><summary>'+E(regime==='sportsbook'?'Sportsbook':'Model Lines')+' leaderboard · settled profit</summary><div class="sb-scroll"><table><thead><tr><th>Bettor</th><th>W–L–P</th><th>ROI</th><th>Profit</th></tr></thead><tbody>'+table+'</tbody></table></div></details>':'')+'<div class="sb-book-content" '+(isMarket()&&regime!=='sportsbook'?'hidden':'')+'><div class="sb-filters"><label>Sport <select id="sb-sport"><option value="">All sports</option>'+allSports.map(s=>'<option '+(s===sport?'selected ':'')+'value="'+E(s)+'">'+E(s.toUpperCase())+'</option>').join('')+'</select></label><label>Market <select id="sb-market"><option value="">All markets</option>'+['moneyline','spread','total'].map(m=>'<option '+(market===m?'selected ':'')+'value="'+m+'">'+m+'</option>').join('')+[['player_props','player props (all)'],['player_points','prop: points'],['player_rebounds','prop: rebounds'],['player_assists','prop: assists'],['player_points_rebounds_assists','prop: pts+reb+ast']].map(([m,l])=>'<option '+(market===m?'selected ':'')+'value="'+m+'">'+l+'</option>').join('')+'</select></label><label>Tickets <select id="sb-status">'+['open','settled','all'].map(s=>'<option '+(status===s?'selected ':'')+'value="'+s+'">'+s+'</option>').join('')+'</select></label></div>'+bookHTML()+'<p>'+rows.length+' matching sportsbook tickets · one accepted pick per bettor/game/market. Hover names for sportsbook records; click for full history.</p>'+(rows.length?ticketTable(rows.slice(0,100)):'<p>No matching sportsbook picks yet. Agents pass when the price offers insufficient value; stale quotes and unsupported contracts stay on hold.</p>')+(rows.length>100?'<p>Showing latest 100. Click a bettor for their complete history.</p>':'')+'</div>'+(isMarket()?syndicateHTML():'')+'<details><summary>How sportsbook betting works</summary><p>'+E(data.policy)+'</p><p>Orange names: positive recent profit and at least 60% profitable games over the last 10 settled games (minimum five). Red: at least 70%, 10 lifetime games and positive lifetime profit. Records are separate from owner-market heat. No missing prices or past selections are invented.</p></details>';
 if(isMarket()){document.body.classList.toggle('sb-mode',regime==='sportsbook');document.querySelectorAll('#sports,#inactive,#market').forEach(el=>{el.style.display=regime==='sportsbook'?'none':''})}
}
function syndicateHTML(){const s=data.syndicates;if(!s)return '';return '<details open><summary>Syndicates & new agents · '+s.descendants.length+' descendants</summary><p>'+E(s.policy)+'</p>'+s.cohorts.map(g=>'<p><b>'+E(g.syndicate_id)+'</b> · '+E(g.regime==='sportsbook'?'Sportsbook Lines':'Model Lines')+'<br>'+g.founders.map(f=>E(f.agent_id)+' · '+E(money(f.profit))+' · '+E(pct(f.roi_percent))+' ROI / '+f.games+' games').join('<br>')+'</p>').join('')+'<div class="sb-lineage">'+s.descendants.map(a=>'<p>'+E(a.name)+' <button data-sb-agent="'+E(a.agent_id)+'">'+E(a.agent_id)+'</button><br>Parent '+E(a.parent_agent_id)+' · '+E(a.selection_regime)+' · born '+E(when(a.birth_utc))+' · new record</p>').join('')+'</div></details>'}
async function openAgent(id){selected=id;page=0;if(!dialog){dialog=document.createElement('dialog');dialog.className='sb-dialog';document.body.appendChild(dialog)}renderDialog();dialog.showModal();if(!ownerHistory){try{ownerHistory=await fetchJSON('agent-market-history.json');if(selected===id)renderDialog()}catch{}}}
function renderDialog(){if(!dialog||!selected)return;const a=data.agents.find(a=>a.agent_id===selected)||{agent_id:selected};let ts=dialogRegime==='sportsbook'?data.tickets.filter(t=>t.agent_id===selected):(ownerHistory?.agents?.[selected]?.tickets||[]);ts=ts.map(t=>({...t,agent_id:selected}));const m=metrics(ts),pages=Math.max(1,Math.ceil(ts.length/50));page=Math.min(page,pages-1);dialog.innerHTML='<button data-sb-close style="float:right">Close</button><h2>'+E(a.name||selected)+' · '+E(selected)+'</h2><div class="sb-tabs"><button data-sb-dialog="owner_line" aria-pressed="'+(dialogRegime==='owner_line')+'">Model Lines</button><button data-sb-dialog="sportsbook" aria-pressed="'+(dialogRegime==='sportsbook')+'">Sportsbook Lines</button></div><p><b>'+E(title(m))+'</b> · '+ts.filter(t=>!t.result).length+' open tickets</p>'+(!ownerHistory&&dialogRegime==='owner_line'?'<p>Owner history loading or unavailable. Close and retry if needed.</p>':ticketTable(ts.slice(page*50,(page+1)*50)))+'<p><button data-sb-prev '+(page===0?'disabled':'')+'>Previous</button> Page '+(page+1)+' / '+pages+' <button data-sb-next '+(page>=pages-1?'disabled':'')+'>Next</button></p><p>Each competition starts at $10,000 per bettor. Open stakes excluded from ROI. Simulated wagers.</p>';appendComparisons()}
function appendComparisons(){const ts=(data.retrospective_comparisons||[]).filter(t=>t.agent_id===selected);if(!ts.length)return;const m=metrics(ts);dialog.insertAdjacentHTML('beforeend','<details><summary>Retrospective sportsbook comparisons · '+ts.length+'</summary><p>Same owner-market selections and stakes at matching sportsbook quotes saved before the original bet. These were not selected as sportsbook picks and do not enter either competition. '+E(title(m))+'</p>'+ticketTable(ts.slice(0,100))+'</details>')}
async function fetchJSON(file){const r=await fetch(base+file+'?v='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error('Feed unavailable');return r.json()}
async function refresh(){try{const [s,o]=await Promise.all([fetchJSON('agent-market-sportsbook.json'),fetchJSON('agent-market-feed.json')]);if(s.schema!==1||s.regime!=='sportsbook'||s.simulated!==true)throw Error('Wrong feed');data=s;owner=o;render()}catch{if(host&&!data)host.innerHTML='<h2>Agent Picks · Sportsbook Lines</h2><p>Sportsbook feed unavailable. No picks are inferred.</p>'}}
function start(){const s=window.SHELL?.sport;if(!['agent-market','nba','nfl','cfb','nhl','mlb','soccer','mma','ncaam','wnba'].includes(s))return;sport=isMarket()?'':s;regime=isMarket()?'owner_line':'sportsbook';
 const style=document.createElement('style');style.textContent='#sb-panel,.sb-dialog{color:var(--text,#e7edf4);background:var(--panel,#111923);border:1px solid var(--line,#34404d);border-radius:12px;padding:20px;margin:20px auto;max-width:1400px;font:14px/1.5 system-ui}#sb-panel button,.sb-dialog button{cursor:pointer;background:transparent;color:inherit;border:1px solid #55616d;border-radius:6px;padding:7px 10px}#sb-panel button[aria-pressed=true],.sb-dialog button[aria-pressed=true]{background:#244e42}#sb-panel select{background:#182330;color:#fff;padding:6px}.sb-tabs,.sb-filters{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}.sb-scroll{overflow:auto;max-height:560px}.sb-scroll table{border-collapse:collapse;width:100%;min-width:650px}.sb-scroll td,.sb-scroll th{padding:10px;text-align:left;border-bottom:1px solid #34404d;vertical-align:top}.sb-muted{opacity:.7}.sb-dialog{width:min(1200px,92vw);max-height:90vh;overflow:auto}.sb-dialog::backdrop{background:#000a}.sb-red{color:#ff625c!important}.sb-orange{color:#ffb14f!important}.sb-lineage{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}#sb-panel details{margin:16px 0}#sb-panel summary{cursor:pointer;font-weight:700}';document.head.appendChild(style);
 host=document.createElement('section');host.id='sb-panel';host.setAttribute('aria-label','Agent sportsbook competition');if(isMarket()){const main=document.querySelector('main');main.insertBefore(host,document.getElementById('sports'))}else{host=document.createElement('details');host.id='sb-picks';const summary=document.createElement('summary');summary.textContent='Sportsbook Lines & Agent Picks';host.open=true;host.appendChild(summary);const section=document.createElement('section');section.id='sb-panel';host.appendChild(section);(document.querySelector('main')||document.body).appendChild(host);host=section;const jump=document.createElement('a');jump.href='#sb-picks';jump.textContent='Latest sportsbook lines & agent picks';jump.style.cssText='display:block;padding:12px 24px;color:#dfc484';(document.getElementById('shell')||document.body.firstElementChild).after(jump)}
 document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.sbRegime){regime=b.dataset.sbRegime;render()}else if(b.dataset.sbAgent&&!dialog?.open)openAgent(b.dataset.sbAgent);else if(b.hasAttribute('data-sb-close')){dialog.close();selected=null}else if(b.dataset.sbDialog){dialogRegime=b.dataset.sbDialog;page=0;renderDialog()}else if(b.hasAttribute('data-sb-prev')){page--;renderDialog()}else if(b.hasAttribute('data-sb-next')){page++;renderDialog()}});
 document.addEventListener('click',e=>{const a=e.target.closest('[data-owner-agent]');if(!a||!isMarket())return;e.preventDefault();dialogRegime='owner_line';openAgent(a.dataset.ownerAgent)});
 document.addEventListener('change',e=>{if(e.target.id==='sb-book-game')bookGame=e.target.value;else if(e.target.id==='sb-sport')sport=e.target.value;else if(e.target.id==='sb-market')market=e.target.value;else if(e.target.id==='sb-status')status=e.target.value;else return;render()});refresh();setInterval(refresh,30000)
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();

/* BOARD_SPORTSBOOK_PICKS_END */
