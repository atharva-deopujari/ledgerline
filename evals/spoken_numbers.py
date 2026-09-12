"""Reading amounts the way people say them.

Text to speech and transcription both hand us amounts in whatever form the person used: digits,
shorthand like "12k", or words. Every check that reasons about numbers reads them through here,
so there is one answer to "what figures does this sentence contain".
"""

from __future__ import annotations

import re

DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")

# An ISO date is one token, not three numbers; the per-turn block puts today and the window end
# in front of the model and it sometimes reads one back.
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# "12k", "1.5 lakh", "2 crore" — how people say amounts out loud and how STT writes them down.
SHORTHAND = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k|lakhs?|crores?|cr)\b", re.IGNORECASE)
MULTIPLIER = {
    "k": 1_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "cr": 10_000_000,
}

UNITS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
SCALES = {
    "hundred": 100,
    "thousand": 1_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "million": 1_000_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
}

# Amounts this small are days of the month or counts, not money; ignore them when tracing.


def _words_to_numbers(text: str) -> set[int]:
    """Every number spelled out in words. 'forty five thousand and two hundred' -> {45200}.

    ponytail: one left-to-right pass, good enough for spoken amounts; it does not try to parse
    ordinals, fractions or "a hundred and ten percent".
    """
    found: set[int] = set()
    current = total = last_scale = 0
    seen = False

    def close() -> None:
        nonlocal current, total, last_scale, seen
        if seen:
            found.add(total + current)
        current = total = last_scale = 0
        seen = False

    for word in re.findall(r"[a-z]+|[.,;:!?\n]", text.lower()):
        if not word.isalpha():
            # A clause boundary ends an amount. Without this the pass ran through the full stop
            # in "Day thirty. Thirty-eight thousand rupees." and reported 68,000 — a figure
            # nobody said, in place of the 38,000 they did. Splitting here is the safe direction:
            # the worst case is reading "forty-five thousand, two hundred" as two figures rather
            # than inventing a sum.
            close()
            continue
        if word in UNITS:
            current += UNITS[word]
            seen = True
        elif word in SCALES:
            scale = SCALES[word]
            # A scale at or above the one already used starts a new amount: "forty-five thousand
            # and twelve thousand" is two figures, and folding them into 57,000 would hand the
            # assistant a sum nobody said. A smaller scale continues this one: "one thousand and
            # two hundred" is 1,200.
            if last_scale and scale >= last_scale:
                if total:
                    found.add(total)
                total = 0
            if scale >= 1000:
                total += max(current, 1) * scale
                current = 0
            else:
                current = max(current, 1) * scale
            last_scale = scale
            seen = True
        elif word == "and" and seen:
            continue
        elif seen:
            close()
    close()
    return found


def numbers_in(text: str) -> set[int]:
    """Every number in the text, written as digits or spelled out in words."""
    text = ISO_DATE.sub(" ", text)
    found = {int(float(m.replace(",", ""))) for m in DIGITS.findall(text)}
    for digits, suffix in SHORTHAND.findall(text):
        found.add(int(float(digits.replace(",", "")) * MULTIPLIER[suffix.lower()]))
    return found | _words_to_numbers(text)


# Amounts this small are days of the month or counts, not money; ignore them when tracing.
TRACE_FLOOR = 100
