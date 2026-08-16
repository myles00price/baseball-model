"""hr_miss_audit.py — where is the HR model missing?

Joins every home run in hr_audit_events.csv (pitch-level detail) to the
model's walk-forward morning probability for that batter-game
(hr_bt_eval2.csv, from the backtests), then asks, slice by slice:
did the model see it coming?

Slices: model tier (p bucket) | batter power tier | pitcher HR tendency
| pitch type | velocity | zone (Statcast 1-9 heart/edges, 11-14 chase)
| count | inning. For each slice: how many HRs, the mean model p on the
HRs, and — the key number — the share of ALL batter-games in that slice
that homered vs what the model predicted (calibration by slice).

Run:  C:\\Users\\Poons\\Model\\.venv\\Scripts\\python.exe hr_miss_audit.py
"""

import sys

import numpy as np
import pandas as pd

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

pd.set_option("display.width", 160)

ZONE_LABEL = {1: "up-in", 2: "up-mid", 3: "up-away", 4: "mid-in", 5: "HEART",
              6: "mid-away", 7: "low-in", 8: "low-mid", 9: "low-away",
              11: "chase up-in", 12: "chase up-away", 13: "chase low-in", 14: "chase low-away"}


def bucket(p):
    return pd.cut(p, [0, .08, .12, .16, .20, 1.0],
                  labels=["<8", "8-12", "12-16", "16-20", "20+"], right=False)


