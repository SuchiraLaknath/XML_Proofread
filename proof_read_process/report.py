"""Collect numbers about a run and print the final summary.

RunReport records the time of each step, peak memory, AI requests and tokens,
and what happened to every paragraph and mistake. print_summary() is the only
place in the program that uses print(); everything else uses logging.

Two memory numbers are reported:
- process: the most memory the whole program used (peak RSS), as the operating
  system sees it. Not available on Windows, where only the next one is shown.
- Python objects: the most memory Python itself allocated during the run (tracemalloc).
"""

import sys
import time
import tracemalloc
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from llms import InvokeResult


@dataclass
class RunReport:
    """Numbers about one proofreading run."""

    input_path: Path | None = None
    output_path: Path | None = None
    step_seconds: dict[str, float] = field(default_factory=dict)
    total_seconds: float = 0.0
    peak_memory_mb: float = 0.0  # Python objects (tracemalloc)
    peak_process_memory_mb: float | None = None  # whole process; None where it can't be read

    paragraphs_total: int = 0
    paragraphs_checked: int = 0  # the AI answered and the marks were kept
    paragraphs_with_errors: int = 0
    paragraphs_empty: int = 0
    paragraphs_cdata: int = 0  # skipped: editing would destroy the CDATA section
    paragraphs_failed: int = 0  # skipped: the AI request failed
    paragraphs_undone: int = 0  # the safety check undid the marks

    errors_by_type: Counter[str] = field(default_factory=Counter)
    mistakes_skipped: int = 0  # found by the AI but unsafe to mark

    ai_requests: int = 0  # unique paragraph texts sent
    ai_attempts: int = 0  # including re-asks after unusable answers
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0

    # Internal bookkeeping for start()/finish(); not part of the report itself.
    _started_at: float = field(default=0.0, init=False, repr=False)
    _tracking_memory: bool = field(default=False, init=False, repr=False)

    def start(self) -> None:
        """Start the total timer and memory tracking."""
        self._started_at = time.perf_counter()
        if not tracemalloc.is_tracing():
            tracemalloc.start()
            self._tracking_memory = True

    def finish(self) -> None:
        """Stop the total timer and record peak memory."""
        self.total_seconds = time.perf_counter() - self._started_at
        # Peak memory of Python objects since start().
        if tracemalloc.is_tracing():
            self.peak_memory_mb = tracemalloc.get_traced_memory()[1] / 1_000_000
        if self._tracking_memory:
            tracemalloc.stop()
            self._tracking_memory = False
        # Peak memory of the whole process, as the operating system sees it.
        self.peak_process_memory_mb = peak_process_memory_mb()

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        """Time a step: `with report.step("save"): ...`

        Args:
            name: the step's name in the summary, e.g. "read".

        Yields:
            Nothing; the time is added when the `with` block ends, even after an error.
        """
        started = time.perf_counter()
        try:
            yield  # the code inside the `with` block runs here
        finally:  # add the time even if the step failed
            self.step_seconds[name] = self.step_seconds.get(name, 0.0) + time.perf_counter() - started

    def add_ai_results(self, results: Iterable[InvokeResult]) -> None:
        """Add the request, attempt and token counts of the AI results.

        Args:
            results: one result for each request sent.
        """
        for result in results:
            self.ai_requests += 1
            self.ai_attempts += result.attempts
            self.input_tokens += result.input_tokens
            self.cached_input_tokens += result.cached_input_tokens
            self.output_tokens += result.output_tokens

    @property
    def errors_marked(self) -> int:
        """Total number of <error> tags written."""
        return sum(self.errors_by_type.values())


def peak_process_memory_mb() -> float | None:
    """Peak memory of the whole process.

    Returns:
        The peak in MB, or None where it can't be read (Windows).
    """
    try:
        import resource  # Unix only
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports kilobytes.
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    return peak_bytes / 1_000_000


def format_memory(report: RunReport) -> str:
    """Describe the peak memory for the summary.

    Args:
        report: the finished report.

    Returns:
        Text like "85.3 MB process, 6.1 MB Python objects" (the process part is left out where unknown).
    """
    python_part = f"{report.peak_memory_mb:.1f} MB Python objects"
    if report.peak_process_memory_mb is None:
        return python_part
    return f"{report.peak_process_memory_mb:.1f} MB process, {python_part}"


def print_summary(report: RunReport) -> None:
    """Print the summary of a run.

    Args:
        report: the finished report.
    """
    print(f"Proofread: {report.input_path}")
    print(f"Output:    {report.output_path}")
    print()
    print(
        f"Paragraphs: {report.paragraphs_total} total, {report.paragraphs_checked} checked, "
        f"{report.paragraphs_with_errors} with errors"
    )
    print(
        f"  left unchanged: {report.paragraphs_empty} empty, {report.paragraphs_cdata} with CDATA, "
        f"{report.paragraphs_failed} failed AI requests, "
        f"{report.paragraphs_undone} undone by the safety check"
    )
    by_type = ", ".join(f"{name} {count}" for name, count in sorted(report.errors_by_type.items()))
    print(f"Errors marked: {report.errors_marked}" + (f" ({by_type})" if by_type else ""))
    print(f"Mistakes skipped as unsafe: {report.mistakes_skipped}")
    print(
        f"AI: {report.ai_requests} requests, {report.ai_attempts} attempts; tokens: "
        f"{report.input_tokens:,} in ({report.cached_input_tokens:,} cached), {report.output_tokens:,} out"
    )
    steps = ", ".join(f"{name} {seconds:.2f}s" for name, seconds in report.step_seconds.items())
    print(f"Time: {steps}; total {report.total_seconds:.2f}s")
    print(f"Peak memory: {format_memory(report)}")
