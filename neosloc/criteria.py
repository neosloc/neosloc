# neosloc: ignore (detection vocabulary, not usage)
"""The ten dimensions as ladders of checkable requirements, per surface.

This file *is* the specification: docs/dimensions.md renders its tables from
these definitions. Each check returns evidence (met) or a short reason (not
met). Pattern knowledge lives in facts.py.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from .facts import (AGENT_DOCS, BREAKING_MARK, COMPOSITION, CONDITIONAL, DEPRECATION, DOCKERFILE, DOCTEST,
                    DRY_RUN, ENV_READ, ENV_TEMPLATE, EVENT_HOOK_CLI, EVENT_STREAM_CLI, EXCEPTION_CLASS, EXPORT,
                    EXPORT_DOC, EXTRAS, EXT_API_VERSION, FILE_TOKEN_BUDGET, HEALTH, HEALTHCHECK_CFG, HOOKS, IDEMPOTENCY,
                    IMPORT, INTERNAL_EVENTS, JSON_ERRORS_SVC, LIMIT_OPTIONS, LOCKFILES, LOG_LEVEL_CALL, MANAGED_KEYS,
                    METRICS, NONZERO_EXIT, OAUTH, OIDC_SCIM, OPEN_FORMATS, OUTBOUND_WEBHOOK, OUT_OF_TREE, OWNS_DATA_PATH,
                    PAGINATION, PRINT_CALL, PROBLEM_DETAILS, PROFILES, PUBLISH, RATE_LIMIT, README, RETRY_PARAM, SCOPES,
                    SEAM, SECRET_FLAG, SECRET_LOGGED, SIGNED_WEBHOOK, SINGLE_BINARY, STD_LOGGER, STDERR_DIAG, STREAMING,
                    STRUCTURED_LOG, SYS_EXIT, TIMEOUT_PARAM, TOKEN_AUTH, TRACING, VALIDATION, VERBOSITY, VERSIONED_PATH,
                    CI, CLOUDEVENTS, CREDENTIAL_ENV, ENV_FALLBACK, ARG_VALIDATION, Facts, Hit, Hits)
from .ladder import UNIVERSAL, DimensionSpec, Requirement, Surfaces, register

BROKER = re.compile(r"\b(kafka|kafkajs|confluent[-_]kafka|aiokafka|pika|amqp|amqplib|nats|paho[-_]mqtt|"
                    r"google-cloud-pubsub|@google-cloud/pubsub)\b", re.I)
ASYNCAPI = r"(^|/)asyncapi[\w.-]*\.(ya?ml|json)$"
SDK_DIRS = r"(^|/)(sdk|sdks|clients?)/[^/]+\.\w+$"
MINIMAL_DEPS = 10


# ---------------------------------------------------------------------------
# helpers


def ok(ev: Hits, why: str):
    """Evidence when present, otherwise the reason it's missing."""
    return ev if ev else why


def all_of(*results):
    """Met only if every part is met; evidence is the union, the reason the first failure."""
    ev: Hits = []
    for r in results:
        if not r or isinstance(r, str):
            return r if isinstance(r, str) else "not met"
        ev += r
    return ev


def absent(found: Hits, ok_detail: str, why: str):
    """Met when nothing is found (for requirements of the form 'never …')."""
    if found:
        return "%s: %s" % (why, ", ".join(h.path for h in found[:3] if h.path))
    return [Hit(None, ok_detail)]


def cli_files(f: Facts) -> List[str]:
    return f.cli_files()


def library_code(f: Facts) -> List[str]:
    """Product code that isn't the CLI layer or a __main__ module."""
    cli = set(f.cli_files())
    return [p for p in f.code if p not in cli and not p.endswith("__main__.py")]


def agent_docs(f: Facts) -> Hits:
    return f.paths(AGENT_DOCS)


def only(*kinds: str):
    def applicable(s: Surfaces) -> Tuple[List[str], str]:
        present = [k for k in kinds if s.has(k)]
        return present, "no %s surface" % " or ".join(kinds)
    return applicable


def universal_if(*kinds: str):
    def applicable(s: Surfaces) -> Tuple[List[str], str]:
        return ([UNIVERSAL] if any(s.has(k) for k in kinds) else []), "no %s surface" % ", ".join(kinds)
    return applicable


