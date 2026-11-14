"""End-to-end tests of proofread_file() with a fake AI (no network, no API key).

FakeProofreader answers from a table: {piece of paragraph text: [Mistake, ...]}.
A paragraph gets the mistakes of the first key that appears in its text.
"""

from pathlib import Path

import pytest
from lxml import etree

from llms import InvokeResult
from proof_read_process import Mistake, RunReport, corrected_path, error_marker, proofread_file

EXAMPLES = Path(__file__).parent.parent / "examples"


class FakeProofreader:
    """Stands in for Proofreader.check_all. Records which texts were sent."""

    def __init__(
        self, answers: dict[str, list[Mistake]] | None = None, failing: tuple[str, ...] = ()
    ) -> None:
        self.answers = answers or {}
        self.failing = failing
        self.checked: list[str] = []

    def check_all(self, texts: list[str], workers: int | None = None) -> dict[str, InvokeResult]:
        self.checked = list(texts)
        return {text: self.result_for(text) for text in texts}

    def result_for(self, text: str) -> InvokeResult:
        if any(key in text for key in self.failing):
            return InvokeResult(error="AI request failed", attempts=1)
        for key, mistakes in self.answers.items():
            if key in text:
                return InvokeResult(value=mistakes, attempts=1, input_tokens=100, output_tokens=10)
        return InvokeResult(value=[], attempts=1, input_tokens=100, output_tokens=5)


def m(original: str, correction: str, error_type: str = "spelling", reason: str = "") -> Mistake:
    return Mistake(original=original, correction=correction, type=error_type, reason=reason)


def run(tmp_path: Path, xml: bytes, checker: FakeProofreader) -> tuple[bytes, RunReport]:
    """Proofread `xml` and return the output bytes and the report."""
    path = tmp_path / "input.xml"
    path.write_bytes(xml)
    report = proofread_file(path, checker, RunReport())
    return corrected_path(path).read_bytes(), report


def without_error_tags(xml: bytes) -> bytes:
    """Remove every <error> tag but keep its text (to compare with the input)."""
    root = etree.fromstring(xml)
    etree.strip_tags(root, "{*}error", "error")
    return etree.tostring(root)


# ---------- examples/example_input.xml -> examples/example_output.xml ----------

EXAMPLE_ANSWERS = {
    "The committe has decided": [
        m("committe", "committee"),
        m("untill", "until"),
        m("wednesday", "Wednesday", "capitalization"),
        m("availble", "available"),
    ],
    "My name is john": [
        m("john", "John", "capitalization"),
        m("new york", "New York", "capitalization"),
    ],
    "The firm reported": [
        m("$2,000,000", "$2 million", "styleguide", "Spell out million, billion, etc."),
        m("January, 2024", "January 2024", "styleguide", "No comma between month and year"),
        m("it's", "its", "punctuation", "Possessive its has no apostrophe"),
        m("publicly-owned", "publicly owned", "styleguide", "Do not hyphenate ly adverbs"),
    ],
}


def test_example_output_matches_exactly(tmp_path: Path) -> None:
    output, report = run(
        tmp_path, (EXAMPLES / "example_input.xml").read_bytes(), FakeProofreader(EXAMPLE_ANSWERS)
    )
    assert output == (EXAMPLES / "example_output.xml").read_bytes()
    assert report.errors_marked == 10
    assert report.paragraphs_with_errors == 3
    assert report.mistakes_skipped == 0


@pytest.mark.parametrize("name", ["example_input.xml", "sample_input.xml"])
def test_no_mistakes_gives_byte_identical_file(tmp_path: Path, name: str) -> None:
    raw = (EXAMPLES / name).read_bytes()
    output, _ = run(tmp_path, raw, FakeProofreader())
    assert output == raw


def test_only_paragraphs_are_sent_never_headings(tmp_path: Path) -> None:
    raw = (EXAMPLES / "sample_input.xml").read_bytes()
    checker = FakeProofreader()
    run(tmp_path, raw, checker)
    assert len(checker.checked) == raw.count(b"<p>")
    assert not any(
        "implementation Guidelines" in text for text in checker.checked
    )  # a heading with a mistake


def test_output_path_is_next_to_input() -> None:
    assert corrected_path(Path("data") / "a.b.xml") == Path("data") / "a.b.corrected.xml"


# ---------- structure is kept ----------


def test_namespaces_and_attributes_are_kept(tmp_path: Path) -> None:
    xml = (
        b'<?xml version="1.0"?>\n'
        b'<doc xmlns="urn:a" xmlns:m="urn:m"><p m:id="1" class="x">I has a cat.</p></doc>\n'
    )
    output, _ = run(tmp_path, xml, FakeProofreader({"I has": [m("has", "have", "grammar")]}))
    assert output == (
        b'<?xml version="1.0"?>\n'
        b'<doc xmlns="urn:a" xmlns:m="urn:m"><p m:id="1" class="x">'
        b'I <error type="grammar" correction="have">has</error> a cat.</p></doc>\n'
    )


def test_cdata_paragraph_is_skipped_and_kept(tmp_path: Path) -> None:
    xml = b"<doc><p>Text <![CDATA[a < b]]> teh end</p><p>Fine teh</p></doc>"
    checker = FakeProofreader({"teh": [m("teh", "the")]})
    output, report = run(tmp_path, xml, checker)
    assert (
        output
        == b'<doc><p>Text <![CDATA[a < b]]> teh end</p><p>Fine <error type="spelling" correction="the">teh</error></p></doc>'
    )
    assert checker.checked == ["Fine teh"]
    assert report.paragraphs_cdata == 1


