"""pit_snapshot.py — append-only pregame feature snapshots (audit F01).

The picks CSV freezes the champion's PROBABILITY but not the inputs it was
fed (blended starter ERA/WHIP, lineup OPS, team K%), so no live row can be
re-scored by a candidate and the live-frozen class has no features. This
sidecar records, at the moment master_v2 computes a probability, the exact
feature inputs with game_pk and a UTC stamp. Rows are appended, never
rewritten; the FIRST row per (game_pk) before first pitch is the eligible
pregame snapshot, later rows are refreshes.

Wiring (master_v2.run_model, right after the probability is computed):
    pit_snapshot.record_v2(target_str, game_key, game_pk, game.get("gameDate"),
                           home_stats=..., away_stats=..., home_ops=..., ...)
record_v2() can never affect the run: building the inputs AND writing them happen
inside one guard; any failure is printed and swallowed.

Reading it back for training / evaluation:
    rows, report = pit_snapshot.training_rows(root)      # one clean row per game_pk, or nothing
A snapshot becomes a training row only if it was taken BEFORE first pitch of
a game with a known start time, names a game_pk, and carries every V2 input
as a finite number. Everything else is counted in the report and excluded
(fail closed). Labels are attached elsewhere (pit_provenance.live_snapshot_rows)
- an outcome is never stored here.
"""

import glob
import json
import math
import os
import re
from datetime import datetime, timezone

# the eight raw inputs of features_v2.build_feature_vector, in its argument order
REQUIRED_INPUTS = ("home_era", "home_whip", "away_era", "away_whip", "home_ops", "home_kpct", "away_ops", "away_kpct")
_NAME = re.compile(r"^pregame_snapshots_(\d{4}-\d{2}-\d{2})\.jsonl$")


def path_for(date_str, root="."):
    return os.path.join(root, f"pregame_snapshots_{date_str}.jsonl")


def _parse_utc(x):
    dt = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without a timezone: {x!r}")
    return dt.astimezone(timezone.utc)


def _same_game(row, game_pk, game_key):
    if game_pk is not None and row.get("game_pk") is not None:
        return row["game_pk"] == game_pk
    return row.get("game_key") == game_key


