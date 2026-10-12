SHELL := /bin/sh
ENV_FILE := $(wildcard .env)
UV_RUN := uv run $(if $(ENV_FILE),--env-file .env,)

.PHONY: setup fixtures test ports up down reset demo serve stack eval eval-live check-llm screenshots

setup:            ## install Python dependencies
	uv sync

fixtures:         ## regenerate test fixtures from the harness generator
	uv run python scripts/capture_fixtures.py 42 7 2024

test:             ## run the unit and integration tests
	uv run pytest -q

ports:            ## report anything already listening on the ports we need
	@for p in 8081 8025 8090; do if lsof -nP -iTCP:$$p -sTCP:LISTEN >/dev/null 2>&1; then echo "port $$p is in use"; else echo "port $$p free"; fi; done

up:               ## start leadgen (:8081, answer key on) and mailbox (:8025)
	DEBUG=true docker compose up -d --build --wait leadgen mailbox

down:             ## stop everything (keeps databases)
	docker compose down

reset:            ## clear local assistant state and the mock mailbox
	rm -f data/uwagent.db
	-curl -s -X POST http://localhost:8025/reset >/dev/null

demo: up          ## run the seed-42 morning queue, then open the UW board on :8090
	$(UV_RUN) uwagent run --seed 42
	$(UV_RUN) uwagent serve

serve:            ## start the UW board on :8090
	$(UV_RUN) uwagent serve

stack:            ## one-command stack in Docker (harness + board)
	docker compose up --build

eval: up          ## offline eval baseline (free, deterministic)
	uv run python -m evals.run --seeds 42 7 --reply-rounds 2 --redteam

eval-live: up     ## live agent eval (spends tokens; needs ANTHROPIC_API_KEY in .env)
	$(UV_RUN) python -m evals.run --seeds 42 --live --reply-rounds 2 --redteam

check-llm:        ## one tiny live call to verify the Anthropic setup
	$(UV_RUN) python scripts/check_llm.py

screenshots:      ## capture the UW board pages to docs/screenshots (needs Google Chrome)
	uv run python scripts/screenshots.py
