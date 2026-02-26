"""Tests for keywork.tui.state — file-based state reader."""



from keywork.tui.state import (
    count_tasks,
    get_prd_summary,
    load_attention_items,
    load_goal,
    load_registered_repos,
    parse_config_yaml,
    parse_state_md,
)


class TestParseStateMd:
    def test_basic_parsing(self, tmp_path):
        state_file = tmp_path / "state.md"
        state_file.write_text("# Goal State\n\nstatus: building\npriority: high\nrepo: my-project\n")
        result = parse_state_md(state_file)
        assert result["status"] == "building"
        assert result["priority"] == "high"
        assert result["repo"] == "my-project"

    def test_missing_file(self, tmp_path):
        result = parse_state_md(tmp_path / "nonexistent.md")
        assert result == {}

    def test_skips_headings(self, tmp_path):
        state_file = tmp_path / "state.md"
        state_file.write_text("# Goal State\nstatus: created\n")
        result = parse_state_md(state_file)
        assert "# Goal State" not in result
        assert result["status"] == "created"


class TestParseConfigYaml:
    def test_basic_key_value(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("name: my-project\nlanguage: python\ninitialized: true\n")
        result = parse_config_yaml(config)
        assert result["name"] == "my-project"
        assert result["language"] == "python"
        assert result["initialized"] == "true"

    def test_nested_keys(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("checks:\n  lint: ruff check .\n  test: pytest\n")
        result = parse_config_yaml(config)
        assert result["checks.lint"] == "ruff check ."
        assert result["checks.test"] == "pytest"

    def test_list_values(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("skills:\n  - testing\n  - docker\n")
        result = parse_config_yaml(config)
        assert result["skills"] == ["testing", "docker"]

    def test_comments_ignored(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("# comment\nname: test\n# another comment\n")
        result = parse_config_yaml(config)
        assert result == {"name": "test"}

    def test_missing_file(self, tmp_path):
        result = parse_config_yaml(tmp_path / "nonexistent.yaml")
        assert result == {}


class TestCountTasks:
    def test_mixed_statuses(self, tmp_path):
        impl = tmp_path / "IMPLEMENTATION.md"
        impl.write_text(
            "# Implementation Plan\n\n"
            "- [ ] T001: First task\n"
            "- [x] T002: Completed task\n"
            "- [BLOCKED: needs info] T003: Blocked task\n"
            "- [REVIEW: check output] T004: Review task\n"
            "- [ ] T005: Another pending\n"
        )
        total, completed, blocked, review = count_tasks(impl)
        assert total == 5
        assert completed == 1
        assert blocked == 1
        assert review == 1

    def test_no_tasks(self, tmp_path):
        impl = tmp_path / "IMPLEMENTATION.md"
        impl.write_text("# Implementation Plan\n\nNo tasks yet.\n")
        assert count_tasks(impl) == (0, 0, 0, 0)

    def test_missing_file(self, tmp_path):
        assert count_tasks(tmp_path / "nonexistent.md") == (0, 0, 0, 0)


class TestGetPrdSummary:
    def test_extracts_first_content_line(self, tmp_path):
        prd = tmp_path / "prd.md"
        prd.write_text("# My Feature\n\nAdd user authentication to the API.\n\n## Requirements\n")
        assert get_prd_summary(prd) == "Add user authentication to the API."

    def test_truncates_long_lines(self, tmp_path):
        prd = tmp_path / "prd.md"
        prd.write_text(f"# PRD\n\n{'x' * 200}\n")
        assert len(get_prd_summary(prd)) == 120

    def test_missing_file(self, tmp_path):
        assert get_prd_summary(tmp_path / "nonexistent.md") == ""


class TestLoadGoal:
    def test_loads_goal_state(self, tmp_path):
        goal_dir = tmp_path / "my-feature"
        goal_dir.mkdir()
        (goal_dir / "state.md").write_text(
            "status: building\npriority: high\nrepo: my-project\ntotal_cost_usd: 1.50\n"
        )
        (goal_dir / "IMPLEMENTATION.md").write_text(
            "- [x] T001: Done\n- [ ] T002: Todo\n- [BLOCKED: x] T003: Stuck\n"
        )
        (goal_dir / "prd.md").write_text("# Feature\n\nDo the thing.\n")

        goal = load_goal(goal_dir)
        assert goal.name == "my-feature"
        assert goal.status == "building"
        assert goal.priority == "high"
        assert goal.repo_name == "my-project"
        assert goal.completed_tasks == 1
        assert goal.total_tasks == 3
        assert goal.blocked_tasks == 1
        assert goal.total_cost_usd == 1.50
        assert goal.prd_summary == "Do the thing."

    def test_replan_and_feedback_flags(self, tmp_path):
        goal_dir = tmp_path / "test-goal"
        goal_dir.mkdir()
        (goal_dir / "state.md").write_text("status: building\n")
        (goal_dir / ".replan").write_text("needs replan")
        (goal_dir / "feedback.md").write_text("# Feedback\n")

        goal = load_goal(goal_dir)
        assert goal.has_replan is True
        assert goal.has_feedback is True


class TestLoadRegisteredRepos:
    def test_loads_repos(self, tmp_keywork_dir):
        repo_dir = tmp_keywork_dir / "agents" / "repos" / "my-project"
        repo_dir.mkdir(parents=True)
        (repo_dir / "config.yaml").write_text(
            "name: my-project\nlanguage: python\nframework: fastapi\n"
            "remote: git@github.com:org/my-project.git\nbranch: main\n"
            "priority: high\ninitialized: true\n"
        )
        # Create workspace dir — initialized is derived from workspace existence
        (tmp_keywork_dir / "workspace" / "my-project").mkdir(parents=True)

        # Patch REPOS_DIR and WORKSPACE_DIR for testing
        import keywork.tui.state as state_module

        original_repos = state_module.REPOS_DIR
        original_workspace = state_module.WORKSPACE_DIR
        state_module.REPOS_DIR = tmp_keywork_dir / "agents" / "repos"
        state_module.WORKSPACE_DIR = tmp_keywork_dir / "workspace"
        try:
            repos = load_registered_repos()
            assert len(repos) == 1
            assert repos[0].name == "my-project"
            assert repos[0].language == "python"
            assert repos[0].priority == "high"
            assert repos[0].initialized is True
        finally:
            state_module.REPOS_DIR = original_repos
            state_module.WORKSPACE_DIR = original_workspace

    def test_skips_template(self, tmp_keywork_dir):
        template_dir = tmp_keywork_dir / "agents" / "repos" / "_template"
        template_dir.mkdir(parents=True)
        (template_dir / "config.yaml").write_text("name: template\n")

        import keywork.tui.state as state_module

        original = state_module.REPOS_DIR
        state_module.REPOS_DIR = tmp_keywork_dir / "agents" / "repos"
        try:
            repos = load_registered_repos()
            assert len(repos) == 0
        finally:
            state_module.REPOS_DIR = original


class TestLoadAttentionItems:
    def test_finds_review_tasks(self, tmp_keywork_dir):
        goal_dir = tmp_keywork_dir / "agents" / "goals" / "test-goal"
        goal_dir.mkdir(parents=True)
        (goal_dir / "state.md").write_text("status: building\n")
        (goal_dir / "IMPLEMENTATION.md").write_text(
            "- [x] T001: Done\n"
            "- [REVIEW: Check the output format] T002: Verify output\n"
            "  - Depends: T001\n"
        )

        import keywork.tui.state as state_module

        original = state_module.GOALS_DIR
        state_module.GOALS_DIR = tmp_keywork_dir / "agents" / "goals"
        try:
            items = load_attention_items()
            review_items = [i for i in items if i.item_type == "review"]
            assert len(review_items) == 1
            assert review_items[0].title == "Check the output format"
        finally:
            state_module.GOALS_DIR = original

    def test_finds_paused_goals(self, tmp_keywork_dir):
        goal_dir = tmp_keywork_dir / "agents" / "goals" / "paused-goal"
        goal_dir.mkdir(parents=True)
        (goal_dir / "state.md").write_text("status: paused\n")
        (goal_dir / ".pause").write_text("")

        import keywork.tui.state as state_module

        original = state_module.GOALS_DIR
        state_module.GOALS_DIR = tmp_keywork_dir / "agents" / "goals"
        try:
            items = load_attention_items()
            paused_items = [i for i in items if i.item_type == "paused"]
            assert len(paused_items) == 1
        finally:
            state_module.GOALS_DIR = original

    def test_finds_open_questions(self, tmp_keywork_dir):
        goal_dir = tmp_keywork_dir / "agents" / "goals" / "question-goal"
        goal_dir.mkdir(parents=True)
        (goal_dir / "state.md").write_text("status: building\n")
        (goal_dir / "questions.md").write_text(
            "# Agent Information Requests\n\n## Open\n\n"
            "### Q001: What database to use?\n- **Blocked task**: T003\n\n## Answered\n"
        )

        import keywork.tui.state as state_module

        original = state_module.GOALS_DIR
        state_module.GOALS_DIR = tmp_keywork_dir / "agents" / "goals"
        try:
            items = load_attention_items()
            question_items = [i for i in items if i.item_type == "question"]
            assert len(question_items) == 1
            assert question_items[0].question_id == "Q001"
        finally:
            state_module.GOALS_DIR = original
