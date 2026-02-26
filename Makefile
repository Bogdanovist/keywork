.PHONY: tui setup lint test clean

tui:
	uv run python -m keywork.tui

setup:
	uv sync --group dev
	bash agents/sandbox/setup.sh

lint:
	uv run ruff check keywork/ tests/

test:
	uv run pytest tests/

clean:
	docker rmi keywork-sandbox 2>/dev/null || true
	docker volume rm keywork-cache 2>/dev/null || true
