"""Fast event collection - called by hooks, must be lightweight."""

import json
import os
import sys
import time

DATA_DIR = os.path.expanduser("~/.claude-profiler/sessions")
PAIRS_DIR = os.path.expanduser("~/.claude-profiler/pairs")


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

    # Save prompt/response pairs to a separate file
    _save_pair(session_id, event_type, event["ts"], data)


def _save_pair(session_id: str, event_type: str, ts: float, data: dict) -> None:
    """Save tool input/output and model responses for prompt/response tracking."""
    pair = None

    if event_type == "pre_tool_use":
        tool_name = data.get("tool_name")
        tool_input = data.get("tool_input")
        if tool_name and tool_input is not None:
            pair = {
                "ts": ts,
                "type": "tool_call",
                "session_id": session_id,
                "tool_name": tool_name,
                "input": tool_input,
            }

    elif event_type == "post_tool_use":
        tool_name = data.get("tool_name")
        tool_output = data.get("tool_output")
        if tool_name and tool_output is not None:
            pair = {
                "ts": ts,
                "type": "tool_result",
                "session_id": session_id,
                "tool_name": tool_name,
                "output": tool_output,
            }

    elif event_type == "stop":
        message = data.get("message")
        usage = data.get("usage")
        pair = {
            "ts": ts,
            "type": "model_response",
            "session_id": session_id,
            "stop_reason": data.get("stop_reason"),
        }
        if message is not None:
            pair["message"] = message
        if usage:
            pair["usage"] = usage
        # Also capture input/output tokens at top level if present
        for key in ("input_tokens", "output_tokens"):
            if key in data:
                pair[key] = data[key]

    if pair is not None:
        os.makedirs(PAIRS_DIR, exist_ok=True)
        filepath = os.path.join(PAIRS_DIR, f"{session_id}.jsonl")
        with open(filepath, "a") as f:
            f.write(json.dumps(pair) + "\n")
