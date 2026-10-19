# Test bundle code with Python 3 (local).
# Network prerequisite: pulls the python:2.7-slim image once for test-py2.
PY3 ?= python3
DOCKER ?= docker

.PHONY: test test-py2

test:
	$(PY3) -m unittest discover -s tests -v

test-py2:
	$(DOCKER) run --rm -v "$$PWD":/app -w /app python:2.7-slim python -m unittest discover -s tests -v
