"""Character folding, shared by the injection guard and the quote verifier.

Extracted from :mod:`app.security.guard` rather than copied, and the reason is
narrow but important: the guard folds text *before* the model sees it, and the
quote verifier later checks that a figure's quoted span really occurs in that
same text. If the two ever folded differently, a perfectly honest span would
stop matching and a real price would be silently discarded - or worse, a span
that should not match would.

The guard cannot simply be imported here. ``app.security.guard`` reaches into
``app.llm`` for its classifier, and :mod:`app.services.quote_verification` is
deliberately pure: it decides whether a number is allowed to exist, so it must
not be able to call a model even by accident. One dependency-free module, used
by both, is the only arrangement where "the same folding" is a fact rather than
a hope.

Truncation deliberately stays in the guard. Cutting text to a screening limit is
a policy about how much to inspect; folding is about what characters mean.
"""

from __future__ import annotations

import re
import unicodedata

# Homoglyphs that survive NFKC. Cyrillic and Greek lookalikes are the cheap way
# to write "ignore" so that a Latin pattern list never sees it.
CONFUSABLES = str.maketrans(
    {
        "α": "a",
        "ι": "i",
        "ν": "v",
        "ο": "o",
        "ρ": "p",
        "τ": "t",
        "А": "A",
        "Е": "E",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "У": "Y",
        "Х": "X",
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
        "ѕ": "s",
        "і": "i",
        "ԁ": "d",
        "ո": "n",
        "ⅼ": "l",
    }
)

INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤﻿­]")

_HORIZONTAL_SPACE = re.compile(r"[ \t]+")
_BLANK_RUN = re.compile(r"\n{3,}")


def fold(text: str) -> str:
    """Strip obfuscation without changing meaning.

    Order matters: compatibility-fold first so full-width and styled characters
    become plain, then remove invisibles, then fold homoglyphs. Whitespace runs
    collapse but line structure survives, because prompts and pasted business
    letters both rely on paragraphs.
    """
    folded = unicodedata.normalize("NFKC", text)
    folded = INVISIBLE.sub("", folded)
    folded = folded.translate(CONFUSABLES)
    folded = _HORIZONTAL_SPACE.sub(" ", folded)
    folded = _BLANK_RUN.sub("\n\n", folded)
    return folded.strip()
