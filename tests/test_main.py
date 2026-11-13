"""Tests for the command line (main.py). The LLM is replaced by a fake: no network."""

import shutil
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

import main
from llms import ChatLLM, FatalAIError

EXAMPLES = Path(__file__).parent.parent / "examples"
STYLE_GUIDE = str(EXAMPLES / "Style_Guide.docx")


class FakeChatModel:
    """Finds "john" in the user prompt; answers every other paragraph with no mistakes."""

    def __init__(self) -> None:
        self.system_prompts: list[str] = []

    def invoke(self, messages: list) -> AIMessage:
        self.system_prompts.append(messages[0].content)
        user_prompt = messages[1].content
        if "john" in user_prompt:
            text = '{"errors": [{"original": "john", "correction": "John", "type": "capitalization"}]}'
        else:
            text = '{"errors": []}'
        return AIMessage(content=text, response_metadata={"stop_reason": "end_turn"})


@pytest.fixture
def chat_model(monkeypatch: pytest.MonkeyPatch) -> FakeChatModel:
    """Make main.create_llm return a ChatLLM around the fake chat model."""
    fake = FakeChatModel()
    monkeypatch.setattr(main, "create_llm", lambda provider, model: ChatLLM(provider, model or "fake", fake))
    return fake


@pytest.fixture
def input_xml(tmp_path: Path) -> Path:
    path = tmp_path / "example_input.xml"
    shutil.copy(EXAMPLES / "example_input.xml", path)
    return path


def test_full_run(chat_model: FakeChatModel, input_xml: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main.main([str(input_xml), "--lang", "en-US", "--style-guide", STYLE_GUIDE, "--workers", "2"])
    assert exit_code == 0
    output = (input_xml.parent / "example_input.corrected.xml").read_text(encoding="utf-8")
    assert '<error type="capitalization" correction="John">john</error>' in output
    summary = capsys.readouterr().out
    assert "Errors marked: 1 (capitalization 1)" in summary
    # The system prompt names the language and holds the style guide.
    assert "English (United States)" in chat_model.system_prompts[0]
    assert "## Dates (Months, Days, Years)" in chat_model.system_prompts[0]
    assert len(set(chat_model.system_prompts)) == 1  # identical for every request (prompt caching)


@pytest.mark.parametrize(
    "args, message",
    [
        (["--lang", "english"], "BCP-47"),
        (["--lang", "en", "--style-guide", "missing.docx"], "style guide"),
    ],
)
def test_bad_input_gives_one_line_error(
    chat_model: FakeChatModel,
    input_xml: Path,
    caplog: pytest.LogCaptureFixture,
    args: list[str],
    message: str,
) -> None:
    argv = [str(input_xml), "--style-guide", STYLE_GUIDE, *args]
    assert main.main(argv) == 1
    assert message in caplog.text
    assert chat_model.system_prompts == []  # nothing was sent


def test_missing_input_file(
    chat_model: FakeChatModel, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert main.main([str(tmp_path / "nope.xml"), "--lang", "en", "--style-guide", STYLE_GUIDE]) == 1
    assert "Input file not found" in caplog.text


def test_fatal_ai_error_stops_the_run(
    monkeypatch: pytest.MonkeyPatch, input_xml: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def broken_create_llm(provider: str, model: str | None) -> ChatLLM:
        raise FatalAIError("OpenAI client could not start: missing API key")

    monkeypatch.setattr(main, "create_llm", broken_create_llm)
    assert main.main([str(input_xml), "--lang", "en", "--style-guide", STYLE_GUIDE]) == 1
    assert "missing API key" in caplog.text
    assert not (input_xml.parent / "example_input.corrected.xml").exists()


def test_unknown_provider_is_rejected_by_argparse(input_xml: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main.main([str(input_xml), "--lang", "en", "--style-guide", STYLE_GUIDE, "--provider", "gemini"])
    assert exit_info.value.code == 2
