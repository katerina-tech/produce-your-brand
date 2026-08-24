#!/bin/sh
# Runs once per container start, before the API. A freshly-attached Railway
# volume mounts empty at /app/data, which would hide the knowledge docs and
# suppliers.json baked into the image at build time (see Dockerfile). This
# repopulates them from the untouched build-time copy - but only if they are
# not already there, so it never overwrites real state (app.db, checkpoints,
# uploads, or a search index the app already built) on a normal restart.
set -e

if [ ! -e "data/suppliers.json" ]; then
  echo "Empty data volume detected - seeding reference data from the image."
  cp -r data-seed/knowledge data/knowledge
  cp data-seed/suppliers.json data/suppliers.json
fi

exec uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
