# AI integration

This page explains what is sent to the AI, what it must answer, how the answer is read, and
how failures are retried.

## The contract

The AI gets one paragraph at a time and answers with **JSON only**:

```json
{"errors": [
  {"original": "john", "correction": "John", "type": "capitalization", "reason": "Names start with a capital letter"}
]}
```

| Field | Rule |
| --- | --- |
| `original` | Copied **exactly** from the paragraph, as short as possible. Our code searches for it |
| `correction` | The replacement for `original` only. It goes into the `correction` attribute; the text itself is never changed |
| `type` | One of `grammar`, `spelling`, `punctuation`, `capitalization`, `clarity`, `styleguide` |
| `reason` | A short explanation. Required for `styleguide` (it must name the rule) |

Mistakes are listed in the order they appear and never overlap. No mistakes means
`{"errors": []}`.

## Prompts

Both prompts are Markdown templates in
[prompt_templates/xml_proofread/](../prompt_templates/xml_proofread/), filled with
`string.Template` by [prompts.py](../proof_read_process/prompts.py). Each template is read
from disk once per run.

```mermaid
flowchart LR
    subgraph once["Built once per run"]
        st["system_prompt.md"] --> sp["System prompt"]
        lang["$language, $lang<br/>from --lang"] --> sp
        sg["$style_guide<br/>from rule_loader"] --> sp
    end

    subgraph per["Built for each unique paragraph"]
        ut["user_prompt.md"] --> up["User prompt"]
        para["$paragraph"] --> up
    end

    sp --> req["One request"]
    up --> req
```

| Template | Placeholders | Contents |
| --- | --- | --- |
| [system_prompt.md](../prompt_templates/xml_proofread/system_prompt.md) | `$language`, `$lang`, `$style_guide` | Role, the six error types, rules (copy `original` exactly, keep it short, never mark quoted material, apply the English style guide only where it fits the language, ...), answer format, a worked example, the full style guide |
| [user_prompt.md](../prompt_templates/xml_proofread/user_prompt.md) | `$paragraph` | The paragraph to check |

`string.Template` is used instead of `str.format` because the prompts contain JSON examples
with `{ }`. A literal `$` is written as `$$` in the templates (see the `$$3,000,000` example).

### Prompt caching

The system prompt is **identical for every request** in a run. Everything that changes per
paragraph is in the user prompt. This lets the provider serve the long system prompt (with
the style guide, about 2,500 tokens) from its cache:

- **OpenAI** caches long prompts automatically.
- **Anthropic** needs the system prompt marked with `cache_control`, which
  `ChatLLM.make_system_message()` does when `cache_system_prompt=True`.

Cached tokens are shown in the summary, for example `49,253 in (37,147 cached)`.

## Reading the answer

`parse_ai_answer()` in [ai_proofreader.py](../proof_read_process/ai_proofreader.py) turns the
answer text into `Mistake` objects.

```mermaid
flowchart TD
    a[/"Answer text"/] --> fence["Remove code fences"]
    fence --> json{"Valid JSON with an<br/>errors list (or a bare list)?"}
    json -->|no| raise["Raise ValueError:<br/>the whole answer is asked again"]
    json -->|yes| each["For each item"]
    each --> check{"Usable item?"}
    check -->|"not an object, empty original,<br/>correction equals original,<br/>unknown type,<br/>styleguide without reason"| skip["Skip the item, log a warning"]
    check -->|yes| norm["Normalize the type<br/>(style guide, style, typo ... to the six names)"]
    norm --> mistake["Mistake(original, correction, type, reason)"]
```

Small problems are forgiven (code fences, a bare list, `"style guide"` for `"styleguide"`,
`"capitalisation"` for `"capitalization"`). Only an answer that is unusable as a whole is asked
again; one bad item is just skipped.

## Clients

All provider code is in [llms/](../llms/). Both providers use LangChain chat models, so they
share one interface (`chat_model.invoke`) and one error hierarchy.

```mermaid
classDiagram
    class ChatLLM {
        provider: str
        model: str
        chat_model: BaseChatModel
        cache_system_prompt: bool
        ask(system_prompt, user_prompt) LLMAnswer
    }
    class OpenAILLM {
        ChatOpenAI
        JSON mode
        reasoning_effort or temperature 0
    }
    class AnthropicLLM {
        ChatAnthropic
        no temperature
        cache_control on system prompt
        refusal fallback
    }
    ChatLLM <|-- OpenAILLM
    ChatLLM <|-- AnthropicLLM
```

