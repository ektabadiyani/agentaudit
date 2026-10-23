"""Remove customer personal data from conversations before they leave the machine.

Pattern-based, so it catches structured identifiers (emails, phone and card numbers, IP
addresses) but not names or free-text addresses. Grading only needs what the customer
asked and what the AI said, so these placeholders don't change the verdict.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
CARD_CANDIDATE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PHONE = re.compile(r"(?<![\w+])\+?\(?\d[\d\s().-]{7,}\d(?!\w)")
IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


@dataclass
class Redactor:
    """Replace personal data with typed placeholders like [EMAIL]. `extra` adds
    company-specific patterns, e.g. {"ACCOUNT_ID": r"\\bACC-\\d{6}\\b"}."""

    extra: dict[str, str] = field(default_factory=dict)
    counts: Counter = field(default_factory=Counter)

    def __post_init__(self):
        self._extra = [(name.upper(), re.compile(pattern)) for name, pattern in self.extra.items()]

    def _sub(self, pattern: re.Pattern, label: str, text: str, check=None) -> str:
        def replace(match: re.Match) -> str:
            if check and not check(match.group()):
                return match.group()
            self.counts[label] += 1
            return f"[{label}]"
        return pattern.sub(replace, text)

    def redact(self, text: str) -> str:
        if not text:
            return text
        for label, pattern in self._extra:
            text = self._sub(pattern, label, text)
        text = self._sub(EMAIL, "EMAIL", text)
        text = self._sub(CARD_CANDIDATE, "CARD", text, lambda s: luhn_valid(re.sub(r"\D", "", s)))
        text = self._sub(SSN, "SSN", text)
        text = self._sub(IPV4, "IP", text)
        # Ten or more digits reads as a phone number; shorter runs are usually amounts, dates or ids.
        text = self._sub(PHONE, "PHONE", text, lambda s: len(re.sub(r"\D", "", s)) >= 10)
        return text