# Reused checks

def noninteractive(f: Facts):
    prompts = f.prompts()
    if not prompts:
        return [Hit(None, "no interactive prompts")]
    return ok(f.noninteractive_guard(), "prompts without a non-TTY guard: %s" % ", ".join(h.path for h in prompts[:3]))


def errors_on_stderr_and_exit_codes(f: Facts):
    return all_of(ok(f.grep(STDERR_DIAG), "diagnostics aren't written to stderr"),
                  ok(f.grep(NONZERO_EXIT), "no non-zero exit on failure"))


def exit_classes(f: Facts):
    n = f.distinct_error_exit_codes()
    return all_of(ok(f.exit_codes_documented(), "exit statuses aren't documented"),
                  [Hit(None, "%d documented exit statuses" % n)] if n >= 2 else
                  "documented exit statuses don't distinguish error classes")


# ---------------------------------------------------------------------------
# 1. Interface


def _service_contract_coverage(f: Facts):
    if f.generated_spec():
        return [Hit(h.path, "generated from code: " + h.detail) for h in f.generated_spec()]
    if not f.api_specs():
        return "no contract"
    cov = f.spec_coverage()
    if cov is None or cov >= 0.8:
        return f.api_specs()
    return "the contract covers ~%d%% of declared routes" % round(cov * 100)


def _second_surface(f: Facts):
    return ok(f.mcp_server() + (f.json_output() if f.entry_points() else []) + f.paths(SDK_DIRS)[:1],
              "only one programmatic surface")


def _cli_help(f: Facts):
    with_help, total, ev = f.option_help()
    if total == 0:
        return ok(f.arg_parsing()[:1], "no argument parser")  # framework-generated help
    if with_help / float(total) >= 0.9:
        return ev
    return "%d of %d options have help text" % (with_help, total)


register(DimensionSpec(
    "interface", "Interface surface",
    "Can another program use it through a documented, machine-readable surface?",
    {
        "service": [
            Requirement(1, "routes", "Routes (or an MCP server) exist.",
                        lambda f: ok(f.route_hits() + f.mcp_server(), "no routes")),
            Requirement(2, "contract", "A contract exists: a checked-in OpenAPI/GraphQL/protobuf/AsyncAPI spec, "
                        "a framework-generated spec, or MCP tool schemas.",
                        lambda f: ok(f.api_specs() + f.generated_spec() + f.mcp_server(), "no machine-readable contract")),
            Requirement(3, "coverage", "The contract covers at least 80% of declared routes (generated contracts do).",
                        _service_contract_coverage),
            Requirement(4, "second-surface", "A second surface: an MCP server, a CLI with JSON output, or an SDK.",
                        _second_surface),
        ],
        "cli": [
            Requirement(1, "non-interactive", "Invocable non-interactively: no prompts, or prompts guarded by a "
                        "TTY check or a --yes/--no-input option.", noninteractive),
            Requirement(2, "help", "--help documents every option (at least 90% of options have help text).", _cli_help),
            Requirement(3, "machine-output", "Machine-readable output (--json/--format) and documented exit statuses.",
                        lambda f: all_of(ok(f.json_output(), "no --json/--format option"),
                                         ok(f.exit_codes_documented(), "exit statuses aren't documented"))),
            Requirement(4, "output-schema", "The output format is specified by a JSON Schema.",
                        lambda f: ok(f.output_schema(), "no JSON Schema for the output")),
        ],
        "library": [
            Requirement(1, "importable", "An importable, packaged API exists.",
                        lambda f: ok(f.library(), "no package")),
            Requirement(2, "public-api", "The public API is delimited (__all__, an exports map, exported identifiers).",
                        lambda f: ok(f.public_api_delimited(), "no __all__/exports defining the public API")),
            Requirement(3, "typed", "The public API is statically typed (py.typed, type declarations, a typed language).",
                        lambda f: ok(f.typed_api(), "no py.typed or type declarations")),
            Requirement(4, "api-reference", "An API reference is generated from the code (autodoc, mkdocstrings, "
                        "typedoc, …).", lambda f: ok(f.api_reference(), "no generated API reference")),
        ],
        "frontend": [
            Requirement(1, "programmatic", "A programmatic surface besides the UI.",
                        lambda f: "a UI is not a programmatic surface"),
        ],
        "none": [
            Requirement(1, "surface", "A programmatic surface exists (routes, a CLI or a library).",
                        lambda f: "no service, CLI, library or frontend detected"),
        ],
    },
    # Never n/a: having no programmatic surface is the lowest interface level, not an exemption.
    lambda s: ([k for k in ("service", "cli", "library", "frontend") if s.has(k)] or ["none"], ""),
))


