"""Analyze profiled session data and compute statistics."""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Optional

DATA_DIR = os.path.expanduser("~/.claude-profiler/sessions")

# Max gap to consider as "model thinking" (seconds).
# Gaps larger than this are treated as idle time.
MAX_MODEL_THINKING_GAP = 300  # 5 minutes


def load_session(session_id: str) -> List[dict]:
    """Load events for a session."""
    filepath = os.path.join(DATA_DIR, f"{session_id}.jsonl")
    events = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    events.sort(key=lambda e: e["ts"])
    return events


def list_sessions(since: Optional[datetime] = None,
                  until: Optional[datetime] = None) -> List[dict]:
    """List all sessions with basic info, optionally filtered by time range."""
    if not os.path.isdir(DATA_DIR):
        return []

    sessions = []
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith(".jsonl"):
            continue
        session_id = fname[:-6]
        filepath = os.path.join(DATA_DIR, fname)

        first_ts = None
        last_ts = None
        event_count = 0

        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                ts = event["ts"]
                event_count += 1
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts

        if first_ts is None:
            continue

        first_dt = datetime.fromtimestamp(first_ts)
        last_dt = datetime.fromtimestamp(last_ts)

        if since and last_dt < since:
            continue
        if until and first_dt > until:
            continue

        sessions.append({
            "session_id": session_id,
            "start": first_dt,
            "end": last_dt,
            "duration": last_ts - first_ts,
            "event_count": event_count,
        })

    sessions.sort(key=lambda s: s["start"])
    return sessions


def analyze_session(events: List[dict]) -> dict:
    """Analyze a single session's events and compute time breakdown.

    Returns dict with:
      - total_time: total session duration
      - model_time: time spent on model generation
      - tool_time: total tool execution time
      - tool_breakdown: {tool_name: total_seconds}
      - tool_call_counts: {tool_name: count}
      - idle_time: time waiting for user
      - turns: number of conversation turns
      - events: total number of events
    """
    if not events:
        return _empty_result()

    total_time = events[-1]["ts"] - events[0]["ts"]
    tool_time = 0.0
    tool_breakdown = defaultdict(float)
    tool_call_counts = defaultdict(int)
    model_time = 0.0
    idle_time = 0.0
    turns = 0

    # State tracking
    pending_tool_start = None  # timestamp of PreToolUse
    pending_tool_name = None
    last_event_ts = events[0]["ts"]
    in_turn = False  # whether we're in an active turn (between first event and stop)
    last_stop_ts = None

    for event in events:
        ts = event["ts"]
        etype = event["event"]

        if etype == "pre_tool_use":
            if not in_turn:
                # New turn starting
                in_turn = True
                turns += 1
                if last_stop_ts is not None:
                    idle_time += ts - last_stop_ts
                    last_stop_ts = None
                    # Don't count idle gap as model time
                    last_event_ts = ts

            # Time since last event is model thinking
            gap = ts - last_event_ts
            if gap > 0 and gap < MAX_MODEL_THINKING_GAP:
                model_time += gap

            pending_tool_start = ts
            pending_tool_name = event.get("tool_name", "unknown")
            last_event_ts = ts

        elif etype == "post_tool_use":
            if pending_tool_start is not None:
                duration = ts - pending_tool_start
                tool_name = event.get("tool_name", pending_tool_name or "unknown")
                tool_time += duration
                tool_breakdown[tool_name] += duration
                tool_call_counts[tool_name] += 1
                pending_tool_start = None
                pending_tool_name = None
            last_event_ts = ts

        elif etype == "stop":
            if pending_tool_start is not None:
                # Tool didn't finish cleanly
                pending_tool_start = None
                pending_tool_name = None

            if in_turn:
                # Time since last event is final model generation
                gap = ts - last_event_ts
                if gap < MAX_MODEL_THINKING_GAP:
                    model_time += gap

            if not in_turn and turns == 0:
                turns = 1

            in_turn = False
            last_stop_ts = ts
            last_event_ts = ts

        elif etype == "notification":
            last_event_ts = ts

    # If session ended without a stop event
    if in_turn and turns == 0:
        turns = 1

    return {
        "total_time": total_time,
        "model_time": model_time,
        "tool_time": tool_time,
        "tool_breakdown": dict(tool_breakdown),
        "tool_call_counts": dict(tool_call_counts),
        "idle_time": idle_time,
        "turns": turns,
        "events": len(events),
    }


