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
      - ttft_list: list of TTFT values (seconds) per turn
      - tpot_list: list of TPOT values (seconds) per turn
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

    # TTFT/TPOT tracking
    ttft_list = []  # TTFT per turn
    tpot_list = []  # TPOT per turn

    # State tracking
    pending_tool_start = None  # timestamp of PreToolUse
    pending_tool_name = None
    last_event_ts = events[0]["ts"]
    in_turn = False  # whether we're in an active turn (between first event and stop)
    last_stop_ts = None
    turn_start_ts = None  # when current turn started (for TTFT)
    turn_first_event = False  # whether we've seen the first event in current turn
    turn_model_time = 0.0  # model time accumulated in current turn

    for event in events:
        ts = event["ts"]
        etype = event["event"]

        if etype == "pre_tool_use":
            if not in_turn:
                # New turn starting
                in_turn = True
                turns += 1
                turn_start_ts = ts
                turn_first_event = False
                turn_model_time = 0.0
                if last_stop_ts is not None:
                    idle_time += ts - last_stop_ts
                    last_stop_ts = None
                    # Don't count idle gap as model time
                    last_event_ts = ts

            # Time since last event is model thinking
            gap = ts - last_event_ts
            if gap > 0 and gap < MAX_MODEL_THINKING_GAP:
                model_time += gap
                turn_model_time += gap

            # TTFT: time from turn start to first tool call
            if not turn_first_event:
                turn_first_event = True
                ttft_list.append(ts - turn_start_ts)

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
                    turn_model_time += gap

                # TTFT for turns with no tool calls (pure text response)
                if not turn_first_event:
                    turn_first_event = True
                    ttft_list.append(ts - turn_start_ts)

            if not in_turn and turns == 0:
                turns = 1
                turn_start_ts = events[0]["ts"]
                turn_model_time = model_time

            # Compute TPOT from token usage if available
            output_tokens = _get_output_tokens(event)
            if output_tokens and output_tokens > 1 and turn_model_time > 0:
                tpot_list.append(turn_model_time / output_tokens)

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
        "ttft_list": ttft_list,
        "tpot_list": tpot_list,
    }


def _get_output_tokens(event: dict) -> Optional[int]:
    """Extract output token count from a stop event."""
    if "output_tokens" in event:
        return event["output_tokens"]
    usage = event.get("usage")
    if isinstance(usage, dict):
        return usage.get("output_tokens")
    return None


def aggregate_stats(since: Optional[datetime] = None,
                    until: Optional[datetime] = None) -> dict:
    """Aggregate statistics across all sessions in a time range."""
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

        all_ttft.extend(result["ttft_list"])
        all_tpot.extend(result["tpot_list"])

        session_details.append({
            **session_info,
            **result,
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
        "ttft_avg": sum(all_ttft) / len(all_ttft) if all_ttft else 0,
        "ttft_max": max(all_ttft) if all_ttft else 0,
        "tpot_avg": sum(all_tpot) / len(all_tpot) if all_tpot else 0,
        "tpot_max": max(all_tpot) if all_tpot else 0,
        "ttft_samples": len(all_ttft),
        "tpot_samples": len(all_tpot),
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
        "ttft_list": [],
        "tpot_list": [],
    }
