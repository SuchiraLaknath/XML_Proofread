"""The main proofreading flow for one XML file.

    1. Load the XML.
    2. Read ALL paragraphs first, before anything is changed.
    3. Send each unique, non-empty text to the AI once, in parallel.
       Paragraphs with CDATA are not sent.
    4. For each paragraph: drop_conflicts() (mistakes that go against the style
       guide), mark_errors(), then verify_or_undo().
    5. Save <input-name>.corrected.xml next to the input, and return the report.

One bad paragraph never stops the run: it is left unchanged and counted in
the report. Only a FatalAIError (bad API key, unknown model) stops everything.
"""

import logging
from pathlib import Path

from .ai_proofreader import Checker, CheckResult
from .error_marker import mark_errors
from .report import RunReport
from .safety_check import verify_or_undo
from .style_rules import drop_conflicts
from .xml_reader import Paragraph, find_paragraphs, load_xml, save_xml

logger = logging.getLogger(__name__)


def proofread_file(
    input_path: str | Path, checker: Checker, report: RunReport, workers: int | None = None
) -> RunReport:
    """Proofread the <p> elements of one XML file and save the marked copy."""
    input_path = Path(input_path)
    report.input_path = input_path

    with report.step("read"):
        xml_file = load_xml(input_path)
        paragraphs = find_paragraphs(xml_file)
    report.paragraphs_total = len(paragraphs)

    with report.step("ai"):
        results = checker.check_all(texts_to_check(paragraphs), workers=workers)
    report.add_ai_results(results.values())

    with report.step("mark"):
        for paragraph in paragraphs:
            process_paragraph(paragraph, results, report)

    report.output_path = corrected_path(input_path)
    with report.step("save"):
        save_xml(xml_file, report.output_path)
    return report


def texts_to_check(paragraphs: list[Paragraph]) -> list[str]:
    """Unique, non-empty paragraph texts in document order, without CDATA paragraphs."""
    texts = [p.text for p in paragraphs if p.text.strip() and not p.has_cdata]
    return list(dict.fromkeys(texts))


def process_paragraph(paragraph: Paragraph, results: dict[str, CheckResult], report: RunReport) -> None:
    """Mark one paragraph's mistakes, or leave it unchanged and count why."""
    if not paragraph.text.strip():
        report.paragraphs_empty += 1
        return
    if paragraph.has_cdata:
        logger.warning("Skipped the paragraph on line %s: it contains CDATA", paragraph.element.sourceline)
        report.paragraphs_cdata += 1
        return
    result = results.get(paragraph.text)
    if result is None or not result.ok or result.value is None:
        line = paragraph.element.sourceline
        logger.warning("Left the paragraph on line %s unchanged: the AI check failed", line)
        report.paragraphs_failed += 1
        return

    mistakes, against_style_guide = drop_conflicts(result.value, paragraph.text)
    report.mistakes_rejected += len(against_style_guide)
    mark = mark_errors(paragraph, mistakes)
    report.mistakes_skipped += len(mark.skipped)
    if not verify_or_undo(paragraph, mark):
        report.paragraphs_undone += 1
        return
    report.paragraphs_checked += 1
    if mark.marked:
        report.paragraphs_with_errors += 1
        report.errors_by_type.update(mistake.type for mistake in mark.marked)


def corrected_path(input_path: Path) -> Path:
    """sample.xml -> sample.corrected.xml, in the same folder."""
    return input_path.with_suffix(".corrected.xml")