def aggregate_stats(since: Optional[datetime] = None,
                    until: Optional[datetime] = None) -> dict:
    """Aggregate statistics across all sessions in a time range."""
    from claude_profiler.conversation import compute_llm_metrics

    sessions = list_sessions(since=since, until=until)
    if not sessions:
        return {
            "session_count": 0,
            "total_time": 0,
            "model_time": 0,
            "tool_time": 0,
            "idle_time": 0,
            "tool_breakdown": {},
            "tool_call_counts": {},
            "turns": 0,
            "events": 0,
            "sessions": [],
            "ttft_avg": 0,
            "ttft_max": 0,
            "tpot_avg": 0,
            "tpot_max": 0,
        }

    total_time = 0.0
    model_time = 0.0
    tool_time = 0.0
    idle_time = 0.0
    tool_breakdown = defaultdict(float)
    tool_call_counts = defaultdict(int)
    turns = 0
    total_events = 0
    session_details = []
    all_ttft = []
    all_tpot = []
    all_prompt_tokens = []
    all_thinking_tokens = []
    all_response_tokens = []

    for session_info in sessions:
        events = load_session(session_info["session_id"])
        result = analyze_session(events)

        total_time += result["total_time"]
        model_time += result["model_time"]
        tool_time += result["tool_time"]
        idle_time += result["idle_time"]
        turns += result["turns"]
        total_events += result["events"]

        for tool, dur in result["tool_breakdown"].items():
            tool_breakdown[tool] += dur
        for tool, cnt in result["tool_call_counts"].items():
            tool_call_counts[tool] += cnt

        # Get TTFT/TPOT and token breakdown from conversation files
        llm_metrics = compute_llm_metrics(session_info["session_id"])
        all_ttft.extend(llm_metrics["ttft_list"])
        all_tpot.extend(llm_metrics["tpot_list"])
        all_prompt_tokens.extend(llm_metrics["prompt_tokens_list"])
        all_thinking_tokens.extend(llm_metrics["thinking_tokens_list"])
        all_response_tokens.extend(llm_metrics["response_tokens_list"])

        session_details.append({
            **session_info,
            **result,
            "llm_calls": llm_metrics["calls"],
            "ttft_list": llm_metrics["ttft_list"],
            "tpot_list": llm_metrics["tpot_list"],
        })

    return {
        "session_count": len(sessions),
        "total_time": total_time,
        "model_time": model_time,
        "tool_time": tool_time,
        "idle_time": idle_time,
        "tool_breakdown": dict(tool_breakdown),
        "tool_call_counts": dict(tool_call_counts),
        "turns": turns,
        "events": total_events,
        "sessions": session_details,
        "ttft_avg": _avg(all_ttft),
        "ttft_max": max(all_ttft) if all_ttft else 0,
        "tpot_avg": _avg(all_tpot),
        "tpot_max": max(all_tpot) if all_tpot else 0,
        "ttft_samples": len(all_ttft),
        "tpot_samples": len(all_tpot),
        "prompt_tokens": _list_stats(all_prompt_tokens),
        "thinking_tokens": _list_stats(all_thinking_tokens),
        "response_tokens": _list_stats(all_response_tokens),
    }


def _avg(lst: list) -> float:
    return sum(lst) / len(lst) if lst else 0


def _median(lst: list) -> float:
    if not lst:
        return 0
    s = sorted(lst)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _list_stats(lst: list) -> dict:
    """Compute avg, median, max for a list of values."""
    if not lst:
        return {"avg": 0, "median": 0, "max": 0, "samples": 0}
    return {
        "avg": sum(lst) / len(lst),
        "median": _median(lst),
        "max": max(lst),
        "samples": len(lst),
    }


def _empty_result():
    return {
        "total_time": 0,
        "model_time": 0,
        "tool_time": 0,
        "tool_breakdown": {},
        "tool_call_counts": {},
        "idle_time": 0,
        "turns": 0,
        "events": 0,
    }
