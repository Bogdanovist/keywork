"""Shared test fixtures for Keywork tests."""


import pytest


@pytest.fixture
def tmp_keywork_dir(tmp_path):
    """Create a temporary keywork directory structure for testing."""
    goals_dir = tmp_path / "agents" / "goals"
    goals_dir.mkdir(parents=True)
    (goals_dir / "_completed").mkdir()

    repos_dir = tmp_path / "agents" / "repos"
    repos_dir.mkdir(parents=True)

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    return tmp_path
