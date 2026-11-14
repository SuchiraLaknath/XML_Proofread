# Design decisions

The main choices behind the design, why they were made, and what they cost.

## 1. The AI reports mistakes; it never rewrites text

**Decision.** The AI returns a JSON list of `{original, correction, type, reason}`. Our code
finds each `original` in the paragraph and wraps it in `<error>`.

**Why.** If the AI returned a rewritten or tagged paragraph, it could silently change
whitespace, quotes or words, or break the XML. With a list, the original text is never in the
AI's hands, and a safety check can prove it was not changed.

**Cost.** The AI must copy `original` exactly. When it doesn't, the mistake is skipped (a
whitespace-tolerant search reduces this).

## 2. One request per paragraph

**Decision.** Each unique `<p>` text is one request. Requests run in parallel.

**Why.** A paragraph holds at most about 50 words, so one request is small and fast. One failed
request affects only one paragraph. Sending each unique text once saves tokens when text
repeats.

**Cost.** More requests than batching paragraphs together. Prompt caching keeps the repeated
system prompt cheap.

## 3. The whole style guide in the system prompt, no RAG

**Decision.** The full guide (about 2,500 tokens) is converted to Markdown and put in the
system prompt for every request.

**Why.** Retrieval can miss a rule (`1930's` might not retrieve "no apostrophe in plural
years"). The guide is small, and since the system prompt never changes, it is served from the
prompt cache.

**Cost.** A much larger guide would need a different approach.

## 4. No style rules in the code

**Decision.** The code holds no style rules: no regular expressions and no word lists. The AI
applies the style guide it receives in the system prompt.

**Why.** The style guide is an input, so the tool must work with any guide. Rules copied into
the code would only fit one guide, and with a different guide they would give wrong advice.

**Cost.** The AI can still miss a rule or apply one wrongly; nothing in the code double-checks
style guide answers.

## 5. Skip, don't guess

**Decision.** A mistake whose text can't be found, overlaps another, or crosses a tag is
skipped with a warning. A paragraph with CDATA is skipped completely. A failed request leaves
its paragraph unchanged.

**Why.** A wrong or damaged mark is worse than a missing one. Every skip is logged and counted
in the summary, so nothing is lost silently.

**Cost.** Some real mistakes are not marked (for example one that spans `</b>`).

## 6. A safety check after every paragraph

**Decision.** After marking, the paragraph is read again. If its text differs from the original,
every change is undone.

**Why.** It turns "the original text is never changed" from a hope into a checked rule. A bug in
the marking code can't damage a document.

**Cost.** The paragraph is read twice; this is very fast.

## 7. Byte-exact XML input and output

**Decision.** XML is read and written as bytes. The bytes before and after the root element and
Windows line endings are kept as they were.

**Why.** lxml alone rewrites the `<?xml ...?>` line, drops blank lines and the final newline,
and changes `\r\n`. Keeping the original bytes means an unchanged file comes out identical.

**Cost.** Some markup lxml can't reproduce (character references, single-quoted attributes) is
saved as equivalent XML, with a warning.

## 8. LangChain, but only for the clients

**Decision.** `ChatOpenAI` and `ChatAnthropic` give both providers one interface and one error
hierarchy. Nothing else uses LangChain: no chains, agents or vector stores.

**Why.** One code path for both providers, without building the abstraction ourselves.

**Cost.** One more dependency, and provider details (such as temperature rules) still need care
in our own code.

## 9. `llms/` knows nothing about proofreading

**Decision.** The AI layer only sends text and returns text. The caller passes a `parse`
function.

**Why.** Each layer can be understood and tested on its own, and the AI layer could be reused.

## 10. Prompts as Markdown templates with `string.Template`

**Decision.** Prompt text lives in `prompt_templates/xml_proofread/*.md` and uses `$name`
placeholders.

**Why.** Prompts can be read and edited without touching Python. `str.format` would break on
the `{ }` in the JSON examples.

## 11. Simple over clever

**Decision.** No config files, settings classes, abstract base classes, factories or plugin
systems. Command-line flags plus `.env` are enough. Small functions, dataclasses for data.

**Why.** The code should be easy for a junior developer to read and explain line by line.
