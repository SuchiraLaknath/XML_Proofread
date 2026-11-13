"""The proofreading process: read <p> text, ask the AI, mark <error> tags safely, report.

Modules, in the order the flow uses them:
    language.py        check --lang and name the language
    rule_loader.py     read the .docx style guide as Markdown
    prompts.py         build the system and user prompts from the Markdown templates
    xml_reader.py      find <p> elements and read their text as segments
    ai_proofreader.py  ask the AI for each paragraph and read its JSON answer
    error_marker.py    wrap each mistake in <error>, with an undo record
    safety_check.py    undo a paragraph if its text changed
    report.py          numbers about the run and the printed summary
    pipeline.py        proofread_file(): the whole flow for one file
"""

from .ai_proofreader import Checker, CheckResult, Mistake, Proofreader, parse_ai_answer
from .language import LanguageError, Locale, parse_language
from .pipeline import corrected_path, proofread_file
from .prompts import ProofreadPrompts, build_system_prompt, build_user_prompt, load_proofread_prompts
from .report import RunReport, print_summary
from .rule_loader import StyleGuideError, load_style_guide
from .xml_reader import XmlReadError

__all__ = [
    "CheckResult",
    "Checker",
    "LanguageError",
    "Locale",
    "Mistake",
    "ProofreadPrompts",
    "Proofreader",
    "RunReport",
    "StyleGuideError",
    "XmlReadError",
    "build_system_prompt",
    "build_user_prompt",
    "corrected_path",
    "load_proofread_prompts",
    "load_style_guide",
    "parse_ai_answer",
    "parse_language",
    "print_summary",
    "proofread_file",
]
