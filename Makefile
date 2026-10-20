PYTHON ?= python3.12
VENV_PYTHON ?= .venv/bin/python

.PHONY: setup check test-unit test-api smoke run build

setup:
	$(PYTHON) -m venv .venv
	$(VENV_PYTHON) -m pip install -r requirements.txt pytest

check:
	$(VENV_PYTHON) -m compileall -q main.py modules scripts
	$(VENV_PYTHON) scripts/check_runtime.py --offline

test-unit:
	$(VENV_PYTHON) -m pytest -q tests/unit

test-api:
	$(VENV_PYTHON) -m pytest -q tests

smoke:
	$(VENV_PYTHON) scripts/check_runtime.py --offline

run:
	$(VENV_PYTHON) main.py

build:
	$(VENV_PYTHON) -m compileall -q main.py modules scripts
