import streamlit as st
import pandas as pd
import csv
import requests
import altair as alt
from glob import glob
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MLB Model",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────
TEAM_IDS = {
    "Arizona Diamondbacks": 109, "Atlanta Braves": 144,
    "Baltimore Orioles": 110, "Boston Red Sox": 111,
    "Chicago Cubs": 112, "Chicago White Sox": 145,
    "Cincinnati Reds": 113, "Cleveland Guardians": 114,
    "Colorado Rockies": 115, "Detroit Tigers": 116,
    "Houston Astros": 117, "Kansas City Royals": 118,
    "Los Angeles Angels": 108, "Los Angeles Dodgers": 119,
    "Miami Marlins": 146, "Milwaukee Brewers": 158,
    "Minnesota Twins": 142, "New York Mets": 121,
    "New York Yankees": 147, "Athletics": 133,
    "Philadelphia Phillies": 143, "Pittsburgh Pirates": 134,
    "San Diego Padres": 135, "San Francisco Giants": 137,
    "Seattle Mariners": 136, "St. Louis Cardinals": 138,
    "Tampa Bay Rays": 139, "Texas Rangers": 140,
    "Toronto Blue Jays": 141, "Washington Nationals": 120,
}

METRIC_TOOLTIPS = {
    "Overall Accuracy": "Percentage of all games where the model correctly predicted the winner. 50% = random coin flip. Anything above 53% consistently is meaningful.",
    "6-10% Zone Accuracy": "Our primary signal zone. Games where the model disagrees with the market by 6-10%. This zone has historically shown the strongest predictive edge — the market is mispricing these games.",
    "6-10% Zone P&L": "Paper profit/loss on $100 flat bets placed only in the 6-10% edge zone. Positive = model is finding real value. This is the number that matters most.",
    "6-10% Zone ROI": "Return on investment for 6-10% zone bets. Divide total P&L by total amount wagered. Need sustained 5%+ ROI to confirm real edge over variance.",
    "All Flagged Bets": "Win rate on every game the model flagged as a bet, across all edge zones. Lower than 6-10% zone alone because it includes noisier zones.",
}

# ─────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Barlow+Condensed:wght@300;400;500;600;700;800&display=swap');

