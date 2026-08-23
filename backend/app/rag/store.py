"""THE vector store. One loader, one chunker, one index, one search path.

The predecessor project had two knowledge directories, two index locations and
FAISS entry points in two modules, so retrieval behaved differently depending on
which code path you happened to hit. Everything here is deliberately singular:
``data/knowledge/`` in, ``data/index/`` out, and ``build_index`` is the only
function that writes it. ``scripts/audit_architecture.py`` fails the build if a
second store module or index builder appears.

FAISS is used directly rather than through a framework wrapper. That keeps the
dependency surface small and, more usefully, keeps persistence as a plain index
file plus JSON instead of a pickle - a pickled index is arbitrary code execution
waiting for someone to swap the file.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import faiss
import numpy as np
import yaml
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.domain.enums import ProductionMethod
from app.domain.knowledge import KnowledgeCitation, KnowledgeSnippet
from app.llm.factory import EmbeddingProvider
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

INDEX_FILENAME = "index.faiss"
CHUNKS_FILENAME = "chunks.json"
MANIFEST_FILENAME = "manifest.json"

_HEADERS = [("##", "section")]


class KnowledgeBaseError(RuntimeError):
    """The knowledge base or its index is missing or unusable."""


@dataclass(frozen=True)
class Chunk:
    """One indexed passage plus the metadata needed to cite it."""

    text: str
    title: str
    production_method: ProductionMethod | None
    materials: tuple[str, ...]
    source: str | None
    source_url: str | None
    updated_at: date | None
    document: str

    def to_snippet(self, score: float) -> KnowledgeSnippet:
        return KnowledgeSnippet(
            text=self.text,
            citation=KnowledgeCitation(
                title=self.title,
                source=self.source,
                source_url=self.source_url,
                updated_at=self.updated_at,
            ),
            production_method=self.production_method,
            materials=self.materials,
            score=score,
        )


# ------------------------------------------------------------------- loading


def _parse_frontmatter(raw: str, filename: str) -> tuple[dict[str, object], str]:
    """Split YAML frontmatter from the body. Missing frontmatter is an error."""
    if not raw.startswith("---"):
        raise KnowledgeBaseError(f"{filename}: missing YAML frontmatter")
    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise KnowledgeBaseError(f"{filename}: unterminated YAML frontmatter")
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as error:
        # Name the file. A bare ScannerError from deep in the loader tells
        # nobody which of thirteen documents is broken.
        raise KnowledgeBaseError(f"{filename}: invalid YAML frontmatter") from error
    if not isinstance(meta, dict):
        raise KnowledgeBaseError(f"{filename}: frontmatter is not a mapping")
    return meta, parts[2].strip()


def _coerce_method(value: object, filename: str) -> ProductionMethod | None:
    """A cross-cutting reference document legitimately has no single method."""
    if value in (None, "", "null"):
        return None
    try:
        return ProductionMethod(str(value))
    except ValueError:
        logger.warning(
            "unknown production_method in frontmatter; treating as unscoped",
            extra={"event": Event.VALIDATION_ERROR.value, "document": filename, "value": value},
        )
        return None


def load_chunks(knowledge_dir: Path, chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    """Load and chunk every document. The only place chunking happens.

    Splitting on markdown headings first keeps a passage semantically whole; the
    size splitter then only intervenes on sections too long to embed usefully.
    """
    if not knowledge_dir.is_dir():
        raise KnowledgeBaseError(f"knowledge directory not found: {knowledge_dir}")

    paths = sorted(knowledge_dir.glob("*.md"))
    if not paths:
        raise KnowledgeBaseError(f"no documents in {knowledge_dir}")

    header_splitter = MarkdownHeaderTextSplitter(_HEADERS, strip_headers=False)
    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )

    chunks: list[Chunk] = []
    for path in paths:
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"), path.name)

        title = str(meta.get("title") or path.stem)
        method = _coerce_method(meta.get("production_method"), path.name)
        materials_raw = meta.get("materials") or []
        materials = (
            tuple(str(item) for item in materials_raw) if isinstance(materials_raw, list) else ()
        )
        source = meta.get("source")
        source_url = meta.get("source_url")
        updated = meta.get("updated_at")

        for section in header_splitter.split_text(body):
            for piece in size_splitter.split_text(section.page_content):
                text = piece.strip()
                if not text:
                    continue
                chunks.append(
                    Chunk(
                        # The title travels with the passage so an isolated chunk
                        # still says what it is about once retrieved.
                        text=f"{title}\n\n{text}",
                        title=title,
                        production_method=method,
                        materials=materials,
                        source=str(source) if source else None,
                        source_url=str(source_url) if source_url else None,
                        updated_at=updated if isinstance(updated, date) else None,
                        document=path.name,
                    )
                )

    log_event(
        logger,
        Event.RAG_COMPLETED,
        "knowledge base loaded",
        documents=len(paths),
        chunks=len(chunks),
    )
    return chunks


def corpus_fingerprint(knowledge_dir: Path, embedding_model: str) -> str:
    """Identify the corpus plus the model, so a stale index is detectable.

    Editing a document or switching embedding model must invalidate the index;
    silently searching a stale one is worse than rebuilding.
    """
    digest = hashlib.sha256(embedding_model.encode("utf-8"))
    for path in sorted(knowledge_dir.glob("*.md")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:32]


# -------------------------------------------------------------------- store


class KnowledgeStore:
    """Builds, loads and searches the one index."""

    def __init__(
        self,
        knowledge_dir: Path,
        index_dir: Path,
        embeddings: EmbeddingProvider,
        embedding_model: str,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
    ) -> None:
        self._knowledge_dir = knowledge_dir
        self._index_dir = index_dir
        self._embeddings = embeddings
        self._embedding_model = embedding_model
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

        self._index: faiss.Index | None = None
        self._chunks: list[Chunk] = []

    # ------------------------------------------------------------ building

    def build(self) -> int:
        """Embed the corpus and write the index. The only writer of index_dir."""
        chunks = load_chunks(self._knowledge_dir, self._chunk_size, self._chunk_overlap)

        vectors = np.asarray(
            self._embeddings.embed_documents([chunk.text for chunk in chunks]), dtype="float32"
        )
        if vectors.ndim != 2 or vectors.shape[0] != len(chunks):
            raise KnowledgeBaseError("embedding provider returned an unexpected shape")

        # Cosine similarity via inner product on unit vectors.
        faiss.normalize_L2(vectors)
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)

        self._index_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(self._index_dir / INDEX_FILENAME))
        (self._index_dir / CHUNKS_FILENAME).write_text(
            json.dumps([self._chunk_to_json(chunk) for chunk in chunks], ensure_ascii=False),
            encoding="utf-8",
        )
        (self._index_dir / MANIFEST_FILENAME).write_text(
            json.dumps(
                {
                    "fingerprint": corpus_fingerprint(self._knowledge_dir, self._embedding_model),
                    "embedding_model": self._embedding_model,
                    "dimensions": int(vectors.shape[1]),
                    "chunks": len(chunks),
                }
            ),
            encoding="utf-8",
        )

        self._index, self._chunks = index, chunks
        log_event(
            logger,
            Event.RAG_COMPLETED,
            "index built",
            chunks=len(chunks),
            dimensions=int(vectors.shape[1]),
            model=self._embedding_model,
        )
        return len(chunks)

    # ------------------------------------------------------------- loading

    def is_stale(self) -> bool:
        """True when the index is absent or does not match the current corpus."""
        manifest_path = self._index_dir / MANIFEST_FILENAME
        if not (self._index_dir / INDEX_FILENAME).is_file() or not manifest_path.is_file():
            return True
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        return bool(
            manifest.get("fingerprint")
            != corpus_fingerprint(self._knowledge_dir, self._embedding_model)
        )

    def ensure_ready(self) -> None:
        """Load the index, rebuilding it first if it is missing or stale."""
        if self._index is not None and not self._chunks_dirty():
            return
        if self.is_stale():
            logger.info(
                "index missing or stale; rebuilding",
                extra={"event": "index_rebuild"},
            )
            self.build()
            return
        self._load()

    def _chunks_dirty(self) -> bool:
        return not self._chunks

    def _load(self) -> None:
        index_path = self._index_dir / INDEX_FILENAME
        chunks_path = self._index_dir / CHUNKS_FILENAME
        if not index_path.is_file() or not chunks_path.is_file():
            raise KnowledgeBaseError(f"no index at {self._index_dir}; run build first")

        self._index = faiss.read_index(str(index_path))
        payload = json.loads(chunks_path.read_text(encoding="utf-8"))
        self._chunks = [self._chunk_from_json(item) for item in payload]

    # ------------------------------------------------------------ searching

    def search(
        self,
        query: str,
        k: int = 4,
        method: ProductionMethod | None = None,
    ) -> list[KnowledgeSnippet]:
        """Return the closest passages, optionally scoped to one method.

        Metadata filtering is applied after the vector search over a widened
        candidate set, so a method scope narrows results without silently
        returning fewer than requested when the corpus can satisfy them.
        """
        self.ensure_ready()
        if self._index is None or not self._chunks:
            raise KnowledgeBaseError("index is not loaded")

        vector = np.asarray([self._embeddings.embed_query(query)], dtype="float32")
        faiss.normalize_L2(vector)

        fetch = min(len(self._chunks), max(k * 4, k))
        scores, positions = self._index.search(vector, fetch)

        snippets: list[KnowledgeSnippet] = []
        for score, position in zip(scores[0], positions[0], strict=True):
            if position < 0:
                continue
            chunk = self._chunks[int(position)]
            # An unscoped reference document (production_method: null) stays
            # eligible under a method filter - material and artwork guidance
            # applies across methods.
            if (
                method is not None
                and chunk.production_method is not None
                and chunk.production_method is not method
            ):
                continue
            snippets.append(chunk.to_snippet(float(score)))
            if len(snippets) >= k:
                break

        log_event(
            logger,
            Event.RAG_COMPLETED,
            "retrieval completed",
            k=k,
            returned=len(snippets),
            method=method.value if method else None,
            top_score=round(snippets[0].score, 4) if snippets else None,
        )
        return snippets

    def chunk_count(self) -> int:
        self.ensure_ready()
        return len(self._chunks)

    # ------------------------------------------------------------ mapping

    @staticmethod
    def _chunk_to_json(chunk: Chunk) -> dict[str, object]:
        return {
            "text": chunk.text,
            "title": chunk.title,
            "production_method": chunk.production_method.value if chunk.production_method else None,
            "materials": list(chunk.materials),
            "source": chunk.source,
            "source_url": chunk.source_url,
            "updated_at": chunk.updated_at.isoformat() if chunk.updated_at else None,
            "document": chunk.document,
        }

    @staticmethod
    def _chunk_from_json(item: dict[str, object]) -> Chunk:
        method = item.get("production_method")
        updated = item.get("updated_at")
        materials = item.get("materials") or []
        return Chunk(
            text=str(item["text"]),
            title=str(item["title"]),
            production_method=ProductionMethod(str(method)) if method else None,
            materials=tuple(str(m) for m in materials) if isinstance(materials, list) else (),
            source=str(item["source"]) if item.get("source") else None,
            source_url=str(item["source_url"]) if item.get("source_url") else None,
            updated_at=date.fromisoformat(str(updated)) if updated else None,
            document=str(item.get("document") or ""),
        )
