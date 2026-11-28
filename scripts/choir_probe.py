"""Prove the four-figure substrate offline (slice 5a; Decisions K9). No network, no embedding model.

    python -m scripts.choir_probe --offline

Each case is its own traced run through choir.deliberation.deliberation_run (Host, then lanes).
The OpenAI client is faked at the create() level, so the real call_model, its retry and its
labelling are under test; the Host's three calls get canned answers the same way. The four
roster figures are in-memory fakes (BM25 built in memory; passages embedded and length-checked
with the model the loader is given). The model is an OwnedEncoder: deterministic vectors, and it
raises if two threads are ever inside it at once (Decisions K9, amended). The Oracle context reuses Marcus's compiled Horizon with each fake figure's own name. Canned
figure turns make real search, open and ask_oracle tool calls, so tools, budgets and flags run.
"""

import argparse
import asyncio
import copy
from functools import partial
import hashlib
import json
import re
import sys
import threading
import time
from types import SimpleNamespace

import httpx2
import numpy as np
import openai

import choir.deliberation as deliberation
import choir.editor as editor
import choir.oracle as oracle
import core.llm as llm
from choir.deliberation import deliberation_run
from core.config import CALLS, EMBEDDING
from core.runner import relay
from core.trace import TRACES_DIR, RunTrace
from host.cast import load_roster
from retrieval import bm25, hybrid, vectors

CAST = ["marcus_aurelius", "plato", "frederick_douglass", "charles_darwin"]
NAMES = {"marcus_aurelius": "Marcus Aurelius", "plato": "Plato",
         "frederick_douglass": "Frederick Douglass", "charles_darwin": "Charles Darwin"}
PREFIX = {"marcus_aurelius": "mar", "plato": "pla", "frederick_douglass": "fre",
          "charles_darwin": "cha"}
QUESTION = "How should a person govern their own mind?"
CANONICAL = "How should a person govern their own mind?"


# ---------------------------------------------------------------- fake figures

def passage_text(fid, i):
    """Unique marker words per figure, so a leak of another lane's text is detectable."""
    return f"Passage {i} by the {PREFIX[fid]}marker writer on mind, duty and conduct, line {i}."


class StandInEncoder:
    """Deterministic unit vectors from a hash of the text. Stands in for the embedding model."""

    def encode(self, texts, prompt=None, normalize_embeddings=False, convert_to_numpy=True,
               show_progress_bar=False):
        out = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(((prompt or "") + text).encode()).digest()[:8],
                                  "big")
            v = np.random.default_rng(seed).standard_normal(EMBEDDING.dimensions)
            out.append(v / np.linalg.norm(v))
        return np.asarray(out, dtype=np.float32)


class OwnedEncoder(StandInEncoder):
    """The stand-in model, with a misuse detector: every entry records its thread, holds a
    non-blocking guard while it works, and raises if another call is already inside — as a
    shared Hugging Face tokenizer does ("Already borrowed")."""

    def __init__(self):
        self._guard = threading.Lock()
        self.calls: list[tuple[str, str]] = []  # (what, thread name)
        self.overlaps: list[tuple[str, str]] = []
        self.hold_s = 0.003

    def _enter(self, what):
        name = threading.current_thread().name
        self.calls.append((what, name))
        if not self._guard.acquire(blocking=False):
            self.overlaps.append((what, name))
            raise RuntimeError(f"Already borrowed: {what} entered from {name} while in use")
        time.sleep(self.hold_s)

    def encode(self, texts, **kwargs):
        self._enter("encode")
        try:
            return super().encode(texts, **kwargs)
        finally:
            self._guard.release()

    def tokenizer(self, texts, add_special_tokens=True, truncation=False, verbose=False):
        self._enter("tokenizer")
        try:
            return {"input_ids": [[0] * (len(t.split()) + 2) for t in texts]}
        finally:
            self._guard.release()


MODEL = OwnedEncoder()
LOADS: list[tuple[float, float]] = []  # (start, end) of each fake figure load, for case 12
STATE = {"load_delay": 0.0, "unbuilt": set()}
_real_load_figure = hybrid.load_figure
_real_load_context = oracle.load_context
_real_horizon_preflight = deliberation.horizon_preflight
_marcus_ctx = None


def fake_load_figure(figure_id, model, allow_build=True):
    if figure_id in STATE["unbuilt"]:
        return _real_load_figure(figure_id, model, allow_build=allow_build)  # the real failure
    started = time.perf_counter()
    if STATE["load_delay"]:
        time.sleep(STATE["load_delay"])  # blocks its thread, as a real index load does
    # Two books (1–3, 4–6), so the Editor's same-book neighbour rule is actually exercised.
    chunks = [{"chunk_id": f"{PREFIX[figure_id]}-{i:03d}", "locator": f"{i}",
               "book": 1 if i <= 3 else 2,
               "text": passage_text(figure_id, i), "figure_id": figure_id} for i in range(1, 7)]
    lexical = bm25.build_from_analysed([{**c, "tokens": bm25.analyse(c["text"])} for c in chunks])
    vecs = vectors.embed_passages(model, chunks)  # length check + encode, with the given model
    LOADS.append((started, time.perf_counter()))
    manifest = {"figure_id": figure_id, "author": NAMES[figure_id],
                "included_works": [f"The Collected Notes of {NAMES[figure_id]}"],
                "prompt_edition": "in a plain English edition", "reading_rule": None,
                "translation_edition": {"translator": "a probe"}, "period": "probe period"}
    return {"figure_id": figure_id, "manifest": manifest, "chunks": chunks,
            "position": {c["chunk_id"]: i for i, c in enumerate(chunks)}, "bm25": lexical,
            "vectors": {"chunks": [{k: c[k] for k in ("chunk_id", "locator", "text")}
                                   for c in chunks], "vectors": vecs,
                        "meta": {"chunks_sha256": f"probe-{figure_id}"},
                        "cache": {"status": "hit"}},
            "cache": {"status": "hit"}}


def fake_load_context(figure_id):
    global _marcus_ctx
    if _marcus_ctx is None:
        _marcus_ctx = _real_load_context("marcus_aurelius")
    return {**_marcus_ctx, "name_stems": oracle.identity_stems(
        {"author": NAMES[figure_id]}, figure_id)}


# ---------------------------------------------------------------- fake OpenAI client

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/responses")


def err_5xx(retry_after="0"):
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return openai.InternalServerError("probe 503", response=httpx2.Response(
        503, request=REQUEST, headers=headers), body=None)