def test_inline_tags_and_tails(tmp_path: Path) -> None:
    xml = b"<doc><p>Teh <b>quick</b> brwn fox <i>jumpd</i>.</p></doc>"
    answers = {"Teh": [m("Teh", "The"), m("brwn", "brown"), m("jumpd", "jumped")]}
    output, _ = run(tmp_path, xml, FakeProofreader(answers))
    assert output == (
        b'<doc><p><error type="spelling" correction="The">Teh</error> <b>quick</b> '
        b'<error type="spelling" correction="brown">brwn</error> fox '
        b'<i><error type="spelling" correction="jumped">jumpd</error></i>.</p></doc>'
    )


def test_nested_paragraph_text_belongs_to_the_inner_paragraph(tmp_path: Path) -> None:
    xml = b"<doc><p>Outer teh <p>inner teh</p> tail teh</p></doc>"
    checker = FakeProofreader({"teh": [m("teh", "the")] * 2})
    output, _ = run(tmp_path, xml, checker)
    assert checker.checked == ["Outer teh  tail teh", "inner teh"]
    error = b'<error type="spelling" correction="the">teh</error>'
    assert output == b"<doc><p>Outer " + error + b" <p>inner " + error + b"</p> tail " + error + b"</p></doc>"


def test_comment_text_is_not_paragraph_text(tmp_path: Path) -> None:
    xml = b"<doc><p>Teh <!-- teh note --> end</p></doc>"
    checker = FakeProofreader({"Teh": [m("Teh", "The")]})
    output, _ = run(tmp_path, xml, checker)
    assert checker.checked == ["Teh  end"]
    assert (
        output
        == b'<doc><p><error type="spelling" correction="The">Teh</error> <!-- teh note --> end</p></doc>'
    )


def test_special_characters_in_attributes_are_escaped(tmp_path: Path) -> None:
    xml = b"<doc><p>Say hi</p></doc>"
    output, _ = run(
        tmp_path, xml, FakeProofreader({"Say": [m("hi", 'a "hi" & <bye>', "clarity", "Use 'quotes' & more")]})
    )
    error = etree.fromstring(output).find(".//error")
    assert error.get("correction") == 'a "hi" & <bye>'
    assert error.get("reason") == "Use 'quotes' & more"
    assert list(error.attrib) == ["type", "correction", "reason"]


# ---------- unsafe answers are skipped ----------


@pytest.mark.parametrize(
    "mistakes",
    [
        [m("not in text", "x")],  # can't be found
        [m("quick brwn", "quick brown")],  # crosses the </b> tag
        [m("brwn fox", "brown fox"), m("fox", "Fox")],  # second overlaps the first
    ],
)
def test_unsafe_mistakes_are_skipped_and_text_is_unchanged(tmp_path: Path, mistakes: list[Mistake]) -> None:
    xml = b"<doc><p>The <b>quick</b> brwn fox.</p></doc>"
    output, report = run(tmp_path, xml, FakeProofreader({"The": mistakes}))
    assert without_error_tags(output) == etree.tostring(etree.fromstring(xml))
    assert report.mistakes_skipped == 1


def test_repeated_text_is_found_in_order(tmp_path: Path) -> None:
    xml = b"<doc><p>teh cat and teh dog</p></doc>"
    output, _ = run(tmp_path, xml, FakeProofreader({"cat": [m("teh", "the"), m("teh", "the")]}))
    assert output.count(b"<error") == 2


def test_line_breaks_may_differ_from_the_ai(tmp_path: Path) -> None:
    xml = b"<doc><p>I live in new\n    york city.</p></doc>"
    output, _ = run(tmp_path, xml, FakeProofreader({"live": [m("new york", "New York", "capitalization")]}))
    assert b'<error type="capitalization" correction="New York">new\n    york</error>' in output


# ---------- failures leave paragraphs unchanged ----------


def test_failed_ai_request_leaves_paragraph_unchanged(tmp_path: Path) -> None:
    xml = b"<doc><p>Broken teh</p><p>Good teh</p></doc>"
    checker = FakeProofreader({"teh": [m("teh", "the")]}, failing=("Broken",))
    output, report = run(tmp_path, xml, checker)
    assert output.startswith(b"<doc><p>Broken teh</p>")
    assert report.paragraphs_failed == 1 and report.paragraphs_with_errors == 1


def test_safety_check_undoes_a_paragraph_whose_text_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_make_error = error_marker.make_error

    def buggy_make_error(
        parent: etree._Element, tag: str, mistake: Mistake, text: str, tail: str
    ) -> etree._Element:
        return real_make_error(parent, tag, mistake, text.upper(), tail)  # changes the text!

    monkeypatch.setattr(error_marker, "make_error", buggy_make_error)
    xml = b"<doc><p>The <b>quick</b> brwn fox.</p></doc>"
    output, report = run(tmp_path, xml, FakeProofreader({"The": [m("brwn", "brown")]}))
    assert output == xml
    assert report.paragraphs_undone == 1


def test_empty_paragraphs_are_not_sent(tmp_path: Path) -> None:
    xml = b"<doc><p/><p>   </p><p>Same text</p><p>Same text</p></doc>"
    checker = FakeProofreader({"Same": [m("text", "words", "clarity")]})
    output, report = run(tmp_path, xml, checker)
    assert checker.checked == ["Same text"]  # sent once
    assert output.count(b"<error") == 2  # but both paragraphs are marked
    assert report.paragraphs_empty == 2 and report.ai_requests == 1
