# repo-forge:tareas
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; elif command -v python3 >/dev/null 2>&1; then echo python3; else echo python; fi)

.PHONY: doctor test lint build audit check all

doctor:
	$(PYTHON) scripts/doctor.py
	node scripts/validate-catalog.mjs

lint:
	$(PYTHON) -m ruff check .
	npm run lint

test:
	$(PYTHON) -m pytest -q tests magic/tests site/tests
	npm test

build:
	npm run build

audit:
	npm run audit:web

check: doctor lint test build audit

all: check
