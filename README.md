# Claude Code Profiler

Profile your Claude Code sessions — track time breakdown, LLM performance (TTFT/TPOT/TPS), token usage, and full prompt/response history.

## Installation

```bash
pip install claude-profiler
```

Or install from source:

```bash
git clone https://github.com/jlxue/claude_profiler.git
cd claude_profiler
pip install .
```

## Quick Start

```bash
# 1. Install profiler hooks (one-time setup)
claude-profiler install

# 2. Use Claude Code normally — profiling happens automatically

# 3. View statistics
claude-profiler stats
```

## Usage

### Install / Uninstall

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

# Today only
claude-profiler stats -p today

# Custom date range
claude-profiler stats --since 2026-01-01 --until 2026-02-01

# With per-session details
claude-profiler stats -p week -v
```

Example output:

```
============================================================
  Claude Code Profiler - Statistics
============================================================
  Period:   2026-03-01 to 2026-03-06
  Sessions: 2
  Turns:    7
  Events:   196

  Total time:        52m 30s

  Time Breakdown:
    Model generation:     15m 32s  (29.6%)
    Tool execution:        1m 11s  ( 2.3%)
    User idle:            34m 16s  (65.3%)

  LLM Performance:
    TTFT (Time to First Token):
      Average:        8.4s  (138 samples)
      Max:          3m 10s
    TPOT (Time Per Output Token):
      Average:        14.3ms  (64 samples)
      Max:           260.0ms
    TPS (Tokens Per Second):
      Average:        70.1
      Min:             3.8

  Token Breakdown (per LLM call):
                                Avg     Median        Max  Samples
    Prompt tokens             53414      54536     114380      138
    Thinking tokens               1          0         12      138
    Response tokens             561        182      11353      138

  Tool Breakdown:
    Bash                     1m 02s  (87.7%)    39 calls  avg 1.6s
    Edit                       4.1s  ( 5.7%)    28 calls  avg 145ms
    Read                       2.7s  ( 3.8%)    13 calls  avg 210ms
    Glob                      855ms  ( 1.2%)     2 calls  avg 427ms
    Write                     666ms  ( 0.9%)     3 calls  avg 222ms
============================================================
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

### Prompt / Response Pairs

View full LLM input/output history for any session:

```bash
# Show all prompt/response pairs
claude-profiler pairs <session-id>

# Show only the last 5 pairs
claude-profiler pairs <session-id> --last 5

# Show full content without truncation
claude-profiler pairs <session-id> --full
```

Each pair includes:
- **Prompt** — user input text or tool results fed back to the model
- **Thinking** — model's thinking/reasoning content (if extended thinking is enabled)
- **Response** — model's text output
- **Tool calls** — tool names and inputs the model invoked
- **Token usage** — input and output token counts

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
| **Tool execution time** | Time spent executing tools (Bash, Read, Edit, Write, etc.) |
| **User idle time** | Time between Claude finishing and the user's next input |
| **Per-tool breakdown** | Execution time and call count per tool type |
| **TTFT** | Time to First Token — from prompt sent to first response token |
| **TPOT** | Time Per Output Token — generation latency per token |
| **TPS** | Tokens Per Second — output generation throughput (= 1/TPOT) |
| **Prompt tokens** | Input tokens per LLM call (including cached tokens) |
| **Thinking tokens** | Tokens used for model's chain-of-thought reasoning |
| **Response tokens** | Output tokens for text and tool calls |

## How It Works

Claude Code Profiler collects data from two sources:

### 1. Hooks (timing events)

Uses Claude Code's [hooks system](https://docs.anthropic.com/en/docs/claude-code/hooks) to capture tool execution timing:

- **PreToolUse** — records timestamp before each tool call
- **PostToolUse** — records timestamp after each tool call, computes duration
- **Stop** — marks turn boundary when Claude finishes generating
- **Notification** — captured for completeness

Events are stored as JSONL files in `~/.claude-profiler/sessions/`.

### 2. Conversation files (LLM metrics & pairs)

Reads Claude Code's conversation history from `~/.claude/projects/` to extract:

- **TTFT/TPOT/TPS** — computed from per-message timestamps and cumulative `output_tokens` in streaming assistant messages
- **Token breakdown** — `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens` for prompt; cumulative `output_tokens` at thinking vs. final block for thinking/response split
- **Prompt/response pairs** — full message content (user prompts, thinking, text, tool_use blocks)

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

- **Hook events**: `~/.claude-profiler/sessions/<session-id>.jsonl`
- **Conversation data**: read from `~/.claude/projects/<project>/<session-id>.jsonl` (Claude Code's own storage, read-only)

All data stays local. Nothing is sent anywhere.

## License

MIT
