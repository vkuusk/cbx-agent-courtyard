.PHONY: run test lint fmt demo demo-stop db-up db-down db-nuke

run:            ## start the hub in dev mode (needs db-up first)
	uv run courtyard-hub

demo: db-up     ## step-2 demo: two scripted puppets + manual play instructions
	uv run python scripts/demo.py

demo-stop:      ## stop the hub and puppets the demo started
	uv run python scripts/demo.py --stop

test: db-up     ## run the test suite (brings postgres up if needed)
	uv run pytest

lint:
	uv run ruff check src tests scripts
	uv run ruff format --check src tests scripts

fmt:
	uv run ruff format src tests scripts
	uv run ruff check --fix src tests scripts

db-up:          ## start postgres in a container and wait until healthy
	docker compose up -d --wait postgres

db-down:        ## stop containers (data volume survives)
	docker compose down

db-nuke:        ## stop containers and DELETE the postgres data volume
	docker compose down -v