def save(date_str, game_key, game_pk, inputs, game_start_utc=None, now_utc=None, root=".", dedupe=True):
    """Append one snapshot. With dedupe (default) a refresh whose inputs and pregame flag equal the game's
    latest stored snapshot is NOT written again (returns None): the first time a set of inputs was seen is the
    honest cutoff for it, and the lineup checks rerun the model many times a day."""
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    pk = int(game_pk) if game_pk else None
    row = {"date": date_str, "game_key": game_key, "game_pk": pk,
           "cutoff_utc": now.isoformat(), "game_start_utc": game_start_utc,
           "pregame": (game_start_utc is not None and now < datetime.fromisoformat(
               str(game_start_utc).replace("Z", "+00:00"))),
           "inputs": inputs, "provenance": "live-frozen"}
    if dedupe:
        comparable = json.loads(json.dumps(inputs, default=str))
        for prev in reversed(load(date_str, root)):
            if _same_game(prev, pk, game_key):
                if prev.get("inputs") == comparable and prev.get("pregame") == row["pregame"]:
                    return None
                break
    with open(path_for(date_str, root), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return row


def v2_inputs(home_stats, away_stats, home_ops, home_kpct, away_ops, away_kpct, lineup_source, home_prob,
              home_pitcher=None, away_pitcher=None, home_pid=None, away_pid=None, model_meta=None):
    """Exactly what master_v2 fed features_v2.predict_home_win_prob_v2, plus who and which model.
    home_stats / away_stats are the blended starter dicts (pitcher_stats.get_blended_pitcher_stats)."""
    def starter(stats, name, pid):
        s = stats or {}
        return {"name": name, "pid": int(pid) if pid else None, "hand": s.get("hand"),
                "reliability": s.get("reliability"), "ip": s.get("ip")}
    meta = model_meta or {}
    return {"home_era": (home_stats or {}).get("era"), "home_whip": (home_stats or {}).get("whip"),
            "away_era": (away_stats or {}).get("era"), "away_whip": (away_stats or {}).get("whip"),
            "home_ops": home_ops, "home_kpct": home_kpct, "away_ops": away_ops, "away_kpct": away_kpct,
            "lineup_source": lineup_source, "home_prob": home_prob,
            "home_starter": starter(home_stats, home_pitcher, home_pid),
            "away_starter": starter(away_stats, away_pitcher, away_pid),
            # the version's NAME (its UTC stamp), not its path: snapshots are published with the repo
            "model": {"source": meta.get("source"), "promoted_utc": meta.get("promoted_utc"),
                      "version": (os.path.basename(str(meta["version_dir"]).replace("\\", "/").rstrip("/"))
                                  if meta.get("version_dir") else None)}}


def record_v2(date_str, game_key, game_pk, game_start_utc, root=".", **v2_kwargs):
    """save() for the live pipeline: a snapshot is bookkeeping and must never cost a pick. The inputs are
    built (v2_inputs(**v2_kwargs)) and written inside ONE guard; any failure is reported on stdout and
    swallowed. Returns the stored row, or None (duplicate refresh, or failure)."""
    try:
        return save(date_str, game_key, game_pk, v2_inputs(**v2_kwargs), game_start_utc=game_start_utc, root=root)
    except Exception as e:                                  # noqa: BLE001 - by design, see docstring
        print(f"  WARNING: pregame snapshot not saved for {game_key}: {type(e).__name__}: {e}")
        return None


def load(date_str, root="."):
    p = path_for(date_str, root)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue                                    # a torn last line (crash mid-append) is not a snapshot
    return out


def dates(root="."):
    found = []
    for p in glob.glob(os.path.join(root, "pregame_snapshots_*.jsonl")):
        m = _NAME.match(os.path.basename(p))
        if m:
            found.append(m.group(1))
    return sorted(found)


def eligible_pregame(date_str, root=".", select="first"):
    """One snapshot per game_pk that was taken before first pitch: the FIRST (default) or the LAST one.
    Rows without a known start time are never eligible (fail closed)."""
    if select not in ("first", "last"):
        raise ValueError("select must be 'first' or 'last'")
    out = {}
    for r in load(date_str, root):
        if r.get("pregame") and r.get("game_pk") is not None and (select == "last" or r["game_pk"] not in out):
            out[r["game_pk"]] = r
    return out


def _ineligible_reason(r):
    """None if the snapshot may become a training row, else why not. Re-derives 'pregame' from the two
    timestamps instead of trusting the stored flag."""
    if r.get("game_pk") is None:
        return "no-game-pk"
    if not r.get("game_start_utc"):
        return "no-start-time"
    try:
        if not _parse_utc(r["cutoff_utc"]) < _parse_utc(r["game_start_utc"]):
            return "not-before-first-pitch"
    except (KeyError, TypeError, ValueError):
        return "bad-timestamps"
    if not r.get("pregame"):
        return "not-before-first-pitch"
    inputs = r.get("inputs") or {}
    for k in REQUIRED_INPUTS:
        v = inputs.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return "missing-input"
    return None


def training_rows(root=".", select="first"):
    """(rows, report). rows: one dict per game_pk - identity, cutoff, the eight raw V2 inputs, lineup source and
    the champion's frozen probability - from the first (or last) ELIGIBLE snapshot of each game. No label."""
    if select not in ("first", "last"):
        raise ValueError("select must be 'first' or 'last'")
    chosen, excluded, n_snapshots, games_seen = {}, {}, 0, set()
    for d in dates(root):
        for r in load(d, root):
            n_snapshots += 1
            games_seen.add((d, r.get("game_pk") if r.get("game_pk") is not None else r.get("game_key")))
            why = _ineligible_reason(r)
            if why:
                excluded[why] = excluded.get(why, 0) + 1
                continue
            pk = r["game_pk"]
            if select == "last" or pk not in chosen:
                chosen[pk] = r
    rows = []
    for pk, r in chosen.items():
        i = r["inputs"]
        row = {"date": r["date"], "season": int(str(r["date"])[:4]), "game_pk": int(pk), "game_key": r.get("game_key"),
               "cutoff_utc": r["cutoff_utc"], "game_start_utc": r["game_start_utc"],
               "lineup_source": i.get("lineup_source"), "champion_home_prob": i.get("home_prob")}
        row.update({k: float(i[k]) for k in REQUIRED_INPUTS})
        rows.append(row)
    rows.sort(key=lambda x: (x["date"], x["game_pk"]))
    report = {"snapshot_files": len(dates(root)), "snapshots": n_snapshots, "games_seen": len(games_seen),
              "eligible_games": len(rows), "excluded_snapshots": excluded, "select": select}
    return rows, report
