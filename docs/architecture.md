# Architecture

This page explains the parts of the XML Proofreader and how they work together.

## What the system does

The tool takes three inputs:

- an XML file,
- a language tag (`--lang`, BCP-47, for example `en-US`),
- a house style guide (`--style-guide`, a `.docx` file).

It sends the text of every `<p>` element to a GenAI model (OpenAI or Anthropic). The model
answers with a JSON list of mistakes. The tool then wraps each mistake in an `<error>` tag and
writes `<input-name>.corrected.xml` next to the input file.

Only `<p>` text is checked. Headings and all other elements are never sent to the AI.

## Layers

The code is split into four layers. Each layer only calls the layers below it.

```mermaid
flowchart TB
    subgraph CLI["Command line"]
        main["main.py<br/>arguments, wiring, exit codes"]
    end

    subgraph PP["proof_read_process/ — the proofreading flow"]
        direction LR
        subgraph PP_IN["inputs"]
            direction TB
            language["language.py<br/>check --lang"]
            rule_loader["rule_loader.py<br/>style guide → Markdown"]
            prompts["prompts.py<br/>fill the templates"]
        end
        subgraph PP_RUN["run"]
            direction TB
            pipeline["pipeline.py<br/>proofread_file()"]
            xml_reader["xml_reader.py<br/>find p elements, read text"]
            ai_proofreader["ai_proofreader.py<br/>ask the AI, read JSON"]
        end
        subgraph PP_OUT["mark and report"]
            direction TB
            error_marker["error_marker.py<br/>insert error tags"]
            safety_check["safety_check.py<br/>text unchanged?"]
            report["report.py<br/>summary"]
        end
    end

    subgraph LLM["llms/ — AI clients (know nothing about proofreading)"]
        direction LR
        subgraph LLM_API["used by the flow"]
            direction TB
            providers["providers.py<br/>create_llm()"]
            llm_invoke["llm_invoke.py<br/>parallel calls, re-asks"]
        end
        subgraph LLM_CLIENTS["clients"]
            direction TB
            openai_llm["openai_llm.py"]
            anthropic_llm["anthropic_llm.py"]
        end
        subgraph LLM_CORE["shared"]
            direction TB
            base_llm["base_llm.py<br/>ChatLLM.ask()"]
            rate_limit["rate_limit.py<br/>wait on 429"]
        end
    end

    subgraph UT["utils/ — small shared helpers"]
        direction LR
        subgraph UT_FILES["files"]
            direction TB
            rw_xml["read_write_xml.py"]
            rw_docx["read_docx.py"]
            rw_md["read_write_md.py"]
            rw_file["read_write_file.py"]
        end
        subgraph UT_OTHER["settings, prompts, logging"]
            direction TB
            env["environmental_variables.py"]
            prompt_tools["prompt_making_tools.py"]
            logging_setup["logging_setup.py"]
        end
    end

    templates[("prompt_templates/<br/>xml_proofread/*.md")]

    CLI -->|"parse_language, load_style_guide,<br/>proofread_file, print_summary"| PP
    CLI -->|"create_llm"| LLM
    CLI -->|"setup_logging"| UT
    PP -->|"invoke_llm_parallel"| LLM
    PP -->|"XML, .docx and template files"| UT
    LLM -->|".env settings"| UT
    UT -.->|"reads"| templates
```

| Layer | Job | Rule |
| --- | --- | --- |
| `main.py` | Reads the command line, builds the proofreader, turns expected errors into a one-line message and exit code `1` | The only Python file in the project root. No proofreading logic |
| `proof_read_process/` | The proofreading flow, one module per job | Owns everything about paragraphs, mistakes and `<error>` tags |
| `llms/` | Sends a system prompt and a user prompt, returns text and token counts | Knows **nothing** about proofreading. The caller passes in a `parse` function |
| `utils/` | File reading and writing, `.env` settings, prompt loading, logging | Generic helpers, no project rules |

Prompt text lives in Markdown files under `prompt_templates/xml_proofread/`, not in Python code.

## Data flow

```mermaid
flowchart LR
    xml[/"XML file"/] --> reader["xml_reader<br/>find all p elements"]
    docx[/"Style guide .docx"/] --> loader["rule_loader<br/>docx to Markdown"]
    lang[/"--lang"/] --> language["language<br/>check tag, name it"]

    loader --> sys["prompts<br/>system prompt (built once)"]
    language --> sys

    reader --> ai["ai_proofreader<br/>one request per unique text,<br/>in parallel"]
    sys --> ai

    ai --> mark["error_marker<br/>wrap mistakes in error tags"]
    mark --> safe["safety_check<br/>text unchanged? else undo"]
    safe --> save[/"input.corrected.xml"/]
    safe --> summary["report<br/>printed summary"]
```

## One run, step by step

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Main as main.py
    participant Lang as language
    participant Rules as rule_loader
    participant Prompts as prompts
    participant Prov as llms.providers
    participant Pipe as pipeline
    participant Reader as xml_reader
    participant PR as Proofreader
    participant LLM as llms.invoke_llm_parallel
    participant Mark as error_marker + safety_check
    participant Report as report

    User->>Main: python main.py input.xml --lang en --style-guide guide.docx
    Main->>Lang: parse_language("en")
    Lang-->>Main: Locale(tag, name)
    Main->>Main: check that the input file exists
    Main->>Rules: load_style_guide(guide.docx)
    Rules-->>Main: style guide as Markdown
    Main->>Prompts: load_proofread_prompts() and build_system_prompt(...)
    Prompts-->>Main: system prompt (same for every request)
    Main->>Prov: create_llm(provider, model)
    Prov-->>Main: ChatLLM
    Main->>Pipe: proofread_file(input, Proofreader, report, workers)
    Pipe->>Reader: load_xml() and find_paragraphs()
    Reader-->>Pipe: all Paragraphs, read before any change
    Pipe->>PR: check_all(unique non-empty texts, no CDATA)
    PR->>LLM: one user prompt per text
    LLM-->>PR: InvokeResult per prompt
    PR-->>Pipe: text to CheckResult
    loop every paragraph
        Pipe->>Mark: mark_errors, verify_or_undo
    end
    Pipe->>Reader: save_xml(input.corrected.xml)
    Pipe-->>Main: RunReport
    Main->>Report: print_summary(report)
    Main-->>User: exit code 0
