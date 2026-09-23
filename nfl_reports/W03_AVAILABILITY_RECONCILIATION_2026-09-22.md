# Week 3 availability reconciliation — 2026-09-22

Why this exists: a player who disappears from an injury feed is not thereby healthy. The feed we read was capped,
and the roster we checked was stale, so two different silent paths could put a player who is not going to play on
the board. Both are closed below. What could not be settled from evidence is listed as UNRESOLVED rather than
assumed healthy.

## What was wrong

**1. The injury list was capped at 25 players per team.** The public list tops out at 800 records for the league.
Once a team had more, the rest were simply absent, and an absent player carries no flag. Of 39 skill-position
players judged at least 75% likely to miss on the 2026-09-10 copy who were absent from today's capped copy, not
one was shown active by an independent source: 36 were still on reserve, one was still out, two had no roster row
at all. Absence was 0 for 39 as a health signal.

**2. The roster check was reading a Week 1 snapshot.** The board keeps only players listed active on the 53-man
roster, but the roster it loaded for Week 3 was a Week 1 file, because the weekly roster copy on disk stopped at
Week 2 and the older season-wide file was preferred over it. Players who moved to injured reserve after Week 1
therefore still looked like starters.

The most expensive example: **A.J. Brown (NE)** has been on injured reserve since 2026-09-13. He was projected
for 7.4 targets and 61 receiving yards on the board published earlier this evening. Also affected: Tim Patrick
(NYJ) and Malik Davis (DAL), both on reserve, and Darius Slayton (NYG), who has not been on a roster since Week 1.

## What changed

| | before | after |
|---|---|---|
| injury records read | 800 (capped at 25 per team) | 1,931 (the full list) |
| skill-position records | 403 | 579 |
| Week 3 players carrying an availability flag | 58 | 121 |
| players flagged as certain to miss | 21 | 84 |
| roster used for Week 3 | a Week 1 snapshot | the Week 3 roster, published this morning |

The full list comes from the same provider's uncapped endpoint and is a strict superset of the capped one: every
player on the capped list is still present, with the same wording where the capped list had it. The roster fix
makes the newest roster on disk win over an older season-wide file, and a regression test pins it.

## Sources, and what they do and do not establish

Three separately operated publications were compared, all dated today: the injury list, the weekly roster, and the
depth charts. On team assignment they agree completely for players on active rosters, and the injury list and
weekly roster agree on all 1,539 records that can be joined by player id.

That is convergence, not ground truth. None of these is the league's own game-day inactive list. "Active" on a
weekly roster means a player is on the 53, not that he will take a snap: a player can be active all week and be
declared out ninety minutes before kickoff. Nothing here is checked against the games themselves.

## UNRESOLVED — decide before any picks are locked

The official Week 3 injury report is not published yet; it lands Wednesday. The three below are listed as active
by both the roster and the injury list, but the most recent official report available, Week 2's, said otherwise.
No source settles them today, so they are called unresolved rather than healthy:

| player | team | last official report (Week 2) | today |
|---|---|---|---|
| Michael Penix Jr. | ATL | Out (knee) | active; a note says the team considers him ready to play |
| Tua Tagovailoa | ATL | Doubtful (oblique), did not practise | active; first full practice since 2026-09-09 |
| Kyler Murray | MIN | Out (concussion), limited practice | active; nothing states he has cleared the protocol |

They are not excluded from the board, because no evidence supports excluding them; they are flagged here so that
no pick is made on any of them until Wednesday's official report settles it. No prop picks exist for Week 3 at the
time of writing, and none can be made until prop lines are pulled.

## Standing rule

Absence from an injury list is not evidence of availability. Before any Week 3 picks are locked: re-read the
official injury report once it is published, re-check the weekly roster, and resolve every name above by evidence.
