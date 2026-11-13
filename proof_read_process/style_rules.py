"""House style rules that a simple text search can find.

The rules come from the house style guide (examples/Style_Guide.docx). They are
used in two ways:

1. Hints (find_hints): before a paragraph is sent, we search it for likely
   breaks of these rules and add them to the user prompt as hints. The AI still
   decides, because some rules depend on meaning ("a third party" is right,
   "a third party audit" is not). Hints help the AI not to miss a rule in a
   long style guide.

2. Conflict checks (find_conflict, drop_conflicts): after the AI answers, we
   drop a mistake that clearly goes against the style guide:
   - its correction brings in a form the guide rejects ("healthcare" ->
     "health care"), or
   - its reason cites a rule that a text search can check (for example "no
     comma between month and year"), but the text it marks doesn't break that
     rule ("In March 2023, ..." has no comma between month and year).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # imported only for type hints: ai_proofreader imports this module
    from .ai_proofreader import Mistake

logger = logging.getLogger(__name__)

MONTHS = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan\.|Feb\.|Mar\.|Apr\.|Aug\.|Sept?\.|Oct\.|Nov\.|Dec\.)"
)

# "non" words are one word with no hyphen (nonprofit), except these.
NON_WORD_EXCEPTIONS = ("bankruptcy", "debtor", "dischargeability", "lawyer", "priority", "purchase")


@dataclass(frozen=True)
class PatternRule:
    """A style rule that a regular expression can find in the text.

    reason_pattern finds an AI reason that cites this rule. It is None when code
    can't judge the rule (the hyphen in "third party" depends on its use), so the
    rule is only used as a hint.
    """

    name: str
    pattern: re.Pattern[str]
    reason_pattern: re.Pattern[str] | None = None


def rule(name: str, pattern: str, reason_pattern: str | None = None) -> PatternRule:
    """Build a PatternRule; both patterns ignore case."""
    reason = re.compile(reason_pattern, re.IGNORECASE) if reason_pattern else None
    return PatternRule(name, re.compile(pattern, re.IGNORECASE), reason)


PATTERN_RULES = (
    rule("No comma between month and year", rf"\b{MONTHS},\s+\d{{4}}\b", r"month.*year"),
    rule("No apostrophe in plural years (1930s)", r"\b\d{2,4}['’]s\b", r"apostrophe.*year"),
    rule(  # finds 6:00 AM, 6:00am, 6:00 A.M. and 6:00a.m., but not 6:00 a.m. ((?-i:...) = match case)
        'Use lowercase "a.m."/"p.m." with a space after the time (6:00 a.m.)',
        r"\b\d{1,2}(?::\d{2})?(?:\s?[ap]m\b|\s?(?-i:[AP]\.M\.)|(?-i:[ap]\.m\.))",
        r"a\.m\.|p\.m\.",
    ),
    rule("Spell out million, billion, etc. ($3 million)", r"\$\s?\d{1,3}(?:,\d{3}){2,}(?!\d)", r"million"),
    rule(
        "Close up space between currency symbol and amount (US$3,000)",
        r"\b(?:US|USD)\s+\$|\$\s+\d",
        r"currency",
    ),
    rule('Do not hyphenate "ly" adverbs (publicly owned)', r"\b[a-z]+ly-[a-z]+", r"\bly\b|adverb"),
    rule(
        "Non words are one word with no hyphen (nonprofit)",
        r"\bnon[- ](?!(?:" + "|".join(NON_WORD_EXCEPTIONS) + r")\b)[a-z]+",
    ),
    rule(
        "Hyphenate before a noun (a third-party audit, common-law principles), "
        "not as a noun (a third party, the common law)",
        r"\bthird[- ]part(?:y|ies)\b|\bcommon[- ]law\b",
    ),
)

# Forms the style guide rejects -> the form it prefers.
PREFERRED_WORDS = {
    "judgement": "judgment",
    "acknowledgement": "acknowledgment",
    "HIPPA": "HIPAA",
    "health care": "healthcare",
    "web site": "website",
    "time-frame": "time frame",
    "timeframe": "time frame",
    "pre-existing": "preexisting",
    "pre-condition": "precondition",
    "pre-filing": "prefiling",
    "pre-trial": "pretrial",
    "pre petition": "pre-petition",
    "post petition": "post-petition",
    "post filing": "post-filing",
    "set-off": "setoff",
    "carve-out": "carveout",
    "look-back": "lookback",
    "roll-over": "rollover",
    "roll-up": "rollup",
    "super priority": "superpriority",
    "super-priority": "superpriority",
    "anti-fraud": "antifraud",
    "by-laws": "bylaws",
    "record-keeping": "recordkeeping",
    "cyber security": "cybersecurity",
    "cyber-security": "cybersecurity",
    "e-mail": "email",
    "on-line": "online",
    "sub-section": "subsection",
    "towards": "toward",
    "attorney client": "attorney-client",
    "broker dealer": "broker-dealer",
    "cross border": "cross-border",
    "publicly-owned": "publicly owned",
    "publicly-held": "publicly held",
    "wholly-owned": "wholly owned",
    "workers compensation": "workers’ compensation",
    "vs.": "versus",
}


def word_pattern(word: str) -> re.Pattern[str]:
    """Find a word or phrase (and its plural), but not inside a longer word."""
    return re.compile(rf"(?<![\w-]){re.escape(word)}s?(?![\w-])", re.IGNORECASE)


REJECTED_WORDS = {word: word_pattern(word) for word in PREFERRED_WORDS}


def find_hints(text: str) -> list[str]:
    """Likely style guide problems in a paragraph, in text order, each listed once.

    When two rules find the same spot ("publicly-owned"), only the first hint is kept.
    """
    hints_by_start: dict[int, str] = {}
    for style_rule in PATTERN_RULES:
        for match in style_rule.pattern.finditer(text):
            hints_by_start.setdefault(match.start(), f'"{match.group()}": {style_rule.name}')
    for word, pattern in REJECTED_WORDS.items():
        for match in pattern.finditer(text):
            hint = f'"{match.group()}": the style guide uses "{PREFERRED_WORDS[word]}"'
            hints_by_start.setdefault(match.start(), hint)
    in_text_order = [hints_by_start[start] for start in sorted(hints_by_start)]
    return list(dict.fromkeys(in_text_order))


def find_conflict(mistake: Mistake, text: str) -> str | None:
    """Why a mistake goes against the style guide, or None when it doesn't."""
    for word, pattern in REJECTED_WORDS.items():
        if pattern.search(mistake.correction) and not pattern.search(mistake.original):
            return f'the correction uses "{word}", but the style guide uses "{PREFERRED_WORDS[word]}"'
    if mistake.type != "styleguide":
        return None
    for style_rule in PATTERN_RULES:
        cites_rule = style_rule.reason_pattern and style_rule.reason_pattern.search(mistake.reason)
        if cites_rule and not rule_found_at(style_rule, mistake.original, text):
            return f'it cites "{style_rule.name}", but the marked text does not break that rule'
    return None


def rule_found_at(style_rule: PatternRule, original: str, text: str) -> bool:
    """True if the rule's pattern matches text that overlaps an occurrence of original."""
    starts = [match.start() for match in re.finditer(re.escape(original), text)]
    for match in style_rule.pattern.finditer(text):
        if any(start < match.end() and match.start() < start + len(original) for start in starts):
            return True
    # original not found as-is (the marker may still find it): judge the marked text alone.
    return not starts and style_rule.pattern.search(original) is not None


def drop_conflicts(mistakes: list[Mistake], text: str) -> tuple[list[Mistake], list[Mistake]]:
    """Split the AI's mistakes into (kept, dropped). Each dropped one is logged."""
    kept: list[Mistake] = []
    dropped: list[Mistake] = []
    for mistake in mistakes:
        conflict = find_conflict(mistake, text)
        if conflict is None:
            kept.append(mistake)
        else:
            original, correction = mistake.original, mistake.correction
            logger.warning("Dropped the AI's mistake %r -> %r: %s", original, correction, conflict)
            dropped.append(mistake)
    return kept, dropped
