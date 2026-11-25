# Concept lineages

One file per lineage: `<lineage_id>.json`, shared by every figure (Decisions E1).

A lineage is one concept through time — an ordered list of era-specific senses, oldest first.
Each sense id starts with `<lineage_id>.`. Schema: `Lineage` in `epistemic/horizon.py`
(`schema_version` `"1"`): `lineage_id`, `label`, `lcc_class` (one Library of Congress main
class letter), `wikidata` (`Q…` or null), and `senses`, each with `available_in` (tradition,
`from` year — BCE negative, no year 0 — and precision), `prerequisites`, `terms`, `markers`,
`hazards`, `sources` and `confidence`.

Seeded only for the questions in hand; grown on trace evidence. After any edit, recompile
the affected figures: `python -m scripts.compile_horizon <figure_id>`.
