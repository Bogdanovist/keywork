"""File-based state reader for the Keywork TUI.

Reads goal state from agents/goals/ directory structure and repo
configuration from agents/repos/. All state is derived from files
-- no in-memory persistence needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

GOALS_DIR = Path("agents/goals")
REPOS_DIR = Path("agents/repos")
WORKSPACE_DIR = Path("workspace")


@dataclass
class RepoState:
    name: str
    language: str = ""
    framework: str = ""
    remote: str = ""
    branch: str = "main"
    priority: str = "normal"
    initialized: bool = False
    active_goals: int = 0
    path: Path = field(default_factory=Path)


@dataclass
class GoalState:
    name: str
    status: str = "created"
    priority: str = "normal"
    last_activity: str = ""
    completed_tasks: int = 0
    total_tasks: int = 0
    blocked_tasks: int = 0
    review_tasks: int = 0
    total_cost_usd: float = 0.0
    has_replan: bool = False
    has_feedback: bool = False
    prd_summary: str = ""
    repo_name: str = ""
    path: Path = field(default_factory=Path)

    @property
    def progress(self) -> str:
        if self.total_tasks == 0:
            return "no tasks"
        return f"{self.completed_tasks}/{self.total_tasks}"

    @property
    def status_display(self) -> str:
        indicators = []
        if self.has_replan:
            indicators.append("replan")
        if self.has_feedback:
            indicators.append("feedback")
        suffix = f" ({', '.join(indicators)})" if indicators else ""
        return f"{self.status}{suffix}"


@dataclass
class AttentionItem:
    goal_name: str
    item_type: str  # "review", "question", "paused"
    title: str
    task_id: str | None = None
    question_id: str | None = None


def parse_state_md(path: Path) -> dict:
    """Parse a state.md file into a dict of key-value pairs."""
    result = {}
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def parse_config_yaml(path: Path) -> dict:
    """Simple YAML parser for config.yaml files.

    Handles key: value lines, nested keys via indent detection,
    and lists with '- item' syntax. Does not support the full
    YAML specification -- just the subset used in repo configs.
    """
    result = {}
    if not path.exists():
        return result

    lines = path.read_text().splitlines()
    current_key = None
    current_indent = 0

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Measure indent level
        indent = len(line) - len(line.lstrip())

        # List item under a key
        if stripped.startswith("- "):
            if current_key is not None and indent > current_indent:
                item_value = stripped[2:].strip()
                if current_key not in result:
                    result[current_key] = []
                if isinstance(result[current_key], list):
                    result[current_key].append(item_value)
            continue

        # Key-value pair
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            if value:
                # Simple key: value
                if indent == 0:
                    result[key] = value
                elif current_key is not None:
                    # Nested key under a parent -- store as parent.child
                    result[f"{current_key}.{key}"] = value
            else:
                # Key with no value -- becomes a parent for nested keys or a list
                current_key = key
                current_indent = indent

    return result


def count_tasks(impl_path: Path) -> tuple[int, int, int, int]:
    """Count total, completed, blocked, and review tasks in IMPLEMENTATION.md."""
    if not impl_path.exists():
        return 0, 0, 0, 0
    content = impl_path.read_text()
    total = len(re.findall(r"^- \[", content, re.MULTILINE))
    completed = len(re.findall(r"^- \[x\]", content, re.MULTILINE))
    blocked = len(re.findall(r"^- \[BLOCKED", content, re.MULTILINE))
    review = len(re.findall(r"^- \[REVIEW", content, re.MULTILINE))
    return total, completed, blocked, review


def get_prd_summary(prd_path: Path) -> str:
    """Extract first non-empty, non-heading line from PRD as a summary."""
    if not prd_path.exists():
        return ""
    for line in prd_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("<!--"):
            return line[:120]
    return ""


def load_goal(goal_dir: Path) -> GoalState:
    """Load a single goal's state from its directory."""
    name = goal_dir.name
    state_data = parse_state_md(goal_dir / "state.md")
    total, completed, blocked, review = count_tasks(goal_dir / "IMPLEMENTATION.md")

    return GoalState(
        name=name,
        status=state_data.get("status", "created"),
        priority=state_data.get("priority", "normal"),
        last_activity=state_data.get("last_activity", ""),
        completed_tasks=completed,
        total_tasks=total,
        blocked_tasks=blocked,
        review_tasks=review,
        total_cost_usd=float(state_data.get("total_cost_usd", "0")),
        has_replan=(goal_dir / ".replan").exists(),
        has_feedback=(goal_dir / "feedback.md").exists(),
        prd_summary=get_prd_summary(goal_dir / "prd.md"),
        repo_name=state_data.get("repo", ""),
        path=goal_dir,
    )


def load_all_goals() -> list[GoalState]:
    """Load all active goals (not _completed)."""
    goals = []
    if not GOALS_DIR.exists():
        return goals
    for d in sorted(GOALS_DIR.iterdir()):
        if not d.is_dir():
            continue
        if d.name.startswith("_") or d.name.startswith("."):
            continue
        goals.append(load_goal(d))
    return goals


