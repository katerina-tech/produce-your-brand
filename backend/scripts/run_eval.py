"""Behavioural eval harness for the decision layer.

    uv run python scripts/run_eval.py            # print the table
    uv run python scripts/run_eval.py --write    # also update docs/eval.md

**Why this evaluates the deterministic layer, not the model.** The product's
correctness claims live in code, not in prompt behaviour: which field gets
asked about next, whether an unconfirmed capability is scored differently
from a refused one, whether an impossible deadline is caught. All of that is
pure Python (``app/services/completeness.py``, ``app/services/matching.py``),
so it can be evaluated exactly and repeatedly, for free, with no API key and
no network - which is also what makes this suitable to run in CI on every
change, unlike an eval that bills a provider per row.

The extraction step (free text -> ``ProductionRequirement``) is the one part
that genuinely needs a live model, and is verified separately - see the
"Live extraction" note in docs/eval.md.

This harness fails loudly: ``--write`` refuses to update the doc when any
case fails, so a committed results table cannot silently drift away from
what the code actually does.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domain.enums import ProductCategory, ProductionMethod
from app.domain.matching import MatchFactor
from app.domain.requirement import ProductionRequirement
from app.domain.supplier import Supplier, SupplierQuery
from app.repositories.supplier_repo import SupplierRepository
from app.services import completeness, matching

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Fixed so deadline arithmetic is reproducible regardless of when this runs -
# the same reason app/services/matching.py takes `today` as a parameter.
TODAY = date(2026, 8, 21)


@dataclass(frozen=True)
class Case:
    """One evaluated behaviour.

    ``run`` returns the observed behaviour as a short string; the case passes
    when that string equals ``expected``. Comparing rendered strings rather
    than objects keeps the published table and the assertion the same thing,
    so the doc cannot claim something the check did not verify.
    """

    request: str
    expected: str
    run: Callable[[], str]


# --------------------------------------------------------------- fixtures


def _complete() -> ProductionRequirement:
    return ProductionRequirement(
        product="black yoga mats",
        product_category=ProductCategory.SPORTS_EQUIPMENT,
        material="PVC",
        quantity=100,
        customer_owns_product=True,
        customization_description="gold logo",
        deadline=date(2026, 9, 15),
        location="Berlin",
    )


def _supplier(**overrides: object) -> Supplier:
    """A deliberately unremarkable supplier, so each case varies exactly one
    thing and the resulting score change is attributable to it."""
    base: dict[str, object] = {
        "id": "eval-001",
        "name": "Eval Reference Studio",
        "location": {"city": "Berlin", "country": "DE"},
        "supported_methods": (ProductionMethod.SCREEN_PRINTING,),
        "supported_materials": ("PVC", "cotton"),
        "product_categories": (ProductCategory.SPORTS_EQUIPMENT,),
        "min_order_quantity": 50,
        "max_order_quantity": 5000,
        "accepts_customer_owned_products": True,
        "typical_lead_time_days": 10,
    }
    base.update(overrides)
    return Supplier.model_validate(base)


def _next_field(requirement: ProductionRequirement) -> str:
    report = completeness.check(requirement)
    return f"asks: {report.next_field}" if report.next_field else "proceeds to review"


def _funnel(method: ProductionMethod, category: ProductCategory) -> str:
    """How many of the real dataset's partners structurally clear the search,
    before any scoring. This is the number the UI reports so a short match
    list reads as explainable rather than suspicious."""
    repo = SupplierRepository(BACKEND_ROOT / "data" / "suppliers.json")
    found = matching.search_suppliers(repo.all(), SupplierQuery(method=method, category=category))
    return f"{len(found)} of {repo.count()} partners offer this method"


def _factor(
    requirement: ProductionRequirement,
    supplier: Supplier,
    factor: MatchFactor,
    method: ProductionMethod = ProductionMethod.SCREEN_PRINTING,
) -> str:
    """Render one factor's outcome, or the hard-gate exclusion that pre-empts
    scoring entirely."""
    result = matching.score_supplier(supplier, requirement, method, TODAY)
    if not result.eligible:
        return "excluded (hard gate)"
    scored = next(f for f in result.factors if f.factor is factor)
    flag = " + flag" if result.risk_flags else ""
    return f"{scored.verdict.value} {scored.awarded:g}/{scored.max_points:g}{flag}"


# ------------------------------------------------------------------ cases
# Completeness: which single field the workflow asks about next. The order is
# a published priority list (completeness.CRITICAL_FIELD_ORDER), not a
# judgement call, so each of these is exactly checkable.

CASES: tuple[Case, ...] = (
    Case(
        "Complete brief: 100 PVC yoga mats, own them, gold logo, Berlin, 15 Sep",
        "proceeds to review",
        lambda: _next_field(_complete()),
    ),
    Case(
        "Missing quantity",
        "asks: quantity",
        lambda: _next_field(_complete().model_copy(update={"quantity": None})),
    ),
    Case(
        "Missing material",
        "asks: material",
        lambda: _next_field(_complete().model_copy(update={"material": None})),
    ),
    Case(
        "Missing product",
        "asks: product",
        lambda: _next_field(_complete().model_copy(update={"product": None})),
    ),
    Case(
        "Missing ownership (who supplies the goods)",
        "asks: customer_owns_product",
        lambda: _next_field(_complete().model_copy(update={"customer_owns_product": None})),
    ),
    Case(
        "Two fields missing: asks the higher-priority one only",
        "asks: quantity",
        lambda: _next_field(_complete().model_copy(update={"quantity": None, "material": None})),
    ),
    Case(
        "Missing deadline (non-blocking)",
        "proceeds to review",
        lambda: _next_field(_complete().model_copy(update={"deadline": None})),
    ),
    Case(
        "Missing location (non-blocking)",
        "proceeds to review",
        lambda: _next_field(_complete().model_copy(update={"location": None})),
    ),
    # Deadline feasibility.
    Case(
        "Deadline already in the past",
        "mismatch 0/10 + flag",
        lambda: _factor(
            _complete().model_copy(update={"deadline": date(2026, 8, 1)}),
            _supplier(),
            MatchFactor.DEADLINE,
        ),
    ),
    Case(
        "Deadline impossible: 3 days for a 10-day lead time",
        "mismatch 0/10 + flag",
        lambda: _factor(
            _complete().model_copy(update={"deadline": date(2026, 8, 24)}),
            _supplier(),
            MatchFactor.DEADLINE,
        ),
    ),
    Case(
        "Deadline comfortable: 25 days for a 10-day lead time",
        "match 10/10",
        lambda: _factor(_complete(), _supplier(), MatchFactor.DEADLINE),
    ),
    Case(
        "Supplier publishes no lead time (unknown, not 'no')",
        "unknown 5/10 + flag",
        lambda: _factor(_complete(), _supplier(typical_lead_time_days=None), MatchFactor.DEADLINE),
    ),
    # Material compatibility.
    Case(
        "Unsupported material: silicone, not on the published list",
        "mismatch 0/20 + flag",
        lambda: _factor(
            _complete().model_copy(update={"material": "silicone"}),
            _supplier(),
            MatchFactor.MATERIAL,
        ),
    ),
    Case(
        "Material not stated by the customer (unknown, not 'no')",
        "unknown 10/20 + flag",
        lambda: _factor(
            _complete().model_copy(update={"material": None}),
            _supplier(),
            MatchFactor.MATERIAL,
        ),
    ),
    # The null-is-not-false discipline, and the hard gates.
    Case(
        "Customer-owned policy unconfirmed (null, not false)",
        "unknown 7.5/15 + flag",
        lambda: _factor(
            _complete(),
            _supplier(accepts_customer_owned_products=None),
            MatchFactor.CUSTOMER_OWNED,
        ),
    ),
    Case(
        "Customer-owned goods explicitly refused",
        "excluded (hard gate)",
        lambda: _factor(
            _complete(),
            _supplier(accepts_customer_owned_products=False),
            MatchFactor.CUSTOMER_OWNED,
        ),
    ),
    Case(
        "Supplier does not offer the confirmed method",
        "excluded (hard gate)",
        lambda: _factor(
            _complete(),
            _supplier(supported_methods=(ProductionMethod.EMBROIDERY,)),
            MatchFactor.METHOD,
        ),
    ),
    Case(
        "Quantity below the supplier's minimum order",
        "mismatch 0/15 + flag",
        lambda: _factor(
            _complete().model_copy(update={"quantity": 10}),
            _supplier(),
            MatchFactor.QUANTITY,
        ),
    ),
    # The real dataset, not a fixture: proves the funnel stays explainable.
    Case(
        "Real dataset: heat-transfer candidates for sports equipment",
        "7 of 24 partners offer this method",
        lambda: _funnel(ProductionMethod.HEAT_TRANSFER, ProductCategory.SPORTS_EQUIPMENT),
    ),
)


# ----------------------------------------------------------------- running


def _rows() -> tuple[list[tuple[str, str, str, bool]], int]:
    rows: list[tuple[str, str, str, bool]] = []
    passed = 0
    for case in CASES:
        try:
            actual = case.run()
        except Exception as error:  # a crash is a failed case, not a crashed eval
            actual = f"ERROR: {type(error).__name__}: {error}"
        ok = actual == case.expected
        passed += ok
        rows.append((case.request, case.expected, actual, ok))
    return rows, passed


def _render(rows: list[tuple[str, str, str, bool]], passed: int) -> str:
    lines = [
        "| # | Request / scenario | Expected behaviour | Actual behaviour | Result |",
        "|---|---|---|---|---|",
    ]
    for index, (request, expected, actual, ok) in enumerate(rows, start=1):
        mark = "pass" if ok else "**FAIL**"
        lines.append(f"| {index} | {request} | `{expected}` | `{actual}` | {mark} |")
    lines.append("")
    lines.append(f"**{passed} of {len(rows)} cases pass.**")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="update the table in docs/eval.md")
    args = parser.parse_args()

    rows, passed = _rows()
    table = _render(rows, passed)
    print(table)

    if args.write:
        if passed != len(rows):
            print("\nRefusing to write docs/eval.md while cases fail.", file=sys.stderr)
            return 1
        doc = BACKEND_ROOT.parent / "docs" / "eval.md"
        marker = "<!-- generated: scripts/run_eval.py -->"
        body = doc.read_text(encoding="utf-8")
        head = body.split(marker)[0]
        doc.write_text(f"{head}{marker}\n\n{table}\n", encoding="utf-8")
        print(f"\nwrote {doc}")

    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
