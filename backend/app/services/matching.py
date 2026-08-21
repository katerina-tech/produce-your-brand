"""Deterministic supplier matching.

This module is the credibility of the product. Every number it produces is
computed here, in plain Python, from stored supplier facts. The LLM is given the
finished breakdown and may only write prose about it - it cannot produce, nudge
or override a score.

Three properties are deliberately engineered and covered by tests:

*Deterministic.* No randomness and no clock reads - ``today`` is a parameter, so
the same inputs always produce byte-identical output, including tie order.

*Honest about unknowns.* A ``None`` capability is not a ``False`` one. Unknown
scores partially and raises a risk flag; only an explicit refusal is a hard gate.

*No LLM.* This module imports nothing from ``app.llm`` or any model SDK, and
``scripts/audit_architecture.py`` fails the build if that ever changes.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from app.domain.enums import ProductionMethod
from app.domain.matching import (
    WEIGHTS,
    FactorScore,
    MatchFactor,
    MatchResult,
    Verdict,
)
from app.domain.requirement import ProductionRequirement
from app.domain.supplier import Supplier, SupplierQuery

# Days of slack added to a supplier's lead time before comparing to the deadline,
# covering artwork approval and shipping. Overridable via settings.
DEFAULT_DEADLINE_BUFFER_DAYS = 5

# How far past the deadline still counts as "tight but arguable" rather than
# infeasible: 20% over the available window.
DEADLINE_TOLERANCE = 1.2

_SORT_LEAD_TIME_UNKNOWN = 9999

# Material synonyms seen in customer phrasing, mapped to the dataset vocabulary.
# Free text in, canonical token out - the requirement keeps whatever the customer
# said, and normalisation happens only at comparison time.
_MATERIAL_ALIASES: dict[str, str] = {
    "pvc": "pvc",
    "polyvinyl chloride": "pvc",
    "vinyl": "pvc",
    "rubber": "natural_rubber",
    "natural rubber": "natural_rubber",
    "tree rubber": "natural_rubber",
    "tpe": "tpe",
    "thermoplastic elastomer": "tpe",
    "cork": "cork",
    "wood": "wood",
    "timber": "wood",
    "bamboo": "bamboo",
    "leather": "leather",
    "cotton": "cotton",
    "organic cotton": "cotton",
    "polyester": "polyester",
    "canvas": "canvas",
    "aluminium": "aluminium",
    "aluminum": "aluminium",
    "anodised aluminium": "anodised_aluminium",
    "anodized aluminum": "anodised_aluminium",
    "anodised aluminum": "anodised_aluminium",
    "stainless steel": "stainless_steel",
    "steel": "stainless_steel",
    "glass": "glass",
    "ceramic": "ceramic",
    "acrylic": "acrylic",
    "perspex": "acrylic",
    "cardboard": "cardboard",
    "corrugated": "cardboard",
    "kraft paper": "kraft_paper",
    "kraft": "kraft_paper",
    "paper": "kraft_paper",
}

# Static geography table. A deliberate choice over a distance API: no network
# dependency, no flaky test, and city-level granularity is all the 10-point
# location factor needs.
_CITY_COUNTRY: dict[str, str] = {
    "berlin": "DE",
    "potsdam": "DE",
    "hamburg": "DE",
    "dresden": "DE",
    "leipzig": "DE",
    "munich": "DE",
    "muenchen": "DE",
    "münchen": "DE",
    "frankfurt (oder)": "DE",
    "frankfurt": "DE",
    "essen": "DE",
    "bremen": "DE",
    "erfurt": "DE",
    "cologne": "DE",
    "koeln": "DE",
    "stuttgart": "DE",
    "duesseldorf": "DE",
    "warsaw": "PL",
    "warszawa": "PL",
    "krakow": "PL",
    "prague": "CZ",
    "praha": "CZ",
    "brno": "CZ",
    "milan": "IT",
    "milano": "IT",
    "rome": "IT",
    "rotterdam": "NL",
    "amsterdam": "NL",
    "vienna": "AT",
    "paris": "FR",
    "madrid": "ES",
    "copenhagen": "DK",
}

_COUNTRY_ALIASES: dict[str, str] = {
    "germany": "DE",
    "deutschland": "DE",
    "de": "DE",
    "poland": "PL",
    "pl": "PL",
    "czechia": "CZ",
    "czech republic": "CZ",
    "cz": "CZ",
    "italy": "IT",
    "it": "IT",
    "netherlands": "NL",
    "nl": "NL",
    "austria": "AT",
    "france": "FR",
    "spain": "ES",
    "denmark": "DK",
}

_EU_COUNTRIES = frozenset(
    {"DE", "PL", "CZ", "IT", "NL", "AT", "FR", "ES", "DK", "BE", "SE", "FI", "PT", "IE"}
)


class MatchOutcome(BaseModel):
    """Ranked eligible matches plus the suppliers ruled out, with reasons.

    Exclusions are returned rather than silently dropped: "why is my obvious
    supplier not here?" is a question the UI must be able to answer.
    """

    model_config = ConfigDict(extra="forbid")

    top: list[MatchResult]
    excluded: list[MatchResult]
    considered_count: int


# --------------------------------------------------------------- normalisation


def normalize_material(value: str | None) -> str | None:
    """Map free-text material onto the dataset's canonical token."""
    if not value:
        return None
    cleaned = " ".join(value.strip().lower().replace("-", " ").replace("_", " ").split())
    if not cleaned:
        return None
    if cleaned in _MATERIAL_ALIASES:
        return _MATERIAL_ALIASES[cleaned]
    # Fall back to a containment check so "black PVC" still resolves to "pvc".
    for alias, canonical in _MATERIAL_ALIASES.items():
        if alias in cleaned:
            return canonical
    return cleaned.replace(" ", "_")


