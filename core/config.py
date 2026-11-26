"""The one place that says which model and reasoning effort each role uses (Decisions H1).

Nothing else may name a model or an effort. Call sites ask `role_config(role)`; traces record
`config_snapshot()` at run start, so every run says what it actually ran with.
It is also the one place that names the local embedding model (Decisions B4).
"""

from types import MappingProxyType
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict

# Exactly the values the Responses API accepts for reasoning.effort. A typo below fails at import.
Effort = Literal["none", "low", "medium", "high", "xhigh", "max"]


class RoleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    reasoning_effort: Effort


class ModelPrice(BaseModel):
    """List price in USD per 1M tokens.

    Cached reads and cache writes are both slices of input, priced instead of the input rate,
    never on top of it. Reasoning is a slice of output.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    input: float  # uncached input that is not written to the cache
    cached_input: float  # input read from the cache
    cache_write: float  # input written to the cache
    output: float  # reasoning tokens are part of output and billed at this rate


# Every seat starts here; a seat is promoted only on trace evidence (Decisions H1, H3).
LUNA = "gpt-6-luna"

# Checked against OpenAI's model page 2026-11-12 (Decisions H3). Prices drift; re-check on change.
# Re-checked 2026-11-25, before the Host's first live call: prices unchanged; structured outputs,
# the Responses API and `medium` reasoning effort all supported.
PRICES: Mapping[str, ModelPrice] = MappingProxyType(
    {
        LUNA: ModelPrice(input=0.10, cached_input=0.01, cache_write=0.125, output=0.50),
    }
)

# Built when the module loads, so an invalid value stops the server before any run starts.
# MappingProxyType makes the mapping read-only; frozen=True makes each entry read-only.
ROLES: Mapping[str, RoleConfig] = MappingProxyType(
    {
        "figure": RoleConfig(model=LUNA, reasoning_effort="low"),
        "oracle": RoleConfig(model=LUNA, reasoning_effort="low"),
        "host": RoleConfig(model=LUNA, reasoning_effort="medium"),
        "researcher": RoleConfig(model=LUNA, reasoning_effort="medium"),
        "editor": RoleConfig(model=LUNA, reasoning_effort="high"),
        "detective": RoleConfig(model=LUNA, reasoning_effort="high"),
        # Offline build tooling only (Horizon coverage); never part of a figure run.
        "builder": RoleConfig(model=LUNA, reasoning_effort="medium"),
    }
)


class EmbeddingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str
    revision: str  # a full Hub commit SHA, never a branch name
    dimensions: int
    max_tokens: int
    pooling: Literal["cls"]  # anything else fails at import
    normalise: bool
    query_instruction: str  # prefixed to queries only, never to passages


# Decisions B4. Each field is asserted against the loaded model in retrieval/vectors.py.
EMBEDDING = EmbeddingConfig(
    model_id="BAAI/bge-small-en-v1.5",
    revision="5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
    dimensions=384,
    max_tokens=512,
    pooling="cls",
    normalise=True,
    query_instruction="Represent this sentence for searching relevant passages: ",
)


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rrf_k: int  # each list adds 1/(rrf_k + rank) to an item's merged score (Decisions B2)
    candidate_depth: int  # how far down each of BM25 and vector RRF looks
    results_per_search: int  # merged results the model sees per search
    searches_per_turn: int  # per figure per turn
    opens_per_turn: int  # passages returned by open_passage / open_context, per turn
    context_window_max: int  # neighbours each side that open_context may return
    preview_chars: int  # characters of text shown per search result


# Corpus-tool limits per figure per turn (CHOIR_AND_CORPUS §6).
RETRIEVAL = RetrievalConfig(
    rrf_k=60,
    # Decided from the 2e depth measurement: with 8 results per search, RRF gives each list
    # ~4 slots unless items appear in both; deeper lists add consensus items that crowd out
    # single-method catches ("mastering my thoughts": 2 catches survive at depth 8, 1 at 15,
    # 0 at 30).
    candidate_depth=8,
    results_per_search=8,
    searches_per_turn=4,
    opens_per_turn=8,
    context_window_max=2,
    preview_chars=200,
)


class OracleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requests_per_turn: int  # per figure per turn, separate from corpus budgets
    where_encountered_max_chars: int  # the figure's own words, cut to this before sending


# The Oracle's per-turn limits (CHOIR_AND_CORPUS §6; System §7).
ORACLE = OracleConfig(requests_per_turn=3, where_encountered_max_chars=300)


class CallsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_s: float  # per request, passed to the client explicitly
    retry_wait_s: float  # before the one retry, when the error gives no Retry-After
    max_retry_wait_s: float  # a Retry-After longer than this is capped


# One logged retry per failed request, for every role (Topology & Steering §14; Decisions K9).
CALLS = CallsConfig(timeout_s=180, retry_wait_s=2, max_retry_wait_s=30)


def role_config(role: str) -> RoleConfig:
    """The config for one role. An unknown role raises; there is no silent default."""
    try:
        return ROLES[role]
    except KeyError:
        raise KeyError(f"unknown role {role!r}; known roles: {', '.join(ROLES)}") from None


def price_for(model: str) -> ModelPrice:
    """The price of one model. A model with no price raises; cost is never silently zero."""
    try:
        return PRICES[model]
    except KeyError:
        raise KeyError(f"no price for model {model!r}; priced models: {', '.join(PRICES)}") from None


# Every role must have a price, checked at import: a promoted seat without one fails here.
for _role, _cfg in ROLES.items():
    price_for(_cfg.model)


def config_snapshot() -> dict[str, dict[str, Any]]:
    """A plain-dict copy of the whole config, safe to JSON-encode into a trace.

    Each role carries its model's prices, so a summary records the rates its cost estimates used.
    """
    return {
        "roles": {
            role: {**cfg.model_dump(), "usd_per_1m_tokens": price_for(cfg.model).model_dump()}
            for role, cfg in ROLES.items()
        },
        "embedding": EMBEDDING.model_dump(),
        "retrieval": RETRIEVAL.model_dump(),
        "oracle": ORACLE.model_dump(),
        "calls": CALLS.model_dump(),
    }
