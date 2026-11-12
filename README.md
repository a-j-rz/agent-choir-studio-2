# Agent Choir Studio V2

A local, disposable learning instrument for multi-agent orchestration,
evidence-bounded historical agents, topology effects and epistemic leakage.
Not a product. The trace is the point; the final answer is a by-product.

**Status:** Phase 0 (bootstrap). No application code yet.

## Where to start

The design lives in [`docs/`](docs/). Begin with
[`docs/AGENT_CHOIR_V2_INDEX.md`](docs/AGENT_CHOIR_V2_INDEX.md), which gives the
reading order. The docs are the source of truth for intent; once code exists,
the code is the source of truth for behaviour.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
cp .env.example .env   # then add your own API key
```

Corpus texts, built indexes, run traces and `.env` are gitignored by design.