# ---------------------------------------------------------------------------
# 2. Contract stability


def _versioned(f: Facts):
    tags = f.semver_tags()
    if tags:
        return [Hit(None, "%d semver tags, latest %s" % (len(tags), tags[-1]))]
    for h in f.changelog():
        if len(re.findall(r"^#+\s*\[?v?\d+\.\d+", f.repo.read(h.path), re.M)) >= 2:
            return [Hit(h.path, "versioned changelog sections")]
    return "no semver tags or versioned releases"


def _changelog_marks(f: Facts):
    logs = f.changelog()
    if not logs:
        return "no changelog"
    marked = [h for h in logs if BREAKING_MARK.search(f.repo.read(h.path))]
    return ok([Hit(h.path, "marks breaking changes") for h in marked], "the changelog doesn't mark breaking changes")


def _clean_history(f: Facts):
    compared, removed, ev = f.history_removals()
    if not compared:
        return "fewer than two tagged releases to compare"
    if removed:
        return "removed without prior deprecation: " + ", ".join(removed[:3])
    return ev


register(DimensionSpec(
    "stability", "Contract stability",
    "Can integrators rely on it not changing under them?",
    {UNIVERSAL: [
        Requirement(1, "versioned-releases", "Releases are versioned (semver tags or versioned changelog sections).",
                    _versioned),
        Requirement(2, "changelog", "A changelog exists and marks breaking changes.", _changelog_marks),
        Requirement(3, "deprecation", "A deprecation mechanism is used in code (warnings, @deprecated, "
                    "Deprecation/Sunset headers) or the API is versioned.",
                    lambda f: ok(f.grep(DEPRECATION) + f.grep(VERSIONED_PATH, f.route_files(), keep_regex=True),
                                 "no deprecation mechanism or API versioning")),
        Requirement(4, "clean-history", "Across tagged releases, no OpenAPI operation, CLI option or __all__ "
                    "symbol was removed without first being deprecated.", _clean_history),
    ]},
    universal_if("service", "cli", "library"),
))


# ---------------------------------------------------------------------------
# 3. Events


def _events_applicable(s: Surfaces) -> Tuple[List[str], str]:
    out = (["service"] if s.has("service") else []) + (["cli"] if s.has("cli") and s.long_running else [])
    return out, "no service and no long-running CLI mode (batch CLIs and libraries have no events)"


def _robust_delivery(f: Facts):
    outbound, signed = f.grep(OUTBOUND_WEBHOOK), f.grep(SIGNED_WEBHOOK)
    registrable = f.grep(re.compile(r"webhook", re.I), f.route_files(), keep_regex=True)
    if outbound and signed and registrable:
        return outbound[:1] + signed[:1] + registrable[:1]
    mechanisms = [m[0] for m in (outbound, f.grep(STREAMING), f.deps(BROKER)) if m]
    if len(mechanisms) >= 2:
        return mechanisms
    return "one delivery mechanism, or webhooks that are unsigned or not registrable through the API"