```

The steps inside `proofread_file()` ([pipeline.py](../proof_read_process/pipeline.py)):

1. **Read:** load the XML and read **all** paragraphs before anything is changed.
2. **AI:** send each unique, non-empty paragraph text to the AI once, in parallel. Paragraphs
   with CDATA are not sent.
3. **Mark:** for each paragraph, run `mark_errors()`, then `verify_or_undo()`.
4. **Save:** write `<input-name>.corrected.xml` in the same folder.
5. Return the `RunReport` (timings, counts, tokens, memory).

Each step is timed with `report.step("name")`, and the times appear in the summary.

### Why read everything first?

Inserting an `<error>` tag changes the tree. Reading every paragraph first means each one is
read from the original document, and the AI requests can all be sent at once.

### Why pass the checker in?

`proofread_file()` takes any object with a `check_all()` method (the `Checker` protocol in
[ai_proofreader.py](../proof_read_process/ai_proofreader.py)). The real program passes a
`Proofreader`; tests pass a `FakeProofreader` that answers from a table, so they need no
network and no API key.

## Concurrency

```mermaid
flowchart LR
    texts["Paragraph texts"] --> uniq["Remove repeats<br/>(dict.fromkeys)"]
    uniq --> pool["ThreadPoolExecutor<br/>LLM_WORKERS threads (default 8)"]
    pool --> r1["invoke_llm(prompt 1)"]
    pool --> r2["invoke_llm(prompt 2)"]
    pool --> rn["invoke_llm(prompt n)"]
    r1 --> results["text to InvokeResult<br/>(in the original order)"]
    r2 --> results
    rn --> results
```

- AI requests run on threads in `invoke_llm_parallel()` ([llm_invoke.py](../llms/llm_invoke.py)).
  The requests wait on the network, so threads are enough.
- Each unique text is sent **once**. Two paragraphs with the same text share one answer.
- Marking and saving run on the main thread, after every request has finished. The XML tree
  is never changed from more than one thread.
- `--workers` (or `LLM_WORKERS`) sets how many requests run at the same time.

## Error handling

One bad paragraph must never stop the run. Only problems that would make **every** request
fail stop it.

```mermaid
flowchart TD
    start(["Problem"]) --> kind{"What kind?"}

    kind -->|"Bad --lang, missing input,<br/>unreadable XML or style guide"| expected["LanguageError / XmlReadError /<br/>StyleGuideError"]
    kind -->|"Bad API key, no access,<br/>unknown model"| fatal["FatalAIError"]
    kind -->|"One request failed:<br/>network, 5xx, refusal, cut-off answer"| aierr["AIError"]
    kind -->|"Answer is not usable JSON"| parse["ValueError from parse_ai_answer"]
    kind -->|"Mistake text not found, overlaps,<br/>or crosses a tag"| unsafe["Skip that mistake"]
    kind -->|"Text changed after marking"| changed["Undo the paragraph"]

    expected --> stop["main.py logs one line, exit code 1"]
    fatal --> cancel["Cancel requests not yet started"] --> stop

    parse --> reask{"Attempts left?<br/>LLM_MAX_ATTEMPTS"}
    reask -->|yes| again["Ask again"]
    reask -->|no| failed
    aierr --> failed["Paragraph left unchanged,<br/>counted as failed"]

    unsafe --> warn["Log a warning,<br/>count as skipped"]
    changed --> undone["Count as undone"]

    failed --> goes_on["Run goes on"]
    warn --> goes_on
    undone --> goes_on
```

| Error | Raised in | Effect |
| --- | --- | --- |
| `LanguageError` | [language.py](../proof_read_process/language.py) | Stop, exit code 1 |
| `XmlReadError` | [read_write_xml.py](../utils/read_write_files/read_write_xml.py), `main.run()` | Stop, exit code 1 |
| `StyleGuideError` | [rule_loader.py](../proof_read_process/rule_loader.py) | Stop, exit code 1 |
| `FatalAIError` | [base_llm.py](../llms/base_llm.py), [openai_llm.py](../llms/openai_llm.py) | Stop, exit code 1. Not a subclass of `AIError`, so per-paragraph handlers can't swallow it |
| `AIError` | [base_llm.py](../llms/base_llm.py) | That paragraph is left unchanged |
| Parse error (`ValueError`, `KeyError`, `TypeError`) | `parse_ai_answer()` | Ask again, up to `LLM_MAX_ATTEMPTS` times |

Retries for network errors, 5xx and rate limits are described in
[AI integration](ai-integration.md#retries).

## Security

- The XML parser never resolves entities and never uses the network
  (`resolve_entities=False`, `no_network=True`), which blocks XXE attacks.
- API keys come only from the environment or `.env`, which git ignores.
- Log messages go to stderr. The per-request HTTP logs are shown only with `--verbose`
  ([logging_setup.py](../utils/logging_setup.py)).
