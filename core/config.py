"""The one place that says which model and reasoning effort each role uses (Decisions H1).

Nothing else may name a model or an effort. Call sites ask `role_config(role)`; traces record
`config_snapshot()` at run start, so every run says what it actually ran with.
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
    }
)


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
        role: {**cfg.model_dump(), "usd_per_1m_tokens": price_for(cfg.model).model_dump()}
        for role, cfg in ROLES.items()
    }