def load_repo_config(repo_dir: Path) -> RepoState:
    """Load a single repo's configuration from its directory."""
    config = parse_config_yaml(repo_dir / "config.yaml")
    name = repo_dir.name

    # Check if workspace directory exists to determine initialized status
    workspace_path = WORKSPACE_DIR / name
    initialized = workspace_path.exists() and workspace_path.is_dir()

    # Count active goals for this repo
    active_goals = 0
    if GOALS_DIR.exists():
        for d in GOALS_DIR.iterdir():
            if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
                continue
            state_data = parse_state_md(d / "state.md")
            if state_data.get("repo", "") == name:
                active_goals += 1

    return RepoState(
        name=name,
        language=config.get("language", ""),
        framework=config.get("framework", ""),
        remote=config.get("remote", ""),
        branch=config.get("branch", "main"),
        priority=config.get("priority", "normal"),
        initialized=initialized,
        active_goals=active_goals,
        path=repo_dir,
    )


def load_registered_repos() -> list[RepoState]:
    """Load all repos from agents/repos/."""
    repos = []
    if not REPOS_DIR.exists():
        return repos
    for d in sorted(REPOS_DIR.iterdir()):
        if not d.is_dir():
            continue
        if d.name.startswith("_") or d.name.startswith("."):
            continue
        repos.append(load_repo_config(d))
    return repos


def load_activity_log(max_lines: int = 50) -> list[str]:
    """Read the orchestrator log for recent activity."""
    log_path = GOALS_DIR / "orchestrator.log"
    if not log_path.exists():
        return []
    lines = log_path.read_text().splitlines()
    return lines[-max_lines:]


def load_task_list(goal_name: str) -> list[str]:
    """Load task lines from a goal's IMPLEMENTATION.md."""
    impl_path = GOALS_DIR / goal_name / "IMPLEMENTATION.md"
    if not impl_path.exists():
        return []
    lines = []
    for line in impl_path.read_text().splitlines():
        if line.startswith("- ["):
            lines.append(line)
    return lines


def _parse_task_id(line: str) -> str | None:
    """Extract T-number from a task line like '- [x] T003: ...'."""
    m = re.search(r"\bT(\d+)", line)
    return f"T{m.group(1)}" if m else None


def _are_depends_satisfied(depends_line: str, content: str) -> bool:
    """Check if all task IDs in a Depends line are marked [x] in content."""
    dep_ids = re.findall(r"T\d+", depends_line)
    if not dep_ids:
        return True
    for dep_id in dep_ids:
        pattern = rf"^- \[x\] {dep_id}\b"
        if not re.search(pattern, content, re.MULTILINE):
            return False
    return True


def load_review_tasks(goal_name: str) -> list[AttentionItem]:
    """Extract actionable [REVIEW: ...] tasks from IMPLEMENTATION.md.

    Only returns review tasks whose Depends are all satisfied ([x]).
    """
    impl_path = GOALS_DIR / goal_name / "IMPLEMENTATION.md"
    if not impl_path.exists():
        return []
    content = impl_path.read_text()
    lines = content.splitlines()
    items = []
    for i, line in enumerate(lines):
        m = re.match(r"^- \[REVIEW:\s*(.+?)\]", line)
        if not m:
            continue
        title = m.group(1).strip()
        task_id = _parse_task_id(line)
        # Look ahead for Depends line in the indented block
        depends_satisfied = True
        for j in range(i + 1, min(i + 10, len(lines))):
            sub = lines[j]
            if sub.startswith("- ["):
                break
            dep_match = re.match(r"\s+-\s+Depends:\s*(.*)", sub)
            if dep_match:
                depends_satisfied = _are_depends_satisfied(dep_match.group(1), content)
                break
        if depends_satisfied:
            items.append(AttentionItem(
                goal_name=goal_name,
                item_type="review",
                title=title,
                task_id=task_id,
            ))
    return items


def load_open_questions(goal_name: str) -> list[AttentionItem]:
    """Parse questions.md Open section into AttentionItems."""
    questions_path = GOALS_DIR / goal_name / "questions.md"
    if not questions_path.exists():
        return []
    content = questions_path.read_text()
    # Find the ## Open section
    open_match = re.search(r"^## Open\s*$", content, re.MULTILINE)
    if not open_match:
        return []
    # Content between ## Open and the next ## heading (or end of file)
    rest = content[open_match.end():]
    next_section = re.search(r"^## ", rest, re.MULTILINE)
    open_section = rest[:next_section.start()] if next_section else rest
    items = []
    for m in re.finditer(r"^### (Q\d+):\s*(.+)", open_section, re.MULTILINE):
        question_id = m.group(1)
        title = m.group(2).strip()
        items.append(AttentionItem(
            goal_name=goal_name,
            item_type="question",
            title=title,
            question_id=question_id,
        ))
    return items


def load_attention_items() -> list[AttentionItem]:
    """Load all items needing human attention across all active goals."""
    items: list[AttentionItem] = []
    if not GOALS_DIR.exists():
        return items
    for d in sorted(GOALS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
            continue
        goal_name = d.name
        # Review tasks with satisfied dependencies
        items.extend(load_review_tasks(goal_name))
        # Open questions
        items.extend(load_open_questions(goal_name))
        # Paused goals
        if (d / ".pause").exists():
            items.append(AttentionItem(
                goal_name=goal_name,
                item_type="paused",
                title=f"Paused: {goal_name}",
            ))
    return items