def resolve_location(value: str | None) -> tuple[str | None, str | None]:
    """Resolve free-text location into ``(city, country)``, either may be None."""
    if not value:
        return None, None
    parts = [part.strip().lower() for part in value.replace("/", ",").split(",")]
    city: str | None = None
    country: str | None = None
    for part in parts:
        if not part:
            continue
        if part in _COUNTRY_ALIASES:
            country = _COUNTRY_ALIASES[part]
        elif part in _CITY_COUNTRY:
            city = part
            country = country or _CITY_COUNTRY[part]
    return city, country


def _region_of(country: str | None) -> str | None:
    if country is None:
        return None
    return "EU" if country in _EU_COUNTRIES else "non_EU"


# ------------------------------------------------------------------- searching


def search_suppliers(
    suppliers: tuple[Supplier, ...] | list[Supplier], query: SupplierQuery
) -> list[Supplier]:
    """Structural pre-filter. No free-text search, so phrasing cannot sway it.

    Returns candidates worth scoring; scoring then applies the hard gates and the
    weighted factors. Order is stable (by id) so downstream results are stable.
    """
    matched = [
        supplier
        for supplier in suppliers
        if query.method in supplier.supported_methods
        and (query.category is None or query.category in supplier.product_categories)
        and (query.country is None or supplier.location.country == query.country)
    ]
    return sorted(matched, key=lambda supplier: supplier.id)


# --------------------------------------------------------------------- factors


def _score_method(supplier: Supplier, method: ProductionMethod) -> FactorScore:
    supported = method in supplier.supported_methods
    return FactorScore(
        factor=MatchFactor.METHOD,
        awarded=WEIGHTS[MatchFactor.METHOD] if supported else 0.0,
        max_points=WEIGHTS[MatchFactor.METHOD],
        verdict=Verdict.MATCH if supported else Verdict.MISMATCH,
        explanation=(
            f"Supports {method.value.replace('_', ' ')}."
            if supported
            else f"Does not support {method.value.replace('_', ' ')}."
        ),
    )


