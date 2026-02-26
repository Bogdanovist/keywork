"""Keywork Agent TUI -- interactive orchestrator dashboard.

Launch with: python -m keywork.tui
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, Log, Select, Static, TextArea

from keywork.tui.screens import GoalSelectScreen
from keywork.tui.state import (
    load_activity_log,
    load_all_goals,
    load_attention_items,
    load_registered_repos,
    load_task_list,
)

# ---------------------------------------------------------------------------
# Terminal helpers -- simplified from Athena's sandbox/terminal modules.
# Keywork launches scripts directly (no Docker sandbox).
# ---------------------------------------------------------------------------

def _open_terminal(command: str, title: str = "Keywork Agent", working_dir: str | None = None) -> dict:
    """Open a new terminal window running the given command.

    Returns dict with keys: success (bool), method (str), fallback_command (str|None).
    Detection order: iTerm2 -> Terminal.app -> gnome-terminal -> tmux -> fallback.
    """
    import shutil
    import sys

    if working_dir is None:
        working_dir = str(os.getcwd())

    def _applescript_escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    is_mac = sys.platform == "darwin"

    # iTerm2
    if is_mac:
        try:
            check = subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to get name of processes'],
                capture_output=True, text=True, timeout=5,
            )
            if check.returncode == 0 and "iTerm" in check.stdout:
                script = (
                    'tell application "iTerm2"\n'
                    "    create window with default profile\n"
                    "    tell current session of current window\n"
                    f'        set name to "{_applescript_escape(title)}"\n'
                    f'        write text "cd {_applescript_escape(working_dir)}'
                    f" && {_applescript_escape(command)}\"\n"
                    "    end tell\n"
                    "end tell"
                )
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
                if res.returncode == 0:
                    return {"success": True, "method": "iterm2", "fallback_command": None}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Terminal.app
    if is_mac:
        try:
            script = (
                'tell application "Terminal"\n'
                f'    do script "cd {_applescript_escape(working_dir)}'
                f" && {_applescript_escape(command)}\"\n"
                f'    set custom title of front window to "{_applescript_escape(title)}"\n'
                "end tell"
            )
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                return {"success": True, "method": "macos_terminal", "fallback_command": None}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # gnome-terminal
    if shutil.which("gnome-terminal"):
        try:
            full_cmd = f"{command}; echo 'Press Enter to close'; read"
            subprocess.Popen([
                "gnome-terminal", f"--title={title}", f"--working-directory={working_dir}",
                "--", "bash", "-c", full_cmd,
            ])
            return {"success": True, "method": "gnome_terminal", "fallback_command": None}
        except (FileNotFoundError, OSError):
            pass

    # tmux
    if os.environ.get("TMUX"):
        try:
            full_cmd = f"cd {working_dir} && {command}"
            res = subprocess.run(["tmux", "new-window", "-n", title, full_cmd], capture_output=True, timeout=5)
            if res.returncode == 0:
                return {"success": True, "method": "tmux", "fallback_command": None}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Fallback
    full_cmd = f"cd {working_dir} && {command}"
    return {"success": False, "method": "fallback", "fallback_command": full_cmd}


@dataclass
class RunningProcess:
    """A tracked process launched from the TUI."""

    goal_name: str
    action: str
    process: subprocess.Popen
    started_at: datetime
    terminal_pid: int | None = None


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class GoalListWidget(Static):
    """Displays all goals with status, repo, progress, and cost."""

    def compose(self) -> ComposeResult:
        yield DataTable(id="goal-table")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Status", "Repo", "Goal", "Progress", "Priority", "Cost")
        table.cursor_type = "row"
        self.refresh_goals()

    def refresh_goals(self, running_goal_names: set[str] | None = None) -> None:
        table = self.query_one(DataTable)
        table.clear()
        running = running_goal_names or set()
        goals = load_all_goals()
        for g in goals:
            status_style = {
                "building": "[green]building[/]",
                "planning": "[yellow]planning[/]",
                "paused": "[dim]paused[/]",
                "created": "[dim]created[/]",
                "gate_review": "[cyan]gate_review[/]",
                "promoting": "[magenta]promoting[/]",
                "completed": "[bold green]completed[/]",
            }.get(g.status, g.status)
            if g.name in running:
                status_style = f"\u25b6 {status_style}"
            table.add_row(
                status_style,
                g.repo_name or "--",
                g.name,
                g.progress,
                g.priority,
                f"${g.total_cost_usd:.2f}",
                key=g.name,
            )


class ActivityLogWidget(Static):
    """Shows recent orchestrator activity."""

    def compose(self) -> ComposeResult:
        yield Log(id="activity-log", max_lines=200)

    def refresh_log(self) -> None:
        log = self.query_one(Log)
        log.clear()
        lines = load_activity_log()
        for line in lines:
            log.write_line(line)


class NeedsAttentionWidget(Static):
    """Displays items requiring human attention: reviews, questions, paused goals."""

    ICON_MAP = {
        "review": "\U0001f50d",
        "question": "\u2753",
        "paused": "\u23f8",
    }

    def compose(self) -> ComposeResult:
        yield DataTable(id="attention-table")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("", "Item", "Goal")
        table.cursor_type = "row"
        self.refresh_attention()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._attention_count = 0

    def refresh_attention(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        items = load_attention_items()
        self._attention_count = len(items)
        if not items:
            table.add_row("", "Nothing needs your attention", "")
            return
        for item in items:
            icon = self.ICON_MAP.get(item.item_type, "")
            table.add_row(icon, item.title, item.goal_name)

    @property
    def attention_count(self) -> int:
        return self._attention_count


# ---------------------------------------------------------------------------
# Modal screens
# ---------------------------------------------------------------------------


class GoalDetailScreen(ModalScreen[None]):
    """Detail view for a single goal with full lifecycle action keybindings."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("c", "create_prd", "PRD"),
        Binding("b", "start_build", "Build"),
        Binding("p", "force_plan", "Plan"),
        Binding("g", "force_gate", "Gate"),
        Binding("q", "answer_questions", "Questions"),
        Binding("f", "feedback", "Feedback"),
        Binding("F", "feedback_interview", "Interview"),
        Binding("t", "retro", "Retro"),
        Binding("C", "complete_goal", "Complete"),
        Binding("w", "pause_goal", "Pause"),
        Binding("W", "resume_goal", "Resume"),
        Binding("x", "stop_goal", "Stop"),
    ]

    def __init__(self, goal_name: str, repo_name: str = "") -> None:
        super().__init__()
        self.goal_name = goal_name
        self.repo_name = repo_name

    def compose(self) -> ComposeResult:
        tasks = load_task_list(self.goal_name)
        task_text = "\n".join(tasks) if tasks else "No tasks yet."
        title_text = f"Goal: {self.goal_name}"
        if self.repo_name:
            title_text += f" -- repo: {self.repo_name}"

        yield Vertical(
            Label(title_text, id="detail-title"),
            Label("Tasks:", classes="section-header"),
            TextArea(task_text, read_only=True, id="task-area"),
            Label(
                "[c]PRD [b]Build [p]Plan [g]Gate [q]Q&A [f]Feedback [F]Interview\n"
                "[t]Retro [C]Complete [w]Pause [W]Resume [x]Stop [Esc]Back",
                id="detail-footer",
            ),
        )

    def _launch_in_terminal(self, script: str, action: str, args: list[str] | None = None) -> None:
        """Launch an interactive agent session in a new terminal window."""
        cmd_args = args if args is not None else [self.goal_name]
        command = f"bash {script} {' '.join(cmd_args)}"
        result = _open_terminal(
            command=command,
            title=f"Keywork: {action} -- {self.goal_name}",
        )
        if result["success"]:
            self.notify(f"{action.replace('_', ' ').title()} session opened for {self.goal_name}")
        elif result["fallback_command"]:
            self.notify(f"No terminal found. Run manually:\n{result['fallback_command']}", severity="warning")
        else:
            self.notify(f"Failed to open terminal for {action}", severity="error")

    def _launch_background(self, script: str, args: list[str] | None = None) -> None:
        """Launch a background agent process."""
        cmd_args = args if args is not None else [self.goal_name]
        try:
            process = subprocess.Popen(
                ["bash", script] + cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.app._running_processes.append(RunningProcess(
                goal_name=self.goal_name,
                action="build",
                process=process,
                started_at=datetime.now(),
            ))
            self.notify(f"Started background process for {self.goal_name}")
        except Exception as e:
            self.notify(f"Failed to launch: {e}", severity="error")

    def action_create_prd(self) -> None:
        self._launch_in_terminal("agents/create_prd.sh", "prd")

    def action_start_build(self) -> None:
        self._launch_background("agents/loop.sh")

    def action_force_plan(self) -> None:
        self._launch_background("agents/loop.sh", [self.goal_name, "plan"])

    def action_force_gate(self) -> None:
        self._launch_background("agents/loop.sh", [self.goal_name, "final_gate"])

    def action_answer_questions(self) -> None:
        self._launch_in_terminal("agents/questions.sh", "questions")

    def action_feedback(self) -> None:
        self.app.push_screen(FeedbackScreen(self.goal_name))

    def action_feedback_interview(self) -> None:
        self._launch_in_terminal("agents/feedback.sh", "feedback")

    def action_retro(self) -> None:
        self._launch_in_terminal("agents/retro.sh", "retro")

    def action_complete_goal(self) -> None:
        self._launch_in_terminal("agents/complete_goal.sh", "complete")

    def action_pause_goal(self) -> None:
        pause_file = f"agents/goals/{self.goal_name}/.pause"
        with open(pause_file, "w") as f:
            f.write("Paused from TUI\n")
        self.notify(f"Paused {self.goal_name}")

    def action_resume_goal(self) -> None:
        pause_file = f"agents/goals/{self.goal_name}/.pause"
        if os.path.exists(pause_file):
            os.remove(pause_file)
            self.notify(f"Resumed {self.goal_name}")
        else:
            self.notify(f"{self.goal_name} is not paused")

    def action_stop_goal(self) -> None:
        stop_file = f"agents/goals/{self.goal_name}/.stop"
        with open(stop_file, "w") as f:
            f.write("Stopped from TUI\n")
        self.notify(f"Stop signal sent to {self.goal_name}")


class CreateGoalScreen(ModalScreen[str | None]):
    """Form to create a new goal with repo selection."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        # Build repo options from registered repos
        repos = load_registered_repos()
        repo_options = [("(none)", "")] + [(r.name, r.name) for r in repos]

        yield Vertical(
            Label("Create New Goal"),
            Label("Name (kebab-case):"),
            Input(id="goal-name-input", placeholder="e.g. auth-service-refactor"),
            Label("Repo:"),
            Select(repo_options, value="", id="repo-select"),
            Label("Priority:"),
            Select(
                [("low", "low"), ("normal", "normal"), ("high", "high"), ("urgent", "urgent")],
                value="normal",
                id="priority-select",
            ),
            Label("[Enter] Create  [Esc] Cancel"),
            id="create-form",
        )

    @on(Input.Submitted, "#goal-name-input")
    def on_submit(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if not name:
            self.notify("Goal name cannot be empty", severity="error")
            return

        # Build command with optional repo argument
        repo_select = self.query_one("#repo-select", Select)
        repo_name = repo_select.value if repo_select.value else ""
        cmd = ["bash", "agents/new_goal.sh", name]
        if repo_name:
            cmd.append(repo_name)

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            # Update priority if not normal
            priority_select = self.query_one("#priority-select", Select)
            if priority_select.value != "normal":
                state_file = f"agents/goals/{name}/state.md"
                if os.path.exists(state_file):
                    content = open(state_file).read()
                    content = content.replace("priority: normal", f"priority: {priority_select.value}")
                    with open(state_file, "w") as f:
                        f.write(content)
            self.dismiss(name)
        else:
            self.notify(f"Failed: {result.stderr.strip()}", severity="error")


class FeedbackScreen(ModalScreen[None]):
    """Feedback entry for a goal."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, goal_name: str) -> None:
        super().__init__()
        self.goal_name = goal_name

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(f"Feedback for: {self.goal_name}"),
            Label("Describe what you observed during testing:"),
            TextArea(id="feedback-text"),
            Label("[Ctrl+S] Submit  [Esc] Cancel"),
            id="feedback-form",
        )

    def key_ctrl_s(self) -> None:
        import re as _re

        text_area = self.query_one("#feedback-text", TextArea)
        feedback_text = text_area.text.strip()
        if not feedback_text:
            self.notify("Feedback cannot be empty", severity="error")
            return

        # Append directly to feedback.md
        feedback_file = f"agents/goals/{self.goal_name}/feedback.md"
        if not os.path.exists(feedback_file):
            with open(feedback_file, "w") as f:
                f.write("# Human Feedback\n\n<!-- Last incorporated: none -->\n\n## Open\n\n## Resolved\n")

        # Find next F number
        content = open(feedback_file).read()
        existing = _re.findall(r"F(\d+)", content)
        next_num = max((int(n) for n in existing), default=0) + 1

        with open(feedback_file, "a") as f:
            f.write(f"\n### F{next_num:03d}: TUI feedback\n")
            f.write("- **Type**: observation\n")
            f.write("- **Related tasks**: (to be classified by plan agent)\n")
            f.write(f"- **Observed**: {feedback_text}\n")
            f.write("- **Expected**: (to be clarified)\n")
            f.write("- **Notes**: Submitted via TUI\n\n")

        self.notify(f"F{next_num:03d} recorded")
        self.dismiss()


