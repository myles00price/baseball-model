"""
ideas_archive.py — permanent storage for IDEA BOX submissions.

The board's idea box posts to ntfy topic poons-mlb-ideas-k7d24q, which only
caches messages ~12 hours; anything not read in that window was being LOST
(caught 2026-08-19). This polls the topic's cache and appends new messages
to ideas_inbox.json (deduped by ntfy message id), committed with the repo.

Hooked into notify_pick (each watcher cycle, machine-on hours) and the
10:30 nightly. Standalone:  py -3.11 .\ideas_archive.py [--show]
"""

import json
import os
import sys
from datetime import datetime

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

TOPIC = "poons-mlb-ideas-k7d24q"
FN = "ideas_inbox.json"


def load():
    try:
        return json.load(open(FN, encoding="utf-8"))
    except Exception:
        return []


def collect():
    ideas = load()
    seen = {i["id"] for i in ideas}
    try:
        r = requests.get(f"https://ntfy.sh/{TOPIC}/json", params={"poll": 1, "since": "all"}, timeout=20)
        new = 0
        for line in r.text.splitlines():
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("event") != "message" or m.get("id") in seen:
                continue
            ideas.append({"id": m["id"], "t": datetime.fromtimestamp(m["time"]).isoformat(timespec="minutes"),
                          "msg": m.get("message", ""), "status": "new"})
            seen.add(m["id"]); new += 1
        if new:
            ideas.sort(key=lambda i: i["t"])
            json.dump(ideas, open(FN, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
            print(f"ideas_archive: {new} new idea(s) archived ({len(ideas)} total)")
        return new
    except Exception as e:
        print(f"ideas_archive: poll failed ({e})")
        return 0


if __name__ == "__main__":
    collect()
    if "--show" in sys.argv:
        for i in load():
            print(f"[{i['t']}] ({i['status']}) {i['msg']}")
