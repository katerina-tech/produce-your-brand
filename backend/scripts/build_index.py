"""Build the knowledge index.

    uv run python scripts/build_index.py

This calls :meth:`app.rag.store.KnowledgeStore.build` and contains no pipeline
logic of its own - the predecessor project had a build script whose behaviour had
drifted from the one the application used at runtime, so retrieval differed
depending on which had written the index. There is one builder, and this script
is a thin entry point to it.

The application also rebuilds lazily when the index is missing or stale, so this
script is a convenience (and a CI step), not a required setup ritual.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.llm.factory import get_embedding_provider
from app.logging_config import configure_logging
from app.rag.store import KnowledgeStore


def main() -> int:
    configure_logging(level="INFO", fmt="console")
    settings = get_settings()

    # Only the hosted backend needs a key; the local one embeds on-device, and
    # refusing to build without a key would make PYS_EMBEDDING_BACKEND=local
    # useless for exactly the case it exists to serve.
    if settings.embedding_backend == "openai" and not settings.has_api_key:
        print("No API key configured. Copy .env.example to .env and set OPENAI_API_KEY.")
        print("Alternatively set PYS_EMBEDDING_BACKEND=local to embed on-device.")
        return 1

    store = KnowledgeStore(
        knowledge_dir=settings.knowledge_dir,
        index_dir=settings.index_dir,
        embeddings=get_embedding_provider(settings),
        embedding_model=settings.active_embedding_model,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    documents = len(list(settings.knowledge_dir.glob("*.md")))
    print(f"knowledge : {settings.knowledge_dir}  ({documents} documents)")
    print(f"index     : {settings.index_dir}")
    print(f"backend   : {settings.embedding_backend}")
    print(f"model     : {settings.active_embedding_model}")
    print(f"stale     : {store.is_stale()}")

    chunks = store.build()
    print(f"\nindexed {chunks} chunks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
