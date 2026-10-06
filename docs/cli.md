# Command line

`neosloc PATH...` assesses one or more repositories. Everything below is generated from
`neosloc --help` when the documentation is built.

<!-- neosloc:cli -->

## Exit status

- `0`: all paths were assessed.
- `2`: at least one path was not a directory; the others are still reported.
- Credential failures in the LLM evaluators stop the run with a message on stderr.

## Examples

```bash
neosloc .                                   # text report for the current repository
neosloc --json ~/src/a ~/src/b > report.json
neosloc -v --only interface,stability .     # all evidence, two dimensions
neosloc --salary 90000 --overhead 1.8 .     # value in your own cost terms
neosloc --agentic --scope both --transcripts runs/ .
neosloc --review --review-model openrouter:google/gemini-3.8-flash,openrouter:openai/gpt-5.6-luna .
```
