include .env
export

.PHONY: test build logs shell

test:
	docker compose run --rm backend python3 -m pytest tests/ -v

test-fast:
	docker compose run --rm backend python3 -m pytest tests/ -q

build:
	docker compose build backend worker

logs:
	docker compose logs -f backend worker

shell:
	docker compose exec backend bash
