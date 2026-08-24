# Build context is the `backend/` directory (set as this service's root
# directory in Railway). Dependencies are managed with uv and pinned in
# uv.lock - see pyproject.toml's comment on why.

FROM python:3.12-slim
WORKDIR /app

# Official recommended way to get the uv binary without a pip bootstrap step.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# `data/` in the image only holds what's checked into git: the knowledge
# docs and suppliers.json (see .gitignore - the FAISS index, uploads and the
# two SQLite databases are all runtime-generated and never committed). A
# Railway volume gets mounted at /app/data for persistence, which starts
# empty - docker-entrypoint.sh repopulates the checked-in reference data
# from this untouched copy on first boot. The search index is rebuilt
# automatically by the app itself the first time it's needed (see
# scripts/build_index.py's docstring); it does not need seeding here.
RUN cp -r data /app/data-seed

RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
