# Claude Code Profiler

Profile your Claude Code sessions - track time spent on model generation, tool calls, and idle time.

## Installation

```bash
pip install claude-profiler
```

Or install from source:

```bash
git clone https://github.com/user/claude-profiler.git
cd claude-profiler
pip install .
```

## Quick Start

```bash
# 1. Install profiler hooks (one-time setup)
claude-profiler install

# 2. Use Claude Code normally - profiling happens automatically in the background

# 3. View statistics
claude-profiler stats
```

## Usage

### Install/Uninstall

```bash
# Install hooks globally (all projects)
claude-profiler install

# Install hooks for current project only
claude-profiler install --project

# Check installation status
claude-profiler status

# Remove hooks
claude-profiler uninstall
```

### View Statistics

```bash
# All-time statistics
claude-profiler stats

# Last 7 days
claude-profiler stats -p week

# Last 30 days
claude-profiler stats -p month

# Today only
claude-profiler stats -p today

# Custom date range
claude-profiler stats --since 2026-01-01 --until 2026-02-01

# With per-session details
claude-profiler stats -p week -v
```

### Session Management

```bash
# List all profiled sessions
claude-profiler sessions

# List sessions from last week
claude-profiler sessions -p week

# View details for a specific session
claude-profiler session <session-id>

# View event timeline for a session
claude-profiler session <session-id> -t
```

### Export Data

```bash
# Export as JSON to stdout
claude-profiler export

# Export to file
claude-profiler export -o stats.json

# Export specific period
claude-profiler export -p month -o monthly.json
```

## What It Tracks

| Metric | Description |
|--------|-------------|
| **Model generation time** | Time Claude spends thinking and generating responses |
| **Tool execution time** | Time spent executing tools (Bash, Read, Edit, Write, Grep, etc.) |
| **User idle time** | Time between Claude finishing and the user's next input |
| **Per-tool breakdown** | Execution time and call count per tool type |
| **Session duration** | Total time per session with turn count |

## How It Works

Claude Code Profiler uses Claude Code's [hooks system](https://docs.anthropic.com/en/docs/claude-code/hooks) to capture events:

- **PreToolUse**: Fired before each tool call - records start timestamp
- **PostToolUse**: Fired after each tool call - records end timestamp, computes duration
- **Stop**: Fired when Claude finishes a turn - marks turn boundary
- **Notification**: Captured for completeness

Events are stored as JSONL files in `~/.claude-profiler/sessions/`, one file per session. The profiler hook is lightweight (~50ms overhead per event) and runs in the background without affecting your workflow.

### Time Breakdown Logic

```
User types message
  |
  v
[Model thinking] -----> PreToolUse event
                            |
                        [Tool executing] -----> PostToolUse event
                                                    |
                                                [Model thinking] -----> PreToolUse ...
                                                                            ...
                                                [Model thinking] -----> Stop event
                                                                            |
                                                                        [User idle]
                                                                            |
                                                                        User types next message
```

## Data Storage

All profiling data is stored locally in `~/.claude-profiler/sessions/`. Each session has its own JSONL file with timestamped events. No data is sent anywhere.

## License

MIT
