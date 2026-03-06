"""Fast event collection - called by hooks, must be lightweight."""

import json
import os
import sys
import time

DATA_DIR = os.path.expanduser("~/.claude-profiler/sessions")


def log_event(event_type: str) -> None:
    """Read hook data from stdin, append timestamped event to session JSONL file."""
    os.makedirs(DATA_DIR, exist_ok=True)

    raw = sys.stdin.read().strip()
    if not raw:
        data = {}
    else:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"raw": raw}

    session_id = data.get("session_id", "unknown")
    tool_name = data.get("tool_name")

    event = {
        "ts": time.time(),
        "event": event_type,
        "session_id": session_id,
    }
    if tool_name:
        event["tool_name"] = tool_name

    # For post_tool_use, capture output length (not full output to save space)
    if event_type == "post_tool_use" and "tool_output" in data:
        output = data["tool_output"]
        if isinstance(output, str):
            event["output_len"] = len(output)
        elif isinstance(output, dict):
            event["output_len"] = len(json.dumps(output))

    # Capture any token/cost info if present in the data
    for key in ("usage", "tokens", "cost", "input_tokens", "output_tokens",
                "stop_reason", "message", "num_turns"):
        if key in data:
            event[key] = data[key]

    filepath = os.path.join(DATA_DIR, f"{session_id}.jsonl")
    with open(filepath, "a") as f:
        f.write(json.dumps(event) + "\n")
