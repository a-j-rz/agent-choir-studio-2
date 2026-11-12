# CLAUDE.md — standing rules for this repo

Agent Choir Studio V2: a local, disposable **learning instrument** for multi-agent orchestration,
evidence-bounded historical agents, topology effects and epistemic leakage. Not a product.
**The trace is the point; the final answer is a by-product.**

## Where things live

- **Intent and design:** `docs/` — start at `docs/AGENT_CHOIR_V2_INDEX.md`. The non-technical
  glossary is at the repo root. Read the docs a brief points you to before writing anything.
- **Behaviour:** the code. If code and docs disagree on behaviour, the code is the truth; on
  intent, the docs are.
- **Status:** `docs/AGENT_CHOIR_V2_BUILD_PLAN.md` — phases, and what "done" means for each.
- **Settled decisions:** `docs/AGENT_CHOIR_V2_DECISIONS.md`. Don't reopen anything not marked OPEN.

## How to work

- **I'm learning while building.** Explain the concept before the code, and show a file's
  shape before writing it. Small, legible diffs. No premature abstraction.
- **One slice at a time.** Do exactly what the brief scopes. If something adjacent needs doing,
  say so — don't do it.
- **Never commit or push.** Stop when the acceptance tests pass. Show me the evidence, then
  `git status --short` and `git diff --stat`. I review and commit.
- **Report drift.** End every slice by listing anything you did that wasn't in the brief, and
  anything in the brief you didn't do.
- **"Done" means the trace shows it**, not that the code runs.

## Hard constraints

- **No agent frameworks** (LangChain, OpenAI Agents SDK, CrewAI, …), **no MCP for corpus
  retrieval, no hosted vector stores.** The orchestration and retrieval loops are the lesson.
- **Out of scope:** self-improving loops, cross-run state, user override of cast or topology,
  cross-checking-LLM passes, production hardening, real system integration. See the Build Plan.
- **Every run is stateless.** Nothing from one run may reach another.
- **No identifying information** in any file you write: no employer or personal names, no email addresses, no hostnames, no absolute paths from this machine. The project-owned domain named in Decisions G4 is known and accepted — don't flag it.
Before you finish a slice, run
  `git grep` for identifying strings over tracked files and report the result.
- **Never read, print or echo `.env`.** Read secrets only through the environment at runtime.
- **Corpus texts and built indexes never enter the repo.** Commit the recipe, not the texts.
  `traces/` stays gitignored.

## Code conventions

- Python 3.12 · FastAPI · asyncio · Pydantic v2 · hand-rolled SSE · vanilla HTML/JS.
- **Every event goes through `RunTrace.emit()`**, which writes before it returns — the browser
  never sees what the trace doesn't hold. Every run calls `RunTrace.finish()` from a `finally`.
- **No `yield` and no `await` inside a `finally`** in a run generator: the client may be gone and
  the task cancelled. Only synchronous writes there.
- **Model calls use the OpenAI Responses API only** (Decisions H2). **Model name and reasoning
  effort come only from `core/config.py`** — never hard-coded at a call site.
  Exception: `spikes/` is frozen Phase 0 evidence — never edit it.

## Testing

- Test against `http://127.0.0.1:8000` with `curl` (use `-N` for streams). Stop the server when done.
- **Live model calls cost money.** Make one only when the brief says to, and say how many you made.
  The API key has a hard spend cap — an unexpected API error may be the cap, not the code.
