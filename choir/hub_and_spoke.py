"""Hub-and-spoke: four figure turns at once, isolated, each in its own lane (Topology §9, §14;
Decisions K9).

    get the embedding model (worker thread)
    → one task per figure, in cast order: figure_turn in its lane; the lane catches its own error,
      classifies it, emits figure_failed and returns — no exception escapes a lane
    → await lanes as they finish; a second failure cancels the rest (cancelled_by_hard_fail)
    → the independent baseline, written once, on every outcome
    → 0 failed: complete · 1 failed: complete, degraded · 2+ failed: ChoirHardFail (run failed)

Not a TaskGroup: it cancels every sibling on the first failure, and one failure must only
degrade the run. And because asyncio.wait does not cancel what it waits on when the waiter is
cancelled, a `finally` cancels any lane still pending — or an aborted run keeps paying for four.
"""

import asyncio
import json
from typing import Any

from choir.contribution import ContributionInvalid
from choir.figure_turn import RoundTripCapReached, figure_turn
from core.llm import TransientExhausted
from core.trace import RunTrace
from host.records import ChoirInput
from retrieval import vectors

BASELINE_SCHEMA_VERSION = 1


class ChoirHardFail(Exception):
    """Two or more figures failed: the run hard-fails, with no synthesis (Topology §14)."""


def classify(error: BaseException) -> str:
    if isinstance(error, TransientExhausted):
        return "transient_exhausted"
    if isinstance(error, ContributionInvalid):
        return "contribution_invalid"
    if isinstance(error, RoundTripCapReached):
        return "round_trip_cap"
    if isinstance(error, FileNotFoundError):  # includes vectors.CorpusUnavailable
        return "cannot_access_corpus"
    return "other"


async def _lane(trace: RunTrace, figure_id: str, choir_input: ChoirInput, condition: str,
                model) -> dict[str, Any]:
    """One figure's turn. Returns its result; never raises, except when cancelled."""
    lane = trace.for_figure(figure_id)
    try:
        result = await figure_turn(lane, choir_input, condition, model)
        return {"figure_id": figure_id, "outcome": "contributed", "result": result}
    except asyncio.CancelledError as cancel:
        reason = str(cancel.args[0]) if cancel.args else "cancelled"
        try:
            lane.emit("figure_cancelled", "figure", {"reason": reason})
        except RuntimeError:
            pass  # the run already finished (aborted): run_aborted records it; nothing to add
        raise
    except Exception as error:
        failure = classify(error)
        lane.emit("figure_failed", "figure", {"failure_class": failure, "error": repr(error)})
        return {"figure_id": figure_id, "outcome": "failed", "failure_class": failure,
                "error": repr(error)}


def _lane_costs(trace: RunTrace) -> dict[str, dict[str, Any]]:
    """Per figure, the tokens and cost of every round trip in its lane, figure and Oracle,
    read back from this run's own events.jsonl (written and flushed before each emit returned)."""
    costs: dict[str, dict[str, Any]] = {}
    with (trace.dir / "events.jsonl").open(encoding="utf-8") as f:
        for line in f:
            event = json.loads(line)
            if event["type"] != "round_trip" or event.get("figure") is None:
                continue
            p = event["payload"]
            c = costs.setdefault(event["figure"], {
                "round_trips": 0, "input_tokens": 0, "cached_input_tokens": 0,
                "output_tokens": 0, "reasoning_tokens": 0, "est_cost_usd": 0.0})
            c["round_trips"] += 1
            for key in ("input_tokens", "cached_input_tokens", "output_tokens",
                        "reasoning_tokens", "est_cost_usd"):
                c[key] += p[key]
    for c in costs.values():
        c["est_cost_usd"] = round(c["est_cost_usd"], 8)
    return costs


def _baseline(trace: RunTrace, choir_input: ChoirInput, cast: list[str],
              lanes: dict[str, dict[str, Any]], run_outcome: str) -> dict[str, Any]:
    costs = _lane_costs(trace)
    figures = []
    for figure_id in cast:
        lane = lanes[figure_id]
        entry = {"figure_id": figure_id, "outcome": lane["outcome"],
                 "tokens_and_cost": costs.get(figure_id, {
                     "round_trips": 0, "input_tokens": 0, "cached_input_tokens": 0,
                     "output_tokens": 0, "reasoning_tokens": 0, "est_cost_usd": 0.0})}
        if lane["outcome"] == "contributed":
            r = lane["result"]
            entry.update({k: r[k] for k in ("contribution", "check_flags", "search_queries",
                                            "opened", "cited", "oracle_bridges")})
        else:
            entry.update({"failure_class": lane.get("failure_class"), "error": lane.get("error")})
        figures.append(entry)
    return {"schema_version": BASELINE_SCHEMA_VERSION, "run_id": trace.run_id,
            "topology": "hub_and_spoke", "choir_input": choir_input.model_dump(),
            "cast": list(cast), "figures": figures, "run_outcome": run_outcome}


async def hub_and_spoke(trace: RunTrace, choir_input: ChoirInput, cast: list[str],
                        condition: str = "A") -> dict[str, Any]:
    trace.annotate("condition", condition)
    model = await vectors.on_model(vectors.get_model)
    tasks = {asyncio.create_task(_lane(trace, fid, choir_input, condition, model),
                                 name=f"lane:{fid}"): fid for fid in cast}
    lanes: dict[str, dict[str, Any]] = {}
    try:
        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                fid = tasks[task]
                if task.cancelled():
                    lanes[fid] = {"figure_id": fid, "outcome": "cancelled_by_hard_fail"}
                else:
                    lanes[fid] = task.result()
            failed = [f for f, r in lanes.items() if r["outcome"] == "failed"]
            if len(failed) >= 2 and pending:
                for task in pending:
                    task.cancel("cancelled_by_hard_fail")
                # Let each cancelled lane record figure_cancelled before the baseline is written.
                await asyncio.wait(pending)
                for task in pending:
                    lanes[tasks[task]] = {"figure_id": tasks[task],
                                          "outcome": "cancelled_by_hard_fail"}
                pending = set()
    finally:
        # No await here: the run may be mid-cancellation. Synchronous cancels only.
        for task in tasks:
            if not task.done():
                task.cancel("run cancelled while lanes were running")

    failed = [fid for fid in cast if lanes[fid]["outcome"] == "failed"]
    run_outcome = "complete" if not failed else "degraded" if len(failed) == 1 else "hard_fail"
    name, sha = trace.write_baseline(_baseline(trace, choir_input, cast, lanes, run_outcome))
    trace.emit("independent_baseline", "system", {
        "file": name, "sha256": sha,
        "figures": {fid: lanes[fid]["outcome"] for fid in cast}, "run_outcome": run_outcome})

    if len(failed) >= 2:
        raise ChoirHardFail(f"{len(failed)} figures failed: " + ", ".join(
            f"{fid} ({lanes[fid]['failure_class']})" for fid in failed))
    if failed:
        trace.annotate("degraded", failed)
    return {"topology": "hub_and_spoke", "run_outcome": run_outcome,
            "figures": {fid: lanes[fid]["outcome"] for fid in cast}, "baseline_sha256": sha}
