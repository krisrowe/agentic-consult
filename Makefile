.PHONY: install venv docker-build push setup test test-integration test-all precommit precommit-verbose run-analyzer cloud-init cloud-status cloud-pre-deploy

# GCP project for container registry (override with: make push PROJECT=my-project)
PROJECT ?= $(shell gcloud config get-value project 2>/dev/null)
IMAGE_NAME = consult-analyzer
IMAGE_TAG ?= latest

# Create and configure the virtual environment
setup:
	@if [ ! -d ".venv" ]; then \
		echo "Virtual environment not found. Creating it..."; \
		python3 -m venv .venv; \
		. .venv/bin/activate && pip install --upgrade pip && pip install -e '.[dev]' --index-url https://pypi.org/simple; \
	fi

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

build: clean setup
	. .venv/bin/activate && pytest

test: setup
	@. .venv/bin/activate && PYTHONPATH=. pytest tests/unit

test-integration: setup
	@. .venv/bin/activate && PYTHONPATH=. pytest tests/integration

test-all: setup
	@. .venv/bin/activate && PYTHONPATH=. pytest tests/

precommit: setup
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

precommit-verbose: setup
	@echo "Running tests..."
	@. .venv/bin/activate && pytest
	@echo ""
	@echo "Running pre-commit checks via CLI"
	@export PYTHONPATH=${PYTHONPATH}:. && .venv/bin/python -m agentic_consult precommit

run-analyzer: setup
	@. .venv/bin/activate && PYTHONPATH=. python3 -m agentic_consult.email.analyzer

# ============================================
# Cloud Deployment (zero-install, repo-centric)
# ============================================
# These targets let deployers use the SDK without pipx install.
# Run from repo root. Uses local code, no version mismatch.

cloud-init: setup
	@. .venv/bin/activate && PYTHONPATH=. python -m agentic_consult.cli.main cloud init $(ARGS)

cloud-status: setup
	@. .venv/bin/activate && PYTHONPATH=. python -m agentic_consult.cli.main cloud status

cloud-pre-deploy: setup
	@. .venv/bin/activate && PYTHONPATH=. python -m agentic_consult.cli.main cloud pre-deploy

# Full deployment workflow: test -> build -> push -> show terraform commands
deploy: test docker-build push cloud-pre-deploy
	@echo ""
	@echo "Run the terraform commands shown above to complete deployment."

# Build Docker image for analyzer
docker-build:
	@echo "Building Docker image $(IMAGE_NAME):$(IMAGE_TAG)..."
	docker build --target analyzer -t $(IMAGE_NAME):$(IMAGE_TAG) .
	@echo "Done."

# Push Docker image to Google Container Registry
push: docker-build
	@if [ -z "$(PROJECT)" ]; then echo "Error: PROJECT not set. Run: make push PROJECT=your-project-id"; exit 1; fi
	@echo "Tagging and pushing to gcr.io/$(PROJECT)/$(IMAGE_NAME):$(IMAGE_TAG)..."
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) gcr.io/$(PROJECT)/$(IMAGE_NAME):$(IMAGE_TAG)
	docker push gcr.io/$(PROJECT)/$(IMAGE_NAME):$(IMAGE_TAG)
	@echo "Done. Image available at: gcr.io/$(PROJECT)/$(IMAGE_NAME):$(IMAGE_TAG)"

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








