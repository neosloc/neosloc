"""Dimension 1 - Interface surface.

Is there a machine-readable contract, and how much of the implemented surface
does it cover? Routes are counted from framework idioms; contracts are either
checked-in specs or produced by a framework that generates them from code.
"""
from __future__ import annotations

import re
from typing import Dict, List

from ..model import DimensionResult, Evidence, clamp_level
from ..repo import Repo
from ..specs import find_specs
from .base import Context, register

# (framework, file-path regex or None, route regex). Each match ~ one operation.
ROUTE_PATTERNS = [
    ("fastapi/flask", r"\.py$", r"@\w+\.(get|post|put|patch|delete|route|api_route|websocket)\(\s*['\"]"),
    ("django", r"urls\.py$", r"\b(re_)?path\(\s*r?['\"]"),
    ("drf", r"\.py$", r"\.register\(\s*r?['\"]"),
    ("express/koa/hono", r"\.[jt]sx?$", r"\b(app|router|server|api)\.(get|post|put|patch|delete|all|route)\(\s*['\"`]"),
    ("nestjs", r"\.ts$", r"@(Get|Post|Put|Patch|Delete|All)\("),
    ("nextjs-route", r"(^|/)app/.*route\.[jt]s$", r"export\s+(async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE)\b"),
    ("spring/jax-rs", r"\.(java|kt)$", r"@(Get|Post|Put|Patch|Delete|Request)Mapping\b|@(GET|POST|PUT|DELETE|PATCH)\b"),
    ("rails", r"routes\.rb$", r"^\s*(get|post|put|patch|delete|resources?|match)\s+['\":]"),
    ("laravel", r"\.php$", r"Route::(get|post|put|patch|delete|any|resource|apiResource)\("),
    ("slim/php", r"\.php$", r"\$app->(get|post|put|patch|delete|map)\("),
    ("go-http", r"\.go$", r"\.(HandleFunc|Handle|GET|POST|PUT|PATCH|DELETE|Get|Post|Put|Patch|Delete)\(\s*\""),
    ("rust-axum/actix", r"\.rs$", r"\.route\(\s*\"|#\[(get|post|put|patch|delete)\(\s*\""),
    ("aspnet", r"\.cs$", r"\[Http(Get|Post|Put|Patch|Delete)\b|\.Map(Get|Post|Put|Patch|Delete)\("),
]

# Frameworks/libraries that expose a spec generated from code at runtime.

# Frameworks/libraries that expose a spec generated from code at runtime.
# (name, "manifest" | "code", regex). Library names are only trusted in
# dependency manifests; constructors only in product code.
GENERATED_SPEC = [
    ("FastAPI (auto OpenAPI)", "code", r"\bFastAPI\("),
    ("django-ninja", "code", r"\bNinjaAPI\("),
    ("drf-spectacular", "manifest", r"drf[_-]spectacular"),
    ("drf-yasg", "manifest", r"drf[_-]yasg"),
    ("flask-smorest/apispec", "manifest", r"flask[_-]smorest|\bapispec\b|flasgger"),
    ("springdoc/springfox", "manifest", r"springdoc|springfox"),
    ("@nestjs/swagger", "manifest", r"@nestjs/swagger"),
    ("tsoa/zod-openapi/fastify-swagger", "manifest", r"\"(tsoa|@asteasolutions/zod-to-openapi|@hono/zod-openapi|fastify-swagger|@fastify/swagger)\""),
    ("swaggo", "manifest", r"swaggo/swag"),
    ("utoipa/aide/poem-openapi", "manifest", r"\b(utoipa|aide|poem-openapi)\b"),
    ("Swashbuckle/NSwag", "manifest", r"Swashbuckle|NSwag"),
    ("graphql server", "manifest", r"strawberry-graphql|\bgraphene\b|apollo-server|@apollo/server|gqlgen|async-graphql|graphql-yoga"),
]

