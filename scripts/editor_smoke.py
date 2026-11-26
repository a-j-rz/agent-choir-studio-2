"""Editor mechanics check (slice 5c, Stage 2; Decisions K10). Two runs: clean, then degraded.

    python -m scripts.editor_smoke --offline   # dry run: the probe's fake Editor answers
    python -m scripts.editor_smoke --live      # exactly 2 live calls: only the Editor's

The deliberation is the offline probe's synthetic one — fake Host, fake figures, fake passages,
all through scripts.choir_probe's fakes. Only the Editor call differs: in --live it goes to the
real API, once per run. This tests mechanics (schema accepted, output parsed, checks, length,
reasoning tokens, cost), not quality: the content is filler.
"""

import argparse
import asyncio
import json
import sys

import core.llm as llm
import scripts.choir_probe as probe
from choir import editor
from core.config import price_for, role_config

RUNS = [("clean", {}), ("degraded (one figure's contribution invalid)",
                        {"figure": {"plato": "invalid"}})]


def check_table(violations):
    """Every check, 1–10, with its result: the violations name their check numbers."""
    rows = []
    for n in range(1, 11):
        hits = [v for v in violations if v.startswith(f"check {n}:")]
        rows.append(f"  check {n:>2}: {'FAIL ' + '; '.join(hits) if hits else 'pass'}")
    return "\n".join(rows)


def cost_by_hand(trip):
    """The cost arithmetic, by hand, for a call that reasoned: reasoning sits inside output."""
    price = price_for(role_config("editor").model)
    plain = trip["input_tokens"] - trip["cached_input_tokens"] - trip["cache_write_tokens"]
    inside = (plain * price.input + trip["cached_input_tokens"] * price.cached_input
              + trip["cache_write_tokens"] * price.cache_write
              + trip["output_tokens"] * price.output) / 1e6
    on_top = inside + trip["reasoning_tokens"] * price.output / 1e6
    return "\n".join([
        f"  prices (USD per 1M): input {price.input}, cached {price.cached_input}, cache write "
        f"{price.cache_write}, output {price.output}",
        f"  ({plain} × {price.input} + {trip['cached_input_tokens']} × {price.cached_input} + "
        f"{trip['cache_write_tokens']} × {price.cache_write} + {trip['output_tokens']} × "
        f"{price.output}) / 1e6 = {inside:.8f}",
        f"  reasoning inside output: {inside:.8f} · if added on top: {on_top:.8f} · recorded "
        f"est_cost_usd: {trip['est_cost_usd']:.8f} → "
        + ("reasoning is priced inside output, not on top"
           if round(inside, 8) == trip["est_cost_usd"] else "MISMATCH")])


async def one_run(label, scenario_kwargs):
    events, error, run_dir, summary = await probe.run_case(probe.Scenario(**scenario_kwargs))
    print(f"\n################ {label}")
    print(f"trace: traces/{run_dir.name} · status {summary['status']}"
          + (f" · error {error}" if error else ""))
    trips = [e.payload for e in events if e.type == "round_trip" and e.role == "editor"]
    failed = [e.payload for e in events if e.type == "round_trip_failed" and e.role == "editor"]
    out_path = run_dir / "editor_output.json"
    output = json.loads(out_path.read_text()) if out_path.exists() else None
    print(f"schema accepted: {bool(trips) and not failed}"
          + (f" · call failed: {failed}" if failed else ""))
    parsed = output and output["parsed"]
    print(f"output parsed: {bool(parsed)}")
    if parsed:
        baseline = json.loads((run_dir / "baseline.json").read_text())
        record = next(e.payload for e in events if e.type == "host_decision_record")
        out = editor.EditorOutput.model_validate(parsed)
        violations = editor.check_editor_output(
            out, baseline, record["cast"]["would_reject"],
            degraded=baseline["run_outcome"] == "degraded")
        print("checks:\n" + check_table(violations))
        print(f"disposition: {out.synthesis.disposition}")
    print("full output (verbatim message texts):")
    for text in (output or {}).get("message_texts", []):
        print(text)
    for t in trips:
        print(f"tokens: input {t['input_tokens']} (cached {t['cached_input_tokens']}) · output "
              f"{t['output_tokens']} · reasoning {t['reasoning_tokens']} · latency "
              f"{t['latency_s']}s · cost ${t['est_cost_usd']:.8f}")
        if t["reasoning_tokens"] > 0:
            print(cost_by_hand(t))
    return len(trips), sum(t["est_cost_usd"] for t in trips)


async def main(live: bool) -> int:
    real_client = llm.get_client() if live else None  # before the fakes replace it
    restore = probe.install_fakes()
    probe.EDITOR_LIVE = real_client.responses.with_raw_response.create if live else None
    calls, cost = 0, 0.0
    try:
        for label, kwargs in RUNS:
            n, c = await one_run(label, kwargs)
            calls, cost = calls + n, cost + c
    finally:
        probe.EDITOR_LIVE = None
        restore()
    print(f"\nEditor calls: {calls} ({'live' if live else 'offline: fake Editor'}) · "
          f"estimated cost: ${cost:.8f}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--live", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args().live)))
