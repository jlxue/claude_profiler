"""Read Claude Code conversation files for LLM metrics and prompt/response pairs.

Claude Code stores conversations as JSONL files in:
  ~/.claude/projects/<project-hash>/<session-id>.jsonl

Each line is a message with types: system, user, assistant, progress,
file-history-snapshot, last-prompt.

Assistant messages contain:
  - timestamp (ISO 8601)
  - message.content: list of blocks (thinking, text, tool_use)
  - message.usage: {input_tokens, output_tokens, ...}
  - message.stop_reason: null | "tool_use" | "end_turn"
"""

import json
import os
from datetime import datetime
from typing import List, Optional

CLAUDE_DIR = os.path.expanduser("~/.claude")


def _find_conversation_file(session_id: str) -> Optional[str]:
    """Find the conversation JSONL file for a given session ID."""
    projects_dir = os.path.join(CLAUDE_DIR, "projects")
    if not os.path.isdir(projects_dir):
        return None
    for project in os.listdir(projects_dir):
        candidate = os.path.join(projects_dir, project, f"{session_id}.jsonl")
        if os.path.isfile(candidate):
            return candidate
    return None


def load_conversation(session_id: str) -> List[dict]:
    """Load all messages from a conversation file."""
    filepath = _find_conversation_file(session_id)
    if not filepath:
        return []
    messages = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return messages


