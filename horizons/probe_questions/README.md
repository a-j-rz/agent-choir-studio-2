# Probe questions

One file per figure: `<figure_id>.json`, read by `python -m scripts.horizon_coverage_probe
<figure_id>` (Decisions E1).

The questions a figure's coverage probe asks. Each is answered as a well-informed person today
would answer it; the probe then lists the concepts in those answers that are later than the
figure's horizon year and checks them against the figure's compiled Horizon. Schema:
`QuestionsFile` in `scripts/horizon_coverage_probe.py` (`schema_version` `"1"`): `source`, where
the questions came from, and `questions`, a non-empty list of strings.

Generated blind: `python -m scripts.generate_probe_questions <figure_id>` makes one `builder`
call whose prompt names no figure, no year and no project, and gives no example questions. The
`source` records the call's UTC time and the prompt's SHA-256; the raw request and response are
in the run's trace. So the questions cannot carry this project's own assumptions into the
lineages they test.

Write-once: the generator refuses to overwrite an existing file. Never edited, never curated, and
never reused as test questions.

`marcus_aurelius.json` is historical: the Phase 3 questions in hand, chosen by the owner, moved
here verbatim. It predates the generator.
