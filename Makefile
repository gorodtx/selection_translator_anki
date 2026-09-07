.PHONY: bootstrap fmt fmt-check lint lint-check types test verify check clean \
        macos-app macos-backend macos-swift macos-install

# The branch baseline. `fmt-check` only looks at files changed since then:
# ~20 files inherited from the GNOME branch are not ruff-formatted, and
# reformatting them would bury the real diff.
#
# The list has to include the working tree, not just committed history. Taking
# it from `$(BASE)...HEAD` alone let `make verify` pass on an uncommitted edit
# to a file the branch had not touched before — and CI, which diffs against the
# previous push, then failed on exactly that file. A gate that inspects what git
# recorded rather than what was actually edited is not a gate.
BASE ?= origin/gnome
CHANGED_PY = $(shell { \
        git diff --name-only --diff-filter=ACMR $(BASE)...HEAD -- '*.py'; \
        git diff --name-only --diff-filter=ACMR HEAD -- '*.py'; \
        git ls-files --others --exclude-standard -- '*.py'; \
        } | sort -u)

bootstrap:
	uv sync --frozen --dev

fmt:
	uv run --frozen ruff format $(CHANGED_PY)

fmt-check:
	@if [ -z "$(CHANGED_PY)" ]; then \
		echo "no python files changed since $(BASE)"; \
	else \
		uv run --frozen ruff format --check $(CHANGED_PY); \
	fi

lint:
	uv run --frozen ruff check . --fix

lint-check:
	uv run --frozen ruff check .

types:
	uv run --frozen python -m mypy

test:
	uv run --frozen python -m pytest -q

verify: lint-check fmt-check types test

check: lint fmt types

# --- macOS ---------------------------------------------------------------

macos-swift:
	cd macos/AppleLangHelper && swift build -c release
	cd macos/Translator && swift build -c release && scripts/swift-test.sh

macos-app:
	scripts/build_macos_app.sh --out dist

macos-backend:
	scripts/run_backend_macos.sh

macos-install: macos-app
	scripts/install_macos.sh install

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .problems .pyright.json dist out
	rm -rf macos/AppleLangHelper/.build macos/Translator/.build
