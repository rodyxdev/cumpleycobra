# Atajos para Linux, macOS y la nube. En Windows, los mismos comandos están en
# docs/mejora/fase-1.md (sección «Comandos») para PowerShell.
PY ?= backend/.venv/bin/python
PG_TEST_URL ?= postgresql://cyc:cyc_local@localhost:55433/cyc

.PHONY: up down logs test test-pg contract-test importar exportar

up:            ## Postgres + API + frontend
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api

test:          ## backend con state.json
	$(PY) -m pytest backend/tests -q

test-pg:       ## backend contra el Postgres de docker compose (levántalo antes con `docker compose up -d db`)
	CYC_TEST_DATABASE_URL=$(PG_TEST_URL) $(PY) -m pytest backend/tests -q

contract-test:
	cargo test -p cumpleycobra

importar:      ## make importar ARCHIVO=backend/state.json
	DATABASE_URL=$(PG_TEST_URL) $(PY) scripts/estado_postgres.py importar $(ARCHIVO)

exportar:      ## make exportar ARCHIVO=respaldo.json
	DATABASE_URL=$(PG_TEST_URL) $(PY) scripts/estado_postgres.py exportar $(ARCHIVO)
