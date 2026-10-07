# Writing criteria

## Layout

```text
neosloc/
  repo.py            file inventory, cached reads, git, classification (test/example/vendored/generated)
  codeview.py        what facts see: no comments, docstrings, prose or regex literals
  specs.py           OpenAPI/AsyncAPI/GraphQL/proto discovery and parsing (no YAML dependency)
  facts.py           every observation (routes, entry points, docs, tags, …) with evidence
  ladder.py          Requirement, DimensionSpec, register(), surface detection, ladder climbing
  criteria.py        the ten dimensions as ladders: this file is the specification
  assess.py          runs the criteria: surfaces -> ladders -> best surface
  estimate.py        retrofit effort
  value.py           neoCOCOMO
  agentic/           llm.py (providers), loop.py, runner.py (probe), judge.py, review.py,
                     workspace.py (agent tools), grader.py, tasks.py
  report.py, cli.py
```

## Requirements and ladders

A dimension is a `DimensionSpec` registered with `register()` in `neosloc/criteria.py`:

```python
register(DimensionSpec(
    "rollout", "Rollout control",
    "Can integrations be switched on gradually and safely?",
    {UNIVERSAL: [
        Requirement(1, "flags", "A feature-flag mechanism exists.",
                    lambda f: ok(f.deps(FLAG_LIBS) + f.grep(FLAG_CODE), "no feature flags")),
        Requirement(2, "per-client", "Flags can target individual clients or keys.", per_client_flags),
        ...
    ]},
    lambda s: ([UNIVERSAL] if s.has("service") else []), "no service surface"),
))
```

- **A check** takes the `Facts` and returns evidence (a non-empty list of `Hit`s) when the
  requirement is met, or a short reason when it isn't. `ok(evidence, reason)` and
  `all_of(...)` cover most cases; `absent(found, ...)` handles "never …" requirements.
- **Ladders** are keyed by surface (`service`, `cli`, `library`, `frontend`) or
  `UNIVERSAL`. Levels must be 1..N with no gaps; `tests/test_criteria.py` enforces this.
- **Applicability** returns the surfaces the dimension applies to, plus the reason shown
  when there are none (`n/a`). Write it as an explicit rule about surfaces and
  properties (`s.long_running`, `s.owns_data`, `s.uses_credentials`), never as "no
  evidence found".
- **Pattern knowledge belongs in `facts.py`**: add a fact (a regex, or a method returning
  `Hit`s) there and combine facts in `criteria.py`.

The docs render every ladder from these definitions (`<!-- neosloc:ladder <key> -->` in
`docs/dimensions.md`), so a new requirement is documented as soon as it is added.

## Rules

- **Every level needs evidence with a path**, and every missing point should produce a gap
  phrased as an action.
- **Trust library names only in dependency manifests** (`f.deps`). Code is matched through
  the code view (`neosloc/codeview.py`), which drops comments, docstrings, prose strings and
  regex literals, but ordinary identifier-like strings remain.
- **Vocabulary files start with `# neosloc: ignore`** (`facts.py`, `criteria.py`,
  `specs.py`), so neosloc doesn't score itself on its own patterns.
  `tests/test_criteria.py::SelfScan` enforces this.
- **Test each requirement both ways.** `tests/test_criteria.py` builds small fixture
  repositories and checks that a surface climbs exactly one level when the requirement is
  added. Add a regression test for every false positive you fix.
- **Check against real repositories** before changing thresholds. `neosloc --review` with a
  couple of models is a quick way to find disagreements.

