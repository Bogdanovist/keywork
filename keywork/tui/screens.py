"""Additional modal screens for the Keywork TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label


class GoalSelectScreen(ModalScreen[str | None]):
    """Select a goal for an action.

    Lists active goals. Returns the selected goal name on Enter, None on Escape.
    """

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, goal_names: list[str], title: str = "Select Goal") -> None:
        super().__init__()
        self._goal_names = goal_names
        self._title = title

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._title, id="goal-select-title"),
            DataTable(id="goal-select-table"),
            Label("[Enter] Select  [Esc] Cancel", id="goal-select-footer"),
            id="goal-select-form",
        )

    def on_mount(self) -> None:
        table = self.query_one("#goal-select-table", DataTable)
        table.add_column("Goal", key="goal")
        table.cursor_type = "row"
        for name in self._goal_names:
            table.add_row(name, key=name)
        if self._goal_names:
            table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            self.dismiss(str(event.row_key.value))


class RepoSelectScreen(ModalScreen[str | None]):
    """Select a repo for an action.

    Lists registered repos. Returns the selected repo name on Enter, None on Escape.
    """

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, repo_names: list[str], title: str = "Select Repo") -> None:
        super().__init__()
        self._repo_names = repo_names
        self._title = title

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._title, id="repo-select-title"),
            DataTable(id="repo-select-table"),
            Label("[Enter] Select  [Esc] Cancel", id="repo-select-footer"),
            id="repo-select-form",
        )

    def on_mount(self) -> None:
        table = self.query_one("#repo-select-table", DataTable)
        table.add_column("Repo", key="repo")
        table.cursor_type = "row"
        for name in self._repo_names:
            table.add_row(name, key=name)
        if self._repo_names:
            table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            self.dismiss(str(event.row_key.value))
