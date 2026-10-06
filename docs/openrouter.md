# Using OpenRouter

[OpenRouter](https://openrouter.ai) routes one API to hundreds of models from many
vendors. neosloc can use any of its tool-capable models as a probe, judge or reviewer, and
needs no extra package to do so.

## Setup

1. Create a key at <https://openrouter.ai/keys> and add credits.
2. Export it:

    ```bash
    export OPENROUTER_API_KEY=sk-or-...
    ```

3. Pick models from <https://openrouter.ai/models>. Filter for **tools** support; neosloc
   checks this before the run starts and refuses models that can't call tools.

## Examples

```bash
# A cheap reviewer to sanity-check the static levels
neosloc --review --review-model openrouter:google/gemini-3.8-flash .

# Probe with one vendor, judge with another
neosloc --judge \
  --probe-model openrouter:anthropic/claude-sonnet-5.5 \
  --judge-model openrouter:openai/gpt-5.6-luna .

# A three-model probe panel on the docs only, with transcripts
neosloc --agentic --max-cost 10 --transcripts runs/ \
  --probe-model openrouter:anthropic/claude-opus-5.5,openrouter:google/gemini-3.8-flash,openrouter:deepseek/deepseek-v4-pro-0813 .

# Mix providers: Anthropic directly for the probe, OpenRouter for review
neosloc --agentic --review --review-model openrouter:openai/gpt-5.6-luna .
```

## How it works

- Requests go to `https://openrouter.ai/api/v1/chat/completions` in the OpenAI-compatible
  format, with `HTTP-Referer` and `X-Title` identifying neosloc.
- Tools are sent as functions with `tool_choice: auto`. Strict schemas are not requested,
  because not every routed provider supports them. Instead, every tool call's arguments are
  validated locally, and an invalid submission is sent back to the model as a tool error
  so it can correct it.
- `--effort` is sent as `reasoning.effort` to models that list `reasoning` among their
  supported parameters. Assistant messages, including `reasoning_details`, are passed back
  unchanged, so reasoning continues across tool calls.
- **Cost:** the `usage.cost` OpenRouter returns is used when present. Otherwise the cost is
  computed from the model's listed per-token prices, with cached prompt tokens priced as
  cache reads. Every call is charged to the shared `--max-cost` budget.
- **Errors:** 401/403 (bad key) and 402 (no credits) stop the run with a message. 408, 429
  and 5xx are retried with exponential backoff (3 attempts). A `content_filter` finish
  counts as a refusal for that task.

## Choosing models per role

- **Probe:** strong agentic models get the most out of the docs. Weaker ones make the
  documentation gap larger, which can be useful: if a mid-sized model succeeds from the
  docs alone, the docs are good.
- **Judge:** use a different vendor from the probe.
- **Review:** reviews are short. Two or three inexpensive models from different vendors
  make a good panel for calibrating detectors.
