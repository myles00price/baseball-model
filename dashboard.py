import streamlit as st
import pandas as pd
import csv
import requests
import altair as alt
import math
import os
import json
from glob import glob
from datetime import datetime, timedelta, timezone
from collections import defaultdict

st.set_page_config(page_title="MLB Model", page_icon="⚾", layout="wide", initial_sidebar_state="collapsed")

TEAM_IDS = {
    "Arizona Diamondbacks": 109, "Atlanta Braves": 144, "Baltimore Orioles": 110,
    "Boston Red Sox": 111, "Chicago Cubs": 112, "Chicago White Sox": 145,
    "Cincinnati Reds": 113, "Cleveland Guardians": 114, "Colorado Rockies": 115,
    "Detroit Tigers": 116, "Houston Astros": 117, "Kansas City Royals": 118,
    "Los Angeles Angels": 108, "Los Angeles Dodgers": 119, "Miami Marlins": 146,
    "Milwaukee Brewers": 158, "Minnesota Twins": 142, "New York Mets": 121,
    "New York Yankees": 147, "Athletics": 133, "Philadelphia Phillies": 143,
    "Pittsburgh Pirates": 134, "San Diego Padres": 135, "San Francisco Giants": 137,
    "Seattle Mariners": 136, "St. Louis Cardinals": 138, "Tampa Bay Rays": 139,
    "Texas Rangers": 140, "Toronto Blue Jays": 141, "Washington Nationals": 120,
}

# ── Dashboard-only date filter ──────────────────────────────────────────────
# Hides picks before this date from season totals + analytics.
# Picks files themselves are not modified; retrain_log/clv_log untouched.
# Set to None to disable the filter and show full history.
DASHBOARD_START_DATE = "2026-05-26"

# Sharp FADE veto deploy date — used to footnote pre-filter bets in the P&L
FADE_FILTER_START_DATE = "2026-06-01"

# The historically best-performing edge bucket — picks in this bucket get ⭐
# Based on calibration data; update if BET threshold changes (Sunday FADE review).
# Currently 0-3% at 64.1% on 103 games. 3-6% is also strong at 57.5%.
WINNING_EDGE_BUCKET = "0-3%"

PARK_COORDS = {
    "Arizona Diamondbacks": (33.4453,-112.0667), "Atlanta Braves": (33.8908,-84.4678),
    "Baltimore Orioles": (39.2839,-76.6218), "Boston Red Sox": (42.3467,-71.0972),
    "Chicago Cubs": (41.9484,-87.6553), "Chicago White Sox": (41.8300,-87.6339),
    "Cincinnati Reds": (39.0979,-84.5082), "Cleveland Guardians": (41.4962,-81.6852),
    "Colorado Rockies": (39.7559,-104.9942), "Detroit Tigers": (42.3390,-83.0485),
    "Houston Astros": (29.7573,-95.3555), "Kansas City Royals": (39.0517,-94.4803),
    "Los Angeles Angels": (33.8003,-117.8827), "Los Angeles Dodgers": (34.0739,-118.2400),
    "Miami Marlins": (25.7781,-80.2197), "Milwaukee Brewers": (43.0280,-87.9712),
    "Minnesota Twins": (44.9817,-93.2781), "New York Mets": (40.7571,-73.8458),
    "New York Yankees": (40.8296,-73.9262), "Athletics": (37.7516,-122.2005),
    "Philadelphia Phillies": (39.9061,-75.1665), "Pittsburgh Pirates": (40.4469,-80.0057),
    "San Diego Padres": (32.7076,-117.1570), "San Francisco Giants": (37.7786,-122.3893),
    "Seattle Mariners": (47.5914,-122.3325), "St. Louis Cardinals": (38.6226,-90.1928),
    "Tampa Bay Rays": (27.7683,-82.6534), "Texas Rangers": (32.7512,-97.0832),
    "Toronto Blue Jays": (43.6414,-79.3894), "Washington Nationals": (38.8730,-77.0074),
}

METRIC_TOOLTIPS = {
    "Overall Accuracy": "How often the model picks the right winner across ALL games — not just the ones we bet. 50% is what you'd get by flipping a coin. MLB is hard to predict, so anything consistently above 52-53% is meaningful. This number alone doesn't tell you if you should bet — look at the Model P&L instead.",
    "Model P&L": "Total profit/loss across every flagged bet ($100 flat stake). This is the bottom line — is the model actually making money on the games it decides to bet? Uses real moneyline payouts: -200 favorites win $50, +180 dogs win $180. Note: bets prior to 6/1/26 include FADE games that the current filter would now suppress.",
    "Model ROI": "Return on investment across all flagged bets. +5% means every $100 wagered came back as $105 on average. We want this consistently positive over a large sample (50+ bets). Negative ROI = model is bleeding money; positive ROI in green = potentially profitable.",
    "Flagged Record": "Win/loss record on flagged bets. Win % matters less than ROI because moneyline payouts vary — winning 55% on -150 favorites loses money, winning 45% on +150 dogs makes money.",
    "Avg CLV": "Average Closing Line Value across flagged bets. Did the model identify value before the sharp market did? Positive CLV = model beats the market consistently. This is the LEADING indicator of edge — it usually shows up before W/L stabilizes, because closing lines move toward true probability.",
    "If Bet All Games": "Sanity check: what would happen if you flat-bet $100 on every model pick (not just flagged bets)? If this is positive and similar to flagged ROI → model has no real edge, you're just riding home bias or vig. If this is deeply negative while flagged is positive → the BET filter is genuinely identifying value spots.",
}

MAE_TOOLTIPS = {
    "Overall MAE": "Mean Absolute Error — measures how confident the model is vs what actually happened. If the model says 60% and the team wins, the error is 40 (100-60). If the team loses, error is 60. Lower MAE = model confidence lines up better with reality. A coin flip model would score around 50.",
    "Flagged Bet MAE": "Same as Overall MAE but only for games we flagged as bets. If this is LOWER than Overall MAE, the model is more accurate on the games it's most confident about — a great sign.",
    "vs 50% Baseline": "How much better the model is compared to always guessing 50/50. Positive green number = the model adds real value. The bigger the number, the more the model is actually doing something useful.",
}

ANALYTICS_DESCRIPTIONS = {
    "edge_zones": "The model looks at all games and measures how big its disagreement with the sportsbook is. Bigger edge = model is more confident it found a mistake in the market. Note: edge buckets are diagnostic only — small samples can show misleading hit rates (e.g. a small-sample 80% in the 0-3% bucket is almost certainly noise, not a signal). Wait for 4+ weeks of post-XGBoost data before treating any single bucket as 'the key zone.'",
    "calibration": "When the model says a team has a 60% chance of winning, does it actually win 60% of the time? This chart shows that relationship. A perfect model follows the dashed line exactly. If our line is above the dashed line, the model is UNDERCONFIDENT (teams win more than expected). Below = overconfident.",
    "best_worst": "Tracks how accurate the model has been when picking each specific team. BEST = teams the model understands well and picks correctly often. WORST = teams where the model keeps getting it wrong. If your flagged bet is on a WORST team, be extra cautious.",
    "bullpen": "The relief pitchers that come in after the starter. A bad bullpen can blow a lead in the late innings. ERA (Earned Run Average) shows how many runs they give up per 9 innings — lower is better. Under 3.00 is excellent, over 4.50 is a concern.",
    "season_trend": "Shows the model's accuracy day by day over the whole season. The blue line is each day's result. The green dashed line smooths it out over 3 days so you can see the trend. The gray dashed line is 50% — anything above that means the model beat a coin flip that day.",
    "clv": "Closing Line Value — did the model find value BEFORE the sharp bettors moved the line? If the model liked a team at +130 and by game time the line moved to +110, the model beat the market. Consistently positive CLV is one of the strongest signs of a real edge.",
}

def deg_to_compass(deg):
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[round(deg / 22.5) % 16]

WIND_IN  = {"N","NNE","NE","ENE"}
WIND_OUT = {"S","SSW","SW","WSW"}

# ── Module-level helpers ────────────────────────────────────────────────────

def fmt_odds(o):
    """Format American odds with explicit + on positives."""
    try:
        o = int(float(o))
        return f"+{o}" if o > 0 else str(o)
    except:
        return "N/A"

def prob_to_american(p):
    """Convert a 0-100% probability to American odds (no vig)."""
    try:
        p = float(p)
        if p >= 50: return f"-{round((p/(100-p))*100)}"
        else:       return f"+{round(((100-p)/p)*100)}"
    except:
        return "N/A"

def moneyline_win(odds_str):
    """Win amount on a $100 stake at given American odds.
    +180 wins $180.  -200 wins $50.  Returns 100.0 if unparseable."""
    try:
        o = float(odds_str)
        if o > 0:  return o
        else:      return 10000.0 / abs(o)
    except:
        return 100.0

def implied_prob(odds_str):
    """American odds → implied probability %."""
    try:
        o = float(odds_str)
        if o < 0:  return round(abs(o) / (abs(o) + 100) * 100, 1)
        else:      return round(100 / (o + 100) * 100, 1)
    except:
        return None

def pnl_color(v):
    """Green if positive, red if negative, gray if zero."""
    if v > 0:  return "#00d97e"
    if v < 0:  return "#ef4444"
    return "#64748b"

def pnl_str(v):
    """Format P&L as +$X or -$X."""
    if v >= 0: return f"+${v:.0f}"
    return f"-${abs(v):.0f}"

# ── Styling ─────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Barlow+Condensed:wght@300;400;600;700;800&display=swap');

