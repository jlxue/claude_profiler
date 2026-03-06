"""CLI entry point for claude-profiler."""

import argparse
import json
from datetime import datetime, timedelta


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s:02d}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m:02d}m"


def pct(part: float, total: float) -> str:
    if total == 0:
        return "0.0%"
    return f"{part / total * 100:.1f}%"


def cmd_log(args):
    """Handle log subcommand - called by hooks."""
    from claude_profiler.collector import log_event
    log_event(args.event_type)


def cmd_install(args):
    """Install profiler hooks."""
    from claude_profiler.installer import install
    msg = install(project=args.project)
    print(msg)


def cmd_uninstall(args):
    """Uninstall profiler hooks."""
    from claude_profiler.installer import uninstall
    msg = uninstall(project=args.project)
    print(msg)


def cmd_status(args):
    """Show installation status."""
    from claude_profiler.installer import status
    print("Global:", status(project=False))
    print("Project:", status(project=True))

    # Show data stats
    import os
    data_dir = os.path.expanduser("~/.claude-profiler/sessions")
    if os.path.isdir(data_dir):
        files = [f for f in os.listdir(data_dir) if f.endswith(".jsonl")]
        total_size = sum(
            os.path.getsize(os.path.join(data_dir, f)) for f in files
        )
        print(f"Sessions recorded: {len(files)}")
        print(f"Data size: {total_size / 1024:.1f} KB")
    else:
        print("No profiling data yet.")


def _parse_period(period: str) -> datetime:
    """Parse period string into a since datetime."""
    now = datetime.now()
    period = period.lower().strip()
    if period in ("today", "1d", "day"):
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period in ("week", "1w", "7d"):
        return now - timedelta(days=7)
    elif period in ("month", "1m", "30d"):
        return now - timedelta(days=30)
    elif period in ("year", "1y", "365d"):
        return now - timedelta(days=365)
    elif period == "all":
        return datetime(2000, 1, 1)
    else:
        # Try parsing as a date
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%m/%d/%Y"):
            try:
                return datetime.strptime(period, fmt)
            except ValueError:
                continue
        # Try parsing as Nd (number of days)
        if period.endswith("d") and period[:-1].isdigit():
            return now - timedelta(days=int(period[:-1]))
        raise ValueError(f"Unknown period: {period}")


def cmd_stats(args):
    """Show profiling statistics."""
    from claude_profiler.analyzer import aggregate_stats

    since = None
    until = None
    if args.period:
        since = _parse_period(args.period)
    if args.since:
        since = _parse_period(args.since)
    if args.until:
        until = _parse_period(args.until)

    stats = aggregate_stats(since=since, until=until)

    if stats["session_count"] == 0:
        print("No profiling data found for the specified period.")
        if since:
            print(f"  Since: {since.strftime('%Y-%m-%d %H:%M')}")
        print("\nMake sure you have:")
        print("  1. Installed hooks: claude-profiler install")
        print("  2. Used Claude Code after installation")
        return

    # Header
    print("=" * 60)
    print("  Claude Code Profiler - Statistics")
    print("=" * 60)

    if since:
        period_str = f"{since.strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}"
    else:
        period_str = "All time"
    print(f"  Period:   {period_str}")
    print(f"  Sessions: {stats['session_count']}")
    print(f"  Turns:    {stats['turns']}")
    print(f"  Events:   {stats['events']}")
    print()

    total = stats["total_time"]
    print(f"  Total time:        {format_duration(total)}")
    print()

    # Time breakdown
    print("  Time Breakdown:")
    print(f"    Model generation:  {format_duration(stats['model_time']):>10s}  ({pct(stats['model_time'], total):>5s})")
    print(f"    Tool execution:    {format_duration(stats['tool_time']):>10s}  ({pct(stats['tool_time'], total):>5s})")
    print(f"    User idle:         {format_duration(stats['idle_time']):>10s}  ({pct(stats['idle_time'], total):>5s})")

    unaccounted = total - stats["model_time"] - stats["tool_time"] - stats["idle_time"]
    if unaccounted > 1:
        print(f"    Other/untracked:   {format_duration(unaccounted):>10s}  ({pct(unaccounted, total):>5s})")
    print()

    # LLM Performance
    if stats.get("ttft_samples") or stats.get("tpot_samples"):
        print("  LLM Performance:")
        if stats["ttft_samples"]:
            print(f"    TTFT (Time to First Token):")
            print(f"      Average:  {format_duration(stats['ttft_avg']):>10s}  ({stats['ttft_samples']} samples)")
            print(f"      Max:      {format_duration(stats['ttft_max']):>10s}")
        if stats["tpot_samples"]:
            print(f"    TPOT (Time Per Output Token):")
            print(f"      Average:  {stats['tpot_avg']*1000:>10.1f}ms  ({stats['tpot_samples']} samples)")
            print(f"      Max:      {stats['tpot_max']*1000:>10.1f}ms")
        print()

    # Tool breakdown
    if stats["tool_breakdown"]:
        print("  Tool Breakdown:")
        tool_total = stats["tool_time"]
        sorted_tools = sorted(
            stats["tool_breakdown"].items(), key=lambda x: x[1], reverse=True
        )
        for tool, dur in sorted_tools:
            count = stats["tool_call_counts"].get(tool, 0)
            avg = dur / count if count else 0
            print(
                f"    {tool:<20s} {format_duration(dur):>10s}  "
                f"({pct(dur, tool_total):>5s})  "
                f"{count:>4d} calls  "
                f"avg {format_duration(avg)}"
            )
        print()

    # Per-session summary (if not too many)
    if args.verbose and stats["sessions"]:
        print("  Per-Session Details:")
        print(f"    {'Session ID':<20s} {'Start':<18s} {'Duration':>10s} {'Model':>8s} {'Tools':>8s} {'Idle':>8s} {'Turns':>6s}")
        print("    " + "-" * 90)
        for s in stats["sessions"]:
            sid = s["session_id"][:18]
            start = s["start"].strftime("%Y-%m-%d %H:%M")
            print(
                f"    {sid:<20s} {start:<18s} "
                f"{format_duration(s['total_time']):>10s} "
                f"{format_duration(s['model_time']):>8s} "
                f"{format_duration(s['tool_time']):>8s} "
                f"{format_duration(s['idle_time']):>8s} "
                f"{s['turns']:>6d}"
            )
        print()

    print("=" * 60)


