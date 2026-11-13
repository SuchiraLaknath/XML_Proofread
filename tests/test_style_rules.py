"""Tests for proof_read_process/style_rules.py: style hints and conflict checks."""

import pytest

from proof_read_process import Mistake
from proof_read_process.style_rules import drop_conflicts, find_conflict, find_hints


def m(original: str, correction: str, error_type: str = "styleguide", reason: str = "") -> Mistake:
    return Mistake(original=original, correction=correction, type=error_type, reason=reason)


# ---------- find_hints ----------


@pytest.mark.parametrize(
    "text, found",
    [
        ("It began in January, 2020, as planned.", "January, 2020"),
        ("Filed Jan., 2022 in court.", "Jan., 2022"),
        ("Claims rose in the 1930's.", "1930's"),
        ("We meet at 3:30PM today.", "3:30PM"),
        ("We meet at 6:00 AM today.", "6:00 AM"),
        ("We meet at 6:00 A.M. today.", "6:00 A.M."),
        ("We meet at 6:00a.m. today.", "6:00a.m."),
        ("It cost $3,000,000 in all.", "$3,000,000"),
        ("They spent US $4.5 million.", "US $"),
        ("Some publicly-owned firms.", "publicly-owned"),
        ("The non-compliance costs.", "non-compliance"),
        ("A non profit group.", "non profit"),
        ("Under common law principles.", "common law"),
        ("A third party vendor.", "third party"),
        ("The judgement of the court.", "judgement"),
        ("Under HIPPA rules.", "HIPPA"),
        ("Companies running web sites.", "web sites"),
        ("Workers compensation claims.", "Workers compensation"),
    ],
)
def test_hint_for_each_rule(text: str, found: str) -> None:
    hints = find_hints(text)
    assert any(hint.startswith(f'"{found}"') for hint in hints), hints


@pytest.mark.parametrize(
    "text",
    [
        "It began in January 2020, as planned.",
        "In March 2023, the firm grew.",  # the comma comes after the year
        "Claims rose in the 1930s.",
        "We meet at 6:00 a.m. today.",
        "It cost $3 million or US$3,000.",
        "Some publicly owned firms.",
        "The nonprofit group and a non-debtor party.",  # non-debtor is an exception
        "All healthcare providers use the website.",
        "The judgment of the court.",
    ],
)
def test_no_hint_when_the_text_follows_the_guide(text: str) -> None:
    assert find_hints(text) == []


def test_hints_are_in_text_order_and_listed_once() -> None:
    hints = find_hints("The judgement and the publicly-owned firm, and another judgement.")
    assert hints == [
        '"judgement": the style guide uses "judgment"',
        '"publicly-owned": Do not hyphenate "ly" adverbs (publicly owned)',
    ]


def test_hints_do_not_match_inside_longer_words() -> None:
    assert find_hints("The towardsness of e-mailing.") == []


# ---------- find_conflict / drop_conflicts ----------


def test_correction_with_a_rejected_form_is_a_conflict() -> None:
    conflict = find_conflict(m("healthcare", "health care"), "All healthcare providers.")
    assert conflict is not None and "healthcare" in conflict


def test_rejected_form_already_in_the_original_is_not_a_conflict() -> None:
    """The AI fixed something else nearby; it did not bring in "health care"."""
    mistake = m("health care provider's", "health care providers", "grammar")
    assert find_conflict(mistake, "The health care provider's are busy.") is None


def test_cited_rule_that_the_text_does_not_break_is_a_conflict() -> None:
    text = "In March 2023, approximately 1,200 companies reported."
    mistake = m("March 2023,", "March 2023", reason="No comma between month and year")
    assert find_conflict(mistake, text) is not None


@pytest.mark.parametrize(
    "mistake, text",
    [  # the styleguide fixes of examples/example_output.xml
        (
            m("$2,000,000", "$2 million", reason="Spell out million, billion, etc."),
            "approximately $2,000,000 in revenue",
        ),
        (
            m("January, 2024", "January 2024", reason="No comma between month and year"),
            "for January, 2024, and",
        ),
        (
            m("publicly-owned", "publicly owned", reason="Do not hyphenate ly adverbs"),
            "its publicly-owned firms",
        ),
        (m("PM", "p.m.", reason="Use lowercase a.m./p.m."), "at 3:30PM to"),  # short original, rule around it
        (m("iz", "is", "spelling", "No comma between month and year"), "it iz"),  # only styleguide is checked
    ],
)
def test_real_fixes_are_kept(mistake: Mistake, text: str) -> None:
    assert find_conflict(mistake, text) is None


def test_drop_conflicts_splits_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    good = m("judgement", "judgment", reason="Preferred spelling")
    bad = m("healthcare", "health care", reason="Preferred spelling")
    kept, dropped = drop_conflicts([good, bad], "The judgement of healthcare firms.")
    assert kept == [good]
    assert dropped == [bad]
    assert "health care" in caplog.text
