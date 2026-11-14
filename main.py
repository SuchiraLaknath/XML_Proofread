"""Command line: proofread the <p> elements of an XML file with a GenAI model.

    uv run python main.py examples/sample_input.xml --lang en --style-guide examples/Style_Guide.docx

Writes <input-name>.corrected.xml next to the input, with each mistake wrapped
in an <error> tag, and prints a summary. Exit code 0 on success, 1 on error.

This file only handles the command line. The proofreading itself is in
proof_read_process/ and the AI clients are in llms/.
"""

import argparse
import logging
import sys
from pathlib import Path

from llms import DEFAULT_PROVIDER, PROVIDERS, FatalAIError, create_llm
from proof_read_process import (
    LanguageError,
    Locale,
    Proofreader,
    RunReport,
    StyleGuideError,
    XmlReadError,
    build_system_prompt,
    load_proofread_prompts,
    load_style_guide,
    parse_language,
    print_summary,
    proofread_file,
)
from utils.logging_setup import setup_logging

logger = logging.getLogger("main")

# Errors that stop the run with a one-line message instead of a traceback.
EXPECTED_ERRORS = (XmlReadError, StyleGuideError, LanguageError, FatalAIError)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read the command line.

    Args:
        argv: the arguments to read; None means the real command line (sys.argv).

    Returns:
        The options: input, lang, style_guide, provider, model, workers and verbose.
    """
    parser = argparse.ArgumentParser(description="Mark mistakes in the <p> elements of an XML file.")
    parser.add_argument("input", type=Path, help="the XML file to proofread")
    parser.add_argument("--lang", required=True, help="BCP-47 language tag, for example en, en-US or fr")
    parser.add_argument("--style-guide", required=True, type=Path, help="house style guide (.docx)")
    parser.add_argument(
        "--provider",
        choices=list(PROVIDERS),  # the provider names, e.g. "openai", "anthropic"
        default=DEFAULT_PROVIDER,
        help=f"AI provider (default: {DEFAULT_PROVIDER})",
    )
    parser.add_argument(
        "--model", help="model name (default: OPENAI_MODEL / ANTHROPIC_MODEL from .env, else built-in)"
    )
    parser.add_argument(
        "--workers", type=int, help="requests sent at the same time (default: LLM_WORKERS from .env, or 8)"
    )
    parser.add_argument("--verbose", action="store_true", help="show debug messages")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> RunReport:
    """Check the inputs, build the proofreader and proofread the file.

    Args:
        args: the options from parse_args().

    Returns:
        The report with the numbers for the summary.

    Raises:
        LanguageError, XmlReadError, StyleGuideError or FatalAIError: the run can't go on.
    """
    # Check the cheap things first, so mistakes in the command are reported at once.
    locale = parse_language(args.lang)
    if not args.input.is_file():
        raise XmlReadError(f"Input file not found: {args.input}")

    # Start the clock and memory tracking, then do the real work.
    report = RunReport()
    report.start()
    proofreader = build_proofreader(args, locale, report)
    proofread_file(args.input, proofreader, report, workers=args.workers)
    report.finish()
    return report


def build_proofreader(args: argparse.Namespace, locale: Locale, report: RunReport) -> Proofreader:
    """Load the style guide, build the system prompt and create the AI client.

    Args:
        args: the options from parse_args() (style guide path, provider and model).
        locale: the checked --lang value.
        report: the run's report; the time to load the style guide is added to it.

    Returns:
        A Proofreader that is ready to check paragraphs.
    """
    # The style guide is read once and goes, complete, into the system prompt.
    with report.step("style guide"):
        style_guide = load_style_guide(args.style_guide)
    prompts = load_proofread_prompts()
    system_prompt = build_system_prompt(prompts, locale.name, locale.tag, style_guide)
    # Fails here (FatalAIError) if the API key is missing, before any paragraph is read.
    llm = create_llm(args.provider, args.model)
    logger.info("Proofreading %s in %s with %s (%s)", args.input, locale.name, llm.provider, llm.model)
    return Proofreader(llm, prompts, system_prompt)


def main(argv: list[str] | None = None) -> int:
    """Run the program and return the exit code.

    Args:
        argv: the arguments to use; None means the real command line.

    Returns:
        0 on success, 1 when the run stopped with an error.
    """
    args = parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    try:
        report = run(args)
    except EXPECTED_ERRORS as error:
        # Known problems (bad --lang, missing file, bad API key): one clear line, no traceback.
        logger.error("%s", error)
        return 1
    print_summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
