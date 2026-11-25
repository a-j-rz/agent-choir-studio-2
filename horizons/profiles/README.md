# Figure profiles

One file per figure: `<figure_id>.json` (Decisions E1).

A profile says where one figure stood. Schema: `Profile` in `epistemic/horizon.py`
(`schema_version` `"1"`): `figure_id`, `lived` (`born`, `died`), `horizon_year` and its
`horizon_year_basis`, `milieu`, `traditions` (each with basis and confidence — ids from
`../traditions.json`), `exceptions` (a sense made available or unavailable against the
date-and-tradition rule, with basis and confidence), and `oracle_epoch` — an epoch-only
description for the Oracle.

Reviewed by a human before it is compiled.