def _score_material(
    supplier: Supplier, requirement: ProductionRequirement
) -> tuple[FactorScore, str | None]:
    maximum = WEIGHTS[MatchFactor.MATERIAL]
    wanted = normalize_material(requirement.material)

    if wanted is None:
        return (
            FactorScore(
                factor=MatchFactor.MATERIAL,
                awarded=maximum / 2,
                max_points=maximum,
                verdict=Verdict.UNKNOWN,
                explanation="Material not specified, so compatibility is unconfirmed.",
            ),
            "Material not specified - confirm the substrate before ordering.",
        )

    if supplier.supported_materials is None:
        return (
            FactorScore(
                factor=MatchFactor.MATERIAL,
                awarded=maximum / 2,
                max_points=maximum,
                verdict=Verdict.UNKNOWN,
                explanation="Partner has not published a material list.",
            ),
            f"Confirm this partner can process {requirement.material}.",
        )

    supported = {normalize_material(item) for item in supplier.supported_materials}
    if wanted in supported:
        return (
            FactorScore(
                factor=MatchFactor.MATERIAL,
                awarded=maximum,
                max_points=maximum,
                verdict=Verdict.MATCH,
                explanation=f"Processes {requirement.material}.",
            ),
            None,
        )

    return (
        FactorScore(
            factor=MatchFactor.MATERIAL,
            awarded=0.0,
            max_points=maximum,
            verdict=Verdict.MISMATCH,
            explanation=f"{requirement.material} is not in the published material list.",
        ),
        f"Partner does not list {requirement.material} as a supported material.",
    )


def _score_quantity(
    supplier: Supplier, requirement: ProductionRequirement
) -> tuple[FactorScore, str | None]:
    maximum = WEIGHTS[MatchFactor.QUANTITY]
    quantity = requirement.quantity
    moq = supplier.min_order_quantity
    ceiling = supplier.max_order_quantity

    if quantity is None:
        return (
            FactorScore(
                factor=MatchFactor.QUANTITY,
                awarded=maximum / 2,
                max_points=maximum,
                verdict=Verdict.UNKNOWN,
                explanation="Quantity not specified.",
            ),
            "Quantity not specified - minimum order quantity cannot be checked.",
        )

    if moq is not None and quantity < moq:
        return (
            FactorScore(
                factor=MatchFactor.QUANTITY,
                awarded=0.0,
                max_points=maximum,
                verdict=Verdict.MISMATCH,
                explanation=f"Below the minimum order quantity of {moq}.",
            ),
            f"Order of {quantity} is below this partner's minimum of {moq}.",
        )

    if ceiling is not None and quantity > ceiling:
        return (
            FactorScore(
                factor=MatchFactor.QUANTITY,
                awarded=0.0,
                max_points=maximum,
                verdict=Verdict.MISMATCH,
                explanation=f"Above the stated capacity of {ceiling}.",
            ),
            f"Order of {quantity} exceeds this partner's stated capacity of {ceiling}.",
        )

    if moq is None or ceiling is None:
        return (
            FactorScore(
                factor=MatchFactor.QUANTITY,
                awarded=maximum / 2,
                max_points=maximum,
                verdict=Verdict.UNKNOWN,
                explanation="Order-quantity limits not published.",
            ),
            "Partner has not published order-quantity limits.",
        )

    return (
        FactorScore(
            factor=MatchFactor.QUANTITY,
            awarded=maximum,
            max_points=maximum,
            verdict=Verdict.MATCH,
            explanation=f"{quantity} units sits within {moq}-{ceiling}.",
        ),
        None,
    )


def _score_customer_owned(
    supplier: Supplier, requirement: ProductionRequirement
) -> tuple[FactorScore, str | None]:
    maximum = WEIGHTS[MatchFactor.CUSTOMER_OWNED]
    policy = supplier.accepts_customer_owned_products

    if requirement.customer_owns_product is False:
        return (
            FactorScore(
                factor=MatchFactor.CUSTOMER_OWNED,
                awarded=maximum,
                max_points=maximum,
                verdict=Verdict.MATCH,
                explanation="Not applicable - the partner sources the product.",
            ),
            None,
        )

    if requirement.customer_owns_product is None:
        return (
            FactorScore(
                factor=MatchFactor.CUSTOMER_OWNED,
                awarded=maximum / 2,
                max_points=maximum,
                verdict=Verdict.UNKNOWN,
                explanation="Unclear whether you supply the goods.",
            ),
            "Confirm whether you supply the product or the partner sources it.",
        )

    if policy is True:
        return (
            FactorScore(
                factor=MatchFactor.CUSTOMER_OWNED,
                awarded=maximum,
                max_points=maximum,
                verdict=Verdict.MATCH,
                explanation="Accepts customer-supplied goods.",
            ),
            None,
        )

    # policy is None. An explicit False is a hard gate and never reaches scoring.
    return (
        FactorScore(
            factor=MatchFactor.CUSTOMER_OWNED,
            awarded=maximum / 2,
            max_points=maximum,
            verdict=Verdict.UNKNOWN,
            explanation="Policy on customer-supplied goods is unconfirmed.",
        ),
        "Partner has not confirmed whether it accepts customer-supplied goods.",
    )


