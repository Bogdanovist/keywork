"""Terminal session manager for the Keywork TUI.

Launches interactive agent sessions in new terminal windows/tabs.
Detects the available terminal emulator and constructs the appropriate
launch command, tracking sessions for the TUI to display.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from keywork.tui.sandbox import build_sandbox_command

logger = logging.getLogger(__name__)


@dataclass
class TerminalResult:
    """Result of attempting to open a terminal session."""

    success: bool
    method: str  # "iterm2", "macos_terminal", "gnome_terminal", "x_terminal_emulator", "tmux", "fallback"
    pid: int | None = None
    fallback_command: str | None = None  # Command string when fallback is used


@dataclass
class TerminalSession:
    """A tracked terminal session launched from the TUI."""

    session_id: str
    goal_name: str
    action: str  # "prd", "questions", "review", "feedback", "retro", "complete"
    command: str
    method: str
    started_at: datetime
    pid: int | None = None


_sessions: list[TerminalSession] = []


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _is_iterm2_available() -> bool:
    """Check if iTerm2 is running on macOS."""
    if not _is_macos():
        return False
    try:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to get name of processes'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and "iTerm" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _launch_iterm2(command: str, title: str, working_dir: str) -> TerminalResult:
    """Launch a command in a new iTerm2 window via AppleScript."""
    # Escape double quotes and backslashes for AppleScript string embedding
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_cmd = command.replace("\\", "\\\\").replace('"', '\\"')
    safe_dir = working_dir.replace("\\", "\\\\").replace('"', '\\"')

    script = (
        'tell application "iTerm2"\n'
        "    create window with default profile\n"
        "    tell current session of current window\n"
        f'        set name to "{safe_title}"\n'
        f'        write text "cd {safe_dir} && {safe_cmd}"\n'
        "    end tell\n"
        "end tell"
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return TerminalResult(success=True, method="iterm2")
        logger.warning("iTerm2 AppleScript failed: %s", result.stderr.strip())
        return TerminalResult(success=False, method="iterm2")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("iTerm2 launch failed: %s", e)
        return TerminalResult(success=False, method="iterm2")


def _launch_macos_terminal(command: str, title: str, working_dir: str) -> TerminalResult:
    """Launch a command in macOS Terminal.app via AppleScript."""
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_cmd = command.replace("\\", "\\\\").replace('"', '\\"')
    safe_dir = working_dir.replace("\\", "\\\\").replace('"', '\\"')

    script = (
        'tell application "Terminal"\n'
        f'    do script "cd {safe_dir} && {safe_cmd}"\n'
        f'    set custom title of front window to "{safe_title}"\n'
        "end tell"
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return TerminalResult(success=True, method="macos_terminal")
        logger.warning("Terminal.app AppleScript failed: %s", result.stderr.strip())
        return TerminalResult(success=False, method="macos_terminal")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("Terminal.app launch failed: %s", e)
        return TerminalResult(success=False, method="macos_terminal")


def _launch_gnome_terminal(command: str, title: str, working_dir: str) -> TerminalResult:
    """Launch a command in gnome-terminal."""
    full_cmd = f"{command}; echo 'Press Enter to close'; read"
    try:
        proc = subprocess.Popen(
            [
                "gnome-terminal",
                f"--title={title}",
                f"--working-directory={working_dir}",
                "--",
                "bash",
                "-c",
                full_cmd,
            ],
        )
        return TerminalResult(success=True, method="gnome_terminal", pid=proc.pid)
    except (FileNotFoundError, OSError) as e:
        logger.warning("gnome-terminal launch failed: %s", e)
        return TerminalResult(success=False, method="gnome_terminal")


def _launch_x_terminal_emulator(command: str, title: str, working_dir: str) -> TerminalResult:
    """Launch a command in x-terminal-emulator (generic Linux)."""
    full_cmd = f"cd {working_dir} && {command}; echo 'Press Enter to close'; read"
    try:
        proc = subprocess.Popen(
            [
                "x-terminal-emulator",
                "-T",
                title,
                "-e",
                f"bash -c '{full_cmd}'",
            ],
        )
        return TerminalResult(success=True, method="x_terminal_emulator", pid=proc.pid)
    except (FileNotFoundError, OSError) as e:
        logger.warning("x-terminal-emulator launch failed: %s", e)
        return TerminalResult(success=False, method="x_terminal_emulator")


def _launch_tmux(command: str, title: str, working_dir: str) -> TerminalResult:
    """Launch a command in a new tmux window."""
    full_cmd = f"cd {working_dir} && {command}"
    try:
        result = subprocess.run(
            ["tmux", "new-window", "-n", title, full_cmd],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return TerminalResult(success=True, method="tmux")
        logger.warning("tmux launch failed: %s", result.stderr.strip())
        return TerminalResult(success=False, method="tmux")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("tmux launch failed: %s", e)
        return TerminalResult(success=False, method="tmux")


def _fallback(command: str, working_dir: str) -> TerminalResult:
    """Return the command string for manual execution when no terminal is found."""
    full_cmd = f"cd {working_dir} && {command}"
    return TerminalResult(
        success=False,
        method="fallback",
        fallback_command=full_cmd,
    )


def open_terminal_session(
    command: str,
    title: str = "Keywork Agent",
    working_dir: str | None = None,
) -> TerminalResult:
    """Open a new terminal window/tab running the given command.

    Detection order: iTerm2 -> Terminal.app -> gnome-terminal ->
    x-terminal-emulator -> tmux -> fallback.
    """
    if working_dir is None:
        working_dir = str(Path.cwd())

    # 1. macOS -- iTerm2
    if _is_macos() and _is_iterm2_available():
        result = _launch_iterm2(command, title, working_dir)
        if result.success:
            return result

    # 2. macOS -- Terminal.app
    if _is_macos():
        result = _launch_macos_terminal(command, title, working_dir)
        if result.success:
            return result

    # 3. Linux -- gnome-terminal
    if shutil.which("gnome-terminal"):
        result = _launch_gnome_terminal(command, title, working_dir)
        if result.success:
            return result

    # 4. Linux -- x-terminal-emulator
    if shutil.which("x-terminal-emulator"):
        result = _launch_x_terminal_emulator(command, title, working_dir)
        if result.success:
            return result

    # 5. tmux (any platform, if inside a tmux session)
    if os.environ.get("TMUX"):
        result = _launch_tmux(command, title, working_dir)
        if result.success:
            return result

    # 6. Fallback
    return _fallback(command, working_dir)


def get_active_sessions() -> list[TerminalSession]:
    """Return sessions whose terminal processes are still running."""
    active = []
    for session in _sessions:
        if session.pid is not None:
            try:
                os.kill(session.pid, 0)
                active.append(session)
            except OSError:
                pass  # Process is dead
        else:
            # No PID to check (AppleScript-launched sessions) -- include if recent
            active.append(session)
    return active


def get_session_history() -> list[TerminalSession]:
    """Return all sessions launched this TUI session."""
    return list(_sessions)


def launch_agent_in_terminal(
    script: str,
    args: list[str],
    goal_name: str,
    action: str,
    repo_name: str = "",
    extra_ports: list[int] | None = None,
) -> TerminalResult:
    """Build a sandbox command and launch it in a new terminal.

    High-level function that integrates the sandbox launcher with the
    terminal session manager.
    """
    cmd_list, _container_name = build_sandbox_command(
        script=script,
        args=args,
        repo_name=repo_name,
        goal_name=goal_name,
        interactive=True,
        extra_ports=extra_ports,
    )
    # Convert command list to a string for terminal execution
    command = " ".join(_shell_quote(part) for part in cmd_list)
    title = f"Keywork: {action} — {goal_name}"
    if repo_name:
        title = f"Keywork: {action} — {goal_name} ({repo_name})"
    result = open_terminal_session(
        command=command,
        title=title,
        working_dir=str(Path.cwd()),
    )
    if result.success:
        _sessions.append(
            TerminalSession(
                session_id=str(uuid4()),
                goal_name=goal_name,
                action=action,
                command=command,
                method=result.method,
                started_at=datetime.now(),
                pid=result.pid,
            )
        )
    return result


def _shell_quote(s: str) -> str:
    """Quote a string for safe shell usage, wrapping in single quotes if needed."""
    if not s:
        return "''"
    # If the string contains only safe characters, no quoting needed
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-=/.:")
    if all(c in safe_chars for c in s):
        return s
    # Use single quotes, escaping any existing single quotes
    return "'" + s.replace("'", "'\"'\"'") + "'"
