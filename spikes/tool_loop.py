"""Phase 0 spike: prove one model -> tool -> model round trip. Throwaway."""
import json
import time

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI()

MODEL = "gpt-6-luna"
MAX_ROUNDS = 4  # hard stop so a confused model can't loop and spend

# Invented placeholder passages. Not real texts; real corpora arrive in Phase 2.
FAKE_CORPUS = {
    "p1": "FAKE PASSAGE: The mind is the one territory a person fully governs.",
    "p2": "FAKE PASSAGE: Outside events arrive unbidden; judgement about them is ours.",
    "p3": "FAKE PASSAGE: The harbour was quiet and the ships were late.",
}

TOOLS = [{
    "type": "function",
    "name": "search_my_corpus",
    "description": "Search your own corpus. Returns matching passages with ids.",
    "parameters": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Words to search for"}},
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
}]


def search_my_corpus(query: str) -> list[dict]:
    words = {w.lower() for w in query.split()}
    return [{"passage_id": pid, "text": text}
            for pid, text in FAKE_CORPUS.items()
            if words & {w.strip(".,;:").lower() for w in text.split()}]


input_items = [{"role": "user",
                "content": "What does your corpus say about governing one's own mind? Cite passage ids."}]
total_in = total_out = 0

for round_no in range(1, MAX_ROUNDS + 1):
    t0 = time.perf_counter()
    response = client.responses.create(
        model=MODEL,
        instructions="Answer only from passages returned by search_my_corpus. Cite passage ids.",
        input=input_items,
        tools=TOOLS,
        reasoning={"effort": "low"},
    )
    elapsed = time.perf_counter() - t0
    usage = response.usage
    total_in += usage.input_tokens
    total_out += usage.output_tokens
    print(f"\n--- round {round_no}: {elapsed:.2f}s, input={usage.input_tokens} output={usage.output_tokens} tokens")

    calls = [item for item in response.output if item.type == "function_call"]
    if not calls:
        print("final answer:\n" + response.output_text)
        break

    input_items += response.output  # keep the model's own turn, including its call
    for call in calls:
        args = json.loads(call.arguments)
        result = search_my_corpus(**args)
        print(f"model asked: {call.name}({args})  call_id={call.call_id}")
        print(f"we returned: {[r['passage_id'] for r in result]}")
        input_items.append({"type": "function_call_output",
                            "call_id": call.call_id,
                            "output": json.dumps(result)})
else:
    print(f"\nstopped: hit MAX_ROUNDS={MAX_ROUNDS} without a final answer")

cost = total_in / 1e6 * 0.10 + total_out / 1e6 * 0.50
print(f"\ntotals: input={total_in} output={total_out} tokens, ~${cost:.5f} at list price")