def compute_llm_metrics(session_id: str) -> dict:
    """Compute TTFT, TPOT, and token breakdown for each LLM call in a session.

    An LLM call starts with a user message and ends when the assistant
    produces a terminal message (stop_reason = "tool_use" or "end_turn").

    Multiple assistant messages may be streamed for a single LLM call
    (thinking -> text -> tool_use). We track:
      - TTFT: time from user message to first assistant message
      - TPOT: (last_assistant_ts - first_assistant_ts) / (output_tokens - 1)
      - Token breakdown: prompt, thinking, response tokens per call

    Returns:
        {
            "ttft_list": [float, ...],
            "tpot_list": [float, ...],
            "prompt_tokens_list": [int, ...],
            "thinking_tokens_list": [int, ...],
            "response_tokens_list": [int, ...],
            "calls": int,
        }
    """
    messages = load_conversation(session_id)
    if not messages:
        return _empty_llm_metrics()

    ttft_list = []
    tpot_list = []
    prompt_tokens_list = []
    thinking_tokens_list = []
    response_tokens_list = []
    calls = 0

    # Track state for each LLM call
    last_user_ts = None
    first_assistant_ts = None
    last_assistant_ts = None
    call_output_tokens = 0
    call_thinking_tokens = 0
    call_prompt_tokens = 0
    seen_thinking = False

    def _finalize():
        nonlocal calls
        if last_user_ts is not None and first_assistant_ts is not None:
            ttft = first_assistant_ts - last_user_ts
            if ttft >= 0:
                ttft_list.append(ttft)

        if first_assistant_ts is not None and last_assistant_ts is not None \
                and call_output_tokens > 1:
            gen_time = last_assistant_ts - first_assistant_ts
            if gen_time > 0:
                tpot_list.append(gen_time / (call_output_tokens - 1))

        if call_prompt_tokens > 0:
            prompt_tokens_list.append(call_prompt_tokens)
        if call_output_tokens > 0:
            thinking_tokens_list.append(call_thinking_tokens)
            response_tokens_list.append(call_output_tokens - call_thinking_tokens)

        calls += 1

    for msg in messages:
        msg_type = msg.get("type")
        ts_str = msg.get("timestamp")
        if not ts_str:
            continue

        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError):
            continue

        if msg_type == "user":
            # Finalize previous call if in progress
            if first_assistant_ts is not None:
                _finalize()

            last_user_ts = ts
            first_assistant_ts = None
            last_assistant_ts = None
            call_output_tokens = 0
            call_thinking_tokens = 0
            call_prompt_tokens = 0
            seen_thinking = False

        elif msg_type == "assistant" and last_user_ts is not None:
            if first_assistant_ts is None:
                first_assistant_ts = ts

            last_assistant_ts = ts

            inner = msg.get("message", {})
            usage = inner.get("usage", {})
            out_tok = usage.get("output_tokens")
            if out_tok is not None:
                call_output_tokens = out_tok  # cumulative

            # Prompt tokens = input + cache_read + cache_creation
            inp = usage.get("input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            cache_create = usage.get("cache_creation_input_tokens", 0)
            total_prompt = inp + cache_read + cache_create
            if total_prompt > call_prompt_tokens:
                call_prompt_tokens = total_prompt

            # Track thinking tokens from first thinking block
            if not seen_thinking:
                content = inner.get("content", [])
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "thinking":
                        seen_thinking = True
                        if out_tok is not None:
                            call_thinking_tokens = out_tok
                        break

            stop_reason = inner.get("stop_reason")
            if stop_reason in ("tool_use", "end_turn"):
                _finalize()
                first_assistant_ts = None
                last_assistant_ts = None
                call_output_tokens = 0
                call_thinking_tokens = 0
                call_prompt_tokens = 0
                seen_thinking = False

    # Handle unfinished call
    if first_assistant_ts is not None:
        _finalize()

    return {
        "ttft_list": ttft_list,
        "tpot_list": tpot_list,
        "prompt_tokens_list": prompt_tokens_list,
        "thinking_tokens_list": thinking_tokens_list,
        "response_tokens_list": response_tokens_list,
        "calls": calls,
    }


def _empty_llm_metrics() -> dict:
    return {
        "ttft_list": [],
        "tpot_list": [],
        "prompt_tokens_list": [],
        "thinking_tokens_list": [],
        "response_tokens_list": [],
        "calls": 0,
    }


def load_pairs(session_id: str) -> List[dict]:
    """Load prompt/response pairs from a conversation.

    Returns a list of dicts, each representing one LLM call:
      {
          "ts": float,              # timestamp of user message
          "prompt": str,            # user prompt text (or tool_result summary)
          "response": str,          # assistant response text
          "thinking": str,          # thinking content (if any)
          "tool_calls": [           # tool calls made (if any)
              {"name": str, "input": dict},
          ],
          "input_tokens": int,
          "output_tokens": int,
          "stop_reason": str,
      }
    """
    messages = load_conversation(session_id)
    if not messages:
        return []

    pairs = []
    current_prompt = None
    current_prompt_ts = None
    current_response_parts = {
        "thinking": [],
        "text": [],
        "tool_calls": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "stop_reason": None,
    }

    def _flush():
        if current_prompt_ts is not None:
            pairs.append({
                "ts": current_prompt_ts,
                "prompt": current_prompt or "",
                "response": "\n".join(current_response_parts["text"]),
                "thinking": "\n".join(current_response_parts["thinking"]),
                "tool_calls": current_response_parts["tool_calls"],
                "input_tokens": current_response_parts["input_tokens"],
                "output_tokens": current_response_parts["output_tokens"],
                "stop_reason": current_response_parts["stop_reason"],
            })

    for msg in messages:
        msg_type = msg.get("type")

        if msg_type == "user":
            # Flush previous pair
            _flush()

            # Extract prompt text
            content = msg.get("message", {}).get("content", [])
            prompt_parts = []
            for block in content:
                if isinstance(block, str):
                    prompt_parts.append(block)
                elif isinstance(block, dict):
                    if block.get("type") == "text":
                        prompt_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        # Summarize tool results
                        tool_content = block.get("content", "")
                        if isinstance(tool_content, list):
                            texts = [c.get("text", "") for c in tool_content
                                     if isinstance(c, dict) and c.get("type") == "text"]
                            tool_content = "\n".join(texts)
                        if isinstance(tool_content, str) and len(tool_content) > 500:
                            tool_content = tool_content[:500] + "..."
                        prompt_parts.append(f"[tool_result: {tool_content}]")

            ts_str = msg.get("timestamp", "")
            try:
                current_prompt_ts = datetime.fromisoformat(
                    ts_str.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                current_prompt_ts = None

            current_prompt = "\n".join(prompt_parts).strip()
            current_response_parts = {
                "thinking": [],
                "text": [],
                "tool_calls": [],
                "input_tokens": 0,
                "output_tokens": 0,
                "stop_reason": None,
            }

        elif msg_type == "assistant" and current_prompt_ts is not None:
            inner = msg.get("message", {})
            content = inner.get("content", [])

            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "thinking":
                    current_response_parts["thinking"].append(
                        block.get("thinking", ""))
                elif btype == "text":
                    current_response_parts["text"].append(
                        block.get("text", ""))
                elif btype == "tool_use":
                    current_response_parts["tool_calls"].append({
                        "name": block.get("name", ""),
                        "input": block.get("input", {}),
                    })

            usage = inner.get("usage", {})
            if usage.get("input_tokens"):
                current_response_parts["input_tokens"] = usage["input_tokens"]
            if usage.get("output_tokens"):
                current_response_parts["output_tokens"] = usage["output_tokens"]
            if inner.get("stop_reason"):
                current_response_parts["stop_reason"] = inner["stop_reason"]

    # Flush last pair
    _flush()

    return pairs