register(DimensionSpec(
    "events", "Events",
    "Can others react to state changes without polling?",
    {
        "service": [
            Requirement(1, "internal-events", "Internal events exist (signals, queues, an outbox, emitters).",
                        lambda f: ok(f.grep(INTERNAL_EVENTS) + f.grep(OUTBOUND_WEBHOOK) + f.grep(STREAMING),
                                     "no internal events")),
            Requirement(2, "outbound", "Webhooks sent by this system, or a streaming endpoint (SSE, WebSocket).",
                        lambda f: ok(f.grep(OUTBOUND_WEBHOOK) + f.grep(STREAMING), "no outbound webhooks or streams")),
            Requirement(3, "robust-delivery", "Signed webhooks registrable through the API, or two mechanisms "
                        "(webhooks, streams, a broker).", _robust_delivery),
            Requirement(4, "event-contract", "Events are described by AsyncAPI or CloudEvents.",
                        lambda f: ok(f.paths(ASYNCAPI) + f.grep(CLOUDEVENTS) + f.deps(CLOUDEVENTS),
                                     "no AsyncAPI or CloudEvents contract")),
        ],
        "cli": [
            Requirement(1, "progress", "Progress is reported while running.",
                        lambda f: ok(f.grep(STDERR_DIAG, cli_files(f)), "no progress output")),
            Requirement(2, "event-stream", "A machine-readable event stream (NDJSON / JSON Lines).",
                        lambda f: ok(f.grep(EVENT_STREAM_CLI, cli_files(f)), "no NDJSON/JSON Lines stream")),
            Requirement(3, "event-hooks", "Hooks run commands or URLs on events (--on-…, --exec, webhooks).",
                        lambda f: ok(f.grep(EVENT_HOOK_CLI, cli_files(f)), "no event hooks")),
            Requirement(4, "event-format", "The event format is specified (a schema).",
                        lambda f: ok(f.paths(r"event[\w.-]*\.schema\.json$") + f.paths(ASYNCAPI),
                                     "no event schema")),
        ],
    },
    _events_applicable,
))


# ---------------------------------------------------------------------------
# 4. Identity


def _identity_applicable(s: Surfaces) -> Tuple[List[str], str]:
    out = ["service"] if s.has("service") else []
    if s.uses_credentials:
        out += [k for k in ("cli", "library") if s.has(k)]
    return out, "uses no credentials and has no service surface"


def _creds_off_command_line(f: Facts):
    secret_flags = f.grep(SECRET_FLAG, cli_files(f))
    if secret_flags and not f.grep(ENV_FALLBACK, cli_files(f)):
        flag = SECRET_FLAG.search(f.repo.code_text(secret_flags[0].path)).group(1)
        return "--%s takes a secret on the command line (visible in shell history and ps)" % flag
    return _creds_documented(f)


def _creds_documented(f: Facts):
    names = sorted({m.group(3) for p in f.code for m in CREDENTIAL_ENV.finditer(f.repo.code_text(p))})
    if not names:
        return "no credential environment variables"
    return ok(f.docs(re.compile("|".join(map(re.escape, names)))), "credential environment variables aren't documented")


CLIENT_IDENTITY = [
    Requirement(1, "credentials-env", "Credentials can be supplied non-interactively (environment variables).",
                lambda f: ok(f.grep(CREDENTIAL_ENV), "credentials can't come from the environment")),
    Requirement(2, "credentials-off-cli", "Credentials never need to be on the command line, and their "
                "environment variables are documented.", _creds_off_command_line),
    Requirement(3, "secrets-not-logged", "No output or log statement includes a credential.",
                lambda f: absent(f.grep(SECRET_LOGGED), "no credential in print/log statements",
                                 "credentials may be printed or logged")),
    Requirement(4, "profiles", "Several profiles or scoped credentials per target.",
                lambda f: ok(f.grep(PROFILES), "no credential profiles")),
]

register(DimensionSpec(
    "identity", "Identity",
    "Can a machine act with its own revocable, least-privilege identity?",
    {
        "service": [
            Requirement(1, "token-auth", "Programmatic authentication (bearer tokens, API keys).",
                        lambda f: ok(f.deps(TOKEN_AUTH) + f.grep(TOKEN_AUTH) + f.deps(OAUTH), "no token auth")),
            Requirement(2, "managed-credentials", "Per-client, revocable credentials (managed API keys, service "
                        "accounts) or OAuth2.",
                        lambda f: ok(f.grep(MANAGED_KEYS) + f.deps(OAUTH) + f.grep(OAUTH), "no managed keys or OAuth")),
            Requirement(3, "scopes", "Credentials carry scopes or permissions.",
                        lambda f: ok(f.grep(SCOPES), "no scopes or permissions")),
            Requirement(4, "federation", "Standard provisioning or federation (OIDC client credentials, SCIM).",
                        lambda f: ok(f.grep(OIDC_SCIM) + f.deps(OIDC_SCIM), "no OIDC client credentials or SCIM")),
        ],
        "cli": CLIENT_IDENTITY,
        "library": [CLIENT_IDENTITY[0],
                    Requirement(2, "credentials-documented", "The credential environment variables are documented.",
                                _creds_documented),
                    CLIENT_IDENTITY[2], CLIENT_IDENTITY[3]],
    },
    _identity_applicable,
))


