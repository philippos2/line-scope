"""Two-turn, synthetic read-only Tool calling probe; never calls business Tools."""

import argparse
import json
from time import monotonic

from linescope.llm import LLMError, OllamaClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    client = OllamaClient(base_url=args.base_url, model=args.model)
    deadline = monotonic() + 60
    schemas = {
        "probe_equipment_state": {
            "type": "object",
            "properties": {"equipment_code": {"type": "string"}},
            "required": ["equipment_code"],
            "additionalProperties": False,
            "description": "Read synthetic equipment state by exact equipment code.",
        }
    }
    messages = [
        {
            "role": "system",
            "content": "Use the supplied tool to answer the question. Never invent state. After the tool result, answer in Japanese using the returned state code. This is a synthetic probe.",
        },
        {"role": "user", "content": "M-204の状態を調べて。"},
    ]
    started = monotonic()
    try:
        reply = client.complete(messages, schemas=schemas, deadline=deadline)
        if (
            len(reply.tool_calls) != 1
            or reply.tool_calls[0].name != "probe_equipment_state"
            or reply.tool_calls[0].arguments != {"equipment_code": "M-204"}
        ):
            raise LLMError("INTERNAL_ERROR", "Synthetic Tool selection failed")
        messages.append(reply.assistant_message())
        messages.append(
            {
                "role": "tool",
                "tool_name": "probe_equipment_state",
                "content": json.dumps(
                    {
                        "equipment_code": "M-204",
                        "state_code": "STOPPED",
                        "source": "SYNTHETIC_FIXTURE",
                    }
                ),
            }
        )
        final = client.complete(messages, schemas={}, deadline=deadline)
        if (
            final.tool_calls
            or "STOPPED" not in final.content
            or "M-204" not in final.content
        ):
            raise LLMError("INTERNAL_ERROR", "Synthetic answer failed")
    except LLMError as error:
        print(json.dumps({"passed": False, "code": error.code, "check": error.message}))
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "passed": True,
                "model": args.model,
                "turns": 2,
                "duration_seconds": round(monotonic() - started, 2),
                "scope": "synthetic_probe_only",
            }
        )
    )


if __name__ == "__main__":
    main()
