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