# ---------------------------------------------------------------------------
# 5. Data portability


def _owns_data(s: Surfaces) -> Tuple[List[str], str]:
    return ([UNIVERSAL] if s.owns_data else []), "owns no persistent data"


def _round_trip(f: Facts):
    tests = [p for p, t in f.test_text().items() if re.search(r"export", t, re.I) and re.search(r"import_|restore", t)]
    return all_of(ok(f.docs(EXPORT_DOC), "the export format isn't documented"),
                  ok([Hit(p, "export/import test") for p in tests], "no round-trip test"))


register(DimensionSpec(
    "portability", "Data portability",
    "Can its data get in and out, in bulk, in open formats, with an explicit schema?",
    {UNIVERSAL: [
        Requirement(1, "schema", "The data schema is explicit (migrations, DDL, schema files).",
                    lambda f: ok(f.paths(OWNS_DATA_PATH.pattern), "no migrations or schema files")),
        Requirement(2, "export", "An export exists (endpoint or command, not only the UI).",
                    lambda f: ok(f.grep(EXPORT), "no export")),
        Requirement(3, "bulk-open", "A bulk export in an open format, and a bulk import.",
                    lambda f: all_of(ok(f.grep(OPEN_FORMATS), "no open export format"),
                                     ok(f.grep(IMPORT), "no import"))),
        Requirement(4, "documented-round-trip", "The export format is documented and the round trip is tested.",
                    _round_trip),
    ]},
    _owns_data,
))


# ---------------------------------------------------------------------------
# 6. Agent ergonomics

register(DimensionSpec(
    "ergonomics", "Agent ergonomics",
    "Can an automated caller use it without guessing, and recover from failure?",
    {
        "service": [
            Requirement(1, "json-errors", "Errors are consistent JSON.",
                        lambda f: ok(f.grep(JSON_ERRORS_SVC) + f.grep(PROBLEM_DETAILS), "no consistent JSON errors")),
            Requirement(2, "validation-pagination", "Field-level validation errors, and paginated lists.",
                        lambda f: all_of(ok(f.grep(VALIDATION) + f.deps(VALIDATION), "no request validation"),
                                         ok(f.grep(PAGINATION), "no pagination"))),
            Requirement(3, "safe-retries", "Typed errors (RFC 9457 or equivalent), idempotent writes "
                        "(Idempotency-Key), and rate-limit signals.",
                        lambda f: all_of(ok(f.grep(PROBLEM_DETAILS) + f.deps(PROBLEM_DETAILS), "no typed errors"),
                                         ok(f.grep(IDEMPOTENCY), "no idempotency keys"),
                                         ok(f.grep(RATE_LIMIT) + f.deps(RATE_LIMIT), "no rate-limit signals"))),
            Requirement(4, "agent-ready", "Dry-run or validate-only, conditional requests, and agent docs.",
                        lambda f: all_of(ok(f.grep(DRY_RUN), "no dry-run"), ok(f.grep(CONDITIONAL), "no ETags"),
                                         ok(agent_docs(f), "no agent docs"))),
        ],
        "cli": [
            Requirement(1, "never-blocks", "Never blocks on a prompt when stdin is not a TTY.", noninteractive),
            Requirement(2, "streams-and-status", "Data on stdout, diagnostics on stderr, non-zero exit on failure.",
                        errors_on_stderr_and_exit_codes),
            Requirement(3, "typed-failures", "Documented exit statuses distinguish error classes, errors are JSON "
                        "in JSON mode, and color is off when not a TTY.",
                        lambda f: all_of(exit_classes(f), ok(f.json_errors(), "errors aren't JSON in JSON mode"),
                                         ok(f.color_ok(), "colored output ignores NO_COLOR/TTY"))),
            Requirement(4, "agent-ready", "--dry-run, limits for long or costly operations (timeouts, budgets), "
                        "and agent docs.",
                        lambda f: all_of(ok(f.grep(DRY_RUN, cli_files(f)), "no --dry-run"),
                                         ok(f.grep(LIMIT_OPTIONS, cli_files(f)), "no timeout/budget options"),
                                         ok(agent_docs(f), "no agent docs"))),
        ],
        "library": [
            Requirement(1, "typed-exceptions", "Errors are specific exception types, and library code never "
                        "calls sys.exit.",
                        lambda f: all_of(ok(f.grep(EXCEPTION_CLASS, library_code(f)), "no exception classes"),
                                         absent(f.grep(SYS_EXIT, library_code(f)), "no sys.exit in library code",
                                                "library code exits the process"))),
            Requirement(2, "validation", "Inputs are validated with messages naming the bad argument.",
                        lambda f: ok(f.grep(ARG_VALIDATION, library_code(f)), "no input validation errors")),
            Requirement(3, "timeouts-retries", "Timeouts and retries are configurable.",
                        lambda f: all_of(ok(f.grep(TIMEOUT_PARAM, library_code(f)), "no timeout parameter"),
                                         ok(f.grep(RETRY_PARAM, library_code(f)), "no retry parameter"))),
            Requirement(4, "agent-ready", "Agent docs, and examples that run as tests (doctests).",
                        lambda f: all_of(ok(agent_docs(f), "no agent docs"),
                                         ok([Hit(p, "doctest") for p, t in f.test_text().items() if DOCTEST.search(t)],
                                            "examples don't run as tests"))),
        ],
    },
    only("service", "cli", "library"),
))