class BuildLogScreen(ModalScreen[None]):
    """Live build output viewer."""

    BINDINGS = [Binding("escape", "dismiss", "Back")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Build Log (live tail of session.log)"),
            Log(id="build-log", max_lines=500),
            Label("[Esc] Back"),
        )

    def on_mount(self) -> None:
        self.load_logs()

    def load_logs(self) -> None:
        log_widget = self.query_one("#build-log", Log)
        # Show the most recent goal's session log
        goals = load_all_goals()
        active = [g for g in goals if g.status in ("building", "planning")]
        if not active:
            active = goals
        if not active:
            log_widget.write_line("No active goals.")
            return
        session_log = active[0].path / "session.log"
        if session_log.exists():
            lines = session_log.read_text().splitlines()
            for line in lines[-100:]:
                log_widget.write_line(line)
        else:
            log_widget.write_line(f"No session.log for {active[0].name}")


class RepoListScreen(ModalScreen[None]):
    """List of registered repos with management actions."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("a", "add_repo", "Add Repo"),
        Binding("i", "init_repo", "Initialize"),
        Binding("enter", "select_repo", "Details", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Registered Repos", id="repo-list-title"),
            DataTable(id="repo-list-table"),
            Label("[a]Add Repo  [i]Initialize  [Enter]Details  [Esc]Back", id="repo-list-footer"),
        )

    def on_mount(self) -> None:
        table = self.query_one("#repo-list-table", DataTable)
        table.add_columns("Name", "Language", "Priority", "Goals", "Initialized")
        table.cursor_type = "row"
        self.refresh_repos()

    def refresh_repos(self) -> None:
        table = self.query_one("#repo-list-table", DataTable)
        table.clear()
        repos = load_registered_repos()
        if not repos:
            table.add_row("(no repos registered)", "", "", "", "")
            return
        for r in repos:
            table.add_row(
                r.name,
                r.language or "--",
                r.priority,
                str(r.active_goals),
                "yes" if r.initialized else "no",
                key=r.name,
            )

    def _get_selected_repo_name(self) -> str | None:
        table = self.query_one("#repo-list-table", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        if row_key and row_key.value:
            return str(row_key.value)
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            self.app.push_screen(RepoDetailScreen(str(event.row_key.value)))

    def action_select_repo(self) -> None:
        name = self._get_selected_repo_name()
        if name:
            self.app.push_screen(RepoDetailScreen(name))

    def action_add_repo(self) -> None:
        def on_result(result: str | None) -> None:
            if result:
                self.refresh_repos()
                self.notify(f"Repo '{result}' registered")

        self.app.push_screen(AddRepoScreen(), callback=on_result)

    def action_init_repo(self) -> None:
        name = self._get_selected_repo_name()
        if not name:
            self.notify("No repo selected", severity="warning")
            return
        command = f"bash agents/repo_init.sh {name}"
        result = _open_terminal(command=command, title=f"Keywork: init -- {name}")
        if result["success"]:
            self.notify(f"Init session opened for {name}")
        elif result["fallback_command"]:
            self.notify(f"No terminal found. Run manually:\n{result['fallback_command']}", severity="warning")
        else:
            self.notify("Failed to open terminal for init", severity="error")


class RepoDetailScreen(ModalScreen[None]):
    """Detail view for a single repo with management actions."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("i", "init_repo", "Init/Re-init"),
        Binding("n", "new_goal_for_repo", "New Goal"),
        Binding("p", "git_pull", "Git Pull"),
    ]

    def __init__(self, repo_name: str) -> None:
        super().__init__()
        self.repo_name = repo_name

    def compose(self) -> ComposeResult:
        from keywork.tui.state import REPOS_DIR, load_repo_config

        repo_dir = REPOS_DIR / self.repo_name
        repo = load_repo_config(repo_dir)

        detail_lines = [
            f"Name:        {repo.name}",
            f"Remote:      {repo.remote or '(not set)'}",
            f"Branch:      {repo.branch}",
            f"Language:    {repo.language or '(not set)'}",
            f"Framework:   {repo.framework or '(not set)'}",
            f"Priority:    {repo.priority}",
            f"Initialized: {'yes' if repo.initialized else 'no'}",
            f"Active goals: {repo.active_goals}",
        ]

        yield Vertical(
            Label(f"Repo: {self.repo_name}", id="detail-title"),
            TextArea("\n".join(detail_lines), read_only=True, id="repo-detail-area"),
            Label("[i]Init/Re-init  [n]New Goal  [p]Git Pull  [Esc]Back", id="detail-footer"),
        )

    def _launch_in_terminal(self, command: str, action: str) -> None:
        """Launch a command in a new terminal window."""
        result = _open_terminal(
            command=command,
            title=f"Keywork: {action} -- {self.repo_name}",
        )
        if result["success"]:
            self.notify(f"{action.replace('_', ' ').title()} session opened for {self.repo_name}")
        elif result["fallback_command"]:
            self.notify(f"No terminal found. Run manually:\n{result['fallback_command']}", severity="warning")
        else:
            self.notify(f"Failed to open terminal for {action}", severity="error")

    def action_init_repo(self) -> None:
        self._launch_in_terminal(f"bash agents/repo_init.sh {self.repo_name}", "init")

    def action_new_goal_for_repo(self) -> None:
        def on_result(name: str | None) -> None:
            if name:
                self.notify(f"Goal '{name}' created for repo {self.repo_name}")

        self.app.push_screen(CreateGoalScreen(), callback=on_result)

    def action_git_pull(self) -> None:
        from keywork.tui.state import WORKSPACE_DIR

        workspace_path = WORKSPACE_DIR / self.repo_name
        if not workspace_path.exists():
            self.notify(f"Workspace for {self.repo_name} not found. Initialize first.", severity="warning")
            return
        self._launch_in_terminal(f"cd workspace/{self.repo_name} && git pull", "git_pull")