def err_connection():
    return openai.APIConnectionError(request=REQUEST)


def err_quota():
    return openai.RateLimitError("probe quota", response=httpx2.Response(
        429, request=REQUEST), body={"code": "insufficient_quota", "message": "quota"})


def message(obj):
    text = obj if isinstance(obj, str) else json.dumps(obj)
    return {"type": "message", "content": [{"type": "output_text", "text": text}]}


def call(name, n, **args):
    return {"type": "function_call", "name": name, "call_id": f"call-{name}-{n}",
            "arguments": json.dumps(args)}


def contribution(status="grounded", cited=None, insufficiency=None):
    return {"status": status, "position": "Govern the mind by judging what is in your power.",
            "reasoning": "The opened passage speaks of mind, duty and conduct.",
            "citations": [{"passage_id": p, "supports": "mind and conduct"} for p in (cited or [])],
            "extrapolation": [], "insufficiency": insufficiency}


TRIAGE = {"outcome": "proceed", "reason": "probe", "direct_answer": None,
          "clarifying_question": None, "explanation": None, "suggested_question": None,
          "canonical_question": CANONICAL, "answer_criterion": "A direct answer says how.",
          "factual_posture": "normative", "factual_gaps": []}


def score(scores):
    dims = ["value_conflict", "interpretive_ambiguity", "cross_domain_interaction",
            "challenge_value", "consequence_stakes"]
    return {"decomposition": "single", "primary_archetype": "Personal / Existential",
            "secondary_archetypes": [], "units": [{"text": CANONICAL, "depends_on": None, **{
                d: {"rationale": "probe", "score": s} for d, s in zip(dims, scores)}}]}


# J6: a roster-consistent rating is "adequate" where the corpus is built, "unassessable" where not.
ROSTER_CORPUS = {f.figure_id: f.corpus for f in load_roster()}


def assess(fid):
    return {"figure_id": fid, "archetype_relevance": {"reason": "probe", "rating": "adequate"},
            "question_fit": {"reason": "probe", "rating": "adequate"},
            "corpus_suitability": {"reason": "probe", "rating": "adequate"
                                   if ROSTER_CORPUS[fid] == "built" else "unassessable"}}


def cast_out(marcus_weak=False):
    assessments = [assess(f) for f in CAST]
    if marcus_weak:  # the gate would reject Marcus: code records would_reject (J6)
        assessments[0]["corpus_suitability"]["rating"] = "weak"
    return {"candidate_assessments": assessments, "selected": CAST,
            "panel_diversity": "probe", "panel_redundancy": "probe", "panel_tension": "probe",
            "near_misses": []}
ORACLE_ANSWER = {"status": "bridged", "explanation": "A thing a traveller carries.",
                 "anchors": ["couriers"], "left_out": []}


class Scenario:
    """What the fake client does. figure: per-figure script name; errors: (fid, trip) -> list
    of exceptions, one per attempt; delay: per-figure seconds before each response."""

    def __init__(self, figure=None, errors=None, delay=None, scores=(1, 0, 1, 0, 1),
                 editor=(), marcus_weak=False):
        self.editor = list(editor)  # named violations applied to the valid canned Editor output
        self.marcus_weak = marcus_weak
        self.figure = figure or {}
        self.errors = errors or {}
        self.delay = delay or {}
        self.scores = scores
        self.attempts: dict = {}


SCENARIO = Scenario()


def usage(request):
    size = len(json.dumps(request["input"]))
    return SimpleNamespace(
        input_tokens=100 + size // 40,
        input_tokens_details=SimpleNamespace(cached_tokens=0, cache_write_tokens=0),
        output_tokens=40 + size % 17,
        output_tokens_details=SimpleNamespace(reasoning_tokens=5 + size % 7))


class FakeRaw:
    def __init__(self, body, request):
        self.text = json.dumps(body)
        self._body, self._request = body, request

    def parse(self):
        texts = ["".join(p["text"] for p in item["content"]) for item in self._body["output"]
                 if item["type"] == "message"]
        return SimpleNamespace(usage=usage(self._request), output_text="".join(texts))


def figure_script(name, fid, trip):
    """The canned turn for one figure: trip 1 searches, trip 2 opens and asks the Oracle,
    trip 3 answers. Variants change the answer or skip steps."""
    first = f"{PREFIX[fid]}-001"
    if name == "insufficient_no_search":
        return [message(contribution("insufficient_corpus_basis", insufficiency={
            "looked_for": "governing the mind", "not_found": "any passage on it"}))]
    if trip == 1:
        return [call("search_my_corpus", 1, query=f"mind and duty {PREFIX[fid]}marker")]
    if name == "grounded_no_citations" and trip == 2:
        return [message(contribution("grounded", cited=[]))]
    if name == "open_two_cite_edge" and trip == 2:  # opens 003 and 005, will cite 003 only
        return [call("open_passage", 2, passage_id=f"{PREFIX[fid]}-003"),
                call("open_passage", 3, passage_id=f"{PREFIX[fid]}-005"),
                call("ask_oracle", 4, concept="smartphone",
                     where_encountered="a traveller mentioned it")]
    if name == "open_two_cite_edge":
        return [message(contribution("grounded", cited=[f"{PREFIX[fid]}-003"]))]
    if trip == 2:
        return [call("open_passage", 2, passage_id=first),
                call("ask_oracle", 3, concept="smartphone",
                     where_encountered="a traveller mentioned it")]
    if name == "invalid":
        return [message("this is not a contribution")]
    if name == "grounded_with_insufficiency":
        return [message(contribution("grounded", cited=[first], insufficiency={
            "looked_for": "x", "not_found": "y"}))]
    if name == "insufficient_null":
        return [message(contribution("insufficient_corpus_basis", cited=[]))]
    return [message(contribution("grounded", cited=[first]))]