# ---------------------------------------------------------------------------
# 7. Embeddability


def _published_and_used_in_ci(f: Facts):
    names = f.command_names()
    used = f.workflows(re.compile(r"(^|[\s/])(%s)(\s|$)" % "|".join(map(re.escape, names)), re.M)) if names else []
    return all_of(ok(f.workflows(PUBLISH), "not published to a registry"),
                  ok(used, "the command isn't run in CI"))


def _minimal_deps(f: Facts):
    n = f.runtime_deps()
    if n is None or n <= MINIMAL_DEPS:
        return [Hit(None, "%s runtime dependencies" % ("unknown number of" if n is None else n))]
    return "%d runtime dependencies (more than %d)" % (n, MINIMAL_DEPS)


register(DimensionSpec(
    "embeddability", "Embeddability",
    "Can another system run and compose it without a human?",
    {
        "service": [
            Requirement(1, "documented-run", "Runnable from source with documented steps (a README with commands).",
                        lambda f: ok([h for h in f.paths(README) if "```" in f.repo.read(h.path)], "no documented run steps")),
            Requirement(2, "env-config", "Configured through environment variables, documented (.env example or "
                        "config schema).",
                        lambda f: all_of(ok(f.grep(ENV_READ), "configuration isn't read from the environment"),
                                         ok(f.paths(ENV_TEMPLATE), "no .env example or config schema"))),
            Requirement(3, "container", "A container image.", lambda f: ok(f.paths(DOCKERFILE), "no Dockerfile")),
            Requirement(4, "composition", "Composition artifacts (compose, Helm, IaC).",
                        lambda f: ok(f.paths(COMPOSITION) + f.config(re.compile(r"^kind:\s*(Deployment|StatefulSet)", re.M)),
                                     "no compose/Helm/IaC")),
        ],
        "cli": [
            Requirement(1, "runnable", "Runnable from source (a declared entry point).",
                        lambda f: ok(f.entry_points(), "no entry point")),
            Requirement(2, "installable", "Installable as a package that provides the command.",
                        lambda f: ok([h for h in f.entry_points() if h.detail != "go main"]
                                     or ([h for h in f.entry_points()] if f.repo.glob(r"^go\.mod$") else []),
                                     "no package provides the command")),
            Requirement(3, "published", "Published to a public registry and run non-interactively in CI.",
                        _published_and_used_in_ci),
            Requirement(4, "container-or-binary", "Also shipped as a container image or a single binary.",
                        lambda f: ok(f.paths(DOCKERFILE) + f.paths(SINGLE_BINARY), "no container image or binary")),
        ],
        "library": [
            Requirement(1, "importable", "Importable from source.", lambda f: ok(f.library(), "no package")),
            Requirement(2, "installable", "Installable as a package (a package manifest).",
                        lambda f: ok([Hit(h.path, "package manifest") for h in f.library()], "no package manifest")),
            Requirement(3, "published-minimal", "Published to a public registry, with at most %d runtime "
                        "dependencies." % MINIMAL_DEPS,
                        lambda f: all_of(ok(f.workflows(PUBLISH), "not published to a registry"), _minimal_deps(f))),
            Requirement(4, "optional-features", "Optional features behind extras/features.",
                        lambda f: ok(f.deps(EXTRAS), "no optional extras")),
        ],
    },
    only("service", "cli", "library"),
))


