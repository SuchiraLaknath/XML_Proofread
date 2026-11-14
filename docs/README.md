# Documentation

These pages explain how the XML Proofreader is built and why. For setup and how to run the
tool, start with the [project README](../README.md).

Diagrams are written in [Mermaid](https://mermaid.js.org/). They render on GitHub, on GitLab and
in the VS Code Markdown preview.

## Pages

| Page | Read it to learn |
| --- | --- |
| [Architecture](architecture.md) | The parts of the system, how one run flows from start to end, threads and error handling |
| [Codebase guide](codebase-guide.md) | Where everything lives, the main data types, coding rules, and how to make common changes |
| [XML handling and safety](xml-handling-and-safety.md) | How `<p>` text is read, how `<error>` tags are inserted, and how the original text is protected |
| [AI integration](ai-integration.md) | The prompts, the JSON answer format, provider settings, retries and prompt caching |
| [Style guide handling](style-guide-handling.md) | How the `.docx` style guide reaches the AI, and why no style rules live in the code |
| [Configuration](configuration.md) | Command-line options, `.env` settings, `--lang`, output and exit codes |
| [Testing](testing.md) | How the tests work without an API key, and which tests must always pass |
| [Design decisions](design-decisions.md) | The main choices that shaped the design, and what they cost |

## Suggested reading order

1. **New to the project:** [Architecture](architecture.md), then [Codebase guide](codebase-guide.md).
2. **Changing how errors are marked:** [XML handling and safety](xml-handling-and-safety.md), then [Testing](testing.md).
3. **Changing the AI or the prompts:** [AI integration](ai-integration.md), then [Style guide handling](style-guide-handling.md).
4. **Reviewing the design:** [Design decisions](design-decisions.md).

## The idea in one picture

The AI never rewrites text. It only reports mistakes, and our code marks them:

```xml
<!-- input -->
<p>My name is john.</p>

<!-- output -->
<p>My name is <error type="capitalization" correction="John" reason="Names start with a capital letter">john</error>.</p>
```

If every `<error>` tag is removed from the output, the input comes back exactly.
