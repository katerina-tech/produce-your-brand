"""The architecture audit, enforced by the test suite rather than by memory.

``scripts/audit_architecture.py`` has always been able to fail the build - its
own docstring says "run after every phase (and in CI)". Nothing ran it. It
executed only when somebody typed the command, which means the guarantee the
README and the presentation describe ("a build check fails if anyone adds an AI
import to the scorer") was true of the script and false of the project.

Wrapping it in a test closes that gap with the cheapest possible mechanism: the
audit now runs on every ``pytest`` invocation, and therefore on every CI run,
and therefore the claim is enforced rather than asserted.

The audit is invoked through its ``main()`` rather than as a subprocess so a
failure surfaces its own printed diagnosis in the pytest output.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = BACKEND_ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import audit_architecture  # noqa: E402  - path must be set up first


def test_architecture_audit_passes(capsys) -> None:
    """Every architectural invariant holds.

    A failure here is not a flaky test: it means a rule the project publicly
    claims to enforce has just been broken. The audit prints which one.
    """
    exit_code = audit_architecture.main()
    output = capsys.readouterr().out

    assert exit_code == 0, f"architecture audit failed:\n{output}"


def test_scoring_layer_imports_nothing_from_the_ai_layer() -> None:
    """The single invariant the product's credibility rests on.

    Stated separately from the audit sweep because this is the one quoted in the
    README, the presentation and the funding application: the model may read
    language, but it never owns a number. If someone adds ``langchain`` or
    ``openai`` to the scorer, this test names the offence directly instead of
    leaving it inside a generic audit failure.
    """
    scorer = BACKEND_ROOT / "app" / "services" / "matching.py"
    source = scorer.read_text(encoding="utf-8")

    forbidden = ("langchain", "openai", "langgraph", "app.llm")
    offenders = [
        name for name in forbidden if f"import {name}" in source or f"from {name}" in source
    ]

    assert not offenders, (
        f"{scorer.name} imports {offenders} - the deterministic scorer must never "
        "reach into the AI layer. This is the invariant the product is sold on."
    )