# ---------------------------------------------------------------------------
# 8. Extensibility


def _documented_extension_api(f: Facts):
    names = f.seam_names()
    if not names:
        return "no registration functions to document"
    rx = re.compile(r"(@|\b)(%s)\s*\(" % "|".join(map(re.escape, names)))
    return ok(f.docs(rx), "the docs don't show how to use %s" % ", ".join(names))


register(DimensionSpec(
    "extensibility", "Extensibility",
    "Can behaviour be added without modifying the code?",
    {UNIVERSAL: [
        Requirement(1, "seams", "Internal seams: a registry, registration function or plugin manager.",
                    lambda f: ok(f.grep(SEAM), "no registry or registration function")),
        Requirement(2, "documented", "The docs show how to add behaviour through those seams (even in-tree).",
                    _documented_extension_api),
        Requirement(3, "out-of-tree", "Out-of-tree extensions are discovered (entry points, a plugin directory, "
                    "configuration) without editing the package.",
                    lambda f: ok(f.grep(OUT_OF_TREE), "extensions must be added inside the package")),
        Requirement(4, "versioned-api", "The extension API is versioned, has lifecycle hooks, and has example "
                    "extensions.",
                    lambda f: all_of(ok(f.grep(EXT_API_VERSION), "the extension API isn't versioned"),
                                     ok(f.grep(HOOKS), "no lifecycle hooks"),
                                     ok(f.paths(r"(^|/)(examples?|contrib)/[\w-]*(plugin|extension)"), "no example extensions"))),
    ]},
    lambda s: ([UNIVERSAL], ""),
))


# ---------------------------------------------------------------------------
# 9. Observability

register(DimensionSpec(
    "observability", "Observability",
    "Can an operator, or an orchestrating agent, tell whether it works and why not?",
    {
        "service": [
            Requirement(1, "health", "A health or readiness endpoint, or a container healthcheck.",
                        lambda f: ok(f.grep(HEALTH) + f.config(HEALTHCHECK_CFG), "no health endpoint or healthcheck")),
            Requirement(2, "structured-logs", "Structured logs.",
                        lambda f: ok(f.grep(STRUCTURED_LOG) + f.deps(STRUCTURED_LOG), "no structured logging")),
            Requirement(3, "metrics", "Metrics.", lambda f: ok(f.grep(METRICS) + f.deps(METRICS), "no metrics")),
            Requirement(4, "tracing", "Distributed tracing (OpenTelemetry).",
                        lambda f: ok(f.grep(TRACING) + f.deps(TRACING), "no tracing")),
        ],
        "cli": [
            Requirement(1, "exit-and-stderr", "Meaningful exit statuses, and errors on stderr.",
                        errors_on_stderr_and_exit_codes),
            Requirement(2, "verbosity", "Verbosity control for diagnostics (--quiet, --log-level, --debug).",
                        lambda f: ok(f.grep(VERBOSITY, cli_files(f)), "no --quiet or log-level control")),
            Requirement(3, "structured-diagnostics", "Structured logs (e.g. --log-format json) or a machine-readable "
                        "run summary.",
                        lambda f: ok(f.grep(STRUCTURED_LOG) + f.deps(STRUCTURED_LOG), "no structured diagnostics")),
            Requirement(4, "tracing", "Tracing hooks (OpenTelemetry).",
                        lambda f: ok(f.grep(TRACING) + f.deps(TRACING), "no tracing hooks")),
        ],
        "library": [
            Requirement(1, "standard-logger", "Logs through a standard logger namespace and never prints from "
                        "library code.",
                        lambda f: all_of(ok(f.grep(STD_LOGGER, library_code(f)), "no standard logger"),
                                         absent(f.grep(PRINT_CALL, library_code(f)), "no print() in library code",
                                                "library code prints"))),
            Requirement(2, "log-levels", "Log levels are used meaningfully (at least two levels).",
                        lambda f: (lambda lv: [Hit(None, "levels: " + ", ".join(sorted(lv)))] if len(lv) >= 2
                                   else "fewer than two log levels used")(
                            {m.group(1) or m.group(2) for p in library_code(f)
                             for m in LOG_LEVEL_CALL.finditer(f.repo.code_text(p))})),
            Requirement(3, "hooks", "Optional metrics or tracing hooks.",
                        lambda f: ok(f.grep(TRACING, library_code(f)) + f.grep(METRICS, library_code(f)),
                                     "no metrics or tracing hooks")),
            Requirement(4, "otel", "OpenTelemetry instrumentation available.",
                        lambda f: ok(f.deps(TRACING), "no OpenTelemetry instrumentation")),
        ],
    },
    only("service", "cli", "library"),
))