*, html, body, [class*="css"] { font-family: 'Barlow Condensed', sans-serif; background-color: #080c18; color: #dde3f0; font-size: 1rem; }
.main, .block-container { background-color: #080c18 !important; }
h1,h2,h3 { font-family: 'Space Mono', monospace !important; }
.card { background: linear-gradient(145deg, #0f1628 0%, #0a1020 100%); border: 1px solid #1c2540; border-radius: 10px; padding: 18px 20px; margin-bottom: 10px; }
.bet-card { background: linear-gradient(145deg, #0a2018 0%, #061510 100%); border: 1px solid #166534; border-left: 4px solid #00d97e; border-radius: 10px; padding: 20px; margin-bottom: 14px; }
.weather-card { background: #0a1020; border: 1px solid #1c2540; border-radius: 7px; padding: 10px 14px; margin-bottom: 6px; }
.streak-box { background: #0f1628; border: 1px solid #1c2540; border-radius: 8px; padding: 16px 20px; text-align: center; }
.badge { padding:4px 12px; border-radius:4px; font-size:0.85rem; font-weight:700; letter-spacing:1px; }
.badge-green { background:#166534; color:#00d97e; }
.badge-red { background:#7f1d1d; color:#ef4444; }
.lbl { font-size:0.85rem; color:#64748b; text-transform:uppercase; letter-spacing:1.5px; margin-top:4px; }
.sub { font-size:0.9rem; color:#64748b; }
.mono { font-family:'Space Mono',monospace; }
.stat-pill { display:inline-block; background:#1c2540; border-radius:4px; padding:4px 10px; font-family:'Space Mono',monospace; font-size:0.85rem; margin:2px; }
.sec { font-family:'Space Mono',monospace; font-size:0.75rem; color:#334155; text-transform:uppercase; letter-spacing:2.5px; border-bottom:1px solid #1c2540; padding-bottom:8px; margin:24px 0 16px 0; }
p { font-size:0.95rem !important; }
div[data-testid="stMetricLabel"] { font-size:0.85rem !important; }
div[data-testid="stMetricValue"] { font-size:1.4rem !important; }
.stExpander summary p { font-size:1rem !important; }
.stTabs [data-baseweb="tab"] { font-size:0.85rem !important; }
</style>
""", unsafe_allow_html=True)

def logo_url(team):
    tid = TEAM_IDS.get(team)
    return f"https://www.mlbstatic.com/team-logos/{tid}.svg" if tid else None

def headshot_url(pid):
    base = "https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_213,q_auto:best/v1/people"
    return f"{base}/{pid or 'generic'}/headshot/67/current"

@st.cache_data(ttl=86400, show_spinner=False)
def get_player_id(name):
    try:
        r = requests.get("https://statsapi.mlb.com/api/v1/people/search", params={"names": name.strip(), "sportId": 1}, timeout=5)
        people = r.json().get("people", [])
        if people: return people[0]["id"]
    except: pass
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def get_team_standings(team_id):
    try:
        r = requests.get("https://statsapi.mlb.com/api/v1/standings", params={"leagueId": "103,104", "season": 2026}, timeout=8)
        for record in r.json().get("records", []):
            for tr in record.get("teamRecords", []):
                if tr["team"]["id"] == team_id:
                    w = tr.get("wins", 0); l = tr.get("losses", 0)
                    l10w = l10l = None
                    for split in tr.get("records", {}).get("splitRecords", []):
                        if split.get("type") == "lastTen":
                            l10w = split.get("wins"); l10l = split.get("losses")
                    return w, l, l10w, l10l
    except: pass
    return None, None, None, None

@st.cache_data(ttl=3600, show_spinner=False)
def get_weather(lat, lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={"latitude": lat, "longitude": lon, "current": "windspeed_10m,winddirection_10m,weathercode,temperature_2m", "wind_speed_unit": "mph", "temperature_unit": "fahrenheit", "forecast_days": 1}, timeout=8)
        c = r.json().get("current", {})
        return {"speed": c.get("windspeed_10m", 0), "dir": deg_to_compass(c.get("winddirection_10m", 0)), "temp": c.get("temperature_2m", 0), "code": c.get("weathercode", 0)}
    except: return None

def weather_icon(code):
    if code == 0: return "☀️ Clear"
    if code <= 3: return "⛅ Partly cloudy"
    if code <= 48: return "🌫️ Foggy"
    if code <= 67: return "🌧️ Rain"
    if code <= 77: return "❄️ Snow"
    return "⛈️ Storms"

@st.cache_data(ttl=600, show_spinner=False)
def get_results(date_str):
    try:
        r = requests.get("https://statsapi.mlb.com/api/v1/schedule", params={"sportId": 1, "date": date_str, "hydrate": "linescore"}, timeout=10).json()
        out = {}
        for d in r.get("dates", []):
            for g in d.get("games", []):
                if g.get("status", {}).get("abstractGameState") != "Final": continue
                home = g["teams"]["home"]["team"]["name"]; away = g["teams"]["away"]["team"]["name"]
                hs = g["teams"]["home"].get("score", 0); as_ = g["teams"]["away"].get("score", 0)
                w = home if hs > as_ else away
                rec = {"winner": w, "home_score": hs, "away_score": as_}
                out[home] = rec; out[away] = rec
        return out
    except: return {}

def load_picks(filename):
    try:
        with open(filename, encoding="utf-8-sig") as f: return list(csv.DictReader(f))
    except: return []

def parse_edge(s):
    try: return abs(float(str(s).replace("%","").replace("** BET **","").replace("+","").strip()))
    except: return 0.0

def edge_bucket(e):
    if e < 3: return "0-3%"
    if e < 6: return "3-6%"
    if e < 10: return "6-10%"
    return "10%+"

def load_today():
    lv = timezone(timedelta(hours=-7))
    today_str = datetime.now(lv).strftime("%Y-%m-%d")
    tomorrow_str = (datetime.now(lv) + timedelta(days=1)).strftime("%Y-%m-%d")
    if os.path.exists(f"picks_{tomorrow_str}.csv"):
        return load_picks(f"picks_{tomorrow_str}.csv"), tomorrow_str
    return load_picks(f"picks_{today_str}.csv"), today_str

@st.cache_data(ttl=300, show_spinner=False)
def load_season():
    files = sorted(glob("picks_2026-*.csv"))
    total = correct = flagged = flag_correct = 0
    # Full model P&L — across ALL flagged bets (not just 6-10% zone)
    model_pnl = 0.0
    # If-bet-on-all baseline — if you flat-bet every model pick
    all_bets_pnl = 0.0
    all_bets_count = 0
    all_bets_wins = 0
    # Per-edge-bucket diagnostic
    edge_buckets = {"0-3%":[0,0], "3-6%":[0,0], "6-10%":[0,0], "10%+":[0,0]}
    daily = []; all_picks = []; bullpen_latest = {}
    team_stats = defaultdict(lambda: {"total": 0, "correct": 0})
    calib_bins = defaultdict(lambda: [0, 0])
    mae_errors = []; mae_flagged_errors = []

    for fn in files:
        date_str = fn.replace("picks_","").replace(".csv","")
        if DASHBOARD_START_DATE and date_str < DASHBOARD_START_DATE:
            continue
        picks = load_picks(fn)
        if not picks: continue
        results = get_results(date_str)
        if not results: continue
        day_total = day_correct = day_flagged = day_flag_correct = 0
        day_pnl = 0.0   # NEW — P&L for this day's flagged bets
        day_all_pnl = 0.0  # NEW — what every pick would have made
        day_games = []

        for p in picks:
            away = p.get("Away",""); home = p.get("Home","")
            ap = p.get("Model Away%","None"); hp = p.get("Model Home%","None")
            flag = p.get("Flag","")
            try: bullpen_latest[away] = float(p.get("Away BP ERA(7d)",""))
            except: pass
            try: bullpen_latest[home] = float(p.get("Home BP ERA(7d)",""))
            except: pass
            if ap in ("None","N/A") or hp in ("None","N/A"): continue
            try: apf = float(ap); hpf = float(hp)
            except: continue
            result = results.get(home) or results.get(away)
            if not result: continue
            winner = result["winner"]; model_pick = away if apf > hpf else home
            won = model_pick == winner; hs = result.get("home_score", 0); as_ = result.get("away_score", 0)
            picked_home = (hpf > apf)
            total += 1; day_total += 1
            if won: correct += 1; day_correct += 1
            team_stats[model_pick]["total"] += 1
            if won: team_stats[model_pick]["correct"] += 1
            conf = max(apf, hpf); bk = int(conf // 5) * 5
            calib_bins[bk][0] += 1
            if won: calib_bins[bk][1] += 1

            # Compute the per-pick P&L using real moneyline odds
            odds_col = "DK Home Odds" if picked_home else "DK Away Odds"
            pick_odds = p.get(odds_col, "")
            if won:
                pick_pnl = moneyline_win(pick_odds)
            else:
                pick_pnl = -100

            # If-bet-on-all baseline: every pick counts, win or lose
            all_bets_count += 1
            all_bets_pnl += pick_pnl
            day_all_pnl += pick_pnl
            if won: all_bets_wins += 1

            is_flagged = "BET" in str(flag)
            if is_flagged:
                flagged += 1; day_flagged += 1
                model_pnl += pick_pnl
                day_pnl += pick_pnl
                if won: flag_correct += 1; day_flag_correct += 1

            # Use the edge column matching the side the model picked
            edge_col = "DK Edge Home" if picked_home else "DK Edge Away"
            e = parse_edge(p.get(edge_col, ""))
            b = edge_bucket(e)
            edge_buckets[b][0] += 1
            if won: edge_buckets[b][1] += 1

            # MAE — distance between model confidence and true outcome
            model_prob = max(apf, hpf)
            true_outcome = 100.0 if won else 0.0
            abs_error = abs(model_prob - true_outcome)
            mae_errors.append(abs_error)
            if is_flagged: mae_flagged_errors.append(abs_error)

            g_rec = {
                "away": away, "home": home, "away_prob": ap, "home_prob": hp,
                "model_pick": model_pick, "actual_winner": winner, "won": won,
                "score": f"{as_}-{hs}", "flag": is_flagged, "date": date_str,
                "away_sp": p.get("Away SP",""), "home_sp": p.get("Home SP",""),
                "pnl": pick_pnl,                  # per-pick P&L on $100 stake
                "odds": pick_odds,                # the actual odds taken
                "picked_home": picked_home,
            }
            day_games.append(g_rec); all_picks.append(g_rec)

        if day_total > 0:
            daily.append({
                "date": date_str, "total": day_total, "correct": day_correct,
                "pct": day_correct/day_total*100,
                "flagged": day_flagged, "flag_correct": day_flag_correct,
                "pnl": day_pnl,          # NEW — flagged-bet P&L for the day
                "all_pnl": day_all_pnl,  # NEW — if-bet-all P&L for the day
                "games": day_games,
            })

    streak = 0; streak_type = None
    for g in reversed([g for g in all_picks if g["flag"]]):
        if streak_type is None: streak_type = "W" if g["won"] else "L"; streak = 1
        elif (g["won"] and streak_type=="W") or (not g["won"] and streak_type=="L"): streak += 1
        else: break

    return {
        "total": total, "correct": correct,
        "flagged": flagged, "flag_correct": flag_correct,
        "model_pnl": model_pnl,
        "all_bets_pnl": all_bets_pnl,
        "all_bets_count": all_bets_count,
        "all_bets_wins": all_bets_wins,
        "edge_buckets": edge_buckets,
        "daily": daily, "all_picks": all_picks, "bullpen": bullpen_latest,
        "streak": streak, "streak_type": streak_type,
        "team_stats": dict(team_stats), "calib_bins": dict(calib_bins),
        "mae": round(sum(mae_errors)/len(mae_errors),1) if mae_errors else None,
        "mae_flagged": round(sum(mae_flagged_errors)/len(mae_flagged_errors),1) if mae_flagged_errors else None,
    }

# Pull avg CLV from log for the headline tile
def get_avg_clv_flagged():
    try:
        with open("clv_log.json") as f:
            clv_log = json.load(f)
        flagged_clv = [e["clv"] for e in clv_log if e.get("flagged") and e.get("clv") is not None]
        if flagged_clv:
            return round(sum(flagged_clv) / len(flagged_clv), 2), len(flagged_clv)
    except: pass
    return None, 0

# ── HEADER
col_title, col_refresh = st.columns([5, 1])
with col_title:
    st.markdown("<div style='padding:20px 0 4px 0'><span style='font-family:Space Mono,monospace;font-size:1.6rem;font-weight:700;color:#3b82f6'>⚾ MLB MODEL</span><span style='font-family:Space Mono,monospace;font-size:1.6rem;color:#1e2940'> // DASHBOARD</span></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='sub'>Updated: {datetime.now().strftime('%b %d, %Y  %I:%M %p')}</div>", unsafe_allow_html=True)
with col_refresh:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear(); st.rerun()

with st.spinner("Loading..."):
    S = load_season()
    todays, today_str = load_today()
    avg_clv_flagged, clv_n = get_avg_clv_flagged()

# ── KPIs — new headline row
st.markdown("<div class='sec'>Season Performance</div>", unsafe_allow_html=True)
overall_pct = S["correct"]/S["total"]*100 if S["total"] else 0
flag_pct    = S["flag_correct"]/S["flagged"]*100 if S["flagged"] else 0
model_roi   = S["model_pnl"]/(S["flagged"]*100)*100 if S["flagged"] else 0

kpi_data = [
    ("Overall Accuracy",
     f"{overall_pct:.1f}%",
     f"{S['correct']}/{S['total']} games",
     "#3b82f6" if overall_pct>=50 else "#ef4444"),

    ("Model P&L",
     pnl_str(S["model_pnl"]),
     f"{S['flagged']} flagged bets · $100 flat",
     pnl_color(S["model_pnl"])),

    ("Model ROI",
     f"{model_roi:+.1f}%",
     f"on ${S['flagged']*100:,} wagered",
     pnl_color(S["model_pnl"])),

    ("Flagged Record",
     f"{S['flag_correct']}-{S['flagged']-S['flag_correct']}",
     f"{flag_pct:.1f}% win rate",
     "#00d97e" if flag_pct>=55 else "#f59e0b" if flag_pct>=47 else "#ef4444"),

    ("Avg CLV",
     f"{avg_clv_flagged:+.2f}%" if avg_clv_flagged is not None else "—",
     f"flagged bets · n={clv_n}" if avg_clv_flagged is not None else "no CLV data yet",
     pnl_color(avg_clv_flagged) if avg_clv_flagged is not None else "#64748b"),
]
kpi_cols = st.columns(5)
for i, (label, value, sub, color) in enumerate(kpi_data):
    with kpi_cols[i]:
        st.markdown(f"<div class='card' style='text-align:center'><div style='font-family:Space Mono,monospace;font-size:1.85rem;font-weight:700;color:{color}'>{value}</div><div class='lbl'>{label}</div><div class='sub'>{sub}</div></div>", unsafe_allow_html=True)
        with st.expander("ℹ️"):
            st.caption(METRIC_TOOLTIPS.get(label,""))

# Footnote about the FADE filter cutover
st.markdown(
    f"<div class='sub' style='font-size:0.72rem;color:#334155;margin-top:-4px;margin-bottom:8px'>"
    f"Note: bets prior to {FADE_FILTER_START_DATE} include FADE games the current filter would now suppress. "
    f"Post-filter window is the cleaner read of model performance going forward."
    f"</div>",
    unsafe_allow_html=True
)

# ── IF BET ON ALL GAMES — sanity check
st.markdown("<br>", unsafe_allow_html=True)
all_pct = S["all_bets_wins"]/S["all_bets_count"]*100 if S["all_bets_count"] else 0
all_roi = S["all_bets_pnl"]/(S["all_bets_count"]*100)*100 if S["all_bets_count"] else 0
ac1, ac2, ac3 = st.columns([1, 3, 1])
with ac2:
    st.markdown(
        f"<div class='card' style='text-align:center;border:1px dashed #334155'>"
        f"<div class='lbl' style='margin-top:0'>📊 If you bet $100 on every model pick (sanity check)</div>"
        f"<div style='display:flex;justify-content:space-around;margin-top:12px'>"
        f"<div><div style='font-family:Space Mono,monospace;font-size:1.4rem;font-weight:700;color:{pnl_color(S['all_bets_pnl'])}'>{pnl_str(S['all_bets_pnl'])}</div><div class='sub'>P&L</div></div>"
        f"<div><div style='font-family:Space Mono,monospace;font-size:1.4rem;font-weight:700;color:{pnl_color(S['all_bets_pnl'])}'>{all_roi:+.1f}%</div><div class='sub'>ROI</div></div>"
        f"<div><div style='font-family:Space Mono,monospace;font-size:1.4rem;font-weight:700;color:#94a3b8'>{S['all_bets_wins']}-{S['all_bets_count']-S['all_bets_wins']}</div><div class='sub'>Record ({all_pct:.1f}%)</div></div>"
        f"</div></div>",
        unsafe_allow_html=True
    )
    with st.expander("ℹ️ What does this tell me?"):
        st.caption(METRIC_TOOLTIPS["If Bet All Games"])

# ── MAE CARDS
if S.get("mae") is not None:
    mae_overall = S["mae"]; mae_flagged = S["mae_flagged"]
    improvement = round(50.0 - mae_overall, 1)
    imp_color = "#00d97e" if improvement > 0 else "#ef4444"
    st.markdown("<br>", unsafe_allow_html=True)
    mc1,mc2,mc3 = st.columns(3)
    with mc1:
        st.markdown(f"<div class='card' style='text-align:center'><div style='font-family:Space Mono,monospace;font-size:1.5rem;font-weight:700;color:#3b82f6'>{mae_overall}</div><div class='lbl'>Overall MAE</div><div class='sub'>lower = more calibrated</div></div>", unsafe_allow_html=True)
        with st.expander("ℹ️"): st.caption(MAE_TOOLTIPS["Overall MAE"])
    with mc2:
        st.markdown(f"<div class='card' style='text-align:center'><div style='font-family:Space Mono,monospace;font-size:1.5rem;font-weight:700;color:#00d97e'>{mae_flagged or '—'}</div><div class='lbl'>Flagged Bet MAE</div><div class='sub'>vs {mae_overall} overall</div></div>", unsafe_allow_html=True)
        with st.expander("ℹ️"): st.caption(MAE_TOOLTIPS["Flagged Bet MAE"])
    with mc3:
        st.markdown(f"<div class='card' style='text-align:center'><div style='font-family:Space Mono,monospace;font-size:1.5rem;font-weight:700;color:{imp_color}'>{improvement:+.1f}</div><div class='lbl'>vs 50% Baseline</div><div class='sub'>{'✅ better' if improvement > 0 else '❌ worse'} than always picking 50%</div></div>", unsafe_allow_html=True)
        with st.expander("ℹ️"): st.caption(MAE_TOOLTIPS["vs 50% Baseline"])

st.markdown("<br>", unsafe_allow_html=True)

# ── STREAK + CONFIDENCE
sc1, sc2 = st.columns([1, 3])
with sc1:
    st.markdown("<div class='sec'>Streak</div>", unsafe_allow_html=True)
    stype = S.get("streak_type"); scount = S.get("streak", 0)
    if stype=="W":   scolor="#00d97e"; slabel=f"🔥 {scount}-game WIN streak"
    elif stype=="L": scolor="#ef4444"; slabel=f"❄️ {scount}-game LOSS streak"
    else:            scolor="#475569"; slabel="No data"
    st.markdown(f"<div class='streak-box'><div style='font-family:Space Mono,monospace;font-size:2.5rem;font-weight:700;color:{scolor}'>{scount}</div><div style='color:{scolor};font-weight:600;font-size:0.9rem;margin-top:4px'>{slabel}</div><div class='sub' style='margin-top:6px'>Flagged bets only</div></div>", unsafe_allow_html=True)

with sc2:
    st.markdown("<div class='sec'>Betting Confidence</div>", unsafe_allow_html=True)
    # Now anchored to overall flagged ROI instead of 6-10% zone specifically
    if S["flagged"] >= 30 and model_roi >= 5:
        cc="#00d97e"; bp2=100; cm=f"✅ READY — {flag_pct:.1f}% record / {model_roi:+.1f}% ROI on {S['flagged']} bets → consider real money"
    elif S["flagged"] >= 20 and model_roi >= 0:
        cc="#f59e0b"; bp2=66; cm=f"🟡 PROMISING — {flag_pct:.1f}% record / {model_roi:+.1f}% ROI on {S['flagged']} bets → paper trade more"
    else:
        cc="#ef4444"; bp2=33; cm=f"🔴 NOT YET — {flag_pct:.1f}% record / {model_roi:+.1f}% ROI on {S['flagged']} bets → need 30+ bets at +ROI"
    st.markdown(f"<div class='card'><div style='font-family:Space Mono,monospace;color:{cc};font-weight:700;font-size:0.95rem;margin-bottom:10px'>{cm}</div><div style='background:#1c2540;border-radius:4px;height:8px'><div style='background:{cc};width:{bp2}%;height:8px;border-radius:4px'></div></div><div style='display:flex;justify-content:space-between;margin-top:5px'><span class='sub'>0%</span><span class='sub'>Target: +5% ROI / 30+ bets</span><span class='sub'>100%</span></div></div>", unsafe_allow_html=True)

# ── PITCHER SCRATCH ALERTS
scratch_file = f"scratches_{today_str}.json"
if os.path.exists(scratch_file):
    try:
        with open(scratch_file) as f:
            scratch_data = json.load(f)
        scratches = scratch_data.get("scratches", [])
        updated = scratch_data.get("updated", "")
        if scratches:
            st.markdown("<div class='sec'>⚠️ Pitcher Scratch Alerts</div>", unsafe_allow_html=True)
            for s in scratches:
                st.markdown(f"""<div class='card' style='border-left:4px solid #ef4444;padding:12px 16px;margin-bottom:8px'>
                    <div style='display:flex;justify-content:space-between;align-items:center'>
                        <div>
                            <div style='color:#ef4444;font-weight:800;font-size:0.85rem;letter-spacing:1px'>⚠️ SCRATCH — {s['team']}</div>
                            <div style='margin-top:4px'><span style='color:#94a3b8;font-size:0.85rem'>Was: </span><span style='color:#ef4444;font-family:Space Mono,monospace;font-size:0.9rem'>{s['original']}</span></div>
                            <div><span style='color:#94a3b8;font-size:0.85rem'>Now: </span><span style='color:#00d97e;font-family:Space Mono,monospace;font-size:0.9rem'>{s['current']}</span></div>
                        </div>
                        <div style='color:#475569;font-size:0.72rem'>Updated {updated}</div>
                    </div>
                </div>""", unsafe_allow_html=True)
    except:
        pass

# ── TODAY'S FLAGGED BETS
st.markdown(f"<div class='sec'>Today's Flagged Bets — {today_str}</div>", unsafe_allow_html=True)

if not todays:
    st.info("No picks file for today. Run master.py first.")
else:
    flagged_today = [p for p in todays if "BET" in str(p.get("Flag",""))]

    if not flagged_today:
        st.markdown("<div class='card' style='text-align:center;color:#475569'>No flagged bets today</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<span class='badge badge-green'>🎯 {len(flagged_today)} FLAGGED BET{'S' if len(flagged_today)>1 else ''}</span><br><br>", unsafe_allow_html=True)

        for pick in flagged_today:
            away=pick.get("Away",""); home=pick.get("Home","")
            ap=pick.get("Model Away%","N/A"); hp=pick.get("Model Home%","N/A")
            away_sp=pick.get("Away SP","—"); home_sp=pick.get("Home SP","—")
            away_rel=pick.get("Away Reliability%",""); home_rel=pick.get("Home Reliability%","")
            sharp=pick.get("Sharp Signal","N/A")
            dk_ea=pick.get("DK Edge Away",""); dk_eh=pick.get("DK Edge Home","")
            lineup=pick.get("Lineup Source","")
            away_bp=pick.get("Away BP ERA(7d)","—"); home_bp=pick.get("Home BP ERA(7d)","—")
            park=pick.get("Park Factor","100")
            away_velo=pick.get("Away SP Velo","") or "—"; home_velo=pick.get("Home SP Velo","") or "—"
            away_spin=pick.get("Away SP Spin","") or "—"; home_spin=pick.get("Home SP Spin","") or "—"
            away_whiff=pick.get("Away SP Whiff","") or "—"; home_whiff=pick.get("Home SP Whiff","") or "—"
            dk_away_odds=pick.get("DK Away Odds","N/A"); dk_home_odds=pick.get("DK Home Odds","N/A")

            try:
                apf=float(ap); hpf=float(hp)
                model_fav=away if apf>hpf else home
                edge=dk_ea if apf>hpf else dk_eh
            except: model_fav=home; edge=dk_eh

            sc="#00d97e" if "CONFIRMED" in str(sharp) else "#ef4444" if "FADE" in str(sharp) else "#475569"
            sl="✓ CONFIRMED SHARP" if "CONFIRMED" in str(sharp) else "✗ FADE" if "FADE" in str(sharp) else "— N/A"

            if "CONFIRMED" in str(lineup): lineup_color="#00d97e"; lineup_label="✅ CONFIRMED LINEUPS"; lineup_sub=""
            elif "PARTIAL" in str(lineup): lineup_color="#f59e0b"; lineup_label="⚠️ PARTIAL LINEUPS"; lineup_sub="Some lineups not yet confirmed"
            else: lineup_color="#3b82f6"; lineup_label="📊 EARLY LEAN"; lineup_sub="Lineups not yet confirmed — model estimate only"

            st.markdown(f"""<div class='bet-card'><div style='display:flex;justify-content:space-between;align-items:flex-start'><div><div style='font-size:0.9rem;font-weight:800;letter-spacing:1px;color:{lineup_color};margin-bottom:2px'>{lineup_label}</div><div style='font-size:0.72rem;color:#475569;margin-bottom:6px'>{lineup_sub}</div><div style='font-size:1.3rem;font-weight:800;color:#f1f5f9'>{away} <span style='color:#1e2940'>@</span> {home} <span style='font-size:0.75rem;color:#475569'>· Park: {park}</span></div></div><div style='text-align:right'><div style='font-family:Space Mono,monospace;font-size:1.3rem;color:#00d97e;font-weight:700'>{edge}</div><div style='color:{sc};font-size:0.75rem;font-weight:700'>{sl}</div></div></div></div>""", unsafe_allow_html=True)

            t1, t2, t3 = st.columns([2, 1, 2])
            with t1:
                logo = logo_url(away)
                if logo:
                    try: st.image(logo, width=56)
                    except: pass
                st.markdown(f"**{away}**")
                st.markdown(f"<div style='font-family:Space Mono,monospace;font-size:1.6rem;color:#3b82f6;font-weight:700'>{ap}% <span style='font-size:1rem;color:#60a5fa'>({prob_to_american(ap)})</span></div><div class='sub'>model prob · model odds</div>", unsafe_allow_html=True)
                away_imp = implied_prob(dk_away_odds)
                if away_imp is not None:
                    st.markdown(f"<div style='font-family:Space Mono,monospace;font-size:0.85rem;color:#94a3b8'>{away_imp}% implied · <span style='color:#f59e0b'>{fmt_odds(dk_away_odds)}</span></div>", unsafe_allow_html=True)
                tid = TEAM_IDS.get(away)
                if tid:
                    w,l,l10w,l10l = get_team_standings(tid)
                    if w is not None: st.markdown(f"<span class='stat-pill'>{w}-{l}</span>", unsafe_allow_html=True)
                    if l10w is not None:
                        c10="#00d97e" if l10w>=6 else "#f59e0b" if l10w>=4 else "#ef4444"
                        st.markdown(f"<span class='stat-pill' style='color:{c10}'>L10: {l10w}-{l10l}</span>", unsafe_allow_html=True)

            with t2:
                # Streak overlay
                away_tid = TEAM_IDS.get(away); home_tid = TEAM_IDS.get(home)
                away_streak = home_streak = ""
                if away_tid:
                    _,_,l10w,l10l = get_team_standings(away_tid)
                    if l10w is not None:
                        if l10w >= 7: away_streak = f"🔥 {l10w}-{l10l} L10"
                        elif l10w <= 3: away_streak = f"❄️ {l10w}-{l10l} L10"
                if home_tid:
                    _,_,l10w,l10l = get_team_standings(home_tid)
                    if l10w is not None:
                        if l10w >= 7: home_streak = f"🔥 {l10w}-{l10l} L10"
                        elif l10w <= 3: home_streak = f"❄️ {l10w}-{l10l} L10"
                streak_html = ""
                if away_streak: streak_html += f"<div style='font-size:0.72rem;margin-top:4px'>{away} {away_streak}</div>"
                if home_streak: streak_html += f"<div style='font-size:0.72rem;margin-top:2px'>{home} {home_streak}</div>"
                st.markdown(f"<div style='text-align:center;padding-top:16px'><div style='color:#1e2940;font-size:1.4rem;font-weight:700'>VS</div><div style='margin-top:10px'><span class='badge badge-green'>PICK: {model_fav}</span></div>{streak_html}</div>", unsafe_allow_html=True)

            with t3:
                logo = logo_url(home)
                if logo:
                    try: st.image(logo, width=56)
                    except: pass
                st.markdown(f"**{home}**")
                st.markdown(f"<div style='font-family:Space Mono,monospace;font-size:1.6rem;color:#3b82f6;font-weight:700'>{hp}% <span style='font-size:1rem;color:#60a5fa'>({prob_to_american(hp)})</span></div><div class='sub'>model prob · model odds</div>", unsafe_allow_html=True)
                home_imp = implied_prob(dk_home_odds)
                if home_imp is not None:
                    st.markdown(f"<div style='font-family:Space Mono,monospace;font-size:0.85rem;color:#94a3b8'>{home_imp}% implied · <span style='color:#f59e0b'>{fmt_odds(dk_home_odds)}</span></div>", unsafe_allow_html=True)
                tid = TEAM_IDS.get(home)
                if tid:
                    w,l,l10w,l10l = get_team_standings(tid)
                    if w is not None: st.markdown(f"<span class='stat-pill'>{w}-{l}</span>", unsafe_allow_html=True)
                    if l10w is not None:
                        c10="#00d97e" if l10w>=6 else "#f59e0b" if l10w>=4 else "#ef4444"
                        st.markdown(f"<span class='stat-pill' style='color:{c10}'>L10: {l10w}-{l10l}</span>", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            p_col1, p_col2 = st.columns(2)
            for col, sp, rel, bp, velo, spin, whiff, lbl in [
                (p_col1, away_sp, away_rel, away_bp, away_velo, away_spin, away_whiff, "Away SP"),
                (p_col2, home_sp, home_rel, home_bp, home_velo, home_spin, home_whiff, "Home SP"),
            ]:
                with col:
                    pid = get_player_id(sp) if sp not in ("—","TBD","","None") else None
                    hc1, hc2 = st.columns([1, 3])
                    with hc1:
                        try: st.image(headshot_url(pid), width=56)
                        except: pass
                    with hc2:
                        try: rc = float(str(rel).replace("%",""))
                        except: rc = 0
                        rcol = "#00d97e" if rc>=15 else "#f59e0b" if rc>=8 else "#ef4444"
                        st.markdown(f"<div style='font-weight:700;font-size:0.95rem'>{sp}</div><div class='sub'>{lbl} · <span style='color:{rcol}'>{rel} reliability</span></div>", unsafe_allow_html=True)
                    with st.expander(f"📊 {sp} Pitch Stats"):
                        m1,m2,m3,m4 = st.columns(4)
                        m1.metric("Velo", f"{velo}" if velo != "—" else "N/A")
                        m2.metric("Spin", f"{spin}" if spin != "—" else "N/A")
                        m3.metric("Whiff%", f"{whiff}%" if whiff != "—" else "N/A")
                        m4.metric("BP ERA", bp)
                        st.caption(f"Reliability {rel}: how much of this season's data the model has. Higher = more confident estimate.")

            coords = PARK_COORDS.get(home)
            if coords:
                wx = get_weather(*coords)
                if wx:
                    spd=wx["speed"]; dirn=wx["dir"]
                    if dirn in WIND_IN: wx_icon="🔴"; wx_note=f"Wind IN — {spd:.0f}mph {dirn} — suppresses offense"
                    elif dirn in WIND_OUT: wx_icon="🟢"; wx_note=f"Wind OUT — {spd:.0f}mph {dirn} — favors hitters"
                    elif spd < 7: wx_icon="⚪"; wx_note=f"Calm winds — {spd:.0f}mph"
                    else: wx_icon="🟡"; wx_note=f"Cross wind — {spd:.0f}mph {dirn}"
                    st.markdown(f"<div class='weather-card' style='margin-top:10px;display:flex;justify-content:space-between;align-items:center'><span style='font-weight:700;color:#93c5fd'>🌤️ {home.split()[-1]} Weather</span><span>{wx_icon} {wx_note}</span><span class='sub'>{wx['temp']:.0f}°F · {weather_icon(wx['code'])}</span></div>", unsafe_allow_html=True)

            st.markdown("<hr style='border-color:#1c2540;margin:20px 0'>", unsafe_allow_html=True)

    # ── All games clickable
    with st.expander(f"All {len(todays)} Games Today — Click Any to Expand"):
        # Mini legend so coworkers know what symbols mean without asking
        st.markdown(
            "<div class='sub' style='font-size:0.72rem;color:#475569;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #1c2540'>"
            "🎯 = BET-flagged (model has 6-10% edge & passes filters) · "
            f"⭐ = pick is in best historical bucket ({WINNING_EDGE_BUCKET} edge, 64% accurate on 103 games) · "
            "Edge bucket shown next to each game"
            "</div>",
            unsafe_allow_html=True
        )
        for pick in todays:
            away=pick.get("Away",""); home=pick.get("Home","")
            ap=pick.get("Model Away%","N/A"); hp=pick.get("Model Home%","N/A")
            sharp=pick.get("Sharp Signal","N/A")
            flag="BET" in str(pick.get("Flag",""))
            lineup=pick.get("Lineup Source","")
            away_sp=pick.get("Away SP","—"); home_sp=pick.get("Home SP","—")
            away_rel=pick.get("Away Reliability%",""); home_rel=pick.get("Home Reliability%","")
            away_bp=pick.get("Away BP ERA(7d)","—"); home_bp=pick.get("Home BP ERA(7d)","—")
            away_velo=pick.get("Away SP Velo","") or "—"; home_velo=pick.get("Home SP Velo","") or "—"
            away_whiff=pick.get("Away SP Whiff","") or "—"; home_whiff=pick.get("Home SP Whiff","") or "—"
            park=pick.get("Park Factor","100")
            dk_ea=pick.get("DK Edge Away","N/A"); dk_eh=pick.get("DK Edge Home","N/A")
            dk_away_odds=pick.get("DK Away Odds","N/A"); dk_home_odds=pick.get("DK Home Odds","N/A")
            mgm_away_odds=pick.get("MGM Away Odds","N/A"); mgm_home_odds=pick.get("MGM Home Odds","N/A")
            away_move=pick.get("Away Line Move",""); home_move=pick.get("Home Line Move","")
            sc="#00d97e" if "CONFIRMED" in str(sharp) else "#ef4444" if "FADE" in str(sharp) else "#475569"

            # ── Compute who the model picks + which edge bucket it falls into ──
            # The "model pick" is whichever side has the higher probability.
            # The "edge" is on that side specifically (matching column).
            model_pick = None
            model_edge_str = "—"
            model_bucket = None
            try:
                apf = float(ap); hpf = float(hp)
                if apf > hpf:
                    model_pick = away
                    model_edge_str = dk_ea
                else:
                    model_pick = home
                    model_edge_str = dk_eh
                edge_num = parse_edge(model_edge_str)
                model_bucket = edge_bucket(edge_num) if edge_num > 0 else None
            except:
                pass

            # ⭐ if the pick is in the historically best-performing bucket
            star = "⭐ " if model_bucket == WINNING_EDGE_BUCKET else ""
            flag_txt = "🎯 " if flag else ""

            # Build a short pick label (last word of team name for compactness)
            pick_label = model_pick.split()[-1] if model_pick else "—"

            # Build the expander title — leads with PICK so coworkers see it immediately
            if model_pick:
                title = (
                    f"{flag_txt}{star}PICK: {pick_label} ({model_edge_str}) · "
                    f"{away} ({fmt_odds(dk_away_odds)}) @ {home} ({fmt_odds(dk_home_odds)}) · "
                    f"Sharp: {sharp}"
                )
            else:
                # Fallback for N/A games (pitcher lookup failures etc)
                title = (
                    f"{flag_txt}{away} ({fmt_odds(dk_away_odds)}) @ "
                    f"{home} ({fmt_odds(dk_home_odds)}) · PICK: N/A · Sharp: {sharp}"
                )

            with st.expander(title):
                c1, c2, c3 = st.columns(3)
                with c1:
                    logo=logo_url(away)
                    if logo:
                        try: st.image(logo, width=40)
                        except: pass
                    st.markdown(f"**{away}**")
                    st.markdown(f"<div style='font-family:Space Mono,monospace;font-size:1.5rem;color:#3b82f6;font-weight:700'>{ap}% <span style='font-size:1rem;color:#60a5fa'>({prob_to_american(ap)})</span></div><div class='sub'>model prob · model odds</div>", unsafe_allow_html=True)
                    away_imp = implied_prob(dk_away_odds)
                    if away_imp is not None:
                        st.markdown(f"<div style='font-family:Space Mono,monospace;font-size:0.85rem;color:#94a3b8'>{away_imp}% implied · <span style='color:#f59e0b'>{fmt_odds(dk_away_odds)}</span></div>", unsafe_allow_html=True)
                    if away_move not in ("","N/A","0"):
                        try:
                            mv=float(away_move)
                            mc="#00d97e" if mv>0 else "#ef4444"
                            st.markdown(f"<span class='stat-pill' style='color:{mc}'>Line: {mv:+.1f}%</span>", unsafe_allow_html=True)
                        except: pass
                    tid=TEAM_IDS.get(away)
                    if tid:
                        w,l,l10w,l10l=get_team_standings(tid)
                        if w is not None: st.markdown(f"<span class='stat-pill'>{w}-{l}</span>", unsafe_allow_html=True)
                        if l10w is not None:
                            c10="#00d97e" if l10w>=6 else "#f59e0b" if l10w>=4 else "#ef4444"
                            st.markdown(f"<span class='stat-pill' style='color:{c10}'>L10: {l10w}-{l10l}</span>", unsafe_allow_html=True)

                with c2:
                    # New: prominent MODEL PICK badge first, then context.
                    # Pick badge is always shown (whether flagged or not), so coworkers
                    # don't need anyone to explain which side the model likes.
                    if model_pick:
                        pick_badge_color = "#166534" if flag else "#1e3a8a"
                        pick_text_color = "#00d97e" if flag else "#60a5fa"
                        bucket_label = f" · {model_bucket} edge" if model_bucket else ""
                        star_in_badge = "⭐ " if star else ""
                        st.markdown(
                            f"<div style='text-align:center;padding-top:4px'>"
                            f"<div style='color:#334155;font-size:1rem;font-weight:700'>VS</div>"
                            f"<div style='margin-top:8px;background:{pick_badge_color};border-radius:6px;padding:8px 10px;border:1px solid {pick_text_color}'>"
                            f"<div style='color:#94a3b8;font-size:0.65rem;letter-spacing:1.5px;font-weight:700'>{star_in_badge}MODEL PICK</div>"
                            f"<div style='color:{pick_text_color};font-size:1rem;font-weight:800;margin-top:2px'>{model_pick}</div>"
                            f"<div style='color:#94a3b8;font-size:0.7rem;margin-top:2px'>{model_edge_str}{bucket_label}</div>"
                            f"</div>"
                            f"<div style='margin-top:8px;color:{sc};font-size:0.8rem;font-weight:700'>{sharp}</div>"
                            f"<div style='margin-top:4px;font-size:0.7rem;color:#475569'>{lineup}</div>"
                            f"<div style='font-size:0.7rem;color:#475569'>Park: {park}</div>"
                            f"</div>",
                            unsafe_allow_html=True
                        )
                    else:
                        # N/A game fallback — no pick to show
                        st.markdown(
                            f"<div style='text-align:center;padding-top:8px'>"
                            f"<div style='color:#334155;font-size:1rem;font-weight:700'>VS</div>"
                            f"<div style='margin-top:8px;background:#1c2540;border-radius:6px;padding:6px 10px'>"
                            f"<div style='color:#64748b;font-size:0.72rem;font-weight:700'>PICK: N/A — pitcher data missing</div>"
                            f"</div>"
                            f"<div style='margin-top:8px;color:{sc};font-size:0.8rem;font-weight:700'>{sharp}</div>"
                            f"<div style='margin-top:4px;font-size:0.7rem;color:#475569'>{lineup}</div>"
                            f"<div style='font-size:0.7rem;color:#475569'>Park: {park}</div>"
                            f"</div>",
                            unsafe_allow_html=True
                        )

                with c3:
                    logo=logo_url(home)
                    if logo:
                        try: st.image(logo, width=40)
                        except: pass
                    st.markdown(f"**{home}**")
                    st.markdown(f"<div style='font-family:Space Mono,monospace;font-size:1.5rem;color:#3b82f6;font-weight:700'>{hp}% <span style='font-size:1rem;color:#60a5fa'>({prob_to_american(hp)})</span></div><div class='sub'>model prob · model odds</div>", unsafe_allow_html=True)
                    home_imp = implied_prob(dk_home_odds)
                    if home_imp is not None:
                        st.markdown(f"<div style='font-family:Space Mono,monospace;font-size:0.85rem;color:#94a3b8'>{home_imp}% implied · <span style='color:#f59e0b'>{fmt_odds(dk_home_odds)}</span></div>", unsafe_allow_html=True)
                    if home_move not in ("","N/A","0"):
                        try:
                            mv=float(home_move)
                            mc="#00d97e" if mv>0 else "#ef4444"
                            st.markdown(f"<span class='stat-pill' style='color:{mc}'>Line: {mv:+.1f}%</span>", unsafe_allow_html=True)
                        except: pass
                    tid=TEAM_IDS.get(home)
                    if tid:
                        w,l,l10w,l10l=get_team_standings(tid)
                        if w is not None: st.markdown(f"<span class='stat-pill'>{w}-{l}</span>", unsafe_allow_html=True)
                        if l10w is not None:
                            c10="#00d97e" if l10w>=6 else "#f59e0b" if l10w>=4 else "#ef4444"
                            st.markdown(f"<span class='stat-pill' style='color:{c10}'>L10: {l10w}-{l10l}</span>", unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                p1, p2 = st.columns(2)
                for col, sp, rel, bp, velo, whiff, lbl in [(p1,away_sp,away_rel,away_bp,away_velo,away_whiff,"Away SP"),(p2,home_sp,home_rel,home_bp,home_velo,home_whiff,"Home SP")]:
                    with col:
                        try: rc=float(str(rel).replace("%",""))
                        except: rc=0
                        rcol="#00d97e" if rc>=15 else "#f59e0b" if rc>=8 else "#ef4444"
                        st.markdown(f"<div style='font-weight:700'>{sp}</div><div class='sub'>{lbl} · <span style='color:{rcol}'>{rel} rel</span> · Velo: {velo} · Whiff: {whiff}% · BP ERA: {bp}</div>", unsafe_allow_html=True)

                coords=PARK_COORDS.get(home)
                if coords:
                    wx=get_weather(*coords)
                    if wx:
                        spd=wx["speed"]; dirn=wx["dir"]
                        if dirn in WIND_IN: wi="🔴"; wn=f"Wind IN {spd:.0f}mph {dirn}"
                        elif dirn in WIND_OUT: wi="🟢"; wn=f"Wind OUT {spd:.0f}mph {dirn}"
                        elif spd<7: wi="⚪"; wn=f"Calm {spd:.0f}mph"
                        else: wi="🟡"; wn=f"Cross {spd:.0f}mph {dirn}"
                        st.markdown(f"<div class='sub' style='margin-top:6px'>{wi} {wn} · {wx['temp']:.0f}°F · {weather_icon(wx['code'])}</div>", unsafe_allow_html=True)

# ── WEATHER BOARD
if todays:
    st.markdown("<div class='sec'>Today's Ballpark Weather</div>", unsafe_allow_html=True)
    wx_cols=st.columns(4); shown=set(); idx=0
    for pick in todays:
        home=pick.get("Home","")
        if home in shown: continue
        shown.add(home)
        coords=PARK_COORDS.get(home)
        if not coords: continue
        wx=get_weather(*coords)
        if not wx: continue
        spd=wx["speed"]; dirn=wx["dir"]
        if dirn in WIND_IN: icon="🔴"; note="Wind IN"
        elif dirn in WIND_OUT: icon="🟢"; note="Wind OUT"
        elif spd<7: icon="⚪"; note="Calm"
        else: icon="🟡"; note="Cross"
        with wx_cols[idx%4]:
            st.markdown(f"<div class='weather-card'><div style='font-weight:700;font-size:0.82rem'>{icon} {home.split()[-1]}</div><div class='sub'>{note} · {spd:.0f}mph {dirn}</div><div class='sub'>{wx['temp']:.0f}°F · {weather_icon(wx['code'])}</div></div>", unsafe_allow_html=True)
        idx+=1

# ── ANALYTICS TABS
st.markdown("<div class='sec'>Model Analytics</div>", unsafe_allow_html=True)
tabs=st.tabs(["📊 Edge Zones","🎯 Calibration","🏆 Best/Worst Teams","🔥 Bullpen","📈 Season Trend","📉 CLV"])

with tabs[0]:
    st.caption(ANALYTICS_DESCRIPTIONS["edge_zones"])
    st.markdown("<br>", unsafe_allow_html=True)
    for bucket,(tot,cor) in S["edge_buckets"].items():
        if tot==0: continue
        pct=cor/tot*100; color="#00d97e" if pct>=58 else "#f59e0b" if pct>=50 else "#ef4444"
        # Sample-size warning if bucket is too small to read confidently
        n_warn = " <span style='color:#f59e0b;font-size:0.7rem'>· small sample</span>" if tot < 20 else ""
        st.markdown(f"<div class='card' style='padding:12px 16px;margin-bottom:8px'><div style='display:flex;justify-content:space-between;margin-bottom:6px'><span style='font-weight:700'>{bucket}{n_warn}</span><span style='font-family:Space Mono,monospace;font-size:1rem;color:{color};font-weight:700'>{pct:.1f}%</span></div><div style='background:#1c2540;border-radius:3px;height:5px'><div style='background:{color};width:{int(pct)}%;height:5px;border-radius:3px'></div></div><div class='sub' style='margin-top:4px'>{cor}/{tot} games</div></div>", unsafe_allow_html=True)

with tabs[1]:
    st.caption(ANALYTICS_DESCRIPTIONS["calibration"])
    st.markdown("<br>", unsafe_allow_html=True)
    rows=[]
    for bk in sorted(S["calib_bins"].keys()):
        tot,cor=S["calib_bins"][bk]
        if tot>=10: rows.append({"Label":f"{bk}-{bk+5}%","Model %":bk+2.5,"Actual %":round(cor/tot*100,1),"n":tot})
    if rows:
        df_cal=pd.DataFrame(rows)
        df_perf=pd.DataFrame({"x":[35,40,45,50,55,60,65,70],"y":[35,40,45,50,55,60,65,70]})
        line_perf=alt.Chart(df_perf).mark_line(color="#334155",strokeDash=[4,2]).encode(x=alt.X("x:Q",scale=alt.Scale(domain=[35,70]),title="Model Confidence %",axis=alt.Axis(labelColor="#475569",gridColor="#1c2540")),y=alt.Y("y:Q",scale=alt.Scale(domain=[20,85]),title="Actual Win %",axis=alt.Axis(labelColor="#475569",gridColor="#1c2540")))
        line_act=alt.Chart(df_cal).mark_line(color="#3b82f6",strokeWidth=2).encode(x="Model %:Q",y="Actual %:Q")
        dots=alt.Chart(df_cal).mark_circle(size=80,color="#00d97e").encode(x="Model %:Q",y="Actual %:Q",tooltip=["Label","Actual %:Q","n:Q"])
        st.altair_chart((line_perf+line_act+dots).properties(height=260,background="#080c18").configure_view(strokeOpacity=0),use_container_width=True)
    else:
        st.caption("Need more graded games (10+ per bin).")

with tabs[2]:
    st.caption(ANALYTICS_DESCRIPTIONS["best_worst"])
    st.markdown("<br>", unsafe_allow_html=True)
    ts=S["team_stats"]
    team_rows=[{"Team":t,"W":r["correct"],"L":r["total"]-r["correct"],"Pct":round(r["correct"]/r["total"]*100,1)} for t,r in ts.items() if r["total"]>=10]
    if team_rows:
        df_t=pd.DataFrame(team_rows).sort_values("Pct",ascending=False)
        b_col,w_col=st.columns(2)
        with b_col:
            st.markdown("<div style='color:#00d97e;font-weight:700;margin-bottom:8px'>✅ Best</div>", unsafe_allow_html=True)
            for _,row in df_t.head(8).iterrows():
                c1,c2,c3,c4=st.columns([1,4,2,2])
                with c1:
                    l=logo_url(row["Team"])
                    if l:
                        try: st.image(l,width=22)
                        except: pass
                with c2: st.write(row["Team"].split()[-1])
                with c3: st.write(f"{row['W']}-{row['L']}")
                with c4: st.markdown(f"<span style='font-family:Space Mono,monospace;color:#00d97e;font-weight:700'>{row['Pct']:.0f}%</span>",unsafe_allow_html=True)
        with w_col:
            st.markdown("<div style='color:#ef4444;font-weight:700;margin-bottom:8px'>❌ Worst</div>", unsafe_allow_html=True)
            for _,row in df_t.tail(8).sort_values("Pct").iterrows():
                c1,c2,c3,c4=st.columns([1,4,2,2])
                with c1:
                    l=logo_url(row["Team"])
                    if l:
                        try: st.image(l,width=22)
                        except: pass
                with c2: st.write(row["Team"].split()[-1])
                with c3: st.write(f"{row['W']}-{row['L']}")
                with c4: st.markdown(f"<span style='font-family:Space Mono,monospace;color:#ef4444;font-weight:700'>{row['Pct']:.0f}%</span>",unsafe_allow_html=True)
    else:
        st.caption("Need more graded games (10+ per team).")

with tabs[3]:
    st.caption(ANALYTICS_DESCRIPTIONS["bullpen"])
    st.markdown("<br>", unsafe_allow_html=True)
    bp=S["bullpen"]
    if bp:
        sorted_bp=sorted(bp.items(),key=lambda x:x[1])
        b1,b2=st.columns(2)
        for i,(team,era) in enumerate(sorted_bp):
            col=b1 if i<len(sorted_bp)//2 else b2
            with col:
                color="#00d97e" if era<3.0 else "#f59e0b" if era<4.5 else "#ef4444"
                rc=st.columns([1,1,4,2])
                with rc[0]: st.markdown(f"<span class='sub' style='font-size:0.7rem'>#{i+1}</span>",unsafe_allow_html=True)
                with rc[1]:
                    l=logo_url(team)
                    if l:
                        try: st.image(l,width=20)
                        except: pass
                with rc[2]: st.write(team.split()[-1])
                with rc[3]: st.markdown(f"<span style='font-family:Space Mono,monospace;font-size:0.85rem;font-weight:700;color:{color}'>{era:.2f}</span>",unsafe_allow_html=True)

with tabs[4]:
    st.caption(ANALYTICS_DESCRIPTIONS["season_trend"])
    st.markdown("<br>", unsafe_allow_html=True)
    if len(S["daily"])>=3:
        df_t2=pd.DataFrame([{"date":d["date"],"Accuracy":round(d["pct"],1)} for d in S["daily"]])
        df_t2["date"]=pd.to_datetime(df_t2["date"]); df_t2=df_t2.sort_values("date")
        df_t2["Rolling"]=df_t2["Accuracy"].rolling(3,min_periods=1).mean().round(1)
        base=alt.Chart(df_t2).encode(x=alt.X("date:T",title=None,axis=alt.Axis(format="%b %d",labelColor="#475569",gridColor="#1c2540")))
        rule=alt.Chart(pd.DataFrame({"y":[50]})).mark_rule(color="#334155",strokeDash=[6,3]).encode(y="y:Q")
        st.altair_chart((rule+base.mark_line(color="#3b82f6",strokeWidth=2).encode(y=alt.Y("Accuracy:Q",scale=alt.Scale(domain=[0,100]),axis=alt.Axis(labelColor="#475569",gridColor="#1c2540")))+base.mark_line(color="#00d97e",strokeWidth=1.5,strokeDash=[4,2]).encode(y="Rolling:Q")+base.mark_circle(size=55,color="#3b82f6").encode(y="Accuracy:Q",tooltip=["date:T","Accuracy:Q","Rolling:Q"])).properties(height=240,background="#080c18",title=alt.TitleParams(text="Daily Accuracy · Blue=daily · Green=3-day avg · Gray=50%",color="#475569",fontSize=11)).configure_view(strokeOpacity=0),use_container_width=True)
    else:
        st.caption("Need at least 3 days of data.")

with tabs[5]:
    st.caption(ANALYTICS_DESCRIPTIONS["clv"])
    st.markdown("<br>", unsafe_allow_html=True)
    try:
        with open("clv_log.json") as f:
            clv_log = json.load(f)
        all_clv = [e for e in clv_log if e.get("clv") is not None]
        if all_clv:
            avg_clv = round(sum(e["clv"] for e in all_clv) / len(all_clv), 2)
            pos_clv = sum(1 for e in all_clv if e["clv_positive"])
            flagged_clv = [e for e in all_clv if e.get("flagged")]
            flag_avg = round(sum(e["clv"] for e in flagged_clv) / len(flagged_clv), 2) if flagged_clv else 0
            flag_pos = sum(1 for e in flagged_clv if e["clv_positive"])

            # NEW: Open→Close drift on flagged bets — only entries where opening was captured
            flagged_with_drift = [e for e in flagged_clv if e.get("open_close_drift") is not None]
            drift_avg = round(sum(e["open_close_drift"] for e in flagged_with_drift) / len(flagged_with_drift), 2) if flagged_with_drift else None

            # 5 KPI tiles now — adds Open→Close drift card
            m1,m2,m3,m4,m5 = st.columns(5)
            clv_color = "#00d97e" if avg_clv >= 0 else "#ef4444"
            flag_clv_color = "#00d97e" if flag_avg >= 0 else "#ef4444"
            drift_color = "#00d97e" if drift_avg is not None and drift_avg >= 0 else ("#ef4444" if drift_avg is not None else "#64748b")
            drift_val = f"{drift_avg:+.2f}%" if drift_avg is not None else "—"
            drift_sub = f"flagged · n={len(flagged_with_drift)}" if drift_avg is not None else "needs opening data"

            m1.markdown(f"<div class='card' style='text-align:center'><div style='font-family:Space Mono,monospace;font-size:1.4rem;font-weight:700;color:{clv_color}'>{avg_clv:+.2f}%</div><div class='lbl'>Avg CLV All</div></div>", unsafe_allow_html=True)
            m2.markdown(f"<div class='card' style='text-align:center'><div style='font-family:Space Mono,monospace;font-size:1.4rem;font-weight:700;color:{flag_clv_color}'>{flag_avg:+.2f}%</div><div class='lbl'>Avg CLV Flagged</div></div>", unsafe_allow_html=True)
            m3.markdown(f"<div class='card' style='text-align:center'><div style='font-family:Space Mono,monospace;font-size:1.4rem;font-weight:700;color:{drift_color}'>{drift_val}</div><div class='lbl'>Open→Close Drift</div><div class='sub' style='font-size:0.72rem'>{drift_sub}</div></div>", unsafe_allow_html=True)
            m4.markdown(f"<div class='card' style='text-align:center'><div style='font-family:Space Mono,monospace;font-size:1.4rem;font-weight:700;color:#3b82f6'>{pos_clv}/{len(all_clv)}</div><div class='lbl'>Beat Close</div></div>", unsafe_allow_html=True)
            m5.markdown(f"<div class='card' style='text-align:center'><div style='font-family:Space Mono,monospace;font-size:1.4rem;font-weight:700;color:#3b82f6'>{flag_pos}/{len(flagged_clv)}</div><div class='lbl'>Flagged Beat Close</div></div>", unsafe_allow_html=True)

            # Helper text for the new drift metric
            st.markdown(
                "<div class='sub' style='font-size:0.72rem;color:#334155;margin-top:-2px;margin-bottom:10px'>"
                "Open→Close drift = how the market moved from opening to closing on the model's pick. "
                "Positive = market moved toward your pick (sharps confirming the model). Negative = sharps faded you."
                "</div>",
                unsafe_allow_html=True
            )

            st.markdown("<br>", unsafe_allow_html=True)

            daily_clv = {}
            for e in all_clv:
                d = e["date"]
                if d not in daily_clv:
                    daily_clv[d] = []
                daily_clv[d].append(e["clv"])
            clv_rows = [{"date": d, "Avg CLV": round(sum(v)/len(v), 2)} for d,v in sorted(daily_clv.items())]
            if len(clv_rows) >= 2:
                df_clv = pd.DataFrame(clv_rows)
                df_clv["date"] = pd.to_datetime(df_clv["date"])
                zero_rule = alt.Chart(pd.DataFrame({"y":[0]})).mark_rule(color="#334155", strokeDash=[4,2]).encode(y="y:Q")
                clv_bars = alt.Chart(df_clv).mark_bar().encode(
                    x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d", labelColor="#475569")),
                    y=alt.Y("Avg CLV:Q", title="Avg CLV %", axis=alt.Axis(labelColor="#475569", gridColor="#1c2540")),
                    color=alt.condition(alt.datum["Avg CLV"] >= 0, alt.value("#00d97e"), alt.value("#ef4444")),
                    tooltip=["date:T", "Avg CLV:Q"]
                )
                st.altair_chart((zero_rule+clv_bars).properties(height=200, background="#080c18", title=alt.TitleParams(text="Daily Avg CLV — Green = beat closing line", color="#475569", fontSize=11)).configure_view(strokeOpacity=0), use_container_width=True)

            st.markdown("<div style='font-size:0.75rem;color:#475569;margin-bottom:8px'>RECENT CLV BY GAME — Model → Open → Close</div>", unsafe_allow_html=True)
            for e in reversed(all_clv[-20:]):
                clv_val = e["clv"]
                clv_c = "#00d97e" if clv_val >= 0 else "#ef4444"
                flag_txt = "🎯 " if e.get("flagged") else ""
                won_txt = "✓" if e.get("won") else "✗"
                won_c = "#00d97e" if e.get("won") else "#ef4444"

                # Build the price-journey snippet with graceful fallback when opening is missing.
                # Entries logged before this patch went live won't have opening_implied — show "—"
                # instead of erroring out, so the existing 88 entries still render.
                open_imp = e.get("opening_implied")
                close_imp = e.get("closing_implied")
                drift = e.get("open_close_drift")
                if open_imp is not None and drift is not None:
                    drift_c = "#00d97e" if drift >= 0 else "#ef4444"
                    journey = (
                        f"Model: <span style='color:#3b82f6'>{e['model_prob']}%</span> · "
                        f"Open: <span style='color:#94a3b8'>{open_imp}%</span> · "
                        f"Close: <span style='color:#f59e0b'>{close_imp}%</span> · "
                        f"Δ: <span style='color:{drift_c};font-weight:700'>{drift:+.1f}%</span> · "
                        f"CLV: <span style='color:{clv_c};font-weight:700'>{clv_val:+.1f}%</span> · "
                        f"<span style='color:{won_c}'>{won_txt}</span>"
                    )
                else:
                    journey = (
                        f"Model: <span style='color:#3b82f6'>{e['model_prob']}%</span> · "
                        f"Open: <span style='color:#475569'>—</span> · "
                        f"Close: <span style='color:#f59e0b'>{close_imp}%</span> · "
                        f"CLV: <span style='color:{clv_c};font-weight:700'>{clv_val:+.1f}%</span> · "
                        f"<span style='color:{won_c}'>{won_txt}</span>"
                    )

                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1c2540;font-size:0.8rem'>"
                    f"<span style='color:#94a3b8'>{e['date']} · {flag_txt}{e['away']} @ {e['home']}</span>"
                    f"<span>{journey}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )
        else:
            st.caption("No CLV data yet — runs automatically after tonight's check_results.py")
    except:
        st.caption("No CLV data yet — runs automatically after tonight's check_results.py")

# ── DAILY RECORD — now with per-day P&L and per-game P&L
st.markdown("<div class='sec'>Daily Record</div>", unsafe_allow_html=True)
for d in reversed(S["daily"][-12:]):
    flag_txt=f"{d['flag_correct']}/{d['flagged']}" if d["flagged"] else "—"
    day_pnl = d.get("pnl", 0)
    day_pnl_str = pnl_str(day_pnl) if d["flagged"] else "—"
    day_pnl_c = pnl_color(day_pnl)
    # Show daily P&L in the expander header
    pnl_header = f"  · <span style='color:{day_pnl_c};font-weight:700'>{day_pnl_str}</span>" if d["flagged"] else ""
    # Streamlit expanders don't render HTML in their title, so fall back to plain text
    header_plain = f"{d['date']}   {d['correct']}/{d['total']} ({d['pct']:.0f}%)   Flags: {flag_txt}   P&L: {day_pnl_str}"
    with st.expander(header_plain):
        # All-bets-on-this-day P&L summary line up top
        all_day_pnl = d.get("all_pnl", 0)
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;padding:6px 0 10px 0;border-bottom:1px solid #1c2540;margin-bottom:8px'>"
            f"<span class='sub'>Flagged-bet P&L: <span style='color:{day_pnl_c};font-weight:700'>{day_pnl_str}</span> ({d['flagged']} bets)</span>"
            f"<span class='sub'>If-bet-all P&L: <span style='color:{pnl_color(all_day_pnl)};font-weight:700'>{pnl_str(all_day_pnl)}</span> ({d['total']} picks)</span>"
            f"</div>",
            unsafe_allow_html=True
        )
        for g in d.get("games",[]):
            away=g["away"]; home=g["home"]; winner=g["actual_winner"]
            away_bold=f"**{away}**" if winner==away else away
            home_bold=f"**{home}**" if winner==home else home
            flag_badge=" 🎯" if g["flag"] else ""
            game_pnl = g.get("pnl", 0)
            game_pnl_c = pnl_color(game_pnl)
            # Only display P&L next to flagged games — clutter-free for the rest
            pnl_disp = f"<span style='color:{game_pnl_c};font-family:Space Mono,monospace;font-weight:700'>{pnl_str(game_pnl)}</span>" if g["flag"] else "<span class='sub'>—</span>"
            cols=st.columns([1,1,3,1,2,1,1])
            for ci,team in [(0,away),(1,home)]:
                with cols[ci]:
                    l=logo_url(team)
                    if l:
                        try: st.image(l,width=22)
                        except: pass
            with cols[2]: st.write(f"{away_bold} @ {home_bold}{flag_badge}")
            with cols[3]: st.write(g["score"])
            with cols[4]: st.write(f"{g['away_prob']}% / {g['home_prob']}%")
            with cols[5]: st.markdown(pnl_disp, unsafe_allow_html=True)
            with cols[6]:
                if g["won"]: st.success("✓")
                else: st.error("✗")

# ── SEARCH
st.markdown("<div class='sec'>Pick History Search</div>", unsafe_allow_html=True)
search=st.text_input("Search by team or pitcher",placeholder="e.g. Cardinals, Rays, Glasnow...")
if search and len(search)>=2:
    q=search.lower()
    hits=[g for g in S["all_picks"] if q in g.get("away","").lower() or q in g.get("home","").lower() or q in g.get("away_sp","").lower() or q in g.get("home_sp","").lower()]
    if hits:
        wins=sum(1 for h in hits if h["won"])
        flagged_hits = [h for h in hits if h["flag"]]
        hit_pnl = sum(h.get("pnl", 0) for h in flagged_hits)
        st.markdown(f"<div class='sub' style='margin-bottom:8px'>{len(hits)} results · Record: {wins}/{len(hits)} ({wins/len(hits)*100:.1f}%) · Flagged P&L: <span style='color:{pnl_color(hit_pnl)}'>{pnl_str(hit_pnl)}</span> ({len(flagged_hits)} bets)</div>",unsafe_allow_html=True)
        for g in reversed(hits[-20:]):
            flag=" 🎯" if g["flag"] else ""
            game_pnl = g.get("pnl", 0)
            pnl_disp = f"<span style='color:{pnl_color(game_pnl)};font-family:Space Mono,monospace;font-weight:700;font-size:0.85rem'>{pnl_str(game_pnl)}</span>" if g["flag"] else ""
            cols=st.columns([1,1,4,2,1,1])
            for ci,team in [(0,g["away"]),(1,g["home"])]:
                with cols[ci]:
                    l=logo_url(team)
                    if l:
                        try: st.image(l,width=22)
                        except: pass
            with cols[2]: st.write(f"**{g['date']}** — {g['away']} @ {g['home']}{flag}")
            with cols[3]: st.write(f"{g['score']} | Pick: {g['model_pick']}")
            with cols[4]: st.markdown(pnl_disp, unsafe_allow_html=True)
            with cols[5]:
                if g["won"]: st.success("✓")
                else: st.error("✗")
    else:
        st.caption(f"No results for '{search}'")

_filter_note = f"<br><span class='sub' style='font-size:0.7rem;color:#334155'>Dashboard showing picks from {DASHBOARD_START_DATE} onward (logs unchanged) · FADE filter live from {FADE_FILTER_START_DATE}</span>" if DASHBOARD_START_DATE else ""
st.markdown(f"<br><br><div style='text-align:center;border-top:1px solid #1c2540;padding-top:16px'><span class='sub'>MLB Prediction Model · Personal Use Only · Nightly auto-update</span>{_filter_note}</div>", unsafe_allow_html=True)