# Server side only: an MCP *client* consumes other systems, it doesn't expose this one.
MCP_SERVER = re.compile(
    r"\bFastMCP\(|from mcp\.server|@modelcontextprotocol/sdk/server|\bMcpServer\("
    r"|\bServerHandler\b|server\.NewMCPServer|mcp_server\.run\("
)
CLI_FRAMEWORKS = re.compile(
    r"\bimport (argparse|click|typer|fire|docopt)\b|from (click|typer) import|sys\.argv"
    r"|['\"](commander|yargs|oclif|meow|cac)['\"]|process\.argv"
    r"|spf13/cobra|urfave/cli|\"flag\"|os\.Args|\bclap\b|std::env::args|picocli|String\[\] args"
)
CLI_JSON = re.compile(r"""['"]--(json|output|format)['"]|\bjson=True\b|--json\b""")
SDK_DIRS = re.compile(r"(^|/)(sdk|sdks|client|clients)/")


def _library_api(repo: Repo) -> List[Evidence]:
    """A library's public API is its interface; static types make it a contract
    the compiler checks. Weight 3 = typed contract, 1 = untyped API."""
    out = []
    for pj in repo.glob(r"^(packages/[^/]+/)?package\.json$"):
        text = repo.read(pj)
        # "main" alone is common in apps; a web app ships an index.html instead.
        explicit = re.search(r'"(module|exports|types|typings|files)"\s*:', text)
        is_app = bool(repo.glob(r"^(public/|src/|app/)?index\.html$"))
        if not explicit and (is_app or not re.search(r'"main"\s*:', text)):
            continue
        typed = re.search(r'"(types|typings)"\s*:', text) or any(
            repo.language(f) == "typescript" for f in repo.source_files(include_tests=False))
        out.append(Evidence("library-api", "npm package, %s" % ("typed" if typed else "untyped JS"),
                            pj, 3 if typed else 1))
    py_typed = repo.glob(r"(^|/)py\.typed$")
    if py_typed:
        out.append(Evidence("library-api", "Python package with py.typed", py_typed[0], 3))
    elif repo.glob(r"^(pyproject\.toml|setup\.py|setup\.cfg)$"):
        out.append(Evidence("library-api", "Python package without py.typed", None, 1))
    gomod = repo.glob(r"^go\.mod$")
    go_main = re.compile(r"^package main\b", re.M)
    if gomod and any(f.endswith(".go") and not go_main.search(repo.read(f))
                     for f in repo.source_files(include_tests=False)
                     if not re.search(r"(^|/)(cmd|internal)/", f)):
        out.append(Evidence("library-api", "Go module with exported packages", gomod[0], 3))
    if repo.glob(r"^(crates/[^/]+/)?src/lib\.rs$"):
        out.append(Evidence("library-api", "Rust library crate", "Cargo.toml", 3))
    return out


def _count_routes(repo: Repo) -> Dict[str, Dict[str, int]]:
    by_fw: Dict[str, Dict[str, int]] = {}
    src = repo.source_files(include_tests=False)
    for fw, path_rx, route_rx in ROUTE_PATTERNS:
        prx, rrx = re.compile(path_rx), re.compile(route_rx, re.M)
        hits = repo.grep(rrx, [f for f in src if prx.search(f)])
        if hits:
            by_fw[fw] = hits
    return by_fw


def _generated(repo: Repo) -> List[Evidence]:
    out = []
    manifests = repo.manifests()
    code = repo.source_files(include_tests=False)
    for name, where, rx in GENERATED_SPEC:
        files = manifests if where == "manifest" else code
        hits = repo.grep(re.compile(rx), files, limit=1)
        for path in hits:
            out.append(Evidence("generated-spec", name, path, 2))
    return out


