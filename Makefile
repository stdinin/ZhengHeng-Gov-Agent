.DEFAULT_GOAL := help

.PHONY: help setup infra-up infra-down seed backend frontend dev test lint run-eval clean

help:
	@echo "Targets: setup infra-up infra-down seed backend frontend dev test lint run-eval clean"

setup:
	uv sync --all-groups
	npm --prefix frontend install

infra-up:
	docker compose up -d mongo redis opensearch etcd minio milvus

infra-down:
	docker compose down

seed:
	uv run python scripts/seed_users.py

backend:
	uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

frontend:
	npm --prefix frontend run dev

dev:
	@echo "Run 'make infra-up', then use separate terminals for 'make backend' and 'make frontend'."

test:
	uv run pytest
	npm --prefix frontend run test -- --run

lint:
	uv run ruff check backend scripts
	uv run mypy backend/app
	npm --prefix frontend run lint

run-eval:
	uv run python scripts/run_eval.py --evalset evalsets/policy_eval_v1.jsonl

clean:
	docker compose down -v --remove-orphans