def _score_deadline(
    supplier: Supplier, requirement: ProductionRequirement, today: date, buffer_days: int
) -> tuple[FactorScore, str | None]:
    maximum = WEIGHTS[MatchFactor.DEADLINE]
    deadline = requirement.deadline
    lead_time = supplier.typical_lead_time_days

    if deadline is None or lead_time is None:
        missing = "No deadline given" if deadline is None else "Lead time not published"
        return (
            FactorScore(
                factor=MatchFactor.DEADLINE,
                awarded=maximum / 2,
                max_points=maximum,
                verdict=Verdict.UNKNOWN,
                explanation=f"{missing}, so feasibility is unconfirmed.",
            ),
            f"{missing} - confirm timing with the partner.",
        )

    days_available = (deadline - today).days
    days_needed = lead_time + buffer_days

    if days_available <= 0:
        return (
            FactorScore(
                factor=MatchFactor.DEADLINE,
                awarded=0.0,
                max_points=maximum,
                verdict=Verdict.MISMATCH,
                explanation="The deadline has already passed.",
            ),
            "The stated deadline is in the past.",
        )

    if days_needed <= days_available:
        return (
            FactorScore(
                factor=MatchFactor.DEADLINE,
                awarded=maximum,
                max_points=maximum,
                verdict=Verdict.MATCH,
                explanation=(
                    f"{lead_time} days production plus {buffer_days} days buffer "
                    f"fits the {days_available} days available."
                ),
            ),
            None,
        )

    if days_needed <= days_available * DEADLINE_TOLERANCE:
        return (
            FactorScore(
                factor=MatchFactor.DEADLINE,
                awarded=maximum / 2,
                max_points=maximum,
                verdict=Verdict.PARTIAL,
                explanation=(
                    f"Needs about {days_needed} days against {days_available} available - tight."
                ),
            ),
            f"Timeline is tight: about {days_needed} days needed, {days_available} available.",
        )

    return (
        FactorScore(
            factor=MatchFactor.DEADLINE,
            awarded=0.0,
            max_points=maximum,
            verdict=Verdict.MISMATCH,
            explanation=f"Needs about {days_needed} days, only {days_available} available.",
        ),
        f"Deadline appears infeasible: about {days_needed} days needed.",
    )


def _score_location(
    supplier: Supplier, requirement: ProductionRequirement
) -> tuple[FactorScore, str | None]:
    maximum = WEIGHTS[MatchFactor.LOCATION]
    wanted_city, wanted_country = resolve_location(requirement.location)

    if wanted_city is None and wanted_country is None:
        return (
            FactorScore(
                factor=MatchFactor.LOCATION,
                awarded=3.0,
                max_points=maximum,
                verdict=Verdict.UNKNOWN,
                explanation="Delivery location not specified.",
            ),
            "Delivery location not specified.",
        )

    supplier_city = supplier.location.city.strip().lower()

    if wanted_city is not None and supplier_city == wanted_city:
        return (
            FactorScore(
                factor=MatchFactor.LOCATION,
                awarded=maximum,
                max_points=maximum,
                verdict=Verdict.MATCH,
                explanation=f"Located in {supplier.location.city}.",
            ),
            None,
        )

    if wanted_country is not None and supplier.location.country == wanted_country:
        return (
            FactorScore(
                factor=MatchFactor.LOCATION,
                awarded=6.0,
                max_points=maximum,
                verdict=Verdict.PARTIAL,
                explanation=(
                    f"In {supplier.location.country} but not in the delivery city "
                    f"({supplier.location.city})."
                ),
            ),
            None,
        )

    if _region_of(wanted_country) == supplier.location.region:
        return (
            FactorScore(
                factor=MatchFactor.LOCATION,
                awarded=3.0,
                max_points=maximum,
                verdict=Verdict.PARTIAL,
                explanation=f"Cross-border within {supplier.location.region}.",
            ),
            "Cross-border shipping - factor in transit time and duties.",
        )

    return (
        FactorScore(
            factor=MatchFactor.LOCATION,
            awarded=0.0,
            max_points=maximum,
            verdict=Verdict.MISMATCH,
            explanation=f"Outside the delivery region ({supplier.location.city}).",
        ),
        "Partner is outside the delivery region.",
    )