def editor_output(editor_input_text, violations=()):
    """A valid Editor output built from the input the Editor actually received, then any named
    violations applied (c1–c9: one per code check; 'unparseable')."""
    if "unparseable" in violations:
        return "this is not an editor output"
    inp = json.loads(editor_input_text)
    figs = inp["figures"]
    would_reject = {h["figure_id"] for h in inp["host"]["figures"] if h["would_reject"]}
    contributed = [f for f in figs if f["outcome"] == "contributed"]
    c_ids = [f["figure_id"] for f in contributed]
    degraded = len(contributed) < len(figs)
    out = {
        "audit": {
            "figures": [{
                "figure_id": f["figure_id"], "reason": "probe",
                "answer_class": "answered" if f["outcome"] == "contributed" else "not_contributed",
                "evidence": [{"passage_id": p["passage_id"], "note": "probe", "verdict": "supports"}
                             for p in f.get("cited_passages", [])],
                "gate_check": ({"reason": "probe", "borne_out": False}
                               if f["figure_id"] in would_reject else None),
                "modern_knowledge": []} for f in figs],
            "disagreements": [{"about": "probe", "figures": c_ids[:2], "kind": "normative"}],
            "consensus": {"note": "probe", "counterfeit": False}},
        "synthesis": {
            "rationale": "probe", "disposition": "balanced_split", "answer": "probe answer",
            "convergence": [{"point": "probe", "figures": c_ids[:1]}],
            "unresolved": [{"point": "probe", "figures": c_ids[:2], "kind": "normative"}],
            "historical_citations": [{"figure_id": f["figure_id"],
                                      "passage_id": f["cited_passages"][0]["passage_id"],
                                      "supports": "probe"}
                                     for f in contributed if f["cited_passages"]],
            "modern_references": [{"figure_id": f["figure_id"], "bridge_number": e["number"],
                                   "used_for": "probe"}
                                  for f in contributed for e in f["modern_explanations"]
                                  if not e.get("unanswered")],
            "what_would_change": ["a probe fact"],
            "missing_perspective": "probe: one figure did not contribute" if degraded else None}}
    a, syn = out["audit"], out["synthesis"]
    first_c = next(f for f in a["figures"] if f["answer_class"] != "not_contributed")
    if "c1" in violations:
        a["figures"][0], a["figures"][1] = a["figures"][1], a["figures"][0]
    if "c2" in violations:
        first_c["answer_class"] = "not_contributed"
    if "c3" in violations:
        first_c["evidence"] = []
    if "c4" in violations:
        target = next(f for f in a["figures"] if f["figure_id"] not in would_reject)
        target["gate_check"] = {"reason": "probe", "borne_out": True}
    if "c5" in violations:
        a["disagreements"][0]["figures"] = c_ids[:1]
    if "c6" in violations:
        syn["historical_citations"].append({"figure_id": c_ids[0], "passage_id": "zzz-999",
                                            "supports": "probe"})
    if "c7" in violations:
        syn["modern_references"].append({"figure_id": c_ids[0], "bridge_number": 99,
                                         "used_for": "probe"})
    if "c8" in violations:
        syn["what_would_change"] = []
    if "c9" in violations:
        syn["missing_perspective"] = None if degraded else "probe: nobody was missing"
    return out


EDITOR_LIVE = None  # editor_smoke --live: the real client's create, for the Editor call only


class FakeResponses:
    async def _create(self, **request):
        fmt = request["text"]["format"]["name"]
        fid = None
        if fmt in ("contribution",):
            author = re.search(r"You are (.+?)\. You answer", request["instructions"]).group(1)
            fid = next(f for f, n in NAMES.items() if n == author)
        elif fmt == "oracle_answer":
            fid = "oracle"
        elif fmt == "editor_output":
            fid = "editor"
            if EDITOR_LIVE is not None:
                return await EDITOR_LIVE(**request)
        trip = 1 + sum(1 for i in request["input"] if i.get("type") == "function_call_output")
        key = (fid, trip)
        attempt = SCENARIO.attempts[key] = SCENARIO.attempts.get(key, 0) + 1
        await asyncio.sleep(SCENARIO.delay.get(fid, 0.01))
        planned = SCENARIO.errors.get(key, [])
        if attempt <= len(planned) and planned[attempt - 1] is not None:
            raise planned[attempt - 1]
        if fmt == "host_triage":
            output = [message(TRIAGE)]
        elif fmt == "host_classification":
            output = [message(score(SCENARIO.scores))]
        elif fmt == "host_cast":
            output = [message(cast_out(SCENARIO.marcus_weak))]
        elif fmt == "oracle_answer":
            output = [message(ORACLE_ANSWER)]
        elif fmt == "editor_output":
            output = [message(editor_output(request["input"][0]["content"], SCENARIO.editor))]
        else:
            output = figure_script(SCENARIO.figure.get(fid, "clean"), fid, trip)
        return FakeRaw({"output": output}, request)

    @property
    def with_raw_response(self):
        return SimpleNamespace(create=self._create)


FAKE_CLIENT = SimpleNamespace(responses=FakeResponses())


# ---------------------------------------------------------------- running a case

async def run_case(scenario, on_event=None):
    """One traced deliberation run. Returns (events, error, run_dir, summary)."""
    global SCENARIO
    SCENARIO = scenario
    events, error = [], None
    agen = relay(partial(deliberation_run, question=QUESTION), "choir probe (5a)",
                 render=lambda e: e)
    try:
        async for event in agen:
            events.append(event)
            if on_event and on_event(event):
                await agen.aclose()
                break
    except Exception as exc:
        error = repr(exc)
    run_dir = TRACES_DIR / events[0].run_id
    for _ in range(50):  # an aborted run's summary is written by its own finally
        if (run_dir / "summary.json").exists():
            break
        await asyncio.sleep(0.02)
    summary = json.loads((run_dir / "summary.json").read_text())
    return events, error, run_dir, summary


def lane_events(events, fid):
    return [e for e in events if e.figure == fid]


def baseline(run_dir):
    path = run_dir / "baseline.json"
    return json.loads(path.read_text()) if path.exists() else None


def outcomes(run_dir):
    b = baseline(run_dir)
    return {f["figure_id"]: f["outcome"] for f in b["figures"]} if b else None


def failed_class(events, fid):
    return next((e.payload["failure_class"] for e in events
                 if e.type == "figure_failed" and e.figure == fid), None)


def check(cond, msg, misses):
    if not cond:
        misses.append(msg)


# ---------------------------------------------------------------- cases

async def case_0():
    """The client is built with the SDK's retries off and the configured timeout."""
    misses, seen = [], {}

    class Recorder:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            self.responses = None

    real = llm.AsyncOpenAI, llm.load_dotenv, llm._client
    llm.AsyncOpenAI, llm.load_dotenv, llm._client = Recorder, lambda *a, **k: None, None
    try:
        llm.get_client()
    finally:
        llm.AsyncOpenAI, llm.load_dotenv, llm._client = real
    check(seen.get("max_retries") == 0, f"max_retries {seen.get('max_retries')!r} != 0", misses)
    check(seen.get("timeout") == CALLS.timeout_s, f"timeout {seen.get('timeout')!r}", misses)
    return None, misses