# ---------------------------------------------------------------------------
# 10. Change legibility


def _pinned(f: Facts):
    s = f.surfaces
    exempt = (s is not None and s.has("library")) or f.runtime_deps() == 0
    if exempt:
        return [Hit(None, "library or zero-dependency project: lockfile not required")]
    return ok(f.paths(LOCKFILES), "no lockfile (applications should pin dependencies)")


def _fits_and_verified(f: Facts):
    m = f.legibility()
    problems = []
    if m["modules_within_budget"] < 0.9 or m["oversized_files"]:
        problems.append("%d%% of modules fit 32k tokens; %d files over %dk"
                        % (round(m["modules_within_budget"] * 100), len(m["oversized_files"]), FILE_TOKEN_BUDGET // 1000))
    if m["test_ratio"] < 0.3:
        problems.append("test/source token ratio %.2f < 0.3" % m["test_ratio"])
    if m["typed_ratio"] < 0.7:
        problems.append("%d%% of code is typed (< 70%%)" % round(m["typed_ratio"] * 100))
    if problems:
        return "; ".join(problems)
    return [Hit(m["test_example"], "test ratio %.2f, %d%% typed, modules fit"
                % (m["test_ratio"], round(m["typed_ratio"] * 100)))]


def _no_cycles_agent_docs(f: Facts):
    m = f.legibility()
    if m["import_cycles"]:
        return "%d import cycles (largest: %s)" % (m["import_cycles"], ", ".join(m["largest_cycle"][:3]))
    return ok(agent_docs(f), "no agent docs (AGENTS.md, CLAUDE.md, llms.txt)")


register(DimensionSpec(
    "legibility", "Change legibility",
    "Can an agent change it safely with limited context?",
    {UNIVERSAL: [
        Requirement(1, "readme-tests", "A README and some tests.",
                    lambda f: all_of(ok(f.paths(README), "no README"),
                                     ok([Hit(f.legibility()["test_example"], "%d test files" % f.legibility()["test_files"])]
                                        if f.legibility()["test_files"] else [], "no tests"))),
        Requirement(2, "ci-pinned", "CI runs the tests; applications pin dependencies (libraries and "
                    "zero-dependency projects are exempt).",
                    lambda f: all_of(ok(f.paths(CI), "no CI"), _pinned(f))),
        Requirement(3, "fits-and-verified", "At least 90% of modules fit 32k tokens and no file exceeds 12k; "
                    "test/source token ratio at least 0.3; at least 70% of the code is typed.", _fits_and_verified),
        Requirement(4, "acyclic-documented", "No import cycles, and agent docs (AGENTS.md, CLAUDE.md, llms.txt).",
                    _no_cycles_agent_docs),
    ]},
    lambda s: ([UNIVERSAL], ""),
))