| | OpenAI ([openai_llm.py](../llms/openai_llm.py)) | Anthropic ([anthropic_llm.py](../llms/anthropic_llm.py)) |
| --- | --- | --- |
| Default model | `gpt-6.1-terra` (default provider) | `claude-opus-5-5` |
| JSON | `response_format={"type": "json_object"}` always | Asked for in the prompt |
| Temperature | Reasoning models (`gpt-5*`, `gpt-6*`, `o1`, `o3`, `o4`, not `*chat*`) reject `temperature=0`, so they get `reasoning_effort` (`OPENAI_REASONING_EFFORT`, default `low`). Older models (`gpt-4.1`, `gpt-4o`) get `temperature=0` | Not sent: current Claude models reject it |
| Prompt caching | Automatic | `cache_control` on the system prompt |
| Output limit | Provider default | `ANTHROPIC_MAX_TOKENS` (default 16000, thinking plus answer) |
| Refusals | `refusal` / `content_filter` stop reason gives `AIError` | Server-side refusal fallback: `fallbacks="default"` with the `server-side-fallback-2026-07-01` beta |
| API key | `OPENAI_API_KEY` | `ANTHROPIC_API_KEY` |

`is_reasoning_model()` decides the OpenAI temperature setting in our code, because LangChain
only removes `temperature` for `gpt-5*` models.

`create_llm(provider, model)` in [providers.py](../llms/providers.py) picks the client. It
loads `.env` and treats an empty API key (`OPENAI_API_KEY=`) as missing, so the user sees a
clear "missing key" error instead of a confusing 401.

### Error sorting

`ChatLLM.ask()` ([base_llm.py](../llms/base_llm.py)) sorts every failure into one of two kinds:

| Kind | Examples | What happens |
| --- | --- | --- |
| `FatalAIError` | Bad API key, no permission, unknown model, missing key | The run stops. Requests not yet started are cancelled |
| `AIError` | Network or server error after the SDK's retries, rate limit after our retries, refusal, answer cut off (`max_tokens`, `length`), empty answer | That paragraph is left unchanged and the run goes on |

## Retries

There are three retry layers, each for a different problem.

```mermaid
flowchart TD
    invoke["chat_model.invoke(messages)"] --> sdk{"Network error or 5xx?"}
    sdk -->|yes| sdkretry["Layer 1: the OpenAI/Anthropic SDK<br/>retries by itself"]
    sdkretry --> invoke
    sdk -->|"no, 429 rate limit"| rl{"Layer 2: rate_limit.py<br/>retries left?<br/>LLM_RATE_LIMIT_RETRIES"}
    rl -->|yes| wait["Wait Retry-After seconds,<br/>else 10 s, 20 s, 40 s ... (max 120 s)"]
    wait --> invoke
    rl -->|no| aierror["AIError: paragraph unchanged"]
    sdk -->|"no, got an answer"| parse{"parse_ai_answer OK?"}
    parse -->|yes| done["Mistakes"]
    parse -->|no| again{"Layer 3: llm_invoke.py<br/>attempts left?<br/>LLM_MAX_ATTEMPTS"}
    again -->|yes| invoke
    again -->|no| failed["Paragraph unchanged"]
```

1. **SDK** — network errors and 5xx are retried by the OpenAI and Anthropic SDKs. Our code does
   not add its own retries for these.
2. **Rate limits** — [rate_limit.py](../llms/rate_limit.py) waits and tries again on HTTP 429.
   It uses the `Retry-After` header when the provider sends one; otherwise it waits
   `LLM_RATE_LIMIT_WAIT` seconds (default 10), doubling each time, never more than 120 s.
3. **Unusable answers** — [llm_invoke.py](../llms/llm_invoke.py) asks again only when the answer
   can't be parsed, up to `LLM_MAX_ATTEMPTS` tries (default 3). An `AIError` is not retried
   here, because layers 1 and 2 already did.

## One paragraph, end to end

```mermaid
sequenceDiagram
    participant PR as Proofreader.check_all
    participant INV as invoke_llm
    participant LLM as ChatLLM.ask
    participant RL as rate_limit
    participant API as Provider API

    PR->>PR: build_user_prompt(text)
    PR->>INV: invoke_llm_parallel(system, prompts, parse_ai_answer)
    loop up to LLM_MAX_ATTEMPTS
        INV->>LLM: ask(system_prompt, user_prompt)
        LLM->>RL: call_with_rate_limit_retry
        RL->>API: chat_model.invoke
        alt 429 rate limited
            API-->>RL: RateLimitError
            RL->>RL: wait, then try again
            RL->>API: chat_model.invoke
        end
        API-->>LLM: reply
        LLM->>LLM: check stop reason, read text and tokens
        LLM-->>INV: LLMAnswer
        INV->>INV: parse_ai_answer(text)
        Note over INV: parsed: stop. Unusable: ask again
    end
    INV-->>PR: InvokeResult (mistakes or error, attempts, tokens)
```
