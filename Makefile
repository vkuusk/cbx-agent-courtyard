.PHONY: run test lint fmt db-up db-down db-nuke

run:            ## start the hub in dev mode (needs db-up first)
	uv run courtyard-hub

test: db-up     ## run the test suite (brings postgres up if needed)
	uv run pytest

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests

db-up:          ## start postgres in a container and wait until healthy
	docker compose up -d --wait postgres

db-down:        ## stop containers (data volume survives)
	docker compose down

db-nuke:        ## stop containers and DELETE the postgres data volume
	docker compose down -v