@register("interface", "Interface surface")
def detect(repo: Repo, ctx: Context) -> DimensionResult:
    ev: List[Evidence] = []
    gaps: List[str] = []

    specs = find_specs(repo)
    ctx["specs"] = specs
    api_specs = [s for s in specs if s.kind in ("openapi", "graphql", "protobuf", "asyncapi")]
    for s in specs:
        if s.kind == "jsonschema":
            ev.append(Evidence("spec:jsonschema", "data/config contract", s.path))
        else:
            ev.append(Evidence("spec:" + s.kind, "%d operations" % len(s.operations), s.path, 3))
    spec_ops = sum(len(s.operations) for s in specs if s.kind == "openapi")

    routes = _count_routes(repo)
    route_total = sum(sum(h.values()) for h in routes.values())
    ctx["route_files"] = sorted({f for h in routes.values() for f in h})
    for fw, hits in routes.items():
        top = max(hits, key=hits.get)
        ev.append(Evidence("routes:" + fw, "%d route declarations in %d files"
                           % (sum(hits.values()), len(hits)), top))
    ctx["route_total"] = route_total

    generated = _generated(repo)
    ev.extend(generated)

    mcp = repo.grep(MCP_SERVER, repo.source_files(include_tests=False), limit=3)
    for p in mcp:
        ev.append(Evidence("mcp-server", "Model Context Protocol surface", p, 2))

    cli = repo.grep(CLI_FRAMEWORKS, repo.source_files(include_tests=False), limit=20)
    cli_json = {p: n for p, n in repo.grep(CLI_JSON, list(cli)).items()}
    if cli:
        ev.append(Evidence("cli", "CLI framework in %d files" % len(cli), next(iter(cli))))
    if cli_json:
        ev.append(Evidence("cli-machine-output", "CLI offers JSON/structured output",
                           next(iter(cli_json)), 2))

    library = _library_api(repo)
    ev.extend(library)
    typed_library = any(e.weight >= 3 for e in library)

    sdk = [f for f in repo.files if SDK_DIRS.search(f) and repo.language(f)]
    if sdk:
        ev.append(Evidence("sdk", "%d files under sdk/client dirs" % len(sdk), sdk[0]))

    ctx["has_surface"] = bool(specs or route_total or generated or mcp or cli or library)

    # ---- scoring -----------------------------------------------------------
    has_contract = bool(api_specs) or bool(generated) or typed_library
    surfaces = sum([bool(api_specs or generated), bool(mcp), bool(cli_json), bool(sdk),
                    typed_library])
    coverage = None
    if spec_ops and route_total:
        coverage = min(1.0, spec_ops / float(route_total))

    if not route_total and not has_contract and not mcp and not cli and not library:
        level = 0
        why = "No programmatic surface detected (no routes, contracts, library API, CLI or MCP)."
        gaps.append("Expose an API, CLI or MCP server; today only the UI/source is integrable.")
    elif not has_contract and not mcp and not cli_json:
        level = 1
        why = "A programmatic surface exists (routes, CLI or untyped library) but no machine-readable contract."
        if route_total:
            gaps.append("Publish an OpenAPI/GraphQL/proto contract or generate one from code.")
        if library and not route_total:
            gaps.append("Ship type declarations (.d.ts, py.typed) so the library API is a checked contract.")
    else:
        level = 2
        why = "A machine-readable contract or structured surface exists."
        if api_specs and (coverage is None or coverage >= 0.8):
            level = 3
            why = "A checked-in contract covers the implemented surface."
        elif generated and not api_specs:
            level = 3
            why = "The framework generates a contract from code, so it tracks the implementation."
            gaps.append("Check the generated spec into the repo so changes are reviewable and diffable.")
        elif typed_library and not route_total:
            level = 3
            why = "The library's public API is statically typed: a contract the compiler checks."
        elif coverage is not None:
            gaps.append("Spec covers ~%d%% of detected routes." % round(coverage * 100))
        if level >= 3 and surfaces >= 2:
            level = 4
            why += " Multiple surfaces (%d) are offered." % surfaces
        elif level >= 3:
            gaps.append("Offer a second surface for agents/tools (MCP server, CLI --json, SDK).")

    return DimensionResult(
        "interface", "Interface surface", clamp_level(level), why, ev,
        metrics={
            "route_declarations": route_total,
            "routes_by_framework": {k: sum(v.values()) for k, v in routes.items()},
            "spec_files": len(specs),
            "spec_operations": spec_ops,
            "spec_coverage": None if coverage is None else round(coverage, 2),
            "surfaces": surfaces,
            "library_api": [e.detail for e in library],
        },
        gaps=gaps,
    )
