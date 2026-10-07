# Getting started

## Install

=== "pip"

    ```bash
    pip install neosloc
    ```

=== "pipx / uv tool"

    ```bash
    pipx install neosloc
    # or
    uv tool install neosloc
    ```

=== "From GitHub"

    ```bash
    pip install git+https://github.com/neosloc/neosloc
    ```

This installs the `neosloc` command. `python -m neosloc` also works.

The static analysis needs nothing else and runs on Python 3.8 or later. LLM evaluators
have their own requirements:

| You want to use | Install | Set |
|---|---|---|
| Anthropic models (`anthropic:…`) | `pip install 'neosloc[agentic]'` (Python ≥ 3.10) | `ANTHROPIC_API_KEY` |
| OpenRouter models (`openrouter:…`) | nothing extra | `OPENROUTER_API_KEY` |

## First run

```bash
cd your/project
neosloc .
```

The report has four parts:

1. **Inventory**: files, source files, size in tokens, languages.
2. **Dimensions**: one line per dimension with its level (`■■□□ 2 partial`) and a one-line
   reason. Under it, `+` lines are evidence (with the file that shows it) and `-` lines
   are gaps, phrased as actions. Use `-v` to see all evidence.
3. **Retrofit effort**: the integrability index (mean level), the person-days to bring every
   dimension to level 3, and a *wrappability* verdict.
4. **Value**: classic COCOMO next to neoCOCOMO, and the share of knowledge at risk.

Use `--json` for a machine-readable report ([schema](json.md)), for example to track a
project over time in CI:

```bash
neosloc --json . > neosloc.json
```

## Assessing several projects

```bash
neosloc ~/src/service-a ~/src/legacy-b ~/src/lib-c
```

Reports are printed one after another (or as a JSON list with `--json`). Comparing old and
new projects side by side is one of the main uses: a legacy application with no API but a
clean CLI, tests and a readable schema often turns out *cheap to wrap*.

## Next steps

- Read what each [dimension](dimensions.md) checks, and why.
- Try an [LLM evaluator](evaluators.md): `neosloc --review .` asks a model to audit the
  detector's levels; `neosloc --agentic .` has a model attempt real integration tasks.
