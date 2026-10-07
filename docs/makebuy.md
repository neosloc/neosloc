# Make or buy

When agents write code, a product is only worth adopting if rebuilding what you need costs
more. neosloc costs both options over the same horizon (default 3 years), in tokens, time
and money, and gives a verdict:

```text
Make or buy (over 3 years; see neosloc/makebuy.py)
  Make with agents:  934k output + 23.3M input tokens (85% cached) on anthropic:claude-opus-5-5 = $37;
                     10.4 agent-hours, 39.7 human days (14.1 steering + 25.6 rediscovering history), ~39.7 calendar days
                     build $21k, then $3k/year to maintain -> $31k
  Buy (adopt as is): 5 min to running (via service) + 4.0 h to first use (via service), $5k/year price, 8.0 h/year of upgrades -> $17k
  Verdict:           BUY: adopting this is cheaper (make/buy = 1.83); buying wins below $10k/year
```

```bash
neosloc --buy-price 5000 --horizon 3 --make-model anthropic:claude-opus-5-5 path/to/repo
```

## Make: rebuild an equivalent with agents

| Quantity | Model |
|---|---|
| Final tokens | the product code + the tests needed to verify it (the existing tests, at least 0.3 × code) + a spec for behaviour that isn't captured: 0.1 × code × (1 − capture) |
| Output tokens | final × 3 (drafts, fixes, failed attempts) |
| Input tokens | output × 25 (agents re-read their context every turn); 85% served from the prompt cache |
| Model cost | the tokens at `--make-model`'s prices: Anthropic models offline, OpenRouter models from its price list |
| Agent hours | output / 50 tokens per second × 2 (tools, test runs), spread over 4 parallel agents |
| Human days | **steering**: final / 50,000 tokens per day × (1 + 2 × (1 − capture)), plus **rediscovery**: the knowledge in the commit history that isn't captured in tests, contracts or docs (neoCOCOMO's rediscover term) |
| Yearly | 15% of the build cost, for maintenance |

*Capture* is neoCOCOMO's share of behaviour pinned down by tests, contracts and docs
([Value](value.md)). Well-captured software is cheap to remake. A long history of fixes
that nobody wrote down is what makes remaking expensive. On old projects this term
dominates: the tokens cost tens of dollars, while rediscovering what 400 commits taught
the authors takes weeks.

## Buy: adopt it as it is

A buyer doesn't change the code. They install it and use its best way in, so buying costs
**adoption time**, read off the project's own ladders:

| Step | Read from | Minutes, level 0 → 4 |
|---|---|---|
| Getting it running | Embeddability level of its best surface | CLI or library: 240, 60, 15, 2, 1 (source only … published to a registry). Service: 960, 240, 60, 15, 5 (undocumented setup … container … compose/Helm). Desktop: 480, 120, 10, 2, 2 (build from source … installer … package manager) |
| First successful use | Interface level, or the UI | 2400 (× size; no programmatic surface: wrap the UI), 240, 60, 10, 2 (specified contract plus a second surface such as client libraries). Products with a UI (desktop app, web frontend) are first used by a person through it: 5 |
| Upgrades per year | Contract stability | 480, 240, 120, 30, 5 |

So `pip install neosloc && neosloc .` costs minutes, and so does geomqtt
(`docker compose up`, then any Redis/MQTT client or its published client libraries). The
[retrofit estimate](estimate.md) is the *owner's* cost of making a project integrable,
and isn't used here.

**Measured adoption.** With `--agentic`, the probe's docs-only `run` (get it running) and
`list` (first use) tasks are exactly the adoption steps, done by an agent. Their real
time, tokens and cost are reported next to the estimate:

```text
  Measured:          the <model> probe succeeded at getting it running and a first call from the docs in <time> (<tokens> tokens)
```

`--buy-price` adds a price per year (default 0, for open source).

## Verdict

| make / buy | Verdict |
|---|---|
| ≥ 1.5 | **buy**: adopting is cheaper |
| ≤ 1 / 1.5 | **make**: rebuilding with agents is cheaper |
| in between | **toss-up** |

The **break-even price** is the yearly price at which both cost the same. If it is zero or
negative, making wins even if the product is free.

Human time is priced at the same day rate as neoCOCOMO (`--salary`, `--overhead`).

## Calibration

The steering rate (50,000 final tokens per human day) is anchored on neosloc itself:
about 70k tokens of code and tests, built in roughly two days by one person directing an
agent. neosloc's own make estimate comes out at 2.2 human days. The other constants are
guesses, kept in `neosloc/makebuy.py` to be fitted.

!!! warning "neoCOCOMO's reproduce term is not calibrated the same way"
    [Value](value.md) still prices reproduction as a share of classic COCOMO effort, which
    puts neosloc at about 1.9 person-months, roughly 20 times its real build time. The
    make estimate uses the token model above instead. Bringing neoCOCOMO's reproduce term
    in line with it is an open item.

The adoption minutes are estimates per level, not yet compared with measured adoptions.
Running the probe on a few projects is the way to fit them.

Not modelled: licence terms, vendor risk, support, and the value of the vendor's roadmap.
Treat the verdict as the cost side of the decision.
