"""Turn a day of German procurement notices into the handful this product cares about.

The export is a zip of about twenty CSVs joined on ``(noticeIdentifier,
noticeVersion, lotIdentifier)`` - one row per notice for some facts, one per lot
for others, and the two kinds are mixed in the same file. Reading it correctly
is most of the work here, and it is worth doing in a pure function so it can be
tested against a fixture rather than against a federal server.

Two shapes in the data cost a reading if you miss them:

* **A fact can live at the notice level or at the lot level.** ``placeOfPerformance``
  often carries one row with an empty ``lotIdentifier`` and nothing per lot; the
  lookup therefore falls back from the lot to the notice, never the other way.
* **One notice appears once per lot.** A framework agreement for print with five
  lots is one contract, not five - so notices are folded into one record and the
  first lot that matched a CPV family decides what it is filed under.

A month of notices is roughly 23,000 across Germany, of which about 200 are
printing, textile or engraving work. That ratio is why the CPV filter runs
before anything else touches the data.

**The submission deadline is not in the CSV**, and it is not in the OCDS export
either - both were checked. It lives only in the eForms XML, as
``TenderSubmissionDeadlinePeriod``. Since the deadline is the single most
actionable thing on a tender board, the importer reads both formats: the CSV
for the structured fields it states cleanly, and one targeted element out of
the XML for the date bids actually close.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.domain.tender import Tender, family_for
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

# Where a reader can see the notice itself. The service publishes one page per
# notice identifier, and a tender nobody can open is not worth listing.
NOTICE_URL = "https://oeffentlichevergabe.de/ui/de/bekanntmachung/{identifier}"

Row = dict[str, str]
Key = tuple[str, str]


@dataclass
class _Tables:
    """The CSVs this import reads, keyed for lookup."""

    notices: dict[str, Row] = field(default_factory=dict)
    purpose: dict[Key, Row] = field(default_factory=dict)
    classification: dict[Key, Row] = field(default_factory=dict)
    place: dict[Key, Row] = field(default_factory=dict)
    submission: dict[Key, Row] = field(default_factory=dict)
    sme: dict[Key, Row] = field(default_factory=dict)
    procedure: dict[str, Row] = field(default_factory=dict)
    buyers: dict[str, Row] = field(default_factory=dict)


def _read(archive: zipfile.ZipFile, name: str) -> list[Row]:
    if name not in archive.namelist():
        return []
    text = archive.read(name).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _tables(archive: zipfile.ZipFile) -> _Tables:
    tables = _Tables()

    for row in _read(archive, "notice.csv"):
        tables.notices[row["noticeIdentifier"]] = row
    for row in _read(archive, "procedure.csv"):
        tables.procedure.setdefault(row["noticeIdentifier"], row)

    for name, target in (
        ("purpose.csv", tables.purpose),
        ("classification.csv", tables.classification),
        ("placeOfPerformance.csv", tables.place),
        ("submissionTerms.csv", tables.submission),
        ("additionalInformation.csv", tables.sme),
    ):
        for row in _read(archive, name):
            target[(row["noticeIdentifier"], row.get("lotIdentifier", ""))] = row

    # The buyer, not the winner. An award notice lists both, and attributing a
    # contract to the company that won it would name the wrong organisation on
    # every completed tender.
    for row in _read(archive, "organisation.csv"):
        if row.get("organisationRole", "").strip().casefold() == "winner":
            continue
        tables.buyers.setdefault(row["noticeIdentifier"], row)

    return tables


def _sme_of(table: dict[Key, Row], notice: str) -> bool | None:
    """Whether any lot of this contract is declared suitable for small firms.

    Across every lot rather than the one that matched the CPV filter. The
    declaration is made per lot and the matched lot is often the notice-level
    row, which carries none - reading only that one reported "not stated" for
    every tender in Germany, which was wrong about fifty-six of them a month.

    Any rather than all, because a framework with one SME-suitable lot is worth
    a small shop's attention even if the other four are not.
    """
    answers = [
        _flag(row.get("suitableForSMEs", "")) for (nid, _), row in table.items() if nid == notice
    ]
    stated = [answer for answer in answers if answer is not None]
    if not stated:
        return None
    return any(stated)


def _at(table: dict[Key, Row], notice: str, lot: str) -> Row:
    """A fact for this lot, or the notice-level one standing in for it.

    Never the reverse: a value stated for one lot does not describe the notice,
    and borrowing it upwards would put one lot's deadline on four others.
    """
    return table.get((notice, lot)) or table.get((notice, "")) or {}


def _number(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _moment(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _day(value: str) -> date | None:
    moment = _moment(value)
    return moment.date() if moment else None


def _flag(value: str) -> bool | None:
    """Three-valued, because the buyer not saying is not the buyer saying no."""
    cleaned = value.strip().casefold()
    if cleaned in {"true", "yes", "1"}:
        return True
    if cleaned in {"false", "no", "0"}:
        return False
    return None


# One element out of eForms, by pattern rather than by parsing the whole
# schema. eForms is a large UBL vocabulary and this import needs exactly one
# thing from it; a namespace-aware parse of 20 KB per notice to reach a single
# date would be machinery guarding nothing. The pattern is anchored on the
# element name, so it cannot match a date somewhere else in the document.
_DEADLINE = re.compile(
    r"<cac:TenderSubmissionDeadlinePeriod>(.*?)</cac:TenderSubmissionDeadlinePeriod>",
    re.DOTALL,
)
_END_DATE = re.compile(r"<cbc:EndDate>([^<]+)</cbc:EndDate>")
_END_TIME = re.compile(r"<cbc:EndTime>([^<]+)</cbc:EndTime>")
# "+02:00", "-05:00" or "Z" at the end of an eForms date or time.
_OFFSET = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")


def deadlines_from_eforms(data: bytes) -> dict[str, datetime]:
    """The submission deadline of every notice in an eForms export, by id.

    The earliest, when a notice states one per lot: a bidder reading the notice
    needs the date by which they must have acted, and the latest lot's deadline
    would tell them they have longer than they do.
    """
    found: dict[str, datetime] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if not name.endswith(".xml"):
                continue
            # "<notice id>-<version>.xml" - the same identifier the CSV uses.
            identifier = name.rsplit("/", 1)[-1].rsplit("-", 1)[0]
            text = archive.read(name).decode("utf-8", errors="replace")
            for block in _DEADLINE.findall(text):
                day = _END_DATE.search(block)
                if not day:
                    continue
                clock = _END_TIME.search(block)
                moment = _moment_from_parts(day.group(1), clock.group(1) if clock else "")
                if moment is None:
                    continue
                if identifier not in found or moment < found[identifier]:
                    found[identifier] = moment
    return found


def _moment_from_parts(day: str, clock: str) -> datetime | None:
    """eForms writes the date and the time as separate values, each carrying its
    own offset - "2026-10-20+02:00" and "08:00:00+02:00".

    The offset is kept rather than trimmed off with the rest of the date. A
    deadline is a moment, and 08:00 in Berlin is not 08:00 in UTC: dropping
    "+02:00" would tell somebody in October that they had two hours longer than
    they do.
    """
    date_part = day.strip()[:10]
    time_part = clock.strip() or "23:59:59"
    if not _OFFSET.search(time_part):
        # No offset on the time: take the one the date carried, and failing
        # that leave it naive rather than inventing a timezone.
        offset = _OFFSET.search(day.strip())
        time_part = f"{time_part}{offset.group(0) if offset else ''}"
    try:
        return datetime.fromisoformat(f"{date_part}T{time_part}")
    except ValueError:
        return None


def _codes(row: Row) -> list[str]:
    main = (row.get("mainClassificationCode") or "").strip()
    extra = (row.get("additionalClassificationCodes") or "").replace(",", " ").split()
    return [code for code in [main, *extra] if code]


def read_export(
    data: bytes,
    *,
    fallback_day: date | None = None,
    deadlines: dict[str, datetime] | None = None,
) -> tuple[Tender, ...]:
    """Every printing, textile or engraving tender in one export.

    ``data`` is the CSV zip exactly as the API returns it. ``deadlines`` comes
    from :func:`deadlines_from_eforms` over the same day, because the CSV does
    not carry one. Anything whose CPV codes fall outside the families in
    :mod:`app.domain.tender` is dropped here and never reaches the database -
    about 23,000 notices a month become 200.
    """
    closing = deadlines or {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        tables = _tables(archive)

        # Which lots matched, in the order they appear, so the first match on a
        # notice is the one that files it.
        matched: dict[str, tuple[str, str]] = {}
        for (notice, lot), row in tables.classification.items():
            if notice in matched:
                continue
            if (row.get("classificationType") or "cpv").strip().casefold() != "cpv":
                continue
            for code in _codes(row):
                if family_for(code) is not None:
                    matched[notice] = (lot, code)
                    break

        found: list[Tender] = []
        for notice, (lot, code) in matched.items():
            header = tables.notices.get(notice, {})
            family = family_for(code)
            if family is None:  # pragma: no cover - matched implies a family
                continue

            purpose = _at(tables.purpose, notice, lot)
            place = _at(tables.place, notice, lot)
            buyer = tables.buyers.get(notice, {})
            procedure = tables.procedure.get(notice, {})

            title = (purpose.get("title") or "").strip()
            if not title:
                # A notice with no title is one nobody can act on, and showing
                # a blank row would be this product filling a page rather than
                # answering a question.
                continue

            published = _day(header.get("publicationDate", "")) or fallback_day
            if published is None:
                continue

            found.append(
                Tender(
                    id=notice,
                    title=title,
                    description=(purpose.get("description") or "").strip(),
                    cpv=code,
                    family_prefix=family.prefix,
                    family_label=family.label,
                    implied_method=family.implied_method,
                    buyer=(buyer.get("organisationName") or "").strip(),
                    buyer_city=(buyer.get("organisationCity") or "").strip(),
                    place_city=(place.get("placePerformanceCity") or "").strip(),
                    place_region=(place.get("placePerformanceCountrySubdivision") or "").strip(),
                    estimated_value=_number(purpose.get("estimatedValue", "")),
                    currency=(purpose.get("estimatedValueCurrency") or "").strip(),
                    published_on=published,
                    deadline=closing.get(notice),
                    suitable_for_smes=_sme_of(tables.sme, notice),
                    procedure_type=(procedure.get("procedureType") or "").strip(),
                    notice_type=(header.get("noticeType") or "").strip(),
                    source_url=NOTICE_URL.format(identifier=notice),
                )
            )

    log_event(
        logger,
        Event.SUPPLIER_CANDIDATES_FOUND,
        "tender export read",
        notices=len(tables.notices),
        kept=len(found),
    )
    return tuple(
        sorted(found, key=lambda tender: (tender.published_on, tender.title), reverse=True)
    )


def summarise(tenders: tuple[Tender, ...]) -> dict[str, Any]:
    """Counts worth printing after an import, for a person watching it run."""
    berlin = [tender for tender in tenders if tender.is_berlin]
    return {
        "kept": len(tenders),
        "berlin": len(berlin),
        "sme_suitable": sum(1 for tender in tenders if tender.suitable_for_smes),
        "with_value": sum(1 for tender in tenders if tender.estimated_value),
    }
