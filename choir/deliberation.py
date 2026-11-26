"""A deliberation run: the Host, then the Choir in the topology the Host's score chose (K1, K9).

    host_decide → not proceed: the Host's outcome, as host_run returns it
                → token_ring: topology_not_built, run complete (Phase 6; never a silent
                  hub-and-spoke — there is no threshold override)
                → hub_and_spoke: four lanes over the cast, then the independent baseline

No Editor yet (5c): annotated `editor: not_built` on the hub path. No endpoint in this slice.
"""

from typing import Any

from choir.hub_and_spoke import hub_and_spoke
from core.trace import RunTrace
from host.run import host_decide


async def deliberation_run(trace: RunTrace, question: str, condition: str = "A") -> dict[str, Any]:
    decision = await host_decide(trace, question)
    if decision.choir_input is None:
        return decision.returned
    scoring = decision.scored.scoring
    if scoring.topology == "token_ring":
        trace.emit("topology_not_built", "system", {"topology": scoring.topology,
                                                    "rule": scoring.rule})
        trace.annotate("outcome", "topology_not_built")
        return {**decision.returned, "outcome": "topology_not_built"}
    trace.annotate("editor", "not_built")
    choir = await hub_and_spoke(trace, decision.choir_input,
                                list(decision.cast.record.output.selected), condition)
    return {**decision.returned, "choir": choir}
