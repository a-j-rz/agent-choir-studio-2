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


# Every seat starts here; a seat is promoted only on trace evidence (Decisions H1, H3).
LUNA = "gpt-6-luna"

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


def config_snapshot() -> dict[str, dict[str, Any]]:
    """A plain-dict copy of the whole config, safe to JSON-encode into a trace."""
    return {role: cfg.model_dump() for role, cfg in ROLES.items()}
