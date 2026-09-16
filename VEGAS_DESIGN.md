# Vegas After Dark

The live site inherits the design through `shell.js`, which loads `vegas.css`
and `vegas.js`. Generated sport pages keep their existing renderers, element IDs,
data sources, and grading logic. Rebuilding a sport page retains the design.

Sport navigation is followed by market categories; MLB and soccer player props
have another row of categories. Market selection is encoded in the URL fragment,
so a link such as `board.html#market=props&prop=homers` opens that exact view.
Record and Research hold the original ledgers, disclosures and model explanations.

MLB hit and home-run cards retain the original player detail handler. Their price
tiles compare quoted American-odds payouts for the same market and side. Tied best
prices are all highlighted; a lone price is not called best. Run Line groups book
quotes by team and exact handicap before comparison. Missing quotes stay missing.
First 5 shows the existing shadow ledger. No new recommendations are generated.

Regression checks performed with local pages and actual published data:

- All six main pages render without horizontal page overflow at 390px.
- MLB market and prop tabs isolate their sections; First 5 and Research retain data.
- NFL Touchdowns and soccer prop categories show the correct sections.
- CFB Record and MMA Fight Card remain accessible.
- HR price highlights match maximum payouts, including ties and negative odds.
- Keyboard activation opens the existing player details and survives rerendering.
- Desktop layout, dark/light switching and JavaScript console checked.

These are presentation checks, not a revalidation of the models or historical data.
`mlb_model_vault.html` is a separate archived artifact and is not restyled.

## Portrait edition

MLB hit and home-run views use two desktop columns, soft CSS portrait masks,
team-logo watermarks, and 426px MLB headshots (original small image fallback).
Player details, probabilities, and book-price comparisons remain unchanged.

`player-art.json` is an optional local-art registry keyed by MLB player ID.
Each entry may specify `src` under `assets/player-art/`, `approved: true`,
and source/license notes. Only add approved artwork with verified reuse rights.
An empty registry uses existing headshots; no third-party action photos are
bundled. Gray-background photos are softened, not represented as true cutouts.


## Action artwork correction
Two sourced cutouts are installed: Aaron Judge (592450), Mookie Betts (605141). Other players retain headshots; this is not full roster action coverage. Provenance and derivative licenses are in player-art.json and photo-credits.html. Built-in imagegen was used with background-extraction prompts: extract only the named player and bat, remove background, preserve face/pose/uniform/equipment, transparent PNG, no invented pose. Files: assets/player-art/592450.png and assets/player-art/605141.png. Team badges are independent of watermarks. 2+ Hits now receives the same card treatment as 1+ Hits without changing its market or probability.


## Locked play cards — September 15, 2026

Moneyline showcase cards now display a muted team logo, fading featured player, saved DraftKings odds, model probability, $100 model tracked stake, potential profit and expandable explanation. Official status requires a BET flag, a flagged side and a notified game key. Live results prefer GamePk to avoid doubleheader mismatches; missing odds remain unavailable. Unlocked leans are labeled separately. No wager-placement control or invented lock time is added.

Five approved cutouts are installed in assets/player-art/: Aaron Judge (592450), Mookie Betts (605141), Cal Raleigh (663728), Freddie Freeman (518692) and Matt Olson (621566). Cal and Matt are posed portraits; Freddie, Judge and Betts supply action imagery. Featured artwork requires current roster membership and a matching source team; unavailable artwork leaves the team logo. All five have genuine RGBA transparency. Licenses, author and original source links are maintained in player-art.json and photo-credits.html.

The three new images were edited with built-in imagegen. Prompt: remove only the photographic background to transparent alpha, preserve identity, face, pose, framing, uniform, logos and equipment; no new anatomy, shadows or fade. CSS supplies the fade. Original generated files are retained. Remaining research candidates are not installed or represented as finished artwork: Wikimedia rejected further media downloads with HTTP 429/robot-policy responses during this rollout.

Validation: Node syntax check; rendering regression tests for official/lean classification, skipped games, money calculations, missing odds, team mismatch, doubleheaders, tied scores and stable rerenders; desktop and 390px mobile browser inspection, image load checks, details interaction and no horizontal mobile overflow.
For teams without approved cutouts, the card uses a roster-verified hitter from the hit-projection list (highest listed probability), or the named starting pitcher, with a feathered MLB headshot. These are labeled FEATURED or STARTER and are not claimed to be action cutouts. If neither can be verified, only the logo remains.