class AddRepoScreen(ModalScreen[str | None]):
    """Form to register a new repo."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Register New Repo"),
            Label("Name (kebab-case):"),
            Input(id="repo-name-input", placeholder="e.g. my-web-app"),
            Label("Git remote URL:"),
            Input(id="repo-remote-input", placeholder="e.g. git@github.com:org/repo.git"),
            Label("[Enter] Register  [Esc] Cancel"),
            id="add-repo-form",
        )

    @on(Input.Submitted, "#repo-name-input")
    def on_name_submitted(self, event: Input.Submitted) -> None:
        # Move focus to remote input
        self.query_one("#repo-remote-input", Input).focus()

    @on(Input.Submitted, "#repo-remote-input")
    def on_submit(self, event: Input.Submitted) -> None:
        name = self.query_one("#repo-name-input", Input).value.strip()
        remote = event.value.strip()

        if not name:
            self.notify("Repo name cannot be empty", severity="error")
            return
        if not remote:
            self.notify("Git remote URL cannot be empty", severity="error")
            return

        # Launch repo_init.sh in terminal
        command = f"bash agents/repo_init.sh {name} {remote}"
        result = _open_terminal(command=command, title=f"Keywork: register -- {name}")

        if result["success"]:
            self.dismiss(name)
        elif result["fallback_command"]:
            self.notify(f"No terminal found. Run manually:\n{result['fallback_command']}", severity="warning")
        else:
            self.notify("Failed to open terminal for repo registration", severity="error")


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------


class KeyworkTUI(App):
    """Keywork Agent System TUI."""

    TITLE = "Keywork Agent System"
    CSS = """
    #top-row { height: 2fr; }
    #goal-list { width: 1fr; }
    #attention { width: 1fr; }
    #activity { height: 1fr; }
    #status-bar { height: 3; padding: 0 1; background: $surface; }
    GoalListWidget { height: 1fr; }
    NeedsAttentionWidget { height: 1fr; }
    ActivityLogWidget { height: 1fr; }
    .section-header { text-style: bold; margin-top: 1; }
    #detail-title { text-style: bold; padding: 1; }
    #detail-footer { margin-top: 1; }
    #create-form { padding: 2; }
    #feedback-form { padding: 2; }
    #add-repo-form { padding: 2; }
    #task-area { height: 1fr; }
    #repo-detail-area { height: 1fr; }
    #repo-list-title { text-style: bold; padding: 1; }
    #repo-list-footer { margin-top: 1; }
    """

    BINDINGS = [
        Binding("n", "new_goal", "New Goal"),
        Binding("m", "manage_repos", "Repos"),
        Binding("a", "focus_attention", "Attention"),
        Binding("f", "feedback", "Feedback"),
        Binding("s", "start_orchestrator", "Start"),
        Binding("x", "stop_orchestrator", "Stop"),
        Binding("l", "show_log", "Build Log"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    orchestrator_running: reactive[bool] = reactive(False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._running_processes: list[RunningProcess] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top-row"):
            with Vertical(id="goal-list"):
                yield Label("Goals", classes="section-header")
                yield GoalListWidget()
            with Vertical(id="attention"):
                yield Label("Needs Attention", classes="section-header")
                yield NeedsAttentionWidget()
        with Vertical(id="activity"):
            yield Label("Activity", classes="section-header")
            yield ActivityLogWidget()
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_display()
        self.set_interval(5, self.refresh_display)

    def refresh_display(self) -> None:
        # Poll running processes: remove dead ones
        alive = []
        for rp in self._running_processes:
            if rp.process.poll() is None:
                alive.append(rp)
        self._running_processes = alive

        # Update orchestrator_running based on tracked processes
        self.orchestrator_running = any(rp.action == "orchestrator" for rp in self._running_processes)

        running_goal_names = {rp.goal_name for rp in self._running_processes}
        self.query_one(GoalListWidget).refresh_goals(running_goal_names=running_goal_names)
        self.query_one(ActivityLogWidget).refresh_log()
        attention_widget = self.query_one(NeedsAttentionWidget)
        attention_widget.refresh_attention()
        attn_count = attention_widget.attention_count
        status = "Orchestrator: RUNNING" if self.orchestrator_running else "Orchestrator: STOPPED"
        goals = load_all_goals()
        total_cost = sum(g.total_cost_usd for g in goals)
        self.query_one("#status-bar", Static).update(
            f"  {status}  |  Goals: {len(goals)}  |  Attn: {attn_count}  |  "
            f"Total cost: ${total_cost:.2f}  |  "
            f"[n]ew  [m]repos  [a]ttn  [f]eedback  [s]tart  [x]stop  [l]og  [r]efresh  [q]uit"
        )

    @on(DataTable.RowSelected, "#goal-table")
    def on_goal_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            goal_name = str(event.row_key.value)
            # Find the repo_name for this goal
            goals = load_all_goals()
            repo_name = ""
            for g in goals:
                if g.name == goal_name:
                    repo_name = g.repo_name
                    break
            self.push_screen(GoalDetailScreen(goal_name, repo_name=repo_name))

    def action_new_goal(self) -> None:
        def on_result(name: str | None) -> None:
            if name:
                self.notify(f"Goal '{name}' created")
                self.refresh_display()

        self.push_screen(CreateGoalScreen(), callback=on_result)

    def action_manage_repos(self) -> None:
        self.push_screen(RepoListScreen())

    def action_feedback(self) -> None:
        goals = load_all_goals()
        active = [g for g in goals if g.status not in ("completed", "created")]
        if not active:
            self.notify("No active goals for feedback", severity="warning")
            return
        if len(active) == 1:
            self.push_screen(FeedbackScreen(active[0].name))
        else:
            def on_goal_selected(goal_name: str | None) -> None:
                if goal_name:
                    self.push_screen(FeedbackScreen(goal_name))

            self.push_screen(
                GoalSelectScreen([g.name for g in active], title="Feedback: Select Goal"),
                callback=on_goal_selected,
            )

    def action_show_log(self) -> None:
        self.push_screen(BuildLogScreen())

    def action_focus_attention(self) -> None:
        self.query_one("#attention-table", DataTable).focus()

    def action_refresh(self) -> None:
        self.refresh_display()
        self.notify("Refreshed")

    def action_start_orchestrator(self) -> None:
        if self.orchestrator_running:
            self.notify("Orchestrator already running", severity="warning")
            return
        try:
            process = subprocess.Popen(
                ["bash", "agents/orchestrate.sh"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self._running_processes.append(RunningProcess(
                goal_name="__orchestrator__",
                action="orchestrator",
                process=process,
                started_at=datetime.now(),
            ))
            self.orchestrator_running = True
            self.refresh_display()
        except Exception as e:
            self.notify(f"Orchestrator error: {e}", severity="error")

    def _append_activity(self, line: str) -> None:
        log = self.query_one("#activity-log", Log)
        log.write_line(line)

    def action_stop_orchestrator(self) -> None:
        if not self.orchestrator_running:
            self.notify("Orchestrator not running", severity="warning")
            return
        # Write stop files for all active goals
        goals = load_all_goals()
        for g in goals:
            if g.status in ("building", "planning"):
                stop_file = g.path / ".stop"
                stop_file.write_text("Stopped from TUI\n")
        self.notify("Stop signal sent")


def main():
    app = KeyworkTUI()
    app.run()


if __name__ == "__main__":
    main()
