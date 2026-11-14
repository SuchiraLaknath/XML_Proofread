"""Tests for proof_read_process/report.py."""

import sys

import pytest

from proof_read_process import RunReport, print_summary
from proof_read_process.report import format_memory, peak_process_memory_mb


def test_steps_are_timed_and_added_up() -> None:
    report = RunReport()
    with report.step("ai"):
        pass
    with report.step("ai"):
        pass
    assert set(report.step_seconds) == {"ai"} and report.step_seconds["ai"] >= 0


def test_finish_records_memory() -> None:
    report = RunReport()
    report.start()
    data = [bytes(1000) for _ in range(1000)]  # about 1 MB of Python objects
    report.finish()
    del data
    assert report.peak_memory_mb > 0.5
    if sys.platform != "win32":
        assert (
            report.peak_process_memory_mb is not None
            and report.peak_process_memory_mb > report.peak_memory_mb
        )


def test_process_memory_is_skipped_where_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "resource", None)  # like Windows: "import resource" fails
    assert peak_process_memory_mb() is None
    assert format_memory(RunReport(peak_memory_mb=6.0)) == "6.0 MB Python objects"


def test_summary_shows_the_key_numbers(capsys: pytest.CaptureFixture[str]) -> None:
    report = RunReport(
        paragraphs_total=3,
        paragraphs_checked=3,
        mistakes_skipped=1,
        peak_memory_mb=6.0,
        peak_process_memory_mb=85.25,
    )
    report.errors_by_type.update(["spelling", "spelling", "styleguide"])
    report.step_seconds["ai"] = 1.5
    print_summary(report)
    out = capsys.readouterr().out
    assert "Errors marked: 3 (spelling 2, styleguide 1)" in out
    assert "Mistakes skipped as unsafe: 1" in out
    assert "ai 1.50s" in out
    assert "Peak memory: 85.2 MB process, 6.0 MB Python objects" in out
