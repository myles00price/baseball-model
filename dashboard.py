import streamlit as st
import pandas as pd
import csv
import requests
from glob import glob
from datetime import datetime, timedelta, timezone

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="MLB Model Dashboard",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Custom CSS ────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Barlow+Condensed:wght@400;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Barlow Condensed', sans-serif;
        background-color: #0a0e1a;
        color: #e2e8f0;
    }

    .main { background-color: #0a0e1a; }

    h1, h2, h3 { font-family: 'Space Mono', monospace; }

    .metric-card {
        background: linear-gradient(135deg, #1a1f35 0%, #0f1525 100%);
        border: 1px solid #2d3555;
        border-radius: 8px;
        padding: 20px;
        text-align: center;
    }

    .metric-value {
        font-family: 'Space Mono', monospace;
        font-size: 2.2rem;
        font-weight: 700;
        color: #60a5fa;
    }

    .metric-label {
        font-size: 0.85rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 4px;
    }

    .bet-card {
        background: linear-gradient(135deg, #0f2a1a 0%, #0a1f12 100%);
        border: 1px solid #16a34a;
        border-left: 4px solid #22c55e;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
    }

    .fade-card {
        background: linear-gradient(135deg, #2a0f0f 0%, #1f0a0a 100%);
        border: 1px solid #dc2626;
        border-left: 4px solid #ef4444;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
    }

    .neutral-card {
        background: linear-gradient(135deg, #1a1f35 0%, #0f1525 100%);
        border: 1px solid #2d3555;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 8px;
    }

    .badge-green {
        background: #16a34a;
        color: white;
        padding: 2px 10px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 1px;
    }

    .badge-red {
        background: #dc2626;
        color: white;
        padding: 2px 10px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 1px;
    }

    .badge-blue {
        background: #2563eb;
        color: white;
        padding: 2px 10px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 1px;
    }

    .team-name { font-size: 1.1rem; font-weight: 700; color: #f1f5f9; }
    .prob { font-family: 'Space Mono', monospace; font-size: 1.4rem; color: #60a5fa; font-weight: 700; }
    .edge { font-family: 'Space Mono', monospace; font-size: 0.9rem; color: #22c55e; }
    .edge-neg { font-family: 'Space Mono', monospace; font-size: 0.9rem; color: #ef4444; }
    .sub { font-size: 0.8rem; color: #64748b; }

    .section-header {
        font-family: 'Space Mono', monospace;
        font-size: 0.75rem;
        color: #475569;
        text-transform: uppercase;
        letter-spacing: 2px;
        border-bottom: 1px solid #1e2940;
        padding-bottom: 8px;
        margin-bottom: 16px;
    }

    .stDataFrame { background: #0f1525; }
    div[data-testid="stMetricValue"] { color: #60a5fa; font-family: 'Space Mono', monospace; }
</style>
""", unsafe_allow_html=True)


# ── Data helpers ──────────────────────────────────────────────
def load_picks(filename):
    picks = []
    try:
        with open(filename, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                picks.append(row)
    except:
        pass
    return picks

def get_game_results(date_str):
    try:
        schedule = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str, "hydrate": "linescore"},
            timeout=10
        ).json()
        results = {}
        for date in schedule.get("dates", []):
            for game in date.get("games", []):
                if game.get("status", {}).get("abstractGameState") != "Final":
                    continue
                home = game["teams"]["home"]["team"]["name"]
                away = game["teams"]["away"]["team"]["name"]
                home_score = game["teams"]["home"].get("score", 0)
                away_score = game["teams"]["away"].get("score", 0)
                winner = home if home_score > away_score else away
                results[home] = {"winner": winner, "home_score": home_score, "away_score": away_score}
                results[away] = results[home]
        return results
    except:
        return {}

def get_season_stats():
    picks_files = sorted(glob("picks_2026-*.csv"))
    total = correct = flagged = flag_correct = 0
    pnl = 0.0
    edge_buckets = {"0-3%": [0,0], "3-6%": [0,0], "6-10%": [0,0], "10%+": [0,0]}
    daily = []

    for filename in picks_files:
        date_str = filename.replace("picks_", "").replace(".csv", "")
        picks = load_picks(filename)
        if not picks:
            continue
        results = get_game_results(date_str)
        if not results:
            continue

        day_total = day_correct = day_flagged = day_flag_correct = 0

        for pick in picks:
            away = pick.get("Away", "")
            home = pick.get("Home", "")
            away_prob = pick.get("Model Away%", "None")
            home_prob = pick.get("Model Home%", "None")
            flag = pick.get("Flag", "")

            if away_prob == "None" or home_prob == "None":
                continue
            try:
                away_prob = float(away_prob)
                home_prob = float(home_prob)
            except:
                continue

            result = results.get(home) or results.get(away)
            if not result:
                continue

            actual_winner = result["winner"]
            model_winner = away if away_prob > home_prob else home
            won = model_winner == actual_winner

            total += 1; day_total += 1
            if won:
                correct += 1; day_correct += 1

            is_flagged = "BET" in str(flag)
            if is_flagged:
                flagged += 1; day_flagged += 1
                dk_odds = pick.get("DK Home Odds" if model_winner == home else "DK Away Odds", "N/A")
                try:
                    odds = float(dk_odds)
                    payout = (100 / -odds * 100) if odds < 0 else (odds / 100 * 100)
                except:
                    payout = 90
                if won:
                    flag_correct += 1; day_flag_correct += 1
                    pnl += payout
                else:
                    pnl -= 100

            try:
                dk_edge = pick.get("DK Edge Away", "N/A")
                e = abs(float(dk_edge.replace("%","").replace("** BET **","").replace("+","").strip()))
                b = "0-3%" if e < 3 else "3-6%" if e < 6 else "6-10%" if e < 10 else "10%+"
                edge_buckets[b][0] += 1
                if won: edge_buckets[b][1] += 1
            except:
                pass

        if day_total > 0:
            daily.append({"date": date_str, "total": day_total, "correct": day_correct,
                         "flagged": day_flagged, "flag_correct": day_flag_correct})

    return {
        "total": total, "correct": correct,
        "flagged": flagged, "flag_correct": flag_correct,
        "pnl": pnl, "edge_buckets": edge_buckets, "daily": daily
    }

def load_todays_picks():
    lv = timezone(timedelta(hours=-7))
    today_str = datetime.now(lv).strftime("%Y-%m-%d")
    filename = f"picks_{today_str}.csv"
    return load_picks(filename), today_str


# ── Main Dashboard ────────────────────────────────────────────
st.markdown("""
<div style='padding: 24px 0 8px 0'>
    <span style='font-family: Space Mono, monospace; font-size: 1.8rem; font-weight: 700; color: #60a5fa'>⚾ MLB MODEL</span>
    <span style='font-family: Space Mono, monospace; font-size: 1.8rem; color: #334155'> // DASHBOARD</span>
</div>
""", unsafe_allow_html=True)

st.markdown(f"<div class='sub' style='margin-bottom:24px'>Last updated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}</div>", unsafe_allow_html=True)

# Load data
with st.spinner("Loading season data..."):
    stats = get_season_stats()
    todays_picks, today_str = load_todays_picks()

# ── Season Metrics ────────────────────────────────────────────
st.markdown("<div class='section-header'>Season Performance</div>", unsafe_allow_html=True)

col1, col2, col3, col4, col5 = st.columns(5)

overall_pct = stats["correct"] / stats["total"] * 100 if stats["total"] else 0
flag_pct = stats["flag_correct"] / stats["flagged"] * 100 if stats["flagged"] else 0
roi = stats["pnl"] / (stats["flagged"] * 100) * 100 if stats["flagged"] else 0
pnl_str = f"+${stats['pnl']:.0f}" if stats["pnl"] >= 0 else f"-${abs(stats['pnl']):.0f}"

with col1:
    st.markdown(f"""
    <div class='metric-card'>
        <div class='metric-value'>{overall_pct:.1f}%</div>
        <div class='metric-label'>Overall Accuracy</div>
        <div class='sub'>{stats['correct']}/{stats['total']} games</div>
    </div>""", unsafe_allow_html=True)

with col2:
    color = "#22c55e" if flag_pct >= 55 else "#f59e0b" if flag_pct >= 47 else "#ef4444"
    st.markdown(f"""
    <div class='metric-card'>
        <div class='metric-value' style='color:{color}'>{flag_pct:.1f}%</div>
        <div class='metric-label'>Flagged Bets</div>
        <div class='sub'>{stats['flag_correct']}/{stats['flagged']} bets</div>
    </div>""", unsafe_allow_html=True)

with col3:
    color = "#22c55e" if stats["pnl"] >= 0 else "#ef4444"
    st.markdown(f"""
    <div class='metric-card'>
        <div class='metric-value' style='color:{color}'>{pnl_str}</div>
        <div class='metric-label'>P&L ($100/bet)</div>
        <div class='sub'>paper trading</div>
    </div>""", unsafe_allow_html=True)

with col4:
    color = "#22c55e" if roi >= 0 else "#ef4444"
    st.markdown(f"""
    <div class='metric-card'>
        <div class='metric-value' style='color:{color}'>{roi:+.1f}%</div>
        <div class='metric-label'>ROI</div>
        <div class='sub'>{stats['flagged']} bets placed</div>
    </div>""", unsafe_allow_html=True)

with col5:
    bucket_6_10 = stats["edge_buckets"]["6-10%"]
    pct_6_10 = bucket_6_10[1] / bucket_6_10[0] * 100 if bucket_6_10[0] else 0
    st.markdown(f"""
    <div class='metric-card'>
        <div class='metric-value' style='color:#22c55e'>{pct_6_10:.1f}%</div>
        <div class='metric-label'>6-10% Edge Zone</div>
        <div class='sub'>{bucket_6_10[1]}/{bucket_6_10[0]} games</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Edge Bucket Analysis ──────────────────────────────────────
col_left, col_right = st.columns([1, 1])

with col_left:
    st.markdown("<div class='section-header'>Edge Zone Performance</div>", unsafe_allow_html=True)
    for bucket, (total, correct) in stats["edge_buckets"].items():
        if total == 0:
            continue
        pct = correct / total * 100
        bar_width = int(pct)
        color = "#22c55e" if pct >= 58 else "#f59e0b" if pct >= 50 else "#ef4444"
        st.markdown(f"""
        <div class='neutral-card' style='padding:12px 16px'>
            <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px'>
                <span style='font-weight:700;color:#e2e8f0'>{bucket}</span>
                <span style='font-family:Space Mono,monospace;font-size:1rem;color:{color};font-weight:700'>{pct:.1f}%</span>
            </div>
            <div style='background:#0f1525;border-radius:3px;height:6px'>
                <div style='background:{color};width:{bar_width}%;height:6px;border-radius:3px'></div>
            </div>
            <div class='sub' style='margin-top:4px'>{correct}/{total} games</div>
        </div>""", unsafe_allow_html=True)

with col_right:
    st.markdown("<div class='section-header'>Daily Record</div>", unsafe_allow_html=True)
    if stats["daily"]:
        for d in reversed(stats["daily"][-8:]):
            pct = d["correct"] / d["total"] * 100 if d["total"] else 0
            flag_txt = f"{d['flag_correct']}/{d['flagged']}" if d["flagged"] else "—"
            color = "#22c55e" if pct >= 55 else "#f59e0b" if pct >= 45 else "#ef4444"
            st.markdown(f"""
            <div class='neutral-card' style='padding:10px 16px;display:flex;justify-content:space-between;align-items:center'>
                <span style='font-family:Space Mono,monospace;font-size:0.8rem;color:#64748b'>{d['date']}</span>
                <span style='font-family:Space Mono,monospace;color:{color};font-weight:700'>{d['correct']}/{d['total']} ({pct:.0f}%)</span>
                <span style='font-size:0.8rem;color:#94a3b8'>Flags: {flag_txt}</span>
            </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Today's Picks ─────────────────────────────────────────────
st.markdown(f"<div class='section-header'>Today's Picks — {today_str}</div>", unsafe_allow_html=True)

if not todays_picks:
    st.info("No picks file found for today. Run `master.py` or `todays_report.py` first.")
else:
    flagged_picks = [p for p in todays_picks if "BET" in str(p.get("Flag", ""))]
    other_picks = [p for p in todays_picks if "BET" not in str(p.get("Flag", ""))]

    if flagged_picks:
        st.markdown(f"<span class='badge-green'>🎯 {len(flagged_picks)} FLAGGED BET{'S' if len(flagged_picks) > 1 else ''}</span><br><br>", unsafe_allow_html=True)
        for pick in flagged_picks:
            away = pick.get("Away", "")
            home = pick.get("Home", "")
            away_prob = pick.get("Model Away%", "N/A")
            home_prob = pick.get("Model Home%", "N/A")
            away_sp = pick.get("Away SP", "")
            home_sp = pick.get("Home SP", "")
            away_rel = pick.get("Away Reliability%", "")
            home_rel = pick.get("Home Reliability%", "")
            sharp = pick.get("Sharp Signal", "N/A")
            dk_edge_away = pick.get("DK Edge Away", "")
            dk_edge_home = pick.get("DK Edge Home", "")
            lineup = pick.get("Lineup Source", "")
            away_bp = pick.get("Away BP ERA(7d)", "")
            home_bp = pick.get("Home BP ERA(7d)", "")

            try:
                model_fav = away if float(away_prob) > float(home_prob) else home
                edge = dk_edge_away if float(away_prob) > float(home_prob) else dk_edge_home
            except:
                model_fav = home
                edge = dk_edge_home

            sharp_color = "#22c55e" if "CONFIRMED" in str(sharp) else "#ef4444" if "FADE" in str(sharp) else "#64748b"

            st.markdown(f"""
            <div class='bet-card'>
                <div style='display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px'>
                    <div>
                        <div style='font-size:0.75rem;color:#64748b;margin-bottom:4px'>{lineup}</div>
                        <div class='team-name'>{away} @ {home}</div>
                    </div>
                    <div style='text-align:right'>
                        <div style='font-family:Space Mono,monospace;font-size:1.1rem;color:#22c55e;font-weight:700'>{edge}</div>
                        <div style='font-size:0.75rem;color:{sharp_color};margin-top:2px'>{sharp}</div>
                    </div>
                </div>
                <div style='display:flex;gap:24px;margin-bottom:10px'>
                    <div>
                        <div class='sub'>Away — {away}</div>
                        <div class='prob'>{away_prob}%</div>
                    </div>
                    <div>
                        <div class='sub'>Home — {home}</div>
                        <div class='prob'>{home_prob}%</div>
                    </div>
                </div>
                <div style='display:flex;gap:16px;flex-wrap:wrap'>
                    <span class='sub'>🧢 Away SP: {away_sp} ({away_rel} rel)</span>
                    <span class='sub'>🏠 Home SP: {home_sp} ({home_rel} rel)</span>
                    <span class='sub'>🔥 BP: {away_bp} vs {home_bp} ERA(7d)</span>
                </div>
                <div style='margin-top:8px'>
                    <span class='badge-green'>MODEL PICK: {model_fav}</span>
                </div>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown("<div class='neutral-card' style='text-align:center;padding:24px;color:#64748b'>No flagged bets today — model sees no high-conviction edges</div>", unsafe_allow_html=True)

    with st.expander(f"All Games Today ({len(todays_picks)} total)"):
        for pick in todays_picks:
            away = pick.get("Away", "")
            home = pick.get("Home", "")
            away_prob = pick.get("Model Away%", "N/A")
            home_prob = pick.get("Model Home%", "N/A")
            dk_edge_away = pick.get("DK Edge Away", "N/A")
            dk_edge_home = pick.get("DK Edge Home", "N/A")
            sharp = pick.get("Sharp Signal", "N/A")
            sharp_color = "#22c55e" if "CONFIRMED" in str(sharp) else "#ef4444" if "FADE" in str(sharp) else "#64748b"

            st.markdown(f"""
            <div class='neutral-card' style='padding:10px 14px'>
                <div style='display:flex;justify-content:space-between;align-items:center'>
                    <span class='team-name' style='font-size:0.95rem'>{away} @ {home}</span>
                    <div style='display:flex;gap:16px;align-items:center'>
                        <span style='font-family:Space Mono,monospace;font-size:0.85rem;color:#60a5fa'>{away_prob}% / {home_prob}%</span>
                        <span style='font-family:Space Mono,monospace;font-size:0.8rem;color:#94a3b8'>{dk_edge_away} | {dk_edge_home}</span>
                        <span style='font-size:0.75rem;color:{sharp_color}'>{sharp}</span>
                    </div>
                </div>
            </div>""", unsafe_allow_html=True)

# ── Confidence Indicator ──────────────────────────────────────
st.markdown("<br><div class='section-header'>Betting Confidence</div>", unsafe_allow_html=True)

if stats["flagged"] >= 30 and flag_pct >= 57:
    msg = f"✅ READY — {flag_pct:.1f}% on {stats['flagged']} bets → consider $100 bets"
    color = "#22c55e"
elif stats["flagged"] >= 20 and flag_pct >= 52:
    msg = f"🟡 CLOSE — {flag_pct:.1f}% on {stats['flagged']} bets → paper trade only"
    color = "#f59e0b"
else:
    msg = f"🔴 NOT YET — {flag_pct:.1f}% on {stats['flagged']} bets → need 55%+ over 30+ bets"
    color = "#ef4444"

st.markdown(f"""
<div class='neutral-card' style='text-align:center;padding:20px'>
    <div style='font-family:Space Mono,monospace;font-size:1rem;color:{color};font-weight:700'>{msg}</div>
</div>""", unsafe_allow_html=True)

st.markdown("<br><div class='sub' style='text-align:center'>MLB Prediction Model — Personal Use Only</div>", unsafe_allow_html=True)