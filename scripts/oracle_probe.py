"""Exercise the Oracle in isolation: handlers called directly, as a figure would. ≤ 8 live calls.

    python -m scripts.oracle_probe             # Turns A, B (6 live calls) and C (offline)
    python -m scripts.oracle_probe --offline   # no live calls: render composed inputs, Turn C

One traced run. Turn A (one binding): smartphone, SSRI, inflation (an identity-flag test by
description), then a 4th request that must be refused. Turn B (fresh binding): tea, blockchain,
quantum entanglement. Turn C (fresh binding, call_model patched to raise — no live call): a
request naming the figure (flagged and redacted), a plain simulated failure, and a repeat of
the second concept (repeat_of).

After each handler call the probe emits the same tool_result event core.llm.call_model would,
so the trace shows what the figure received.
"""

import asyncio
from functools import partial
import json
import sys
import time

import choir.oracle as oracle
from core.events import Event
from core.runner import relay
from core.trace import TRACES_DIR

FIGURE = "marcus_aurelius"
COST_CAP_USD = 0.01

TURN_A = [
    ("smartphone", "A traveller told me everyone now carries a 'smartphone' and looks at it constantly."),
    ("SSRI", "I heard that physicians now give a pill called an 'SSRI' to those who are anxious."),
    ("inflation", "as one who has ruled Rome these many years, I have seen coins lose their worth"),
    ("tea", "A merchant from the far east offered me a dried leaf he called 'tea'."),  # refused
]
TURN_B = [
    ("tea", "A merchant from the far east offered me a dried leaf he called 'tea'."),
    ("blockchain", "Someone said their wealth is now kept on a 'blockchain'."),
    ("quantum entanglement", "A learned visitor spoke of 'quantum entanglement' between distant particles."),
]
TURN_C = [
    ("inflation", "I, Marcus, have seen coins lose their worth"),
    ("smartphone", "A traveller told me everyone now carries a 'smartphone'."),
    ("smartphone", "Again: what is this 'smartphone' the traveller spoke of?"),
]
RENDER = [("A3", TURN_A[2]), ("B1", TURN_B[0]), ("B2", TURN_B[1]), ("C1", TURN_C[0])]


class ProbeStopped(Exception):
    pass


async def _simulated_outage(**_kwargs):
    raise RuntimeError("simulated Oracle outage (probe): no live call made")


async def run_turn(trace, label, requests, spent):
    lane = trace.for_figure(FIGURE)
    _, ask, state = oracle.bind_oracle(FIGURE, lane)
    trace.emit("probe_turn", "system", {"turn": label, "requests": len(requests)})
    for n, (concept, where) in enumerate(requests, 1):
        started = time.monotonic()
        result = await ask(concept=concept, where_encountered=where)
        lane.emit("tool_result", "figure", {
            "name": "ask_oracle", "call_id": f"probe-{label}{n}",
            "arguments": {"concept": concept, "where_encountered": where},
            "result": result, "duration_s": round(time.monotonic() - started, 3)})
        spent += state()[-1].get("cost_usd", 0.0)
        if spent > COST_CAP_USD:
            raise ProbeStopped(f"cost ${spent:.6f} passed ${COST_CAP_USD}")
        if label != "C" and state()[-1]["outcome"] == "failed":
            raise ProbeStopped(f"unexpected Oracle failure in turn {label}: {result}")
    return spent, state()


async def body(trace, offline=False):
    spent, a, b = 0.0, [], []
    if not offline:
        spent, a = await run_turn(trace, "A", TURN_A, spent)
        spent, b = await run_turn(trace, "B", TURN_B, spent)
    real = oracle.call_model
    oracle.call_model = _simulated_outage
    try:
        spent, c = await run_turn(trace, "C", TURN_C, spent)
    finally:
        oracle.call_model = real  # synchronous restore; no await here
    outcomes = {t: [r["outcome"] for r in s] for t, s in (("A", a), ("B", b), ("C", c)) if s}
    return {"outcomes": outcomes, "cost_usd": round(spent, 8)}


def line(event: Event) -> str:
    p = event.payload
    if event.type == "round_trip":
        d = (f"{p['latency_s']}s · in {p['input_tokens']} / out {p['output_tokens']} "
             f"(reasoning {p['reasoning_tokens']}) · ${p['est_cost_usd']:.6f}")
    elif event.type == "oracle_request":
        d = (f"#{p['number']} {p['concept']!r} · {p['lookup']['kind']} · identity "
             f"{p['identity_terms_in_request']} · repeat_of {p['repeat_of']}")
    elif event.type == "oracle_bridge":
        d = f"#{p['number']} {p['answer']['status']}"
    elif event.type == "tool_result":
        d = json.dumps(p["result"], ensure_ascii=False)[:120]
    else:
        d = json.dumps(p, ensure_ascii=False)[:200]
    return f"#{event.seq:<3} {event.type:<24} {event.role:<16} {d}"


