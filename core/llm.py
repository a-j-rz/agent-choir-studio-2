"""The one model-call wrapper: a traced tool-call loop on the Responses API (Decisions H2).

Every model call in the system goes through `call_model`. Per round trip it writes the raw
request/response to raw/, then emits a `round_trip` event naming that file; per tool execution it
emits a `tool_result` event. It never stops silently: the loop ends either `answered` or with a
`round_trip_cap_reached` event.
"""

import inspect
import json
import time
from typing import Any, Callable, Literal, Mapping

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel

from core.config import ModelPrice, price_for, role_config
from core.events import utc_iso
from core.trace import RunTrace

StopReason = Literal["answered", "round_trip_cap_reached"]

# A tool handler takes the model's arguments as keywords and returns anything JSON-encodable.
# It may be sync or async (an Oracle handler will itself call a model).
ToolHandler = Callable[..., Any]

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Created on first use, so importing this module needs no key. The key is read from the
    environment by the SDK and never touched here."""
    global _client
    if _client is None:
        load_dotenv()  # does not override variables already set in the environment
        _client = AsyncOpenAI()
    return _client


class LLMResult(BaseModel):
    text: str
    stop_reason: StopReason
    round_trips: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int  # includes reasoning tokens
    reasoning_tokens: int
    cost_usd: float


def estimate_cost(price: ModelPrice, input_tokens: int, cached: int, output_tokens: int) -> float:
    """USD at list price. Cached tokens are a subset of input; reasoning is a subset of output
    (per the SDK's usage schema), so neither is added on top."""
    uncached = input_tokens - cached
    return (uncached * price.input + cached * price.cached_input + output_tokens * price.output) / 1e6


async def call_model(
    *,
    role: str,
    instructions: str,
    input_items: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    handlers: Mapping[str, ToolHandler],
    trace: RunTrace,
    max_round_trips: int = 8,
) -> LLMResult:
    if max_round_trips < 1:
        raise ValueError(f"max_round_trips must be at least 1, got {max_round_trips}")
    cfg = role_config(role)
    price = price_for(cfg.model)
    client = _get_client()
    items = list(input_items)  # our own copy: the caller's list is never mutated
    totals = dict(input=0, cached=0, output=0, reasoning=0)
    cost = 0.0

    for trip in range(1, max_round_trips + 1):
        request = {
            "model": cfg.model,
            "instructions": instructions,
            "input": list(items),  # a snapshot: later appends must not change what raw/ records
            "tools": tools,
            "reasoning": {"effort": cfg.reasoning_effort},
        }
        started_at = utc_iso()
        t0 = time.monotonic()
        raw = await client.responses.with_raw_response.create(**request)
        latency_s = round(time.monotonic() - t0, 3)
        body = json.loads(raw.text)  # the HTTP body exactly as returned
        response = raw.parse()  # the SDK's typed view of the same body

        usage = response.usage
        cached = usage.input_tokens_details.cached_tokens
        reasoning = usage.output_tokens_details.reasoning_tokens
        trip_cost = estimate_cost(price, usage.input_tokens, cached, usage.output_tokens)
        totals["input"] += usage.input_tokens
        totals["cached"] += cached
        totals["output"] += usage.output_tokens
        totals["reasoning"] += reasoning
        cost += trip_cost

        # Function calls taken from the raw body, so they go back to the model exactly as sent.
        calls = [item for item in body["output"] if item.get("type") == "function_call"]
        requested = [{"name": c["name"], "call_id": c["call_id"], "arguments": c["arguments"]} for c in calls]

        # Evidence first, then the event that names it. No `await` between these two lines.
        raw_file = trace.write_raw(f"{role}-rt{trip}", {"request": request, "response": body})
        trace.emit(
            "round_trip",
            role,
            {
                "trip": trip,
                "started_at": started_at,
                "latency_s": latency_s,
                "input_tokens": usage.input_tokens,
                "cached_input_tokens": cached,
                "output_tokens": usage.output_tokens,
                "reasoning_tokens": reasoning,
                "tool_calls_requested": requested,
                "est_cost_usd": trip_cost,
                "raw_file": raw_file,
            },
        )

        if not calls:
            return _result(response.output_text, "answered", trip, totals, cost)

        if trip == max_round_trips:
            # The model still wants tools, but there is no trip left to show it their results,
            # so they are not run. Say so loudly.
            trace.emit(
                "round_trip_cap_reached",
                role,
                {"max_round_trips": max_round_trips, "unexecuted_tool_calls": requested},
            )
            return _result(response.output_text, "round_trip_cap_reached", trip, totals, cost)

        items += body["output"]  # the model's own turn, including its reasoning and its calls
        for call in calls:
            handler = handlers.get(call["name"])
            if handler is None:
                raise KeyError(f"model called tool {call['name']!r}, which has no handler")
            args = json.loads(call["arguments"])
            t1 = time.monotonic()
            result = handler(**args)
            if inspect.isawaitable(result):
                result = await result
            duration_s = round(time.monotonic() - t1, 3)
            trace.emit(
                "tool_result",
                role,
                {
                    "name": call["name"],
                    "call_id": call["call_id"],
                    "arguments": args,
                    "result": result,
                    "duration_s": duration_s,
                },
            )
            output = result if isinstance(result, str) else json.dumps(result)
            items.append({"type": "function_call_output", "call_id": call["call_id"], "output": output})

    raise AssertionError("unreachable: the last trip always returns")


def _result(text: str, stop: StopReason, trips: int, totals: dict[str, int], cost: float) -> LLMResult:
    return LLMResult(
        text=text,
        stop_reason=stop,
        round_trips=trips,
        input_tokens=totals["input"],
        cached_input_tokens=totals["cached"],
        output_tokens=totals["output"],
        reasoning_tokens=totals["reasoning"],
        cost_usd=cost,
    )