def cmd_sessions(args):
    """List profiled sessions."""
    from claude_profiler.analyzer import list_sessions

    since = None
    if args.period:
        since = _parse_period(args.period)

    sessions = list_sessions(since=since)
    if not sessions:
        print("No sessions found.")
        return

    print(f"{'Session ID':<40s} {'Start':<18s} {'Duration':>10s} {'Events':>8s}")
    print("-" * 80)
    for s in sessions:
        sid = s["session_id"][:38]
        start = s["start"].strftime("%Y-%m-%d %H:%M")
        print(f"{sid:<40s} {start:<18s} {format_duration(s['duration']):>10s} {s['event_count']:>8d}")


def cmd_session_detail(args):
    """Show detailed breakdown for a specific session."""
    from claude_profiler.analyzer import load_session, analyze_session

    events = load_session(args.session_id)
    if not events:
        print(f"No events found for session {args.session_id}")
        return

    result = analyze_session(events)
    total = result["total_time"]

    print(f"Session: {args.session_id}")
    print(f"Events:  {result['events']}")
    print(f"Turns:   {result['turns']}")
    print(f"Total:   {format_duration(total)}")
    print()
    print("Time Breakdown:")
    print(f"  Model generation:  {format_duration(result['model_time']):>10s}  ({pct(result['model_time'], total):>5s})")
    print(f"  Tool execution:    {format_duration(result['tool_time']):>10s}  ({pct(result['tool_time'], total):>5s})")
    print(f"  User idle:         {format_duration(result['idle_time']):>10s}  ({pct(result['idle_time'], total):>5s})")
    print()

    # TTFT/TPOT per session
    ttft_list = result.get("ttft_list", [])
    tpot_list = result.get("tpot_list", [])
    if ttft_list or tpot_list:
        print("LLM Performance:")
        if ttft_list:
            avg_ttft = sum(ttft_list) / len(ttft_list)
            max_ttft = max(ttft_list)
            print(f"  TTFT avg: {format_duration(avg_ttft)}  max: {format_duration(max_ttft)}  ({len(ttft_list)} turns)")
        if tpot_list:
            avg_tpot = sum(tpot_list) / len(tpot_list)
            max_tpot = max(tpot_list)
            print(f"  TPOT avg: {avg_tpot*1000:.1f}ms  max: {max_tpot*1000:.1f}ms  ({len(tpot_list)} turns)")
        print()

    if result["tool_breakdown"]:
        print("Tool Breakdown:")
        for tool, dur in sorted(result["tool_breakdown"].items(), key=lambda x: x[1], reverse=True):
            count = result["tool_call_counts"].get(tool, 0)
            print(f"  {tool:<20s} {format_duration(dur):>10s}  ({pct(dur, result['tool_time']):>5s})  {count} calls")
    print()

    if args.timeline:
        print("Event Timeline:")
        start_ts = events[0]["ts"]
        for e in events:
            offset = e["ts"] - start_ts
            tool = e.get("tool_name", "")
            line = f"  +{format_duration(offset):>10s}  {e['event']:<20s}"
            if tool:
                line += f"  {tool}"
            print(line)


