"""Horizon reconciliation after a figure turn: deterministic, no model (Leakage & Detective §5).

List A: post-horizon terms the figure actually used (find_breaches over its contribution).
List B: the sanctioned channels that could account for each — the question, an Oracle answer
the figure received, or a passage it opened. A term in A with no channel in B is a candidate
hard breach: `unbridged`. These are signals, not verdicts.
"""

from epistemic.horizon import find_breaches, term_stems
from retrieval.bm25 import analyse

METHOD = ("Term matching by stem, on mapped lineages only. Markers (old words in new senses) "
          "are not checked. Absence of unbridged hits is not evidence of clean reasoning.")
ANSWERED = ("bridged", "cannot_bridge")


def figure_text(contribution) -> str:
    """Everything the figure asserted: position, reasoning, extrapolation, citation supports."""
    parts = [contribution.position, contribution.reasoning, *contribution.extrapolation,
             *(c.supports for c in contribution.citations)]
    return "\n".join(parts)


def _stems(text):
    return [stem for _, stem in analyse(text)]


def _occurs(seq, stems):
    n = len(seq)
    return n > 0 and any(stems[i:i + n] == seq for i in range(len(stems) - n + 1))


def reconcile(contribution, question, oracle_requests, opened_passages, compiled) -> dict:
    """oracle_requests: the Oracle binding's state(); opened_passages: [(passage_id, text)]."""
    text = figure_text(contribution)
    text_stems = _stems(text)
    answered = [r for r in oracle_requests if r.get("outcome") in ANSWERED]

    channels = [("question", _stems(question))]
    for r in answered:
        channels.append((f"oracle:{r['number']}",
                         _stems(r["answer"]["explanation"]), _stems(r["concept"])))
    for passage_id, passage_text in opened_passages:
        channels.append((f"passage:{passage_id}", _stems(passage_text)))

    hits = []
    for hit in find_breaches(text, compiled):
        found = [name for name, *sources in channels
                 if any(_occurs(hit["stems"], s) for s in sources)]
        hits.append({**hit, "channels": found})

    uptake = {str(r["number"]): [h["matched_surface"] for h in hits
                                 if f"oracle:{r['number']}" in h["channels"]]
              for r in answered}
    return {
        "hits": hits,
        "unbridged": [h for h in hits if not h["channels"]],
        "bridges_unused": [{"number": r["number"], "concept": r["concept"]} for r in answered
                           if not _occurs(list(term_stems(r["concept"])), text_stems)],
        "uptake": uptake,
        "horizon_gaps": [{"number": r["number"], "concept": r["concept"]}
                         for r in oracle_requests
                         if r.get("outcome") != "refused" and r["lookup"]["kind"] == "unmapped"],
        "method": METHOD,
    }