# ---------------------------------------------------------------------- gating


def _hard_gate(
    supplier: Supplier, requirement: ProductionRequirement, method: ProductionMethod
) -> str | None:
    """Return an exclusion reason, or None when the supplier is eligible.

    Hard gates are structural impossibilities, not low scores. A partner that
    cannot perform the technique must not surface as a strong match because it
    happens to be nearby and cheap.
    """
    if method not in supplier.supported_methods:
        return f"Does not offer {method.value.replace('_', ' ')}."

    if (
        requirement.customer_owns_product is True
        and supplier.accepts_customer_owned_products is False
    ):
        return "Does not accept customer-supplied goods."

    if (
        requirement.product_category is not None
        and requirement.product_category not in supplier.product_categories
    ):
        return f"Does not work with {requirement.product_category.value.replace('_', ' ')}."

    return None


# --------------------------------------------------------------------- scoring


def score_supplier(
    supplier: Supplier,
    requirement: ProductionRequirement,
    method: ProductionMethod,
    today: date,
    buffer_days: int = DEFAULT_DEADLINE_BUFFER_DAYS,
) -> MatchResult:
    """Score one supplier. Pure: ``today`` is injected, never read from a clock."""
    exclusion = _hard_gate(supplier, requirement, method)

    material_score, material_flag = _score_material(supplier, requirement)
    quantity_score, quantity_flag = _score_quantity(supplier, requirement)
    owned_score, owned_flag = _score_customer_owned(supplier, requirement)
    deadline_score, deadline_flag = _score_deadline(supplier, requirement, today, buffer_days)
    location_score, location_flag = _score_location(supplier, requirement)

    factors = (
        _score_method(supplier, method),
        material_score,
        quantity_score,
        owned_score,
        deadline_score,
        location_score,
    )
    flags = tuple(
        flag
        for flag in (material_flag, quantity_flag, owned_flag, deadline_flag, location_flag)
        if flag is not None
    )

    total = 0.0 if exclusion else round(sum(factor.awarded for factor in factors), 2)

    return MatchResult(
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        score=total,
        eligible=exclusion is None,
        exclusion_reason=exclusion,
        factors=factors,
        risk_flags=flags,
    )


def _rank_key(result: MatchResult, supplier: Supplier) -> tuple[float, int, int, str]:
    """Total order, so ties never resolve differently between two runs.

    Higher score first, then verified partners, then shorter lead time, then id.
    The final ``id`` term is what makes it total - without it, two otherwise
    identical partners could swap places between runs.
    """
    lead = supplier.typical_lead_time_days
    return (
        -result.score,
        0 if supplier.verified else 1,
        lead if lead is not None else _SORT_LEAD_TIME_UNKNOWN,
        result.supplier_id,
    )


def rank_matches(
    suppliers: tuple[Supplier, ...] | list[Supplier],
    requirement: ProductionRequirement,
    method: ProductionMethod,
    today: date,
    top_n: int = 3,
    buffer_days: int = DEFAULT_DEADLINE_BUFFER_DAYS,
) -> MatchOutcome:
    """Score every candidate and return the ranked eligible ones plus exclusions."""
    by_id = {supplier.id: supplier for supplier in suppliers}

    results = [
        score_supplier(supplier, requirement, method, today, buffer_days) for supplier in suppliers
    ]

    eligible = sorted(
        (result for result in results if result.eligible),
        key=lambda result: _rank_key(result, by_id[result.supplier_id]),
    )
    excluded = sorted(
        (result for result in results if not result.eligible),
        key=lambda result: result.supplier_id,
    )

    return MatchOutcome(top=eligible[:top_n], excluded=excluded, considered_count=len(results))
