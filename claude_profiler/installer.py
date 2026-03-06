"""Install/uninstall Claude Code hooks for profiling."""

import json
import os
import shutil
import sys

HOOK_MARKER = "claude-profiler"

HOOK_EVENTS = {
    "PreToolUse": {"matcher": "", "command": "{profiler_bin} log pre_tool_use"},
    "PostToolUse": {"matcher": "", "command": "{profiler_bin} log post_tool_use"},
    "Stop": {"matcher": "", "command": "{profiler_bin} log stop"},
    "Notification": {"matcher": "", "command": "{profiler_bin} log notification"},
}


def _has_marker(hook_entry: dict) -> bool:
    """Check if a hook entry contains the profiler marker (supports old and new format)."""
    # New format: {"matcher": "...", "hooks": [{"type": "command", "command": "..."}]}
    for sub_hook in hook_entry.get("hooks", []):
        if HOOK_MARKER in sub_hook.get("command", ""):
            return True
    # Old format: {"command": "..."}
    if HOOK_MARKER in hook_entry.get("command", ""):
        return True
    return False


def _get_settings_path(project: bool = False) -> str:
    if project:
        return os.path.join(os.getcwd(), ".claude", "settings.json")
    return os.path.expanduser("~/.claude/settings.json")


def _get_profiler_bin() -> str:
    """Get the full path to the claude-profiler binary."""
    which = shutil.which("claude-profiler")
    if which:
        return which
    # Fallback: try to find it relative to this file
    # (in case installed in a venv that's not in PATH)
    bin_dir = os.path.dirname(sys.executable)
    candidate = os.path.join(bin_dir, "claude-profiler")
    if os.path.isfile(candidate):
        return candidate
    return "claude-profiler"


def _load_settings(path: str) -> dict:
    if os.path.isfile(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_settings(path: str, settings: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


def install(project: bool = False) -> str:
    """Install profiler hooks into Claude Code settings.

    Returns a message describing what was done.
    """
    path = _get_settings_path(project)
    settings = _load_settings(path)
    profiler_bin = _get_profiler_bin()

    if "hooks" not in settings:
        settings["hooks"] = {}

    hooks = settings["hooks"]
    added = []

    for event_name, hook_template in HOOK_EVENTS.items():
        if event_name not in hooks:
            hooks[event_name] = []

        # Check if profiler hook already exists (support both old and new format)
        already_installed = any(
            _has_marker(h) for h in hooks[event_name]
        )
        if already_installed:
            continue

        command = hook_template["command"].format(profiler_bin=profiler_bin)
        hook = {
            "matcher": hook_template.get("matcher", ""),
            "hooks": [
                {
                    "type": "command",
                    "command": command,
                }
            ],
        }
        hooks[event_name].append(hook)
        added.append(event_name)

    _save_settings(path, settings)

    scope = "project" if project else "global"
    if added:
        return f"Installed hooks for {', '.join(added)} in {scope} settings ({path})"
    return f"Profiler hooks already installed in {scope} settings ({path})"


def uninstall(project: bool = False) -> str:
    """Remove profiler hooks from Claude Code settings."""
    path = _get_settings_path(project)
    settings = _load_settings(path)

    if "hooks" not in settings:
        return "No hooks found in settings."

    hooks = settings["hooks"]
    removed = []

    for event_name in list(hooks.keys()):
        original_len = len(hooks[event_name])
        hooks[event_name] = [
            h for h in hooks[event_name]
            if not _has_marker(h)
        ]
        if len(hooks[event_name]) < original_len:
            removed.append(event_name)
        if not hooks[event_name]:
            del hooks[event_name]

    if not hooks:
        del settings["hooks"]

    _save_settings(path, settings)

    if removed:
        return f"Removed hooks for {', '.join(removed)} from {path}"
    return "No profiler hooks found to remove."


def status(project: bool = False) -> str:
    """Check if profiler hooks are installed."""
    path = _get_settings_path(project)
    settings = _load_settings(path)

    if "hooks" not in settings:
        return f"Not installed ({path})"

    hooks = settings["hooks"]
    installed = []
    for event_name, hook_list in hooks.items():
        for h in hook_list:
            if _has_marker(h):
                installed.append(event_name)
                break

    if installed:
        return f"Installed: {', '.join(installed)} ({path})"
    return f"Not installed ({path})"
