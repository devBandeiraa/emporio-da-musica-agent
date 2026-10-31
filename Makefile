.PHONY: install test lint format run docker-build docker-run

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e ".[dev]"
	pre-commit install

test:
	$(PYTHON) -m pytest --cov --cov-report=term-missing

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

run:
	$(PYTHON) -m emporio_agent

docker-build:
	docker build -t emporio-agent .

docker-run:
	docker run --rm -it --env-file .env emporio-agent
