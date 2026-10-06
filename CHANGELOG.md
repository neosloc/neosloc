# Changelog

All notable changes are listed here. The project follows [semantic versioning](https://semver.org/);
breaking changes to the CLI, the JSON report or the scoring are called out explicitly.

## 0.3.0

- OpenRouter as a model provider (`openrouter:<vendor/model>`), with no extra dependency.
- Three evaluator roles: `--agentic` (probe), `--judge` (checks grounded probe answers
  against the source) and `--review` (audits each static level). Comma-separated models
  run a panel and report agreement.
- One `--max-cost` budget shared by every model call; the report states total spend.
- **Breaking (JSON):** `agentic` is now `{"runs": [...], "panel": ...}` instead of a
  single run. New top-level `review` and `spend` keys.
- **Breaking (CLI):** `--model` is now an alias of `--probe-model` and accepts `provider:model`.
- `pip install neosloc` provides the `neosloc` command. Documentation site added.

## 0.2.0

- Events, identity, portability, agent ergonomics, extensibility and observability dimensions.
- neoCOCOMO value model (cost approach for the agent era), with classic COCOMO for comparison.
- Agentic probe with docs/source scopes, live HTTP mode and grounding grader.

## 0.1.0

- Static assessment of interface, stability, embeddability and legibility; retrofit estimate.