*, html, body, [class*="css"] {
    font-family: 'Barlow Condensed', sans-serif;
    background-color: #080c18;
    color: #dde3f0;
}
.main, .block-container { background-color: #080c18 !important; }
h1,h2,h3 { font-family: 'Space Mono', monospace !important; }

/* Cards */
.card {
    background: linear-gradient(145deg, #0f1628 0%, #0a1020 100%);
    border: 1px solid #1c2540;
    border-radius: 10px;
    padding: 18px 20px;
}
.card-metric {
    background: linear-gradient(145deg, #0f1628 0%, #0a1020 100%);
    border: 1px solid #1c2540;
    border-radius: 10px;
    padding: 20px;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.2s;
}
.card-metric:hover { border-color: #3b82f6; }

/* Typography */
.val { font-family:'Space Mono',monospace; font-size:2rem; font-weight:700; color:#3b82f6; }
.val-green { color:#00d97e !important; }
.val-red { color:#ef4444 !important; }
.val-yellow { color:#f59e0b !important; }
.lbl { font-size:0.72rem; color:#64748b; text-transform:uppercase; letter-spacing:1.5px; margin-top:4px; }
.sub { font-size:0.78rem; color:#475569; }
.mono { font-family:'Space Mono',monospace; }

/* Section headers */
.sec {
    font-family:'Space Mono',monospace;
    font-size:0.65rem;
    color:#334155;
    text-transform:uppercase;
    letter-spacing:2.5px;
    border-bottom:1px solid #1c2540;
    padding-bottom:8px;
    margin: 24px 0 16px 0;
}

/* Bet cards */
.bet-card {
    background: linear-gradient(145deg, #0a2018 0%, #061510 100%);
    border:1px solid #166534;
    border-left:4px solid #00d97e;
    border-radius:10px;
    padding:20px;
    margin-bottom:14px;
    position:relative;
}
.neutral-row {
    background:#0f1628;
    border:1px solid #1c2540;
    border-radius:6px;
    padding:10px 14px;
    margin-bottom:6px;
}
.win-row {
    background:#061510;
    border-left:3px solid #00d97e;
    padding:8px 12px;
    margin-bottom:4px;
    border-radius:4px;
}
.loss-row {
    background:#180808;
    border-left:3px solid #ef4444;
    padding:8px 12px;
    margin-bottom:4px;
    border-radius:4px;
}

/* Badges */
.badge { padding:3px 10px; border-radius:4px; font-size:0.7rem; font-weight:700; letter-spacing:1px; }
.badge-green { background:#166534; color:#00d97e; }
.badge-red { background:#7f1d1d; color:#ef4444; }
.badge-blue { background:#1e3a8a; color:#93c5fd; }
.badge-yellow { background:#78350f; color:#fcd34d; }

/* Bullpen table */
.bp-row {
    display:flex;
    justify-content:space-between;
    align-items:center;
    padding:7px 12px;
    border-radius:5px;
    margin-bottom:3px;
    background:#0f1628;
    border:1px solid #1c2540;
}
.bp-rank { font-family:'Space Mono',monospace; font-size:0.7rem; color:#334155; width:24px; }
.bp-team { font-size:0.9rem; font-weight:600; flex:1; }
.bp-era { font-family:'Space Mono',monospace; font-size:0.85rem; font-weight:700; }

/* Sharp signal */
.confirmed { color:#00d97e; font-size:0.75rem; font-weight:700; }
.fade { color:#ef4444; font-size:0.75rem; font-weight:700; }
.na { color:#475569; font-size:0.75rem; }

/* Streak */
.streak-box {
    background:#0f1628;
    border:1px solid #1c2540;
    border-radius:8px;
    padding:16px 20px;
    text-align:center;
}

/* Search result */
.search-row {
    background:#0f1628;
    border:1px solid #1c2540;
    border-radius:6px;
    padding:10px 14px;
    margin-bottom:5px;
}

/* Stacked layout helpers */
.flex-row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
.team-block { display:flex; align-items:center; gap:8px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def logo_url(team):
    tid = TEAM_IDS.get(team)
    return f"https://www.mlbstatic.com/team-logos/{tid}.svg" if tid else None

@st.cache_data(ttl=86400, show_spinner=False)
def get_player_id(name):
    try:
        r = requests.get(
            "https://statsapi.mlb.com/api/v1/people/search",
            params={"names": name.strip(), "sportId": 1},
            timeout=5
        )
        people = r.json().get("people", [])
        if people:
            return people[0]["id"]
    except:
        pass
    return None

def headshot_url(pid):
    base = "https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_213,q_auto:best/v1/people"
    pid = pid or "generic"
    return f"{base}/{pid}/headshot/67/current"

def load_picks(filename):
    try:
        with open(filename, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except:
        return []

@st.cache_data(ttl=600, show_spinner=False)
def get_results(date_str):
    try:
        r = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str, "hydrate": "linescore"},
            timeout=10
        ).json()
        out = {}
        for d in r.get("dates", []):
            for g in d.get("games", []):
                if g.get("status", {}).get("abstractGameState") != "Final":
                    continue
                home = g["teams"]["home"]["team"]["name"]
                away = g["teams"]["away"]["team"]["name"]
                hs = g["teams"]["home"].get("score", 0)
                as_ = g["teams"]["away"].get("score", 0)
                w = home if hs > as_ else away
                rec = {"winner": w, "home": home, "away": away,
                       "home_score": hs, "away_score": as_}
                out[home] = rec
                out[away] = rec
        return out
    except:
        return {}

def parse_edge(s):
    try:
        return abs(float(str(s).replace("%","").replace("** BET **","").replace("+","").strip()))
    except:
        return 0.0

def edge_bucket(e):
    if e < 3:   return "0-3%"
    if e < 6:   return "3-6%"
    if e < 10:  return "6-10%"
    return "10%+"

# ─────────────────────────────────────────────────────────────
# SEASON DATA LOADER
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def load_season():
    files = sorted(glob("picks_2026-*.csv"))
    total = correct = flagged = flag_correct = 0
    zone_bets = zone_wins = 0
    zone_pnl = 0.0
    edge_buckets = {"0-3%":[0,0], "3-6%":[0,0], "6-10%":[0,0], "10%+":[0,0]}
    daily = []
    all_picks = []  # for search
    bullpen_latest = {}  # team -> most recent ERA

    for fn in files:
        date_str = fn.replace("picks_","").replace(".csv","")
        picks = load_picks(fn)
        if not picks: continue
        results = get_results(date_str)
        if not results: continue

        day_total = day_correct = day_flagged = day_flag_correct = 0
        day_games = []

        for p in picks:
            away = p.get("Away","")
            home = p.get("Home","")
            ap = p.get("Model Away%","None")
            hp = p.get("Model Home%","None")
            flag = p.get("Flag","")

            # Track bullpen for leaderboard
            try:
                away_bp = float(p.get("Away BP ERA(7d)",""))
                bullpen_latest[away] = away_bp
            except: pass
            try:
                home_bp = float(p.get("Home BP ERA(7d)",""))
                bullpen_latest[home] = home_bp
            except: pass

            if ap in ("None","N/A") or hp in ("None","N/A"):
                continue
            try:
                apf = float(ap); hpf = float(hp)
            except: continue

            result = results.get(home) or results.get(away)
            if not result: continue

            winner = result["winner"]
            model_pick = away if apf > hpf else home
            won = model_pick == winner
            hs = result.get("home_score", 0)
            as_ = result.get("away_score", 0)

            total += 1; day_total += 1
            if won: correct += 1; day_correct += 1

            is_flagged = "BET" in str(flag)
            if is_flagged:
                flagged += 1; day_flagged += 1
                if won: flag_correct += 1; day_flag_correct += 1

            e = parse_edge(p.get("DK Edge Away",""))
            b = edge_bucket(e)
            edge_buckets[b][0] += 1
            if won: edge_buckets[b][1] += 1

            if b == "6-10%" and is_flagged:
                zone_bets += 1
                if won: zone_wins += 1; zone_pnl += 100
                else: zone_pnl -= 100

            g_rec = {
                "away": away, "home": home,
                "away_prob": ap, "home_prob": hp,
                "model_pick": model_pick,
                "actual_winner": winner,
                "won": won,
                "score": f"{as_}-{hs}",
                "flag": is_flagged,
                "date": date_str,
                "away_sp": p.get("Away SP",""),
                "home_sp": p.get("Home SP",""),
            }
            day_games.append(g_rec)
            all_picks.append(g_rec)

        if day_total > 0:
            pct = day_correct/day_total*100
            daily.append({
                "date": date_str, "total": day_total, "correct": day_correct,
                "pct": pct, "flagged": day_flagged, "flag_correct": day_flag_correct,
                "games": day_games
            })

    # Streak calculation from recent flagged bets
    recent_flags = [g for g in all_picks if g["flag"]]
    streak = 0
    streak_type = None
    for g in reversed(recent_flags):
        if streak_type is None:
            streak_type = "W" if g["won"] else "L"
            streak = 1
        elif (g["won"] and streak_type == "W") or (not g["won"] and streak_type == "L"):
            streak += 1
        else:
            break

    return {
        "total": total, "correct": correct,
        "flagged": flagged, "flag_correct": flag_correct,
        "zone_bets": zone_bets, "zone_wins": zone_wins, "zone_pnl": zone_pnl,
        "edge_buckets": edge_buckets, "daily": daily,
        "all_picks": all_picks,
        "bullpen": bullpen_latest,
        "streak": streak, "streak_type": streak_type,
    }

def load_today():
    lv = timezone(timedelta(hours=-7))
    today_str = datetime.now(lv).strftime("%Y-%m-%d")
    return load_picks(f"picks_{today_str}.csv"), today_str


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

# ── Header
col_title, col_refresh = st.columns([5,1])
with col_title:
    st.markdown("""
    <div style='padding:20px 0 4px 0'>
        <span style='font-family:Space Mono,monospace;font-size:1.6rem;font-weight:700;color:#3b82f6'>⚾ MLB MODEL</span>
        <span style='font-family:Space Mono,monospace;font-size:1.6rem;color:#1e2940'> // DASHBOARD</span>
    </div>""", unsafe_allow_html=True)
    st.markdown(f"<div class='sub'>Updated: {datetime.now().strftime('%b %d, %Y  %I:%M %p')}</div>", unsafe_allow_html=True)

with col_refresh:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── Load data
with st.spinner("Loading..."):
    S = load_season()
    todays, today_str = load_today()

# ─────────────────────────────────────────────────────────────
# SEASON KPIs
# ─────────────────────────────────────────────────────────────
st.markdown("<div class='sec'>Season Performance</div>", unsafe_allow_html=True)

overall_pct  = S["correct"]/S["total"]*100 if S["total"] else 0
flag_pct     = S["flag_correct"]/S["flagged"]*100 if S["flagged"] else 0
b610         = S["edge_buckets"]["6-10%"]
pct_610      = b610[1]/b610[0]*100 if b610[0] else 0
zone_roi     = S["zone_pnl"]/(S["zone_bets"]*100)*100 if S["zone_bets"] else 0
pnl_str      = f"+${S['zone_pnl']:.0f}" if S["zone_pnl"]>=0 else f"-${abs(S['zone_pnl']):.0f}"

kpi_data = [
    ("Overall Accuracy",  f"{overall_pct:.1f}%",  f"{S['correct']}/{S['total']} games",
     "#3b82f6" if overall_pct>=50 else "#ef4444"),
    ("6-10% Zone Accuracy", f"{pct_610:.1f}%",    f"{b610[1]}/{b610[0]} games",
     "#00d97e" if pct_610>=60 else "#f59e0b" if pct_610>=52 else "#ef4444"),
    ("6-10% Zone P&L",    pnl_str,                f"{S['zone_bets']} flagged bets",
     "#00d97e" if S["zone_pnl"]>=0 else "#ef4444"),
    ("6-10% Zone ROI",    f"{zone_roi:+.1f}%",    f"{S['zone_wins']}/{S['zone_bets']} wins",
     "#00d97e" if zone_roi>=0 else "#ef4444"),
    ("All Flagged Bets",  f"{flag_pct:.1f}%",     f"{S['flag_correct']}/{S['flagged']} bets",
     "#00d97e" if flag_pct>=55 else "#f59e0b" if flag_pct>=47 else "#ef4444"),
]

kpi_cols = st.columns(5)
for i, (label, value, sub, color) in enumerate(kpi_data):
    with kpi_cols[i]:
        with st.expander(f"{value}", expanded=False):
            st.markdown(f"**{label}**")
            st.caption(METRIC_TOOLTIPS.get(label, ""))
            st.markdown(f"<div class='sub'>{sub}</div>", unsafe_allow_html=True)
        st.markdown(f"""
        <div style='text-align:center;margin-top:-8px'>
            <div style='font-family:Space Mono,monospace;font-size:1.85rem;font-weight:700;color:{color}'>{value}</div>
            <div class='lbl'>{label}</div>
            <div class='sub'>{sub}</div>
        </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# STREAK + CONFIDENCE ROW
# ─────────────────────────────────────────────────────────────
s_col1, s_col2 = st.columns([1,3])

with s_col1:
    st.markdown("<div class='sec'>Current Streak</div>", unsafe_allow_html=True)
    stype = S.get("streak_type")
    scount = S.get("streak", 0)
    if stype == "W":
        scolor = "#00d97e"
        slabel = f"🔥 {scount}-game WIN streak"
    elif stype == "L":
        scolor = "#ef4444"
        slabel = f"❄️ {scount}-game LOSS streak"
    else:
        scolor = "#475569"
        slabel = "No streak data"
    st.markdown(f"""
    <div class='streak-box'>
        <div style='font-family:Space Mono,monospace;font-size:2.5rem;font-weight:700;color:{scolor}'>{scount}</div>
        <div style='color:{scolor};font-weight:600;font-size:0.9rem;margin-top:4px'>{slabel}</div>
        <div class='sub' style='margin-top:6px'>Flagged bets only</div>
    </div>""", unsafe_allow_html=True)

with s_col2:
    st.markdown("<div class='sec'>Betting Confidence</div>", unsafe_allow_html=True)
    zone_pct = S["zone_wins"]/S["zone_bets"]*100 if S["zone_bets"] else 0
    if S["zone_bets"] >= 20 and zone_pct >= 60:
        conf_color = "#00d97e"
        conf_msg = f"✅ READY — 6-10% zone at {zone_pct:.1f}% over {S['zone_bets']} bets → consider real money"
        bar_pct = 100
    elif S["zone_bets"] >= 15 and zone_pct >= 55:
        conf_color = "#f59e0b"
        conf_msg = f"🟡 GETTING CLOSE — {zone_pct:.1f}% on {S['zone_bets']} bets → paper trade only"
        bar_pct = 66
    else:
        conf_color = "#ef4444"
        conf_msg = f"🔴 NOT YET — {zone_pct:.1f}% on {S['zone_bets']} bets → need 60%+ over 20+ bets"
        bar_pct = 33

    progress_html = f"""
    <div style='background:#0f1628;border:1px solid #1c2540;border-radius:8px;padding:20px'>
        <div style='font-family:Space Mono,monospace;color:{conf_color};font-weight:700;font-size:0.95rem;margin-bottom:12px'>{conf_msg}</div>
        <div style='background:#1c2540;border-radius:4px;height:8px'>
            <div style='background:{conf_color};width:{bar_pct}%;height:8px;border-radius:4px;transition:width 0.5s'></div>
        </div>
        <div style='display:flex;justify-content:space-between;margin-top:6px'>
            <span class='sub'>0%</span>
            <span class='sub'>Target: 60%+ over 20+ bets</span>
            <span class='sub'>100%</span>
        </div>
    </div>"""
    st.markdown(progress_html, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# TODAY'S FLAGGED BETS
# ─────────────────────────────────────────────────────────────
st.markdown(f"<div class='sec'>Today's Flagged Bets — {today_str}</div>", unsafe_allow_html=True)

if not todays:
    st.info("No picks file for today. Run master.py first.")
else:
    flagged_today = [p for p in todays if "BET" in str(p.get("Flag",""))]
    other_today   = [p for p in todays if "BET" not in str(p.get("Flag",""))]

    if not flagged_today:
        st.markdown("""
        <div style='background:#0f1628;border:1px solid #1c2540;border-radius:8px;padding:24px;text-align:center;color:#475569;font-size:1rem'>
            No flagged bets today — model sees no high-conviction edges
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"<span class='badge badge-green'>🎯 {len(flagged_today)} FLAGGED BET{'S' if len(flagged_today)>1 else ''} TODAY</span><br><br>", unsafe_allow_html=True)

        for pick in flagged_today:
            away     = pick.get("Away","")
            home     = pick.get("Home","")
            ap       = pick.get("Model Away%","N/A")
            hp       = pick.get("Model Home%","N/A")
            away_sp  = pick.get("Away SP","—")
            home_sp  = pick.get("Home SP","—")
            away_rel = pick.get("Away Reliability%","")
            home_rel = pick.get("Home Reliability%","")
            sharp    = pick.get("Sharp Signal","N/A")
            dk_ea    = pick.get("DK Edge Away","")
            dk_eh    = pick.get("DK Edge Home","")
            lineup   = pick.get("Lineup Source","")
            away_bp  = pick.get("Away BP ERA(7d)","—")
            home_bp  = pick.get("Home BP ERA(7d)","—")
            away_velo= pick.get("Away SP Velo","")
            home_velo= pick.get("Home SP Velo","")
            park     = pick.get("Park Factor","100")

            try:
                apf = float(ap); hpf = float(hp)
                model_fav = away if apf > hpf else home
                edge = dk_ea if apf > hpf else dk_eh
            except:
                model_fav = home; edge = dk_eh

            sharp_color = "#00d97e" if "CONFIRMED" in str(sharp) else "#ef4444" if "FADE" in str(sharp) else "#475569"
            sharp_label = "✓ CONFIRMED SHARP" if "CONFIRMED" in str(sharp) else "✗ FADE SIGNAL" if "FADE" in str(sharp) else "— NO SIGNAL"

            away_logo = logo_url(away)
            home_logo = logo_url(home)

            # Pitcher IDs for headshots
            away_pid = get_player_id(away_sp) if away_sp not in ("—","TBD","") else None
            home_pid = get_player_id(home_sp) if home_sp not in ("—","TBD","") else None

            st.markdown(f"""
            <div class='bet-card'>
                <div style='display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px'>
                    <div>
                        <div class='sub' style='margin-bottom:6px'>{lineup}</div>
                        <div style='font-size:1.3rem;font-weight:800;color:#f1f5f9'>{away} <span style='color:#1e2940'>@</span> {home}</div>
                    </div>
                    <div style='text-align:right'>
                        <div style='font-family:Space Mono,monospace;font-size:1.3rem;color:#00d97e;font-weight:700'>{edge}</div>
                        <div style='color:{sharp_color};font-size:0.75rem;font-weight:700;margin-top:2px'>{sharp_label}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

            # Team logos + probabilities
            logo_col1, prob_col, logo_col2 = st.columns([2, 1, 2])

            with logo_col1:
                if away_logo:
                    try:
                        st.image(away_logo, width=64)
                    except: pass
                st.markdown(f"""
                <div style='margin-top:4px'>
                    <div style='font-weight:700;font-size:1rem'>{away}</div>
                    <div style='font-family:Space Mono,monospace;font-size:1.6rem;color:#3b82f6;font-weight:700'>{ap}%</div>
                    <div class='sub'>model probability</div>
                </div>""", unsafe_allow_html=True)

            with prob_col:
                st.markdown(f"""
                <div style='text-align:center;padding-top:20px'>
                    <div style='color:#1e2940;font-size:1.5rem;font-weight:700'>VS</div>
                    <div style='margin-top:8px'>
                        <span class='badge badge-green' style='font-size:0.65rem'>PICK: {model_fav}</span>
                    </div>
                    <div style='margin-top:8px;font-size:0.7rem;color:#334155'>Park: {park}</div>
                </div>""", unsafe_allow_html=True)

            with logo_col2:
                if home_logo:
                    try:
                        st.image(home_logo, width=64)
                    except: pass
                st.markdown(f"""
                <div style='margin-top:4px'>
                    <div style='font-weight:700;font-size:1rem'>{home}</div>
                    <div style='font-family:Space Mono,monospace;font-size:1.6rem;color:#3b82f6;font-weight:700'>{hp}%</div>
                    <div class='sub'>model probability</div>
                </div>""", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # Pitcher headshots row
            p_col1, p_col2 = st.columns(2)

            with p_col1:
                hs1 = headshot_url(away_pid)
                pc1a, pc1b = st.columns([1, 3])
                with pc1a:
                    try:
                        st.image(hs1, width=56)
                    except: pass
                with pc1b:
                    bp_color_a = "#00d97e" if float(away_bp) < 3.5 else "#f59e0b" if float(away_bp) < 5.0 else "#ef4444" if away_bp != "—" else "#475569"
                    st.markdown(f"""
                    <div>
                        <div style='font-weight:700;font-size:0.9rem'>{away_sp}</div>
                        <div class='sub'>Away SP · {away_rel} reliability</div>
                        <div style='font-family:Space Mono,monospace;font-size:0.8rem;color:{bp_color_a};margin-top:2px'>BP ERA: {away_bp}</div>
                    </div>""", unsafe_allow_html=True)

            with p_col2:
                hs2 = headshot_url(home_pid)
                pc2a, pc2b = st.columns([1, 3])
                with pc2a:
                    try:
                        st.image(hs2, width=56)
                    except: pass
                with pc2b:
                    try:
                        bp_color_h = "#00d97e" if float(home_bp) < 3.5 else "#f59e0b" if float(home_bp) < 5.0 else "#ef4444"
                    except:
                        bp_color_h = "#475569"
                    st.markdown(f"""
                    <div>
                        <div style='font-weight:700;font-size:0.9rem'>{home_sp}</div>
                        <div class='sub'>Home SP · {home_rel} reliability</div>
                        <div style='font-family:Space Mono,monospace;font-size:0.8rem;color:{bp_color_h};margin-top:2px'>BP ERA: {home_bp}</div>
                    </div>""", unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)

    # All games today
    with st.expander(f"All Games Today ({len(todays)} total)"):
        for pick in todays:
            away = pick.get("Away","")
            home = pick.get("Home","")
            ap   = pick.get("Model Away%","N/A")
            hp   = pick.get("Model Home%","N/A")
            dkea = pick.get("DK Edge Away","N/A")
            dkeh = pick.get("DK Edge Home","N/A")
            sharp= pick.get("Sharp Signal","N/A")
            flag = "BET" in str(pick.get("Flag",""))
            sharp_color = "#00d97e" if "CONFIRMED" in str(sharp) else "#ef4444" if "FADE" in str(sharp) else "#475569"
            border = "#166534" if flag else "#1c2540"

            away_logo = logo_url(away)
            home_logo = logo_url(home)

            cols = st.columns([1, 1, 4, 2, 2, 2])
            with cols[0]:
                if away_logo:
                    try: st.image(away_logo, width=28)
                    except: pass
            with cols[1]:
                if home_logo:
                    try: st.image(home_logo, width=28)
                    except: pass
            with cols[2]:
                flag_txt = " 🎯" if flag else ""
                st.markdown(f"**{away}** @ **{home}**{flag_txt}")
            with cols[3]:
                st.markdown(f"<span class='mono' style='color:#3b82f6'>{ap}% / {hp}%</span>", unsafe_allow_html=True)
            with cols[4]:
                st.markdown(f"<span class='mono' style='color:#475569;font-size:0.8rem'>{dkea} | {dkeh}</span>", unsafe_allow_html=True)
            with cols[5]:
                st.markdown(f"<span style='color:{sharp_color};font-size:0.75rem;font-weight:700'>{sharp}</span>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# LINE MOVEMENT TRACKER
# ─────────────────────────────────────────────────────────────
st.markdown("<div class='sec'>Line Movement Tracker — Today's Biggest Movers</div>", unsafe_allow_html=True)

if todays:
    movers = []
    for pick in todays:
        away = pick.get("Away","")
        home = pick.get("Home","")
        sharp = pick.get("Sharp Signal","N/A")
        try:
            away_move = pick.get("DK Edge Away","0").replace("%","").replace("** BET **","").replace("+","")
            home_move = pick.get("DK Edge Home","0").replace("%","").replace("** BET **","").replace("+","")
            # Parse line movement from the move strings if available
            # Use edge as proxy for movement magnitude
            e = parse_edge(pick.get("DK Edge Away","0"))
            movers.append({
                "matchup": f"{away} @ {home}",
                "away": away, "home": home,
                "sharp": sharp,
                "edge": e,
                "away_edge": pick.get("DK Edge Away",""),
                "home_edge": pick.get("DK Edge Home",""),
            })
        except:
            pass

    movers.sort(key=lambda x: x["edge"], reverse=True)
    top_movers = movers[:6]

    mv_cols = st.columns(3)
    for i, mv in enumerate(top_movers):
        with mv_cols[i % 3]:
            sharp = mv["sharp"]
            sc = "#00d97e" if "CONFIRMED" in str(sharp) else "#ef4444" if "FADE" in str(sharp) else "#475569"
            sl = "CONFIRMED ✓" if "CONFIRMED" in str(sharp) else "FADE ✗" if "FADE" in str(sharp) else "N/A"
            away_logo = logo_url(mv["away"])
            home_logo = logo_url(mv["home"])

            st.markdown(f"""
            <div class='card' style='margin-bottom:10px'>
                <div style='font-size:0.85rem;font-weight:700;margin-bottom:8px'>{mv['matchup']}</div>
                <div style='display:flex;justify-content:space-between'>
                    <span class='sub'>Away edge: <span class='mono'>{mv['away_edge']}</span></span>
                    <span class='sub'>Home edge: <span class='mono'>{mv['home_edge']}</span></span>
                </div>
                <div style='margin-top:6px;color:{sc};font-size:0.75rem;font-weight:700'>{sl}</div>
            </div>""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# EDGE ZONE + BULLPEN LEADERBOARD
# ─────────────────────────────────────────────────────────────
st.markdown("<div class='sec'>Model Analytics</div>", unsafe_allow_html=True)
ez_col, bp_col = st.columns([1,1])

with ez_col:
    st.markdown("<div style='font-weight:700;margin-bottom:12px;color:#94a3b8'>Edge Zone Performance</div>", unsafe_allow_html=True)
    for bucket, (tot, cor) in S["edge_buckets"].items():
        if tot == 0: continue
        pct = cor/tot*100
        color = "#00d97e" if pct>=58 else "#f59e0b" if pct>=50 else "#ef4444"
        star = " ★ KEY ZONE" if bucket=="6-10%" else ""
        bar = int(pct)
        st.markdown(f"""
        <div class='card' style='padding:12px 16px;margin-bottom:8px'>
            <div style='display:flex;justify-content:space-between;margin-bottom:6px'>
                <span style='font-weight:700;color:#e2e8f0'>{bucket}<span style='color:#00d97e;font-size:0.7rem'>{star}</span></span>
                <span style='font-family:Space Mono,monospace;font-size:1rem;color:{color};font-weight:700'>{pct:.1f}%</span>
            </div>
            <div style='background:#1c2540;border-radius:3px;height:5px'>
                <div style='background:{color};width:{bar}%;height:5px;border-radius:3px'></div>
            </div>
            <div class='sub' style='margin-top:4px'>{cor}/{tot} games · Click KPI card above for explanation</div>
        </div>""", unsafe_allow_html=True)

with bp_col:
    st.markdown("<div style='font-weight:700;margin-bottom:12px;color:#94a3b8'>Bullpen Leaderboard (7-day ERA)</div>", unsafe_allow_html=True)
    bp = S["bullpen"]
    if bp:
        sorted_bp = sorted(bp.items(), key=lambda x: x[1])
        for rank, (team, era) in enumerate(sorted_bp[:15], 1):
            color = "#00d97e" if era < 3.0 else "#f59e0b" if era < 4.5 else "#ef4444"
            logo = logo_url(team)
            col_r, col_l, col_t, col_e = st.columns([1, 1, 4, 2])
            with col_r:
                st.markdown(f"<span class='sub' style='font-size:0.7rem'>#{rank}</span>", unsafe_allow_html=True)
            with col_l:
                if logo:
                    try: st.image(logo, width=20)
                    except: pass
            with col_t:
                st.markdown(f"<span style='font-size:0.82rem;font-weight:600'>{team}</span>", unsafe_allow_html=True)
            with col_e:
                st.markdown(f"<span style='font-family:Space Mono,monospace;font-size:0.82rem;font-weight:700;color:{color}'>{era:.2f}</span>", unsafe_allow_html=True)
    else:
        st.caption("Run master.py to populate bullpen data.")

# ─────────────────────────────────────────────────────────────
# SEASON TREND CHART
# ─────────────────────────────────────────────────────────────
st.markdown("<div class='sec'>Season Accuracy Trend</div>", unsafe_allow_html=True)

if len(S["daily"]) >= 3:
    trend_rows = []
    for d in S["daily"]:
        trend_rows.append({
            "date": d["date"],
            "Overall %": round(d["pct"], 1),
            "Games": d["total"],
        })

    df = pd.DataFrame(trend_rows)
    df["date"] = pd.to_datetime(df["date"])

    # Rolling 3-day average
    df = df.sort_values("date")
    df["Rolling Avg"] = df["Overall %"].rolling(3, min_periods=1).mean().round(1)

    base = alt.Chart(df).encode(
        x=alt.X("date:T", title="Date", axis=alt.Axis(format="%b %d", labelColor="#475569", titleColor="#475569", gridColor="#1c2540")),
    )

    line = base.mark_line(color="#3b82f6", strokeWidth=2).encode(
        y=alt.Y("Overall %:Q", title="Accuracy %", scale=alt.Scale(domain=[20,80]),
                axis=alt.Axis(labelColor="#475569", titleColor="#475569", gridColor="#1c2540"))
    )
    rolling = base.mark_line(color="#00d97e", strokeWidth=1.5, strokeDash=[4,2]).encode(
        y="Rolling Avg:Q"
    )
    points = base.mark_circle(size=60, color="#3b82f6").encode(
        y="Overall %:Q",
        tooltip=["date:T", "Overall %:Q", "Rolling Avg:Q", "Games:Q"]
    )
    rule = alt.Chart(pd.DataFrame({"y": [50]})).mark_rule(
        color="#475569", strokeDash=[6,3], strokeWidth=1
    ).encode(y="y:Q")

    chart = (line + rolling + points + rule).properties(
        height=220,
        background="#080c18",
        title=alt.TitleParams(
            text="Daily Accuracy % (blue) + 3-day rolling avg (green dashed)",
            color="#475569", fontSize=11
        )
    ).configure_axis(
        labelFontSize=11, titleFontSize=11
    ).configure_view(strokeOpacity=0)

    st.altair_chart(chart, use_container_width=True)
else:
    st.caption("Need at least 3 days of data for trend chart.")

# ─────────────────────────────────────────────────────────────
# DAILY RECORD
# ─────────────────────────────────────────────────────────────
st.markdown("<div class='sec'>Daily Record — Click to Expand Games</div>", unsafe_allow_html=True)

if S["daily"]:
    for d in reversed(S["daily"][-12:]):
        pct = d["pct"]
        flag_txt = f"{d['flag_correct']}/{d['flagged']}" if d["flagged"] else "—"
        color = "#00d97e" if pct>=55 else "#f59e0b" if pct>=45 else "#ef4444"
        label = f"{d['date']}   {d['correct']}/{d['total']} ({pct:.0f}%)   Flags: {flag_txt}"

        with st.expander(label):
            for g in d.get("games",[]):
                away    = g["away"]
                home    = g["home"]
                winner  = g["actual_winner"]
                won     = g["won"]
                score   = g["score"]
                flagged = g["flag"]
                ap      = g["away_prob"]
                hp      = g["home_prob"]

                icon = "✓" if won else "✗"
                flag_badge = " 🎯" if flagged else ""
                away_bold = f"**{away}**" if winner==away else away
                home_bold = f"**{home}**" if winner==home else home

                # Team logos
                c0, c1, c2, c3, c4, c5 = st.columns([1,1,4,1,2,1])
                with c0:
                    l = logo_url(away)
                    if l:
                        try: st.image(l, width=22)
                        except: pass
                with c1:
                    l = logo_url(home)
                    if l:
                        try: st.image(l, width=22)
                        except: pass
                with c2:
                    st.write(f"{away_bold} @ {home_bold}{flag_badge}")
                with c3:
                    st.write(score)
                with c4:
                    st.write(f"{ap}% / {hp}%")
                with c5:
                    if won: st.success(icon)
                    else:   st.error(icon)

# ─────────────────────────────────────────────────────────────
# PICK HISTORY SEARCH
# ─────────────────────────────────────────────────────────────
st.markdown("<div class='sec'>Pick History Search</div>", unsafe_allow_html=True)

search = st.text_input("Search by team or pitcher name", placeholder="e.g. Cardinals, Rays, Glasnow...")

if search and len(search) >= 2:
    q = search.lower()
    hits = [g for g in S["all_picks"] if
            q in g.get("away","").lower() or
            q in g.get("home","").lower() or
            q in g.get("away_sp","").lower() or
            q in g.get("home_sp","").lower()]

    if hits:
        st.markdown(f"<div class='sub' style='margin-bottom:8px'>{len(hits)} result(s)</div>", unsafe_allow_html=True)
        wins = sum(1 for h in hits if h["won"])
        st.markdown(f"<div class='sub' style='margin-bottom:12px'>Record: {wins}/{len(hits)} ({wins/len(hits)*100:.1f}%)</div>", unsafe_allow_html=True)

        for g in reversed(hits[-20:]):
            won   = g["won"]
            icon  = "✓" if won else "✗"
            color = "#00d97e" if won else "#ef4444"
            flag  = " 🎯" if g["flag"] else ""

            sc1, sc2, sc3, sc4, sc5 = st.columns([1,1,4,2,1])
            with sc1:
                l = logo_url(g["away"])
                if l:
                    try: st.image(l, width=22)
                    except: pass
            with sc2:
                l = logo_url(g["home"])
                if l:
                    try: st.image(l, width=22)
                    except: pass
            with sc3:
                st.write(f"**{g['date']}** — {g['away']} @ {g['home']}{flag}")
            with sc4:
                st.write(f"{g['score']} | Pick: {g['model_pick']}")
            with sc5:
                if won: st.success(icon)
                else:   st.error(icon)
    else:
        st.caption(f"No picks found matching '{search}'")

# ─────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────
st.markdown("<br><br>", unsafe_allow_html=True)
st.markdown("""
<div style='text-align:center;border-top:1px solid #1c2540;padding-top:16px'>
    <span class='sub'>MLB Prediction Model · Personal Use Only · Updates daily after pushing to GitHub</span>
</div>""", unsafe_allow_html=True)