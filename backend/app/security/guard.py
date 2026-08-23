"""Layered defence against prompt injection.

The predecessor project was criticised for relying on regex, and the criticism was
right: a pattern list is trivially defeated by spacing, homoglyphs, zero-width
characters or base64, and it produces a boolean where a judgement is needed. So
patterns are one signal here, not the mechanism.

Five layers, and the two that matter most are not detection at all:

1. **Normalisation** - NFKC, strip invisible and direction-control characters,
   fold homoglyphs, inspect encoded blocks. Obfuscation is removed before
   anything looks at the text.
2. **Heuristic signals** - weighted evidence producing a *score*, never a verdict.
3. **A model classifier** - consulted only when the score clears a threshold, so
   the cost is paid on suspicious input rather than on every request.
4. **Structure** (in :mod:`app.llm.prompts`) - untrusted content never enters a
   system message, and fence tokens inside it are neutralised here so it cannot
   escape its own delimiters.
5. **Output validation** (in :mod:`app.llm.factory`) - every model response is a
   closed Pydantic schema, so a successful injection still cannot produce a field
   the system will act on.

Policy differs by provenance, deliberately. Customer request text is the *subject
of analysis*: a brief that happens to say "ignore" must not be rejected, because
blocking a legitimate request is a worse failure than reading a hostile one that
structure already contains. Uploaded files and other externally-authored content
are different - there, detection blocks.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, get_settings
from app.llm import prompts
from app.llm.factory import LLMError, LLMProvider
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

MAX_SCREEN_LENGTH = 20_000

# Homoglyphs that survive NFKC. Cyrillic and Greek lookalikes are the cheap way
# to write "ignore" so that a Latin pattern list never sees it.
_CONFUSABLES = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
        "і": "i",
        "ѕ": "s",
        "ԁ": "d",
        "ո": "n",
        "ⅼ": "l",
        "А": "A",
        "Е": "E",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "У": "Y",
        "Х": "X",
        "ο": "o",
        "ν": "v",
        "α": "a",
        "ι": "i",
        "ρ": "p",
        "τ": "t",
    }
)

# Characters with no visible width that can hide inside a word.
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤﻿­]")

_BASE64_BLOCK = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")

# Fence tokens. Untrusted content containing these could otherwise close the
# block it is wrapped in and continue as if it were trusted instruction.
_FENCE = re.compile(r"</?untrusted_[a-z_]*>?", re.IGNORECASE)


class Provenance(StrEnum):
    """Where the text came from. Decides whether detection blocks."""

    CUSTOMER_TEXT = "customer_text"
    KNOWLEDGE_BASE = "knowledge_base"
    UPLOADED_FILE = "uploaded_file"


# Weighted signals. Individually weak, collectively meaningful - which is the
# point of scoring rather than matching.
SIGNAL_WEIGHTS: dict[str, float] = {
    "provider_content_filter": 0.50,
    "instruction_override": 0.40,
    "role_marker": 0.35,
    "prompt_exfiltration": 0.35,
    "authority_claim": 0.30,
    "fence_escape": 0.30,
    "task_replacement": 0.25,
    "encoded_payload": 0.15,
}

_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "instruction_override": (
        re.compile(r"\bignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\b"),
        re.compile(r"\bdisregard\s+(all\s+|the\s+)?(previous|prior|above|instructions)\b"),
        re.compile(r"\bforget\s+(everything|all|your)\b"),
        re.compile(r"\boverride\s+(the\s+)?(system|instructions|rules)\b"),
    ),
    "role_marker": (
        re.compile(r"^\s*(system|assistant|developer)\s*:", re.MULTILINE),
        re.compile(r"<\|?(im_start|im_end|endoftext|system)\|?>"),
        re.compile(r"\[/?(INST|SYS)\]"),
        re.compile(r"###\s*(instruction|system)"),
    ),
    "prompt_exfiltration": (
        re.compile(
            r"\b(reveal|print|repeat|output|show)\s+(me\s+)?(your|the)\s+"
            r"(system\s+)?(prompt|instructions|rules|guidelines)\b"
        ),
        re.compile(r"\bwhat\s+(are|were)\s+your\s+(original\s+)?instructions\b"),
        re.compile(r"\bverbatim\b.{0,30}\b(prompt|instructions)\b"),
    ),
    "authority_claim": (
        re.compile(r"\b(developer|admin|debug|god)\s+mode\b"),
        re.compile(r"\byou\s+are\s+now\s+(a|an|the)\b"),
        re.compile(r"\bi\s+am\s+(the\s+)?(developer|administrator|your\s+creator)\b"),
        re.compile(r"\b(authorised|authorized|approved)\s+by\s+(anthropic|openai|the\s+system)\b"),
    ),
    "task_replacement": (
        re.compile(r"\byour\s+(new|real|actual)\s+(task|job|instruction)\b"),
        re.compile(
            r"\binstead\s+of\s+(that|this|the\s+above)\b.{0,40}\b(do|output|write|return)\b"
        ),
        re.compile(r"\bfrom\s+now\s+on\b.{0,30}\b(you|respond|answer)\b"),
    ),
}


class InjectionCategory(StrEnum):
    NONE = "none"
    INSTRUCTION_OVERRIDE = "instruction_override"
    PROMPT_EXFILTRATION = "prompt_exfiltration"
    ROLE_HIJACK = "role_hijack"
    OTHER = "other"


class InjectionVerdict(BaseModel):
    """Model classifier output. Advisory input to the decision, not the decision."""

    model_config = ConfigDict(extra="forbid")

    is_injection: bool
    confidence: float = Field(ge=0.0, le=1.0)
    category: InjectionCategory = InjectionCategory.NONE
    rationale: str = Field(description="One short sentence. No chain of thought.")


@dataclass(frozen=True)
class ScreeningResult:
    """What screening produced: safe text, plus what was noticed."""

    text: str
    signals: tuple[str, ...]
    score: float
    classified: bool
    verdict: InjectionVerdict | None
    blocked: bool

    @property
    def suspicious(self) -> bool:
        return bool(self.signals) or (self.verdict is not None and self.verdict.is_injection)


# --------------------------------------------------------------- normalisation


def normalise(text: str) -> str:
    """Strip obfuscation. Runs before any inspection and before any prompt use.

    Order matters: compatibility-fold first so full-width and styled characters
    become plain, then remove invisibles, then fold homoglyphs.
    """
    folded = unicodedata.normalize("NFKC", text)
    folded = _INVISIBLE.sub("", folded)
    folded = folded.translate(_CONFUSABLES)
    # Collapse runs of whitespace but keep line structure, since prompts and
    # documents rely on paragraphs.
    folded = re.sub(r"[ \t]+", " ", folded)
    folded = re.sub(r"\n{3,}", "\n\n", folded)
    return folded.strip()[:MAX_SCREEN_LENGTH]


def neutralise_fences(text: str) -> str:
    """Defang delimiter tokens so untrusted content cannot close its own fence.

    Without this, a document containing ``</untrusted_knowledge_excerpts>``
    followed by instructions would appear to the model as though the untrusted
    block had ended and trusted instruction had resumed.
    """
    return _FENCE.sub("[fence-removed]", text)


def _decoded_payloads(text: str) -> list[str]:
    """Decode base64-looking blocks so hidden instructions can be inspected.

    The decoded text is used for *detection only* and never substituted into the
    text that reaches a prompt.
    """
    payloads: list[str] = []
    for match in _BASE64_BLOCK.findall(text)[:5]:
        try:
            raw = base64.b64decode(match, validate=True)
        except (binascii.Error, ValueError):
            continue
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if decoded.isprintable() or "\n" in decoded:
            payloads.append(decoded)
    return payloads


# ------------------------------------------------------------------ heuristics


def heuristic_signals(text: str) -> tuple[tuple[str, ...], float]:
    """Score the evidence. Returns the signal names and a 0-1 score.

    Deliberately a score, not a verdict: a single phrase should not condemn a
    legitimate brief, while several together are worth a closer look.
    """
    lowered = text.lower()
    found: list[str] = []

    for name, patterns in _PATTERNS.items():
        if any(pattern.search(lowered) for pattern in patterns):
            found.append(name)

    if _FENCE.search(text):
        found.append("fence_escape")

    for payload in _decoded_payloads(text):
        payload_signals, _ = heuristic_signals_of_decoded(payload)
        if payload_signals:
            found.append("encoded_payload")
            found.extend(payload_signals)
            break

    unique = tuple(dict.fromkeys(found))
    score = min(1.0, sum(SIGNAL_WEIGHTS.get(name, 0.1) for name in unique))
    return unique, round(score, 3)


def heuristic_signals_of_decoded(text: str) -> tuple[tuple[str, ...], float]:
    """Pattern check on decoded content, without recursing into more decoding."""
    lowered = text.lower()
    found = [
        name
        for name, patterns in _PATTERNS.items()
        if any(pattern.search(lowered) for pattern in patterns)
    ]
    return tuple(found), min(1.0, sum(SIGNAL_WEIGHTS.get(n, 0.1) for n in found))


# ----------------------------------------------------------------------- guard


class InjectionGuard:
    """Screens untrusted text. One entry point per provenance."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings or get_settings()

    def assess(self, text: str, provenance: Provenance) -> ScreeningResult:
        """Run all layers and decide. Never raises on hostile input."""
        cleaned = normalise(text)
        signals, score = heuristic_signals(cleaned)

        verdict: InjectionVerdict | None = None
        classified = False
        if (
            self._provider is not None
            and self._settings.injection_classifier_enabled
            and score >= self._settings.injection_heuristic_threshold
        ):
            verdict, refused = self._classify(cleaned)
            classified = verdict is not None
            if refused:
                # The upstream provider declined to process this text under its
                # own content policy. That is evidence, not an outage, so it
                # counts toward the score instead of being thrown away.
                signals = tuple(dict.fromkeys((*signals, "provider_content_filter")))
                score = min(1.0, score + SIGNAL_WEIGHTS["provider_content_filter"])

        blocked = self._should_block(provenance, score, verdict)
        safe_text = neutralise_fences(cleaned)

        if signals or verdict is not None:
            log_event(
                logger,
                Event.INJECTION_SUSPECTED,
                "screening flagged untrusted content",
                level=logging.WARNING if blocked else logging.INFO,
                provenance=provenance.value,
                signals=list(signals),
                score=score,
                classified=classified,
                is_injection=verdict.is_injection if verdict else None,
                blocked=blocked,
            )

        return ScreeningResult(
            text=safe_text,
            signals=signals,
            score=score,
            classified=classified,
            verdict=verdict,
            blocked=blocked,
        )

    def screen(self, text: str, label: str) -> str:
        """Sanitise text on its way into a prompt.

        Used by the workflow for customer-authored text, which is analysed rather
        than obeyed. It normalises and defangs delimiters, and records what it
        noticed, but does not reject: refusing a legitimate brief because it
        contains the word "ignore" is the worse failure, and structure plus
        output validation already contain the hostile case.
        """
        provenance = (
            Provenance.KNOWLEDGE_BASE if label.startswith("knowledge") else Provenance.CUSTOMER_TEXT
        )
        return self.assess(text, provenance).text

    def _classify(self, text: str) -> tuple[InjectionVerdict | None, bool]:
        """Ask the cheap model. Returns ``(verdict, provider_refused)``.

        A classifier outage must never block the workflow, so failure degrades to
        heuristics. The refusal flag is reported separately because a provider
        rejecting the text on content grounds is itself informative - in practice
        the most blatant injections are refused upstream rather than classified.
        """
        if self._provider is None:
            return None, False
        try:
            verdict = self._provider.structured(
                InjectionVerdict,
                prompts.injection_classifier_messages(text),
                purpose="classifier",
            )
        except LLMError as error:
            refused = getattr(error, "content_filtered", False)
            log_event(
                logger,
                Event.LLM_ERROR,
                "injection classifier unavailable; falling back to heuristics",
                level=logging.WARNING,
                provider_refused=refused,
            )
            return None, refused
        return verdict, False

    def _should_block(
        self, provenance: Provenance, score: float, verdict: InjectionVerdict | None
    ) -> bool:
        """Blocking policy, by provenance.

        Uploads fail closed: an externally-authored file that looks like an attack
        has no legitimate reason to proceed. Customer text and our own curated
        knowledge fail open with a log, because a false positive there breaks a
        real user's project or the product's own reference material.
        """
        if provenance is Provenance.UPLOADED_FILE:
            if verdict is not None and verdict.is_injection and verdict.confidence >= 0.6:
                return True
            return score >= 0.6
        return False


def build_guard(
    provider: LLMProvider | None = None, settings: Settings | None = None
) -> InjectionGuard:
    """Construct the guard. The single wiring point."""
    return InjectionGuard(provider, settings)
