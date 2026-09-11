.PHONY: run run-chrome run-stop check test test-comms lint fmt demo demo-chrome demo-stop db-up db-ui db-down db-nuke install uninstall hub-start hub-stop hub-restart hub-status hub-open tray zip-package

# local overrides (copied from .env.default; gitignored); exported so the hub,
# tests and compose all see the same values
-include .env
export

CHROME ?= /Applications/Google Chrome.app/Contents/MacOS/Google Chrome

run: db-up      ## start the hub in dev mode (brings postgres up if needed)
	uv run courtyard-hub

run-chrome: db-up  ## app mode: hub in the background (log: sandbox/courtyard.log) + the WebUI in its own Chrome window
	@mkdir -p sandbox
	@port=$${COURTYARD_PORT:-2626}; url="http://127.0.0.1:$$port"; \
	if curl -sf "$$url/api/health" >/dev/null 2>&1; then \
		echo "hub already running at $$url"; \
	else \
		echo "starting the hub at $$url (log: sandbox/courtyard.log)"; \
		nohup uv run courtyard-hub >> sandbox/courtyard.log 2>&1 & echo $$! > sandbox/courtyard.pid; \
		for i in $$(seq 1 75); do curl -sf "$$url/api/health" >/dev/null 2>&1 && break; sleep 0.2; done; \
		curl -sf "$$url/api/health" >/dev/null 2>&1 || { echo "hub did not start — see sandbox/courtyard.log"; exit 1; }; \
	fi; \
	"$(CHROME)" --app="$$url" >/dev/null 2>&1 &

run-stop:       ## stop the hub that run-chrome started in the background
	@if [ -f sandbox/courtyard.pid ] && kill $$(cat sandbox/courtyard.pid) 2>/dev/null; then \
		rm -f sandbox/courtyard.pid; echo "hub stopped"; \
	else \
		rm -f sandbox/courtyard.pid; echo "no background hub to stop (a hub started with 'make run' stops with Ctrl+C)"; \
	fi

demo: db-up     ## step-2 demo: two scripted dummies + manual play instructions
	uv run python scripts/demo.py

demo-chrome: db-up  ## the demo, with the board opening in its own Chrome window
	COURTYARD_CHROME="$(CHROME)" uv run python scripts/demo.py --chrome

demo-stop:      ## stop the hub and dummies the demo started
	uv run python scripts/demo.py --stop

check: test lint  ## the automated "done" bar: full test suite + lint

test: db-up     ## run the test suite (brings postgres up if needed)
	uv run pytest

test-comms: db-up  ## operator -> agent1 -> operator with a LIVE Claude Code session (config: tests/communications/communication-test-config.yml)
	uv run python tests/communications/oper-agent1-oper.py

lint:
	uv run ruff check src tests scripts
	uv run ruff format --check src tests scripts

fmt:
	uv run ruff format src tests scripts
	uv run ruff check --fix src tests scripts

db-up:          ## start postgres in a container and wait until healthy
	docker compose up -d --wait postgres

db-ui: db-up    ## browse the postgres in Adminer (http://127.0.0.1:$$COURTYARD_ADMINER_PORT, default 8080)
	docker compose --profile tools up -d --wait adminer
	@echo "Adminer: http://127.0.0.1:$${COURTYARD_ADMINER_PORT:-8080}  (server postgres, user courtyard, password courtyard, db courtyard)"
	@open "http://127.0.0.1:$${COURTYARD_ADMINER_PORT:-8080}/?pgsql=postgres&username=courtyard&db=courtyard" 2>/dev/null || true

db-down:        ## stop containers (data volume survives)
	docker compose --profile tools down

db-nuke:        ## stop containers and DELETE the postgres data volume
	docker compose --profile tools down -v

# ---- the hub as a macOS app: a LaunchAgent that runs at login (scripts/install.py) -------

install:        ## install the hub as a LaunchAgent: venv, .env, postgres image, start at login
	python3 scripts/install.py install

uninstall:      ## remove both LaunchAgents and the Admin app, stop containers, drop .venv (PURGE=1: also the data volume)
	python3 scripts/install.py uninstall $(if $(filter 1,$(PURGE)),--purge)

hub-start:      ## load the LaunchAgent (the hub starts, and again at every login)
	python3 scripts/install.py start

hub-stop:       ## unload the LaunchAgent (the hub stays down until hub-start)
	python3 scripts/install.py stop

hub-restart:    ## restart the hub under launchd
	python3 scripts/install.py restart

hub-status:     ## is the LaunchAgent loaded, is the hub answering
	python3 scripts/install.py status

hub-open:       ## open the WebUI as its own window: the Dock app, else Chrome app mode, else the browser
	python3 scripts/install.py open

tray:           ## run the menu bar app by hand (make install runs it at login)
	uv run courtyard-tray

zip-package:    ## zip the committed tree for `unzip; make install` -> ./courtyard-<version>.zip
	@v=$$(git describe --tags --always --dirty); \
	git archive --worktree-attributes --format=zip --prefix=courtyard-$$v/ -o courtyard-$$v.zip HEAD && \
	echo "courtyard-$$v.zip  (unzip anywhere, cd in, make install)"
