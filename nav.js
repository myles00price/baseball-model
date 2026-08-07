/* Shared sport navigation for the board site.
   One source of truth for the menu: add a sport here and every page gets it.
   Pages include:  <div id="sportnav"></div><script src="nav.js"></script>
   Active tab is detected from the filename. */
(function () {
  var SPORTS = [
    { id: "hub",   label: "HOME",   href: "index.html", status: "live"  },
    { id: "mlb",   label: "MLB",    href: "board.html", status: "live"  },
    { id: "nfl",   label: "NFL",    href: "nfl.html",   status: "paper" },
    { id: "nba",   label: "NBA",    href: null,         status: "soon"  },
    { id: "ncaam", label: "NCAAM",  href: null,         status: "soon"  },
    { id: "nhl",   label: "NHL",    href: null,         status: "soon"  },
    { id: "soccer",label: "SOCCER", href: null,         status: "soon"  }
  ];
  var path = (location.pathname.split("/").pop() || "index.html").toLowerCase();
  var css =
    "#sportnav{display:flex;gap:6px;flex-wrap:wrap;align-items:center;" +
      "background:#050505;border:1px solid #1c1c1c;padding:6px 10px;margin-bottom:10px}" +
    "#sportnav a,#sportnav span.soon{font-family:'VT323',monospace;font-size:17px;" +
      "letter-spacing:.08em;padding:3px 12px;text-decoration:none;border:1px solid transparent}" +
    "#sportnav a{color:#8a8a8a}" +
    "#sportnav a:hover{color:#2bff64;border-color:#1f7a3d}" +
    "#sportnav a.active{color:#2bff64;border-color:#2bff64;" +
      "text-shadow:0 0 8px rgba(43,255,100,.5)}" +
    "#sportnav .tag{font-size:11px;margin-left:5px;color:#ffb000}" +
    "#sportnav span.soon{color:#2e2e2e;cursor:default}" +
    "#sportnav span.soon .tag{color:#2e2e2e}" +
    /* light mode (board.html toggle adds body.light) */
    "body.light #sportnav{background:#f7f4ec;border-color:#d8d2c2}" +
    "body.light #sportnav a{color:#6b6355}" +
    "body.light #sportnav a:hover{color:#0d7a2e;border-color:#0d7a2e}" +
    "body.light #sportnav a.active{color:#0d7a2e;border-color:#0d7a2e;text-shadow:none}" +
    "body.light #sportnav span.soon,body.light #sportnav span.soon .tag{color:#c9c2b2}";
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  var mount = document.getElementById("sportnav");
  if (!mount) return;
  mount.innerHTML = SPORTS.map(function (s) {
    var tag = s.status === "paper" ? "<span class='tag'>PAPER</span>"
            : s.status === "soon" ? "<span class='tag'>SOON</span>" : "";
    if (!s.href) return "<span class='soon'>" + s.label + tag + "</span>";
    var active = path === s.href.toLowerCase() ? " class='active'" : "";
    return "<a href='" + s.href + "'" + active + ">" + s.label + tag + "</a>";
  }).join("");
})();