def main():
    hr = pd.read_csv("hr_audit_events.csv")
    ev = pd.read_csv("hr_bt_eval2.csv")
    lo, hi = hr["game_date"].min(), hr["game_date"].max()
    ev = ev[(ev["date"] >= lo) & (ev["date"] <= hi)].copy()
    core = ev["bat_rate"] * ev["f_pit"] * ev["f_park"]
    ev["p"] = 1 - (1 - core.clip(1e-5, .5)) ** ev["exp_pa"]
    ev["tier"] = bucket(ev["p"])
    print(f"window {lo}..{hi}: {len(hr)} HR | model rows {len(ev)} "
          f"({ev['y'].sum()} batter-games with HR, {ev['y'].mean()*100:.1f}%)")

    # ── join HR events to model rows ─────────────────────────────────────
    j = hr.merge(ev[["batter", "game_pk", "p", "tier", "f_bat", "f_pit", "c_pa_n", "c_hr"]],
                 on=["batter", "game_pk"], how="left")
    cov = j["p"].notna().mean()
    print(f"HRs matched to a model row: {cov*100:.0f}% "
          f"(unmatched = <100 PA at the time or pinch-hitters, model never rated them)")
    m = j[j["p"].notna()].copy()
    for lab, sign in (("batter", "stand"), ("pitcher", "p_throws")):
        pass

    # ── 1. what tier did the homers come from vs where model mass sits ──
    print("\n1) WHERE THE HOMERS CAME FROM (matched HRs by model tier)")
    tot_by_tier = ev.groupby("tier", observed=False).agg(n=("y", "size"), pred=("p", "sum"), act=("y", "sum"))
    tot_by_tier["hr_share_%"] = tot_by_tier["act"] / tot_by_tier["act"].sum() * 100
    tot_by_tier["pred_share_%"] = tot_by_tier["pred"] / tot_by_tier["pred"].sum() * 100
    tot_by_tier["act_rate_%"] = tot_by_tier["act"] / tot_by_tier["n"] * 100
    tot_by_tier["pred_rate_%"] = tot_by_tier["pred"] / tot_by_tier["n"] * 100
    print(tot_by_tier.round(1).to_string())
    unrated = len(hr) - len(m)
    print(f"  + {unrated} HR by hitters the model did not rate at all (below 100 PA / call-ups / PH)")

    # ── 2. by batter power tier (f_bat) ──────────────────────────────────
    print("\n2) BY HITTER POWER TIER (season HR rate vs league, at the time)")
    ev["bat_tier"] = pd.cut(ev["f_bat"], [0, .7, 1.0, 1.3, 1.7, 9], labels=["<.7 weak", ".7-1", "1-1.3", "1.3-1.7", "1.7+ elite"])
    t = ev.groupby("bat_tier", observed=False).agg(n=("y", "size"), pred=("p", "mean"), act=("y", "mean"), hrs=("y", "sum"))
    t["pred"] *= 100; t["act"] *= 100; t["gap"] = t["act"] - t["pred"]
    print(t.round(1).to_string())

    # ── 3. by pitcher tendency (f_pit) ───────────────────────────────────
    print("\n3) BY OPPOSING STARTER HR TENDENCY (shrunk factor at the time)")
    ev["pit_tier"] = pd.cut(ev["f_pit"], [0, .93, .99, 1.01, 1.07, 9], labels=["stingy", "below", "neutral", "above", "gopher"])
    t = ev.groupby("pit_tier", observed=False).agg(n=("y", "size"), pred=("p", "mean"), act=("y", "mean"), hrs=("y", "sum"))
    t["pred"] *= 100; t["act"] *= 100; t["gap"] = t["act"] - t["pred"]
    print(t.round(1).to_string())

    # ── 4. pitch type on the HR, split by model tier ─────────────────────
    print("\n4) PITCH TYPE HOMERED ON — share of HRs, and mean model p on those HRs")
    t = m.groupby("pitch_name").agg(hrs=("p", "size"), mean_p=("p", "mean"), velo=("release_speed", "mean"))
    t["share_%"] = t["hrs"] / t["hrs"].sum() * 100
    t["mean_p"] *= 100
    print(t.sort_values("hrs", ascending=False).round(1).to_string())
    print("  (mean_p is what the model gave the hitter that morning; lower = more surprised)")

    # ── 5. zone ──────────────────────────────────────────────────────────
    print("\n5) ZONE HOMERED FROM (Statcast zone; 5 = heart of plate)")
    m["zone_lab"] = m["zone"].map(ZONE_LABEL).fillna("?")
    t = m.groupby("zone_lab").agg(hrs=("p", "size"), mean_p=("p", "mean"), ev_mph=("launch_speed", "mean"))
    t["share_%"] = t["hrs"] / t["hrs"].sum() * 100
    t["mean_p"] *= 100
    print(t.sort_values("hrs", ascending=False).round(1).to_string())
    heart = m["zone"].isin([5]).mean() * 100
    inzone = m["zone"].between(1, 9).mean() * 100
    print(f"  heart {heart:.0f}% | in-zone {inzone:.0f}% | chase {100-inzone:.0f}%")

    # ── 6. surprises: low-p homers — who are they? ───────────────────────
    print("\n6) THE SURPRISES — HRs where the model gave <8% (bottom tier)")
    s = m[m["p"] < .08]
    print(f"  {len(s)} of {len(m)} matched HRs ({len(s)/len(m)*100:.0f}%) came from sub-8% hitters")
    print(f"  their season line at the time: {s['c_hr'].mean():.1f} HR in {s['c_pa_n'].mean():.0f} PA "
          f"(f_bat {s['f_bat'].mean():.2f}) | facing f_pit {s['f_pit'].mean():.2f}")
    print(f"  pitch mix on those: " + ", ".join(f"{k} {v}" for k, v in s["pitch_name"].value_counts().head(5).items()))
    print(f"  mean EV {s['launch_speed'].mean():.1f} mph, dist {s['hit_distance_sc'].mean():.0f} ft "
          f"vs elite-tier HRs {m[m['p']>=.20]['launch_speed'].mean():.1f} mph, {m[m['p']>=.20]['hit_distance_sc'].mean():.0f} ft")

    # ── 7. velocity + count + inning ─────────────────────────────────────
    print("\n7) VELOCITY / COUNT / INNING on matched HRs (mean model p)")
    m["velo_b"] = pd.cut(m["release_speed"], [0, 85, 90, 94, 97, 110], labels=["<85", "85-90", "90-94", "94-97", "97+"])
    print(m.groupby("velo_b", observed=False)["p"].agg(hrs="size", mean_p="mean").assign(mean_p=lambda d: d.mean_p*100).round(1).to_string())
    m["cnt"] = m["balls"].astype(int).astype(str) + "-" + m["strikes"].astype(int).astype(str)
    print(m.groupby("cnt")["p"].agg(hrs="size", mean_p="mean").assign(mean_p=lambda d: d.mean_p*100).sort_values("hrs", ascending=False).head(6).round(1).to_string())
    m["late"] = np.where(m["inning"] >= 7, "7th+ (bullpen)", "1-6 (starter era)")
    print(m.groupby("late")["p"].agg(hrs="size", mean_p="mean").assign(mean_p=lambda d: d.mean_p*100).round(1).to_string())

    # ── 8. batter-side calibration: who is the model over/under-rating ───
    print("\n8) BIGGEST INDIVIDUAL MISSES (window; hitters with 15+ rated games)")
    per = ev.groupby("batter").agg(g=("y", "size"), pred=("p", "sum"), act=("y", "sum"))
    per = per[per["g"] >= 15]
    per["gap"] = per["act"] - per["pred"]
    # Statcast player_name is the PITCHER; batter names come from our logs
    from glob import glob
    names = {}
    for fn in glob("hr_log_*.csv"):
        d = pd.read_csv(fn, usecols=["player_id", "name"])
        names.update(dict(zip(d["player_id"], d["name"])))
    per["name"] = per.index.map(names).fillna("?")
    print("  model UNDER-rated (homered far more than predicted):")
    print(per.sort_values("gap", ascending=False).head(8)[["name", "g", "pred", "act", "gap"]].round(1).to_string())
    print("  model OVER-rated (predicted much more than delivered):")
    print(per.sort_values("gap").head(8)[["name", "g", "pred", "act", "gap"]].round(1).to_string())
    print("  (player_name comes from the HR file, so over-rated hitters with 0 HR show '?')")

    m.to_csv("hr_audit_joined.csv", index=False)
    print("\nwrote hr_audit_joined.csv")


if __name__ == "__main__":
    main()
