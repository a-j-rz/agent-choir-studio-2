"""A deliberation run: the Host, then the Choir in the topology the Host's score chose (K1, K9).

    host_decide → not proceed: the Host's outcome, as host_run returns it
                → token_ring: topology_not_built, run complete (Phase 6; never a silent
                  hub-and-spoke — there is no threshold override)
                → hub_and_spoke: four lanes over the cast, then the independent baseline,
                  then the Editor (K10): it runs on a complete or degraded Choir, never after
                  a Choir hard fail (which has already raised) or an unbuilt topology
"""

from typing import Any

from choir.editor import run_editor
from choir.hub_and_spoke import hub_and_spoke
from core.trace import RunTrace
from epistemic import horizon
from host.cast import load_roster
from host.run import host_decide


def horizon_preflight() -> None:
    """Refuse a deliberation run before any model call if a built figure's compiled Horizon is
    missing or stale, which would otherwise surface as a lane failure after the Host's paid calls,
    recorded as a degraded run (Decisions K12). Reads the roster and horizons; writes nothing."""
    problems = []
    for figure in load_roster():
        if figure.corpus != "built":
            continue
        found = horizon.check(horizon.HORIZONS_DIR, figure.figure_id)
        if not found:
            continue
        if found[0].startswith("no compiled file"):
            problems.append(f"{figure.figure_id} — {found[0]}")
        else:
            problems.append(f"{figure.figure_id} — compiled file is stale "
                            f"(differs in {', '.join(found)})")
    if problems:
        raise RuntimeError("horizon preflight: " + "; ".join(problems)
                           + "; compile its Horizon before a deliberation run")


async def deliberation_run(trace: RunTrace, question: str, condition: str = "A") -> dict[str, Any]:
    horizon_preflight()
    decision = await host_decide(trace, question)
    if decision.choir_input is None:
        return decision.returned
    scoring = decision.scored.scoring
    if scoring.topology == "token_ring":
        trace.emit("topology_not_built", "system", {"topology": scoring.topology,
                                                    "rule": scoring.rule})
        trace.annotate("outcome", "topology_not_built")
        return {**decision.returned, "outcome": "topology_not_built"}
    choir = await hub_and_spoke(trace, decision.choir_input,
                                list(decision.cast.record.output.selected), condition)
    names = {f.figure_id: f.name for f in load_roster()}
    editor = await run_editor(trace, decision.choir_input, decision.record, choir, names,
                              degraded=choir.summary["run_outcome"] == "degraded")
    return {**decision.returned, "choir": choir.summary, "editor": editor}
