.PHONY: install venv

install:
	@command -v pipx >/dev/null 2>&1 || (echo "pipx not found; please install pipx or run 'make venv'"; exit 1)
	@echo "Installing editable package into pipx-managed env 'agentic-consult' (dev extras)"
	@pipx runpip agentic-consult pip install -e '.[dev]' 2>/dev/null || pipx install -e . --force --pip-args "--index-url https://pypi.org/simple" 2>/dev/null || (echo "pipx install failed; try 'make venv' instead"; exit 1)
	@echo "Done. You can run tests with: pipx run agentic-consult pytest -q"

clean:
	rm -rf .venv
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +

build: clean
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip
	. .venv/bin/activate && pip install -e '.[dev]'
	. .venv/bin/activate && pytest

test:
	@if [ ! -d ".venv" ]; then \
		echo "Virtual environment not found. Creating it..."; \
		python3 -m venv .venv; \
		. .venv/bin/activate && pip install --upgrade pip && pip install -e '.[dev]'; \
	fi
	@. .venv/bin/activate && PYTHONPATH=. pytest tests/unit

test-integration:
	@if [ ! -d ".venv" ]; then \
		echo "Virtual environment not found. Creating it..."; \
		python3 -m venv .venv; \
		. .venv/bin/activate && pip install --upgrade pip && pip install -e '.[dev]'; \
	fi
	@. .venv/bin/activate && PYTHONPATH=. pytest tests/integration

test-all:
	@if [ ! -d ".venv" ]; then \
		echo "Virtual environment not found. Creating it..."; \
		python3 -m venv .venv; \
		. .venv/bin/activate && pip install --upgrade pip && pip install -e '.[dev]'; \
	fi
	@. .venv/bin/activate && PYTHONPATH=. pytest tests/

precommit:
	@if [ ! -d ".venv" ]; then \
		echo "Virtual environment not found. Creating it..."; \
		python3 -m venv .venv; \
		. .venv/bin/activate && pip install --upgrade pip && pip install -e '.[dev]'; \
	fi
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "Running precommit checks..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@. .venv/bin/activate && PYTHONPATH=. pytest > /tmp/consult-pytest-output.txt 2>&1; \
	TEST_EXIT=$$?; \
	cat /tmp/consult-pytest-output.txt; \
	PASS_COUNT=$$(grep -oP '\d+(?= passed)' /tmp/consult-pytest-output.txt || echo "0"); \
	TOTAL_COUNT=$$(grep -oP '\d+(?= collected)' /tmp/consult-pytest-output.txt || echo "0"); \
	if [ "$$TOTAL_COUNT" = "0" ]; then \
		TOTAL_COUNT=$$(grep -oP '\d+(?= items)' /tmp/consult-pytest-output.txt || echo "$$PASS_COUNT"); \
	fi; \
	if [ $$TEST_EXIT -eq 0 ]; then \
		echo "✅ Tests: $$PASS_COUNT/$$TOTAL_COUNT passed"; \
	else \
		echo "❌ Tests: FAILED (run 'make test' for details)"; \
	fi; \
	export PYTHONPATH=${PYTHONPATH}:. && .venv/bin/python -m agentic_consult precommit > /tmp/consult-scanner-output.txt 2>&1; \
	SCAN_EXIT=$$?; \
	if [ $$SCAN_EXIT -eq 0 ]; then \
		echo "✅ Scanner: No sensitive data found"; \
	else \
		echo "❌ Scanner: Sensitive data detected"; \
		cat /tmp/consult-scanner-output.txt; \
	fi; \
	echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; \
	if [ $$TEST_EXIT -ne 0 ] || [ $$SCAN_EXIT -ne 0 ]; then \
		exit 1; \
	fi

precommit-verbose:
	@if [ ! -d ".venv" ]; then \
		echo "Virtual environment not found. Creating it..."; \
		python3 -m venv .venv; \
		. .venv/bin/activate && pip install --upgrade pip && pip install -e '.[dev]'; \
	fi
	@echo "Running tests..."
	@. .venv/bin/activate && pytest
	@echo ""
	@echo "Running pre-commit checks via CLI"
	@export PYTHONPATH=${PYTHONPATH}:. && .venv/bin/python -m agentic_consult precommit

run-analyzer:
	@. .venv/bin/activate && PYTHONPATH=. python3 -m agentic_consult.email.analyzer



.PHONY: help refresh preview ensure-exec



help:

	@printf "make refresh     Run refresh (execute)\nmake preview     Show prompt only (dry-run)\n"



ensure-exec:

	@# No-op now



refresh:

	@echo "Running refresh (execute)"

	@export PYTHONPATH=${PYTHONPATH}:. && . .venv/bin/activate && agentic-consult refresh --no-dry-run



preview:

	@echo "Preview prompt (dry-run)"

	@export PYTHONPATH=${PYTHONPATH}:. && . .venv/bin/activate && agentic-consult refresh --dry-run








