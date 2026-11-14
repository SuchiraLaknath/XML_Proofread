"""The main proofreading flow for one XML file.

    1. Load the XML.
    2. Read ALL paragraphs first, before anything is changed.
    3. Send each unique, non-empty text to the AI once, in parallel.
       Paragraphs with CDATA are not sent.
    4. For each paragraph: mark_errors(), then verify_or_undo().
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
from .xml_reader import Paragraph, find_paragraphs, load_xml, save_xml

logger = logging.getLogger(__name__)


def proofread_file(
    input_path: str | Path, checker: Checker, report: RunReport, workers: int | None = None
) -> RunReport:
    """Proofread the <p> elements of one XML file and save the marked copy.

    Args:
        input_path: the XML file to proofread.
        checker: sends the paragraph texts to the AI (a Proofreader, or a fake in tests).
        report: collects the numbers for the summary.
        workers: requests sent at the same time; None means the default.

    Returns:
        The same report, filled in. The marked copy is saved as <input-name>.corrected.xml.

    Raises:
        XmlReadError: the file can't be read or parsed.
        XmlWriteError: the marked copy can't be saved.
        FatalAIError: every AI request would fail (bad API key, unknown model).
    """
    input_path = Path(input_path)
    report.input_path = input_path

    # 1. Read every paragraph first, so all texts are taken from the untouched file.
    #    Each Paragraph points to a real <p> element inside xml_file.tree (no copy is made).
    with report.step("read"):
        xml_file = load_xml(input_path)
        paragraphs = find_paragraphs(xml_file)
    report.paragraphs_total = len(paragraphs)

    # 2. Ask the AI about all paragraph texts at once (in parallel).
    with report.step("ai"):
        results = checker.check_all(texts_to_check(paragraphs), workers=workers)
    report.add_ai_results(results.values())

    # 3. Mark the mistakes in each paragraph, one paragraph at a time.
    #    The <error> tags are inserted straight into xml_file.tree, through those <p> elements.
    with report.step("mark"):
        for paragraph in paragraphs:
            process_paragraph(paragraph, results, report)

    # 4. Save the marked copy next to the input. xml_file.tree already holds every change
    #    from step 3, so saving it writes the tagged paragraphs; nothing else is passed in.
    report.output_path = corrected_path(input_path)
    with report.step("save"):
        save_xml(xml_file, report.output_path)
    return report


def texts_to_check(paragraphs: list[Paragraph]) -> list[str]:
    """Choose the paragraph texts to send to the AI.

    Args:
        paragraphs: all paragraphs of the file.

    Returns:
        Unique, non-empty texts in document order, without paragraphs that contain CDATA.
    """
    texts = [p.text for p in paragraphs if p.text.strip() and not p.has_cdata]
    # A text that appears in several <p> is sent to the AI once. This list is only for the
    # requests: the XML is not changed, and every <p> still gets its own tags.
    return list(dict.fromkeys(texts))


def process_paragraph(paragraph: Paragraph, results: dict[str, CheckResult], report: RunReport) -> None:
    """Mark one paragraph's mistakes, or leave it unchanged and count why.

    Args:
        paragraph: the paragraph, as read before any change.
        results: the AI's results, {text: result}.
        report: the counts for the summary are added here.
    """
    # Paragraphs that were never sent to the AI.
    if not paragraph.text.strip():
        report.paragraphs_empty += 1
        return
    if paragraph.has_cdata:
        logger.warning("Skipped the paragraph on line %s: it contains CDATA", paragraph.element.sourceline)
        report.paragraphs_cdata += 1
        return
    # The AI request failed (after its retries): leave the paragraph as it is.
    result = results.get(paragraph.text)
    if result is None or not result.ok or result.value is None:
        line = paragraph.element.sourceline
        logger.warning("Left the paragraph on line %s unchanged: the AI check failed", line)
        report.paragraphs_failed += 1
        return

    # Wrap the mistakes in <error> tags, then make sure the text did not change.
    mark = mark_errors(paragraph, result.value)
    report.mistakes_skipped += len(mark.skipped)
    if not verify_or_undo(paragraph, mark):
        report.paragraphs_undone += 1
        return

    # The marks are kept: count them for the summary.
    report.paragraphs_checked += 1
    if mark.marked:
        report.paragraphs_with_errors += 1
        report.errors_by_type.update(mistake.type for mistake in mark.marked)


def corrected_path(input_path: Path) -> Path:
    """Name the output file: sample.xml -> sample.corrected.xml, in the same folder.

    Args:
        input_path: the input XML file.

    Returns:
        The path of the output file.
    """
    return input_path.with_suffix(".corrected.xml")
