"""Tests for utils/environmental_variables.py."""

import pytest

from utils.environmental_variables import get_int_variable, get_text_variable, get_variable

KEY = "UTILS_TEST_SETTING"


@pytest.fixture(autouse=True)
def unset_test_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with the key unset (monkeypatch restores it afterwards)."""
    monkeypatch.setenv(KEY, "placeholder")
    monkeypatch.delenv(KEY)


def test_get_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert get_variable(KEY) is None
    assert get_variable(KEY, "default") == "default"
    monkeypatch.setenv(KEY, "value")
    assert get_variable(KEY) == "value"


@pytest.mark.parametrize(
    "raw, expected", [("gpt-4.1-mini", "gpt-4.1-mini"), (" x ", "x"), ("", "d"), ("  ", "d")]
)
def test_get_text_variable(monkeypatch: pytest.MonkeyPatch, raw: str, expected: str) -> None:
    monkeypatch.setenv(KEY, raw)
    assert get_text_variable(KEY, default="d") == expected


def test_get_text_variable_when_not_set() -> None:
    assert get_text_variable(KEY, default="d") == "d"


@pytest.mark.parametrize("raw, expected", [("5", 5), (" 12 ", 12), ("", 3), ("   ", 3)])
def test_get_int_variable(monkeypatch: pytest.MonkeyPatch, raw: str, expected: int) -> None:
    monkeypatch.setenv(KEY, raw)
    assert get_int_variable(KEY, default=3) == expected


def test_get_int_variable_when_not_set() -> None:
    assert get_int_variable(KEY, default=3) == 3


@pytest.mark.parametrize("raw", ["abc", "2.5", "0", "-1"])
def test_bad_values_fall_back_to_default_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
) -> None:
    monkeypatch.setenv(KEY, raw)
    assert get_int_variable(KEY, default=3, minimum=1) == 3
    assert KEY in caplog.text


def test_zero_is_allowed_when_minimum_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY, "0")
    assert get_int_variable(KEY, default=3, minimum=0) == 0
