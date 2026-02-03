.PHONY: bootstrap fmt fmt-check lint lint-check mypy pyright pylance typecheck \
        problems verify check clean

bootstrap:
	uv sync --dev

fmt:
	uv run ruff format .

lint:
	uv run ruff check . --fix

fmt-check:
	uv run ruff format --check .

lint-check:
	uv run ruff check .

mypy:
	uv run mypy

pyright:
	uv run pyright

pylance: pyright

typecheck: mypy pyright

problems:
	uv run python tools/problems.py

verify: fmt-check lint-check problems

check: lint fmt typecheck

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .problems .pyright.json
