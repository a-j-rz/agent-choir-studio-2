# Compiled Horizons

One file per figure: `<figure_id>.json`, written by `python -m scripts.compile_horizon
<figure_id>` from `../traditions.json`, `../profiles/<figure_id>.json` and every file in
`../lineages/`. Never edit these by hand.

This compiled file is what is reviewed and committed (Decisions E1). Its `sources_sha256`
covers every source it was built from, so `python -m scripts.compile_horizon <figure_id>
--check` fails, naming the difference, when a source has changed since.