def report(run_dir):
    events = [json.loads(x) for x in (run_dir / "events.jsonl").read_text().splitlines()]
    out, turn, trip = [], None, None
    for e in events:
        p = e["payload"]
        if e["type"] == "probe_turn":
            turn = p["turn"]
            out.append(f"\n################ TURN {turn}")
        elif e["type"] == "oracle_request":
            look = p["lookup"]
            composed = json.loads((run_dir / "raw" / p["input_file"]).read_text())
            out += [f"\n=== {turn}{p['number']}  concept {p['concept']!r}",
                    f"lookup: kind={look['kind']} lineage={look['lineage_id']} "
                    f"distance={look['bridge_distance']}",
                    f"  asker sense:  {look['asker_sense']}",
                    f"  target sense: {look['target_sense']}",
                    f"  hits: {[(h['matched_surface'], h['stems']) for h in look['hits']]}"
                    + (f"  his_match: {look['his_match']}" if look.get("his_match") else ""),
                    f"where_encountered: {p['where_encountered']!r} (truncated {p['truncated']})",
                    f"identity_terms_in_request: {p['identity_terms_in_request']} · "
                    f"redacted: {p['redacted']} · "
                    f"identity guarantee held: {p['identity_guarantee_held']} · "
                    f"repeat_of: {p['repeat_of']} · requests_used: {p['requests_used']}",
                    f"--- composed input ({p['input_file']}) ---",
                    "[instructions]", composed["instructions"].rstrip(),
                    f"[input] {json.dumps(composed['input'], ensure_ascii=False)}"]
        elif e["type"] == "round_trip" and e["role"] == "oracle":
            trip = p
        elif e["type"] == "oracle_bridge":
            out += ["--- answer ---", json.dumps(p["answer"], indent=2, ensure_ascii=False),
                    f"extra message items: {p['extra_message_items']} · tokens in "
                    f"{trip['input_tokens']} / out {trip['output_tokens']} (reasoning "
                    f"{trip['reasoning_tokens']}) · cost ${trip['est_cost_usd']:.8f}"]
        elif e["type"] == "oracle_failed":
            out += ["--- FAILED ---", json.dumps(p, ensure_ascii=False)]
        elif e["type"] == "oracle_request_refused":
            out += [f"\n=== {turn}{p['number']}  concept {p['concept']!r}  REFUSED",
                    json.dumps(p, ensure_ascii=False)]
        elif e["type"] == "tool_result" and turn == "C" or (
                e["type"] == "tool_result" and "error" in p["result"]):
            out.append(f"figure received: {json.dumps(p['result'], ensure_ascii=False)}")
    trips = [e["payload"] for e in events if e["type"] == "round_trip"]
    out.append(f"\nlive calls: {len(trips)} · estimated cost: "
               f"${sum(t['est_cost_usd'] for t in trips):.8f}")
    return "\n".join(out)


def render_composed():
    """The composed inputs for chosen requests, straight from choir.oracle.prepare(). No calls."""
    ctx = oracle.load_context(FIGURE)
    for label, (concept, where) in RENDER:
        prep = oracle.prepare(concept, where, ctx)
        print(f"\n=== {label}  {concept!r}  lookup {prep['lookup']['kind']} · identity "
              f"{prep['identity_terms_in_request']} · redacted {prep['redacted']}")
        print(prep["composed"]["instructions"].rstrip())
        print(f"[input] {json.dumps(prep['composed']['input'], ensure_ascii=False)}")


async def main(offline=False):
    events = []
    if offline:
        print("######## COMPOSED INPUTS (rendered from code; no Oracle call)")
        render_composed()
        print("\n######## TURN C, traced (call_model patched; no live call)")
    try:
        async for event in relay(partial(body, offline=offline), "oracle probe (3b)"
                                 + (" — offline" if offline else ""), render=lambda e: e):
            print(line(event), flush=True)
            events.append(event)
    except Exception as error:
        print(f"RUN FAILED: {error!r}")
    if not events:
        return 1
    run_dir = TRACES_DIR / events[-1].run_id
    print(f"\ntrace: traces/{events[-1].run_id}")
    print(report(run_dir))
    return 0 if events[-1].type == "run_complete" else 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args().offline)))
