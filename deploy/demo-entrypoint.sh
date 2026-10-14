#!/bin/sh
# Entrypoint for the single-image demo: prepare the database, then serve.
#
# Migrating and seeding here rather than inside the API keeps one rule intact — a service that
# silently migrates its own database is hard to reason about. This is the same command the
# compose stack runs as a one-shot service, just executed inline.
set -e

echo "[demo] preparing the database at ${LRC_DATABASE_URL}"
python -m line_rca_api.db.bootstrap

echo "[demo] serving on 0.0.0.0:8080"
exec uvicorn line_rca_api.main:app --host 0.0.0.0 --port 8080
