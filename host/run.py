"""The Host's run bodies: call 1, then calls 2 and 3 if and only if call 1 returned proceed.

Call 3 receives the canonical question and call 2's archetypes, and nothing else: not the scores,
not the topology, not the original wording.

The decision record is emitted once, at the end, carrying everything. ChoirInput is emitted just
before it, on proceed only: the canonical question, and nothing the Host learned on the way.
"""

from typing import Any, NamedTuple

from core.trace import RunTrace
from host.cast import Cast, select_cast
from host.records import ChoirInput, HostDecisionRecord
from host.score import Scored, score_canonical
from host.triage import Triaged, host_outcome, run_triage


class HostDecision(NamedTuple):
    """Everything the Host decided, reachable by whoever runs the Choir next."""

    triaged: Triaged
    scored: Scored | None
    cast: Cast | None
    record: HostDecisionRecord
    choir_input: ChoirInput | None  # on proceed only
    returned: dict[str, Any]  # exactly what host_run returns


def _finish(trace: RunTrace, question: str, t: Triaged, scored: Scored | None,
            cast: Cast | None = None) -> HostDecision:
    out = t.output
    prompts = {"triage": t.prompt_sha256}
    if scored is not None:
        prompts["score"] = scored.prompt_sha256
    if cast is not None:
        prompts["cast"] = cast.prompt_sha256
    record = HostDecisionRecord(
        original_question=question, prompt_sha256=prompts, triage=out,
        research_needed=t.research_needed,
        researcher_status="not_built" if t.research_needed else None,
        classification=scored.classification if scored else None,
        scoring=scored.scoring if scored else None,
        cast=cast.record if cast else None)

    choir_input = None
    if out.outcome == "proceed":
        choir_input = ChoirInput(canonical_question=out.canonical_question)
        trace.emit("choir_input", "host", choir_input.model_dump())
    trace.emit("host_decision_record", "host", record.model_dump())

    outcome = host_outcome(out)
    trace.annotate("host_outcome", outcome)
    returned = {"host_outcome": outcome}
    if out.outcome == "answer_directly":
        returned["answer"] = out.direct_answer
    if scored is not None:
        returned["topology"] = scored.scoring.topology
    return HostDecision(t, scored, cast, record, choir_input, returned)


async def host_decide(trace: RunTrace, question: str) -> HostDecision:
    """Triage, then (on proceed) scoring and cast. The same events as host_run, in the same order."""
    t = await run_triage(trace, question)
    scored = cast = None
    if t.output.outcome == "proceed":
        scored = await score_canonical(trace, t.output.canonical_question,
                                       research_needed=bool(t.research_needed))
        c = scored.classification
        cast = await select_cast(trace, t.output.canonical_question, c.primary_archetype,
                                 list(c.secondary_archetypes))
    return _finish(trace, question, t, scored, cast)


async def host_run(trace: RunTrace, question: str) -> dict[str, Any]:
    """The Host alone, as a run body. Returns outcome, answer, topology."""
    return (await host_decide(trace, question)).returned


async def host_triage_only(trace: RunTrace, question: str) -> dict[str, Any]:
    """Call 1 alone (stage 2a). On proceed the record's classification and scoring stay null."""
    trace.annotate("host_mode", "triage_only")
    return _finish(trace, question, await run_triage(trace, question), None).returned