async def case_1():
    events, error, run_dir, summary = await run_case(Scenario())
    misses = []
    check(summary["status"] == "complete", f"status {summary['status']} {error}", misses)
    check(outcomes(run_dir) == {f: "contributed" for f in CAST}, f"outcomes {outcomes(run_dir)}",
          misses)
    check([e.seq for e in events] == list(range(1, len(events) + 1)), "seq has gaps", misses)
    for e in events:
        if e.role in ("figure", "oracle"):
            check(e.figure in CAST, f"#{e.seq} {e.type} role {e.role} has figure {e.figure!r}",
                  misses)
        else:
            check(e.figure is None, f"#{e.seq} {e.type} role {e.role} has figure {e.figure!r}",
                  misses)
    # The stamp is the right figure, not just present: each figure round trip's raw request
    # was written for that figure, and its file name carries the same lane.
    for e in events:
        if e.type == "round_trip" and e.figure:
            raw = e.payload["raw_file"]
            check(re.match(rf"^\d{{4}}-{e.figure}-{e.role}-rt\d+\.json$", raw) is not None,
                  f"raw file {raw} for lane {e.figure}", misses)
            if e.role == "figure":
                text = (run_dir / "raw" / raw).read_text()
                check(f"You are {NAMES[e.figure]}." in text, f"{raw}: not {e.figure}'s request",
                      misses)
    for name in sorted(p.name for p in (run_dir / "raw").iterdir()):
        lane = next((f for f in CAST if f"-{f}-" in name), None)
        if lane:
            check(re.match(rf"^\d{{4}}-{lane}-(figure|oracle)-", name) is not None,
                  f"raw name {name}", misses)
        else:
            check(re.match(r"^\d{4}-(host|editor)-", name) is not None, f"raw name {name}",
                  misses)
    labels = [e.figure for e in events if e.figure]
    switches = sum(1 for a, b in zip(labels, labels[1:]) if a != b)
    check(switches > len(CAST), f"lanes did not interleave ({switches} switches)", misses)
    # Baseline tokens and cost equal the lane's round_trip events, figure and Oracle, summed
    # here from the events as streamed (not from the file the orchestrator read back).
    b = baseline(run_dir)
    for f in (b["figures"] if b else []):
        trips = [e.payload for e in events if e.type == "round_trip" and e.figure == f["figure_id"]]
        want = {"round_trips": len(trips),
                **{k: sum(t[k] for t in trips) for k in ("input_tokens", "cached_input_tokens",
                                                         "output_tokens", "reasoning_tokens")},
                "est_cost_usd": round(sum(t["est_cost_usd"] for t in trips), 8)}
        roles = {e.role for e in events if e.type == "round_trip" and e.figure == f["figure_id"]}
        check(roles == {"figure", "oracle"}, f"{f['figure_id']} round-trip roles {roles}", misses)
        check(f["tokens_and_cost"] == want,
              f"{f['figure_id']} baseline {f['tokens_and_cost']} != events {want}", misses)
    return run_dir, misses


async def case_2():
    events, error, run_dir, summary = await run_case(Scenario())
    misses = []
    for fid in CAST:
        others = [f for f in CAST if f != fid]
        forbidden = [*others, *(f"{PREFIX[f]}-0" for f in others),
                     *(f"{PREFIX[f]}marker" for f in others), *(NAMES[f] for f in others)]
        files = [p for p in (run_dir / "raw").iterdir() if f"-{fid}-" in p.name]
        check(len(files) >= 5, f"{fid}: only {len(files)} raw files", misses)
        for p in files:
            text = p.read_text()
            hits = [w for w in forbidden if w in text]
            check(not hits, f"{p.name} contains {hits}", misses)
    return run_dir, misses


async def case_3():
    sc = Scenario(errors={("plato", 1): [err_5xx("0")]})
    events, error, run_dir, summary = await run_case(sc)
    misses = []
    retries = [e for e in events if e.type == "round_trip_retry"]
    check(len(retries) == 1 and retries[0].figure == "plato", f"retries {retries}", misses)
    check(retries and retries[0].payload["wait_source"] == "retry_after", "wait source", misses)
    check(not [e for e in events if e.type == "round_trip_failed"], "a round_trip_failed", misses)
    check(outcomes(run_dir) == {f: "contributed" for f in CAST}, f"{outcomes(run_dir)}", misses)
    check("degraded" not in summary["annotations"], "degraded", misses)
    return run_dir, misses


async def case_4():
    sc = Scenario(errors={("plato", 1): [err_connection(), err_connection()]})
    events, error, run_dir, summary = await run_case(sc)
    misses = []
    retries = [e for e in events if e.type == "round_trip_retry"]
    failed = [e for e in events if e.type == "round_trip_failed"]
    check(len(retries) == 1 and retries[0].payload["wait_s"] == CALLS.retry_wait_s
          and retries[0].payload["wait_source"] == "config", f"retries {retries}", misses)
    check(len(failed) == 1 and failed[0].payload["transient"] is True
          and failed[0].payload["attempts"] == 2, f"failed {failed}", misses)
    check(failed_class(events, "plato") == "transient_exhausted",
          f"class {failed_class(events, 'plato')}", misses)
    check(summary["status"] == "complete" and summary["annotations"].get("degraded") == ["plato"],
          f"status {summary['status']} annotations {summary['annotations']}", misses)
    return run_dir, misses


async def case_5():
    sc = Scenario(errors={("plato", 1): [err_quota()]})
    events, error, run_dir, summary = await run_case(sc)
    misses = []
    failed = [e for e in events if e.type == "round_trip_failed"]
    check(not [e for e in events if e.type == "round_trip_retry"], "retried the spend cap", misses)
    check(len(failed) == 1 and failed[0].payload["transient"] is False
          and failed[0].payload["code"] == "insufficient_quota"
          and failed[0].payload["status"] == 429, f"failed {failed}", misses)
    check(summary["annotations"].get("degraded") == ["plato"], "not degraded", misses)
    return run_dir, misses


async def case_6():
    events, error, run_dir, summary = await run_case(Scenario(figure={"plato": "invalid"}))
    misses = []
    check([e.figure for e in events if e.type == "contribution_invalid"] == ["plato"],
          "no contribution_invalid for plato", misses)
    check(not [e for e in events if e.type == "round_trip_retry"], "retried an invalid answer",
          misses)
    check(failed_class(events, "plato") == "contribution_invalid", "class", misses)
    check(summary["annotations"].get("degraded") == ["plato"], "not degraded", misses)
    return run_dir, misses


