"""Architectural guard rails, enforced as a check rather than a promise.

The previous project accumulated duplicate RAG pipelines, two knowledge-base
directories, competing retrievers and dead agent code. Reviewer criticism of that
is the reason this file exists: every rule below is one of those failure modes
turned into an assertion.

Run after every phase (and in CI)::

    uv run python scripts/audit_architecture.py

Exits non-zero on violation. Counts of 0 are allowed because a component may not
exist until its phase - the rule is "never more than one", not "must exist now".
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
APP = BACKEND / "app"
EXCLUDED_PARTS = {".venv", "__pycache__", "node_modules", ".git", ".mypy_cache", ".ruff_cache"}


def python_files(root: Path) -> list[Path]:
    return [
        path for path in sorted(root.rglob("*.py")) if not EXCLUDED_PARTS.intersection(path.parts)
    ]


def files_containing(root: Path, needle: str) -> list[Path]:
    return [
        path
        for path in python_files(root)
        if needle in path.read_text(encoding="utf-8", errors="replace")
    ]


def directories_named(root: Path, name: str) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob(name))
        if path.is_dir() and not EXCLUDED_PARTS.intersection(path.parts)
    ]


def code_files_containing(root: Path, needle: str) -> list[Path]:
    """Like :func:`files_containing` but ignores matches inside comments/strings.

    Without this, a docstring that merely mentions ``os.environ`` reads as a
    second environment reader and the audit cries wolf.
    """
    hits: list[Path] = []
    for path in python_files(root):
        source = path.read_text(encoding="utf-8", errors="replace")
        if needle not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            hits.append(path)
            continue
        stripped = "\n".join(
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute | ast.Call | ast.Name)
        )
        if needle in stripped:
            hits.append(path)
    return hits


def imported_modules() -> set[str]:
    """Every module path actually imported anywhere, resolved from the AST.

    Text search is not good enough here. ``from app.repositories import db`` never
    produces the substring ``app.repositories.db``, so a grep-based check silently
    depends on whether some docstring happens to mention the module - which meant
    this audit was reporting live modules as dead. Parsing the imports is exact.
    """
    searchable = python_files(APP) + python_files(BACKEND / "tests")
    scripts_dir = BACKEND / "scripts"
    if scripts_dir.is_dir():
        searchable += python_files(scripts_dir)

    referenced: set[str] = set()
    for path in searchable:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    referenced.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                referenced.add(node.module)
                # `from app.services import matching` imports a submodule, not a
                # name, so record both readings and let the caller match either.
                for alias in node.names:
                    referenced.add(f"{node.module}.{alias.name}")
    return referenced


def unreferenced_modules() -> list[str]:
    """Modules under ``app/`` that nothing imports - i.e. candidate dead code."""
    referenced = imported_modules()

    orphans: list[str] = []
    for path in python_files(APP):
        if path.name in {"__init__.py", "main.py"}:
            continue
        dotted = "app." + path.relative_to(APP).with_suffix("").as_posix().replace("/", ".")
        if dotted not in referenced:
            orphans.append(dotted)
    return orphans


def main() -> int:
    # (label, actual count, maximum allowed)
    rules: list[tuple[str, int, int]] = [
        ("LangGraph StateGraph definitions", len(files_containing(APP, "StateGraph(")), 1),
        ("prompt modules", len(list(APP.rglob("prompts*.py"))), 1),
        ("ChatOpenAI constructions", len(files_containing(APP, "ChatOpenAI(")), 1),
        ("vector-store modules", len(list((APP / "rag").rglob("store.py"))), 1),
        ("FAISS index builders", len(files_containing(APP, "faiss.Index")), 1),
        ("knowledge directories", len(directories_named(BACKEND, "knowledge")), 1),
        ("supplier data files", len(list(BACKEND.rglob("data/suppliers*.json"))), 1),
        ("logging configurations", len(files_containing(APP, "logging.StreamHandler")), 1),
        ("basicConfig calls (must be 0)", len(files_containing(APP, "basicConfig")), 0),
        ("environment readers", len(code_files_containing(APP, "os.environ")), 1),
        ("deterministic scorer LLM imports (must be 0)", _scorer_llm_imports(), 0),
    ]

    failures = [(label, actual, limit) for label, actual, limit in rules if actual > limit]
    orphans = unreferenced_modules()

    width = max(len(label) for label, _, _ in rules)
    for label, actual, limit in rules:
        status = "FAIL" if actual > limit else "ok"
        print(f"  [{status:>4}] {label:<{width}}  {actual} (max {limit})")

    if orphans:
        print("\n  [FAIL] unreferenced modules (dead code):")
        for module in orphans:
            print(f"           {module}")
    else:
        print(f"  [  ok] {'unreferenced modules':<{width}}  0")

    if failures or orphans:
        print("\nARCHITECTURE AUDIT FAILED")
        return 1
    print("\nArchitecture audit passed.")
    return 0


def _scorer_llm_imports() -> int:
    """The deterministic scorer must never import an LLM. 0 or the file is absent."""
    scorer = APP / "services" / "matching.py"
    if not scorer.is_file():
        return 0
    source = scorer.read_text(encoding="utf-8")
    return sum(1 for marker in ("langchain", "openai", "app.llm") if f"import {marker}" in source)


if __name__ == "__main__":
    sys.exit(main())
