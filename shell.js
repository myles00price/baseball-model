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
  document.body.dataset.boardSport = sport;
  var shared = document.createElement("link");
  shared.rel = "stylesheet";
  shared.href = new URL("board-common.css", document.currentScript.src).href;
  document.head.appendChild(shared);
  var vegasStyle = document.createElement("link");
  vegasStyle.rel = "stylesheet";
  vegasStyle.href = new URL("vegas.css?v=locked-20260915", document.currentScript.src).href;
  document.head.appendChild(vegasStyle);
  var vegasScript = document.createElement("script");
  vegasScript.src = new URL("vegas.js?v=locked-20260915", document.currentScript.src).href;
  document.head.appendChild(vegasScript);

  var SPORTS = [
    { id: "hub",   label: "HOME",   href: "index.html", status: "live"  },
    { id: "mlb",   label: "MLB",    href: "board.html", status: "live"  },
    { id: "nfl",   label: "NFL",    href: "nfl.html",   status: "paper" },
    { id: "cfb",   label: "CFB",    href: "cfb.html",   status: "paper" },
    { id: "mma",   label: "MMA",    href: "mma.html",   status: "paper" },
    { id: "soccer",label: "SOCCER", href: "soccer.html",status: "paper" },
    { id: "nba",   label: "NBA",    href: null,         status: "soon"  },
    { id: "ncaam", label: "NCAAM",  href: null,         status: "soon"  },
    { id: "nhl",   label: "NHL",    href: null,         status: "soon"  }
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
    new MutationObserver(fitTables).observe(document.querySelector(".frame"), {childList:true,subtree:true});
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