async def case_7():
    misses, dirs = [], []
    for variant in ("grounded_with_insufficiency", "insufficient_null"):
        events, error, run_dir, summary = await run_case(Scenario(figure={"plato": variant}))
        dirs.append(run_dir.name)
        check(failed_class(events, "plato") == "contribution_invalid",
              f"{variant}: plato {failed_class(events, 'plato')}, outcomes {outcomes(run_dir)}",
              misses)
    return " · ".join(dirs), misses


async def case_8():
    sc = Scenario(figure={"plato": "insufficient_no_search",
                          "charles_darwin": "grounded_no_citations"})
    events, error, run_dir, summary = await run_case(sc)
    misses = []
    checks = {e.figure: e.payload for e in events if e.type == "citation_check"}
    want = {"plato": (True, False), "charles_darwin": (False, True),
            "marcus_aurelius": (False, False), "frederick_douglass": (False, False)}
    for fid, (dws, gwc) in want.items():
        got = (checks.get(fid, {}).get("declared_without_search"),
               checks.get(fid, {}).get("grounded_without_citations"))
        check(got == (dws, gwc), f"{fid} flags {got} != {(dws, gwc)}", misses)
    check(outcomes(run_dir) == {f: "contributed" for f in CAST}, "a flag failed a figure", misses)
    b = baseline(run_dir)
    check(b and next(f for f in b["figures"] if f["figure_id"] == "plato")["check_flags"]
          == {"declared_without_search": True, "grounded_without_citations": False},
          "baseline flags", misses)
    return run_dir, misses


async def case_9():
    sc = Scenario(figure={"plato": "invalid", "charles_darwin": "invalid"},
                  delay={"marcus_aurelius": 0.4, "frederick_douglass": 0.4})
    events, error, run_dir, summary = await run_case(sc)
    misses = []
    check(summary["status"] == "failed", f"status {summary['status']}", misses)
    check(error and "ChoirHardFail" in error, f"error {error}", misses)
    check(outcomes(run_dir) == {"marcus_aurelius": "cancelled_by_hard_fail", "plato": "failed",
                                "frederick_douglass": "cancelled_by_hard_fail",
                                "charles_darwin": "failed"}, f"outcomes {outcomes(run_dir)}",
          misses)
    cancelled = {e.figure: e.payload["reason"] for e in events if e.type == "figure_cancelled"}
    check(cancelled == {"marcus_aurelius": "cancelled_by_hard_fail",
                        "frederick_douglass": "cancelled_by_hard_fail"}, f"{cancelled}", misses)
    check(baseline(run_dir) and baseline(run_dir)["run_outcome"] == "hard_fail", "baseline",
          misses)
    return run_dir, misses