def cmd_pairs(args):
    """Show prompt/response pairs for a session."""
    import os
    from claude_profiler.collector import PAIRS_DIR

    filepath = os.path.join(PAIRS_DIR, f"{args.session_id}.jsonl")
    if not os.path.isfile(filepath):
        print(f"No pairs data found for session {args.session_id}")
        return

    pairs = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line:
                pairs.append(json.loads(line))

    if args.type:
        pairs = [p for p in pairs if p.get("type") == args.type]

    if not pairs:
        print("No matching pairs found.")
        return

    limit = args.last or len(pairs)
    pairs = pairs[-limit:]

    for i, p in enumerate(pairs):
        ts = datetime.fromtimestamp(p["ts"]).strftime("%H:%M:%S")
        ptype = p.get("type", "unknown")
        print(f"--- [{i+1}] {ts} {ptype} ---")

        if ptype == "tool_call":
            print(f"Tool: {p.get('tool_name', '?')}")
            _print_truncated("Input", p.get("input"), args.full)
        elif ptype == "tool_result":
            print(f"Tool: {p.get('tool_name', '?')}")
            _print_truncated("Output", p.get("output"), args.full)
        elif ptype == "model_response":
            if p.get("stop_reason"):
                print(f"Stop reason: {p['stop_reason']}")
            if p.get("input_tokens") or p.get("output_tokens"):
                print(f"Tokens: in={p.get('input_tokens', '?')} out={p.get('output_tokens', '?')}")
            usage = p.get("usage")
            if usage and isinstance(usage, dict):
                print(f"Usage: {json.dumps(usage)}")
            _print_truncated("Message", p.get("message"), args.full)
        print()


def _print_truncated(label: str, value, full: bool = False):
    """Print a value, truncating if too long."""
    if value is None:
        return
    if isinstance(value, dict):
        text = json.dumps(value, indent=2, ensure_ascii=False)
    elif isinstance(value, list):
        text = json.dumps(value, indent=2, ensure_ascii=False)
    else:
        text = str(value)

    max_len = 2000
    if not full and len(text) > max_len:
        print(f"{label} ({len(text)} chars, truncated):")
        print(text[:max_len] + "\n  ... [truncated, use --full to see all]")
    else:
        print(f"{label}:")
        print(text)


def cmd_export(args):
    """Export profiling data as JSON."""
    import json
    from claude_profiler.analyzer import aggregate_stats

    since = None
    if args.period:
        since = _parse_period(args.period)

    stats = aggregate_stats(since=since)

    # Convert datetime objects to strings for JSON serialization
    for s in stats.get("sessions", []):
        if "start" in s:
            s["start"] = s["start"].isoformat()
        if "end" in s:
            s["end"] = s["end"].isoformat()

    if args.output:
        with open(args.output, "w") as f:
            json.dump(stats, f, indent=2)
        print(f"Exported to {args.output}")
    else:
        print(json.dumps(stats, indent=2))


def main():
    parser = argparse.ArgumentParser(
        prog="claude-profiler",
        description="Profile your Claude Code sessions",
    )
    sub = parser.add_subparsers(dest="command")

    # install
    p_install = sub.add_parser("install", help="Install profiler hooks")
    p_install.add_argument("--project", action="store_true",
                           help="Install per-project instead of global")

    # uninstall
    p_uninstall = sub.add_parser("uninstall", help="Remove profiler hooks")
    p_uninstall.add_argument("--project", action="store_true")

    # status
    sub.add_parser("status", help="Show installation status")

    # log (called by hooks - not for user use)
    p_log = sub.add_parser("log", help=argparse.SUPPRESS)
    p_log.add_argument("event_type",
                       choices=["pre_tool_use", "post_tool_use", "stop", "notification"])

    # stats
    p_stats = sub.add_parser("stats", help="Show profiling statistics")
    p_stats.add_argument("--period", "-p", default="all",
                         help="Time period: today, week, month, year, 7d, 30d, or YYYY-MM-DD")
    p_stats.add_argument("--since", help="Start date (YYYY-MM-DD)")
    p_stats.add_argument("--until", help="End date (YYYY-MM-DD)")
    p_stats.add_argument("--verbose", "-v", action="store_true",
                         help="Show per-session details")

    # sessions
    p_sessions = sub.add_parser("sessions", help="List profiled sessions")
    p_sessions.add_argument("--period", "-p", default="all")

    # session (single session detail)
    p_session = sub.add_parser("session", help="Show details for a specific session")
    p_session.add_argument("session_id", help="Session ID")
    p_session.add_argument("--timeline", "-t", action="store_true",
                           help="Show event timeline")

    # pairs (view prompt/response pairs)
    p_pairs = sub.add_parser("pairs", help="Show prompt/response pairs for a session")
    p_pairs.add_argument("session_id", help="Session ID")
    p_pairs.add_argument("--type", choices=["tool_call", "tool_result", "model_response"],
                         help="Filter by pair type")
    p_pairs.add_argument("--last", type=int, help="Show only last N entries")
    p_pairs.add_argument("--full", action="store_true",
                         help="Show full content without truncation")

    # export
    p_export = sub.add_parser("export", help="Export data as JSON")
    p_export.add_argument("--period", "-p", default="all")
    p_export.add_argument("--output", "-o", help="Output file path")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    commands = {
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "status": cmd_status,
        "log": cmd_log,
        "stats": cmd_stats,
        "sessions": cmd_sessions,
        "session": cmd_session_detail,
        "export": cmd_export,
        "pairs": cmd_pairs,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
