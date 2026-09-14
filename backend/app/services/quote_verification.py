"""Deleting figures the supplier never wrote.

The model reads a reply and reports numbers. Nothing in a language model
prevents it from reporting a plausible number that is not there - and a price is
the field a buyer is most likely to act on without checking. Instructing the
model not to do it is not a mechanism; this module is.

Every extracted value arrives with the verbatim words it was read from. Here,
in ordinary Python with no AI import anywhere in its dependency tree, two things
are checked:

1. **The span is really in the text.** Compared after the same folding the guard
   applied, because that folded text is what the model actually saw.
2. **The value is really in the span.** A span is not a rubber stamp: quoting
   "14 Tage" does not license reporting a price of 8.50. Numerals are pulled out
   of the span and the stored figure must be reconstructible from one of them,
   under either German or English separator conventions.

Anything that fails is set to ``None`` and named in ``unverified_fields``, so
the interface can say a figure was discarded rather than show a blank that looks
like silence from the supplier. This module never raises on bad input and never
guesses: it only ever removes.

It also deliberately does not import :mod:`app.security.guard`, which reaches
``app.llm``. Code that decides whether a number may exist must not be able to
call a model, even by accident - the same separation that keeps the scorer
clean, enforced by the architecture audit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.domain.quote import NUMERIC_ANSWER_FIELDS, FieldEvidence
from app.services.text_normalise import fold

# Fields whose value the model may only report if it can point at words. The
# numeric ones additionally have to survive the value check below; the rest can
# only be grounded to the extent that a span exists and is genuinely present.
GROUNDED_FIELDS: tuple[str, ...] = (
    *NUMERIC_ANSWER_FIELDS,
    "feasible",
    "proposed_method",
    "price_basis",
    "price_is_estimate",
    "currency",
    "lead_time_basis",
    "sample_available",
    "accepts_customer_owned_goods",
)

# A run of digits with optional thousands and decimal separators. Deliberately
# permissive: the convention is resolved afterwards, because "1.000" is a
# thousand in German and one in English and the verifier accepts either rather
# than picking a side it cannot know.
_NUMERAL = re.compile(r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class VerificationResult:
    """What survived, and what was taken away."""

    values: dict[str, Any]
    dropped: tuple[str, ...]

    @property
    def anything_dropped(self) -> bool:
        return bool(self.dropped)


def candidate_values(span: str) -> set[float]:
    """Every number a human could honestly read out of this span.

    Both separator conventions are admitted, because guessing the locale of a
    business letter and then deleting a correct figure when the guess is wrong
    would be the very failure this module exists to prevent.

    What is *not* admitted is a reading no convention supports. A thousands
    separator groups exactly three digits, so "8,50" is eight-fifty in German and
    simply not a number in English - it is never eight hundred and fifty. Without
    that rule a model could report 850 while quoting "8,50" and pass.
    """
    found: set[float] = set()

    for token in _NUMERAL.findall(span):
        for thousands, decimal in ((".", ","), (",", ".")):
            if token.count(decimal) > 1:
                continue  # two decimal points is not a number in any convention

            whole, _, fraction = token.partition(decimal)

            # A thousands separator groups exactly three digits. Checked on the
            # integer part alone - this is what stops "8,50" being read as eight
            # hundred and fifty, while leaving "1,234.56" perfectly readable.
            groups = whole.split(thousands)
            if len(groups) > 1 and not (
                1 <= len(groups[0]) <= 3 and all(len(part) == 3 for part in groups[1:])
            ):
                continue

            digits = "".join(groups)
            if not digits.isdigit():
                continue
            if fraction and not fraction.isdigit():
                continue

            try:
                found.add(float(f"{digits}.{fraction}" if fraction else digits))
            except ValueError:
                continue

    return found


def _spans_for(evidence: tuple[FieldEvidence, ...], field: str) -> list[str]:
    return [item.quote for item in evidence if item.field == field]


def verify(
    values: dict[str, Any],
    evidence: tuple[FieldEvidence, ...],
    source_text: str,
) -> VerificationResult:
    """Remove every reported value that the text does not support.

    ``values`` is what the model returned; the returned mapping is what may be
    stored. Fields absent from :data:`GROUNDED_FIELDS` pass through untouched -
    prose such as ``open_questions`` carries no figure and enters no
    calculation, so grounding it would cost accuracy without buying safety.
    """
    folded = fold(source_text)
    surviving = dict(values)
    dropped: list[str] = []

    for field in GROUNDED_FIELDS:
        value = surviving.get(field)
        if value is None:
            continue

        spans = _spans_for(evidence, field)
        present = [span for span in spans if fold(span) and fold(span) in folded]

        if not present:
            # Either no span was offered, or the words quoted are not in the
            # reply. Both mean the same thing: nobody can point at this.
            surviving[field] = None
            dropped.append(field)
            continue

        if field in NUMERIC_ANSWER_FIELDS:
            numeric_value = float(value)
            if not any(numeric_value in candidate_values(span) for span in present):
                # The span exists but does not contain this number - quoting
                # "14 Tage" does not license a price of 8.50.
                surviving[field] = None
                dropped.append(field)

    return VerificationResult(values=surviving, dropped=tuple(dropped))