async def case_10(runs):
    """Baseline checks over the clean, degraded and hard-fail runs, then a direct double write."""
    misses = []
    for label, run_dir in runs.items():
        events = [json.loads(x) for x in (run_dir / "events.jsonl").read_text().splitlines()]
        path = run_dir / "baseline.json"
        check(path.exists(), f"{label}: no baseline.json", misses)
        named = [e for e in events if e["type"] == "independent_baseline"]
        check(len(named) == 1, f"{label}: {len(named)} independent_baseline events", misses)
        if not (path.exists() and named):
            continue
        check(named[0]["payload"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest(),
              f"{label}: hash differs", misses)
        last_lane = max(e["seq"] for e in events if e.get("figure"))
        check(named[0]["seq"] > last_lane, f"{label}: baseline event before a lane event", misses)
        check(named[0]["role"] == "system" and named[0].get("figure") is None,
              f"{label}: baseline event labelled {named[0]['role']}/{named[0].get('figure')}",
              misses)
    trace = RunTrace()
    trace.write_baseline({"probe": 1})
    try:
        trace.write_baseline({"probe": 2})
        misses.append("a second write_baseline did not raise")
    except RuntimeError:
        pass
    trace.finish("complete")
    return f"{' · '.join(r.name for r in runs.values())} + {trace.run_id}", misses


async def case_11():
    sc = Scenario(delay={f: 0.3 for f in CAST})
    seen = {"n": 0}

    def stop(event):  # leave once the lanes are mid-call
        seen["n"] += event.type == "round_trip" and event.figure is not None
        return seen["n"] >= 2

    events, error, run_dir, summary = await run_case(sc, on_event=stop)
    await asyncio.sleep(0.15)
    misses = []
    check(summary["status"] == "aborted", f"status {summary['status']}", misses)
    file_events = [json.loads(x) for x in (run_dir / "events.jsonl").read_text().splitlines()]
    types = [e["type"] for e in file_events]
    check("run_aborted" in types and "round_trip" not in types[types.index("run_aborted"):],
          "round_trip after run_aborted", misses)
    pending = [t.get_name() for t in asyncio.all_tasks()
               if t.get_name().startswith("lane:") and not t.done()]
    check(not pending, f"lane tasks still pending: {pending}", misses)
    for t in asyncio.all_tasks():  # keep later cases clean even when this one fails
        if t.get_name().startswith("lane:"):
            t.cancel()
    await asyncio.sleep(0.05)
    return run_dir, misses


async def case_12():
    STATE["load_delay"], LOADS[:] = 0.3, []
    ticks = []

    async def ticker():
        while True:
            ticks.append(time.perf_counter())
            await asyncio.sleep(0.05)

    tick_task = asyncio.create_task(ticker())
    try:
        events, error, run_dir, summary = await run_case(Scenario())
    finally:
        tick_task.cancel()
        STATE["load_delay"] = 0.0
    misses = []
    inside = sum(1 for t in ticks if any(s < t < e for s, e in LOADS))
    check(len(LOADS) == 4, f"{len(LOADS)} loads", misses)
    check(inside >= 3, f"only {inside} ticks during the loads", misses)
    bound = [e.payload["load_ms"] for e in events if e.type == "figure_bound"]
    check(len(bound) == 4 and all(ms >= 290 for ms in bound), f"load_ms {bound}", misses)
    return run_dir, misses


async def case_13():
    events, error, run_dir, summary = await run_case(Scenario(scores=(2, 2, 1, 0, 0)))
    misses = []
    types = [e.type for e in events]
    check("topology_not_built" in types, "no topology_not_built", misses)
    check(summary["status"] == "complete", f"status {summary['status']}", misses)
    check(summary["annotations"].get("outcome") == "topology_not_built", "outcome", misses)
    check(not [e for e in events if e.figure], "figure events on a token-ring run", misses)
    check(not (run_dir / "baseline.json").exists(), "baseline on a token-ring run", misses)
    nb = next((e for e in events if e.type == "topology_not_built"), None)
    check(nb and nb.payload["rule"] == "governing total 5 ≥ 5 → token_ring", "rule", misses)
    return run_dir, misses


async def case_14():
    STATE["unbuilt"] = {"plato"}
    try:
        events, error, run_dir, summary = await run_case(Scenario())
    finally:
        STATE["unbuilt"] = set()
    misses = []
    check(failed_class(events, "plato") == "cannot_access_corpus",
          f"plato {failed_class(events, 'plato')}", misses)
    check(summary["annotations"].get("degraded") == ["plato"], "not degraded", misses)
    return run_dir, misses


# ---------------------------------------------------------------- Editor cases (5c, K10)

EDITOR_FILES = ("baseline.json", "editor_input.json", "editor_output.json")
FORBIDDEN_KEYS = {"horizon_reconciliation", "reconciliation", "unbridged", "hits", "merged",
                  "lexical_rank", "semantic_rank", "rrf_score", "instructions", "opened",
                  "candidates", "raw_file"}


def editor_events(events):
    return [e for e in events if e.role == "editor"]


def all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from all_keys(v)


def editor_failed(events, summary, run_dir, check_label, misses, error=None):
    """The shared expectation for an Editor failure."""
    inv = [e.payload for e in events if e.type == "editor_invalid"]
    text = json.dumps(inv, ensure_ascii=False)
    check(len(inv) == 1 and check_label in text, f"editor_invalid naming {check_label!r}: {text[:300]}",
          misses)
    check(summary["status"] == "failed", f"status {summary['status']}", misses)
    out = [e.payload for e in events if e.type == "editor_output"]
    check(len(out) == 1 and out[0]["valid"] is False, f"editor_output {out}", misses)
    for name in EDITOR_FILES:
        check((run_dir / name).exists(), f"{name} missing", misses)
    check(not [e for e in events if e.type in ("editor_audit", "editor_synthesis")],
          "audit/synthesis emitted on an invalid output", misses)


async def case_e1():
    events, error, run_dir, summary = await run_case(Scenario())
    misses = []
    ed = editor_events(events)
    check(ed and ed[0].type == "editor_input", f"first Editor event {ed[0].type if ed else None}",
          misses)
    text = (run_dir / "editor_input.json").read_text(encoding="utf-8")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    check(ed and ed[0].payload["sha256"] == sha, "editor_input hash differs from the file", misses)
    bound = next((e for e in ed if e.type == "editor_bound"), None)
    check(bound and bound.payload["input_sha256"] == sha, "editor_bound input hash", misses)
    trip = next((e for e in ed if e.type == "round_trip"), None)
    sent = json.loads((run_dir / "raw" / trip.payload["raw_file"]).read_text())["request"] if trip else None
    check(sent and sent["input"][0]["content"] == text, "the request did not carry the file's exact text",
          misses)
    check(sent and len(sent["input"]) == 1, "the Editor request has more than one input item", misses)
    order = [e.type for e in ed]
    check(order[:3] == ["editor_input", "editor_bound", "round_trip"], f"order {order}", misses)
    return run_dir, misses


CAPTURED = {}


async def case_e2():
    real = editor.compile_editor_input

    def capture(*args):
        CAPTURED["args"] = copy.deepcopy(args)
        return real(*args)
    editor.compile_editor_input = capture
    try:
        events, error, run_dir, summary = await run_case(Scenario())
    finally:
        editor.compile_editor_input = real
    misses = []
    first = editor.serialise(real(*copy.deepcopy(CAPTURED["args"])))
    second = editor.serialise(real(*copy.deepcopy(CAPTURED["args"])))
    check(first == second, "two compiles of the same inputs differ", misses)
    check(first.encode("utf-8") == (run_dir / "editor_input.json").read_bytes(),
          "a recompile differs from the written file", misses)
    return run_dir, misses


async def case_e3():
    sc = Scenario(figure={"plato": "open_two_cite_edge", "charles_darwin": "invalid"})
    events, error, run_dir, summary = await run_case(sc)
    misses = []
    text = (run_dir / "editor_input.json").read_text(encoding="utf-8")
    inp = json.loads(text)
    blocks = {f["figure_id"]: f for f in inp["figures"]}
    plato = blocks.get("plato", {})
    cited = plato.get("cited_passages", [])
    check([p["passage_id"] for p in cited] == ["pla-003"], f"plato cited {cited}", misses)
    neighbours = [(n["side"], n["passage_id"]) for p in cited for n in p["context_neighbours"]]
    check(neighbours == [("before", "pla-002")], f"neighbours {neighbours} (pla-004 is book 2)",
          misses)
    check("pla-005" not in text, "an opened-but-uncited passage reached the Editor input", misses)
    check(set(blocks.get("charles_darwin", {})) == {"figure_id", "name", "outcome", "failure_class"},
          f"failed block keys {sorted(blocks.get('charles_darwin', {}))}", misses)
    check(blocks.get("charles_darwin", {}).get("failure_class") == "contribution_invalid",
          "failure class", misses)
    leaked = sorted(set(all_keys(inp)) & FORBIDDEN_KEYS)
    check(not leaked, f"forbidden keys in the Editor input: {leaked}", misses)
    check([f["figure_id"] for f in inp["figures"]] == CAST, "figures not in cast order", misses)
    check(summary["status"] == "complete", f"status {summary['status']} {error}", misses)
    return run_dir, misses


async def case_e4():
    events, error, run_dir, summary = await run_case(Scenario())
    misses = []
    types = [e.type for e in editor_events(events)]
    check(types[-3:] == ["editor_output", "editor_audit", "editor_synthesis"], f"{types}", misses)
    out = next((e.payload for e in events if e.type == "editor_output"), {})
    check(out.get("valid") is True, f"editor_output {out}", misses)
    check(summary["status"] == "complete", f"status {summary['status']} {error}", misses)
    check(summary["annotations"].get("disposition") == "balanced_split", "disposition annotation",
          misses)
    check("editor" not in summary["annotations"], "editor: not_built still annotated", misses)
    return run_dir, misses


def editor_check_case(n, violation, **scenario):
    async def run():
        events, error, run_dir, summary = await run_case(Scenario(editor=[violation], **scenario))
        misses = []
        editor_failed(events, summary, run_dir, f"check {n}:", misses)
        return run_dir, misses
    return run


async def case_e8_positive():
    """would_reject names Marcus: a gate_check for him (and only him) passes check 4."""
    events, error, run_dir, summary = await run_case(Scenario(marcus_weak=True))
    misses = []
    check(summary["status"] == "complete", f"status {summary['status']} {error}", misses)
    audit = next((e.payload for e in events if e.type == "editor_audit"), {})
    gates = {f["figure_id"]: f["gate_check"] is not None for f in audit.get("figures", [])}
    check(gates == {"marcus_aurelius": True, "plato": False, "frederick_douglass": False,
                    "charles_darwin": False}, f"gate checks {gates}", misses)
    return run_dir, misses


async def case_e14():
    events, error, run_dir, summary = await run_case(Scenario(editor=["c5", "c8", "c9"]))
    misses = []
    editor_failed(events, summary, run_dir, "check 5:", misses)
    inv = json.dumps([e.payload for e in events if e.type == "editor_invalid"])
    for label in ("check 5:", "check 8:", "check 9:"):
        check(label in inv, f"{label} not reported", misses)
    return run_dir, misses


async def case_e15():
    events, error, run_dir, summary = await run_case(Scenario(editor=["unparseable"]))
    misses = []
    editor_failed(events, summary, run_dir, "H4:", misses)
    check(not [e for e in events if e.type == "round_trip_retry"], "retried an unparseable output",
          misses)
    check(len([e for e in events if e.type == "round_trip" and e.role == "editor"]) == 1,
          "more than one Editor call", misses)
    return run_dir, misses


async def case_e16():
    events, error, run_dir, summary = await run_case(Scenario(errors={("editor", 1): [err_5xx("0")]}))
    misses = []
    retries = [e for e in events if e.type == "round_trip_retry"]
    check(len(retries) == 1 and retries[0].role == "editor", f"retries {retries}", misses)
    out = next((e.payload for e in events if e.type == "editor_output"), {})
    check(out.get("valid") is True and summary["status"] == "complete",
          f"editor_output {out} status {summary['status']}", misses)
    return run_dir, misses


async def case_e17():
    misses, dirs = [], []
    events, error, run_dir, summary = await run_case(Scenario(figure={"plato": "invalid"}))
    dirs.append(run_dir.name)
    synth = next((e.payload for e in events if e.type == "editor_synthesis"), {})
    check(summary["status"] == "complete" and summary["annotations"].get("degraded") == ["plato"],
          f"degraded run status {summary['status']} {error}", misses)
    check(bool(synth.get("missing_perspective")), "no missing_perspective on a degraded run", misses)
    audit = next((e.payload for e in events if e.type == "editor_audit"), {})
    plato = next((f for f in audit.get("figures", []) if f["figure_id"] == "plato"), {})
    check(plato.get("answer_class") == "not_contributed" and plato.get("evidence") == [],
          f"plato audit {plato}", misses)
    events, error, run_dir, summary = await run_case(Scenario(figure={"plato": "invalid"},
                                                              editor=["c9"]))
    dirs.append(run_dir.name)
    editor_failed(events, summary, run_dir, "check 9:", misses)
    return " · ".join(dirs), misses


async def case_e18():
    misses, dirs = [], []
    events, error, run_dir, summary = await run_case(
        Scenario(figure={"plato": "invalid", "charles_darwin": "invalid"},
                 delay={"marcus_aurelius": 0.4, "frederick_douglass": 0.4}))
    dirs.append(run_dir.name)
    check(summary["status"] == "failed" and not editor_events(events),
          f"hard fail: status {summary['status']}, Editor events {len(editor_events(events))}",
          misses)
    check(not (run_dir / "editor_input.json").exists(), "editor_input.json on a hard fail", misses)
    events, error, run_dir, summary = await run_case(Scenario(scores=(2, 2, 1, 0, 0)))
    dirs.append(run_dir.name)
    check(summary["status"] == "complete" and not editor_events(events),
          f"token-ring: Editor events {len(editor_events(events))}", misses)
    return " · ".join(dirs), misses


async def case_17():
    """Decisions K3 as built: Darwin is not a translation. His real Manifest's
    translation_edition.translator is null, and list_my_works() returns it as None."""
    from retrieval.tools import bind_corpus_tools
    manifest = json.loads((hybrid.CORPORA_DIR / "charles_darwin" / "manifest.json").read_text(encoding="utf-8"))
    misses = []
    check(manifest["translation_edition"]["translator"] is None,
          f"Darwin's Manifest translator is {manifest['translation_edition']['translator']!r}",
          misses)
    figure = {**fake_load_figure("charles_darwin", MODEL), "manifest": manifest}
    trace = RunTrace()
    try:
        _, handlers, _ = bind_corpus_tools(figure, MODEL, trace.for_figure("charles_darwin"))
        try:
            works = handlers["list_my_works"]()
        except Exception as error:
            works, misses = None, misses + [f"list_my_works raised {error!r}"]
        if works is not None:
            check(works["translator"] is None, f"translator {works['translator']!r}", misses)
            check(works["author"] == "Charles Darwin", f"author {works['author']!r}", misses)
    finally:
        trace.finish("complete")
    return trace.dir, misses


WORDS = ["governing", "government", "governs", "consciousness", "conscious", "happily",
         "happiness", "relational", "relations", "duties", "dutiful", "running", "generously",
         "generalization", "national", "nationalism", "hopefulness", "hoped", "philosophical",
         "philosophies", "reasonable", "reasoning", "adaptation", "adaptive", "selection",
         "selective", "justified", "justice", "dominating", "domination", "consequences",
         "consequential", "ideals", "idealistic", "agency", "agencies", "meaningfulness",
         "controlling", "controllables", "emergence", "emerging", "variations", "harmonious"]


async def case_18():
    """Decisions K12: the real Horizon pre-flight guard, against the real roster and horizons.
    A built figure with no compiled Horizon (Plato) refuses the run before any model call."""
    scenario = Scenario()
    deliberation.horizon_preflight = _real_horizon_preflight  # the real guard, this case only
    try:
        events, error, run_dir, summary = await run_case(scenario)
    finally:
        deliberation.horizon_preflight = lambda: None
    misses = []
    check(error is not None and "RuntimeError" in error and "plato" in error,
          f"expected RuntimeError naming plato, got {error}", misses)
    calls = sum(scenario.attempts.values())
    check(calls == 0, f"{calls} model calls recorded", misses)
    check(summary["status"] == "failed", f"status {summary['status']}", misses)
    return run_dir, misses


async def case_15():
    """The stemmer under threads: every result equals the single-threaded one."""
    import random
    rng = random.Random(5)
    texts = [" ".join(rng.choice(WORDS) for _ in range(rng.randint(3, 12))) for _ in range(200)]
    expected = [bm25.analyse(t) for t in texts]
    mismatches, errors = [0], []
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # switch threads as often as possible: provoke any race

    def worker(barrier, order):
        barrier.wait()
        for i in order:
            try:
                if bm25.analyse(texts[i]) != expected[i]:
                    mismatches[0] += 1
            except Exception as error:
                errors.append(repr(error))
    try:
        for trial in range(20):
            barrier = threading.Barrier(8)
            threads = [threading.Thread(target=worker, args=(barrier, rng.sample(range(200), 200)))
                       for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
    finally:
        sys.setswitchinterval(interval)
    misses = []
    check(mismatches[0] == 0, f"{mismatches[0]} stem mismatches", misses)
    check(not errors, f"{len(errors)} exceptions, e.g. {errors[:2]}", misses)
    return "8 threads × 200 texts × 20 trials", misses


async def case_16():
    """One model owner: loads and searches overlap in time, yet every model call runs on the
    owner thread and no call ever enters while another is inside."""
    STATE["load_delay"] = 0.15
    MODEL.calls, MODEL.overlaps, MODEL.hold_s = [], [], 0.02
    try:
        events, error, run_dir, summary = await run_case(Scenario())
    finally:
        STATE["load_delay"], MODEL.hold_s = 0.0, 0.003
    misses = []
    threads = {name for _, name in MODEL.calls}
    check(MODEL.calls and all(name.startswith("model_") for name in threads),
          f"model calls on threads {sorted(threads)}", misses)
    check(not MODEL.overlaps, f"{len(MODEL.overlaps)} overlapping entries {MODEL.overlaps[:3]}",
          misses)
    check(outcomes(run_dir) == {f: "contributed" for f in CAST}, f"outcomes {outcomes(run_dir)}",
          misses)
    kinds = {what for what, _ in MODEL.calls}
    check(kinds == {"encode", "tokenizer"}, f"model calls seen {kinds}", misses)
    return run_dir, misses


async def case_1_repeated(n=20):
    passed, failures = 0, []
    for _ in range(n):
        run_dir, misses = await case_1()
        if misses:
            failures.append(f"{run_dir.name}: {misses[:2]}")
        else:
            passed += 1
    return f"{passed} of {n} passed", ([] if passed == n else failures)


def install_fakes():
    """Patch in the fake client, figures, Oracle context and model. Returns a restore function."""
    patches = [(llm, "_client", FAKE_CLIENT), (hybrid, "load_figure", fake_load_figure),
               (oracle, "load_context", fake_load_context),
               (deliberation, "horizon_preflight", lambda: None),
               (vectors, "get_model", lambda: MODEL)]
    saved = [(obj, name, getattr(obj, name)) for obj, name, _ in patches]
    for obj, name, value in patches:
        setattr(obj, name, value)

    def restore():
        for obj, name, value in saved:
            setattr(obj, name, value)
    return restore


async def offline() -> int:
    restore = install_fakes()
    rows = []

    async def run(label, coro):
        try:
            where, misses = await coro
        except Exception as error:  # a case that crashes is a failing case
            where, misses = None, [f"case raised {error!r}"]
        rows.append((label, where, misses))
        return where

    try:
        await run("0  client: SDK retries off, timeout set", case_0())
        r1 = await run("1  clean run, lanes stamped, baseline = events", case_1())
        await run("2  no cross-talk in lane raw files", case_2())
        await run("3  one transient error, recovered", case_3())
        r4 = await run("4  two transient errors → degraded", case_4())
        await run("5  insufficient_quota: final, no retry", case_5())
        await run("6  invalid contribution, never retried", case_6())
        await run("7  schema 2 contradictions rejected", case_7())
        await run("8  check flags", case_8())
        r9 = await run("9  two failures → hard fail", case_9())
        runs = {k: v for k, v in (("clean", r1), ("degraded", r4), ("hard_fail", r9)) if v}
        await run("10 baseline once, hashed, after lanes", case_10(runs))
        await run("11 abort mid-lane", case_11())
        await run("12 loads off the loop", case_12())
        await run("13 token-ring → topology_not_built", case_13())
        await run("14 unbuilt corpus → cannot_access_corpus", case_14())
        await run("15 stemmer under threads", case_15())
        await run("17 null translator → list_my_works", case_17())
        await run("18 Horizon pre-flight: refuses before any call", case_18())
        await run("16 one model owner", case_16())
        await run("1×20 case 1 repeated", case_1_repeated())
        await run("E1 input written, hashed, sent verbatim", case_e1())
        await run("E2 compile twice → identical bytes", case_e2())
        await run("E3 input: neighbours, no uncited, no flags", case_e3())
        await run("E4 valid output → audit, synthesis", case_e4())
        await run("E5 check 1: audit ids are the cast", editor_check_case(1, "c1")())
        await run("E6 check 2: not_contributed ⇔ failed", editor_check_case(2, "c2")())
        await run("E7 check 3: evidence = cited", editor_check_case(3, "c3")())
        await run("E8 check 4: gate_check ⇔ would_reject", editor_check_case(4, "c4")())
        await run("E8+ would_reject: gate_check passes", case_e8_positive())
        await run("E9 check 5: ≥2 figures, in cast", editor_check_case(5, "c5")())
        await run("E10 check 6: citations were cited", editor_check_case(6, "c6")())
        await run("E11 check 7: references were bridged", editor_check_case(7, "c7")())
        await run("E12 check 8: what_would_change", editor_check_case(8, "c8")())
        await run("E13 check 9: missing_perspective", editor_check_case(9, "c9")())
        await run("E14 three violations, all reported", case_e14())
        await run("E15 unparseable → invalid, no retry", case_e15())
        await run("E16 one transient error, recovered", case_e16())
        await run("E17 degraded: Editor runs, perspective", case_e17())
        await run("E18 hard fail, token-ring: no Editor", case_e18())
    finally:
        restore()

    print("\n######## CHOIR PROBE (offline: 0 live calls, no embedding model)")
    for label, where, misses in rows:
        loc = where if isinstance(where, str) else (f"traces/{where.name}" if where else "-")
        print(f"{'PASS' if not misses else 'FAIL'}  {label:<48} {loc}"
              + (f"\n      {misses}" if misses else ""))
    ok = all(not m for _, _, m in rows)
    print(f"\n{len(rows)} cases · all checks {'passed' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", required=True)
    parser.parse_args()
    sys.exit(asyncio.run(offline()))
