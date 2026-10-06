"""Dimension 10 - Change legibility (the heir to SLOC).

How much context does an agent (or a human) need to change this code safely?
Size is still measured, but in tokens and per module, because what matters is
whether a unit of change fits in a working context - not the total line count.
Safety nets (tests, types, CI, pinned deps) and coupling decide how risky a
change made with that context is.
"""
from __future__ import annotations

import ast
import posixpath
import re
from collections import defaultdict
from typing import Dict, List, Set

from ..model import DimensionResult, Evidence, clamp_level
from ..repo import STATICALLY_TYPED, Repo, estimate_tokens
from .base import Context, register

# Budget for a module an agent should be able to load whole alongside the task.
MODULE_TOKEN_BUDGET = 32_000
FILE_TOKEN_BUDGET = 12_000

CI = r"(^|/)(\.github/workflows/[^/]+\.ya?ml|\.gitlab-ci\.yml|\.circleci/config\.yml|Jenkinsfile|\.travis\.yml|azure-pipelines\.yml|\.woodpecker\.ya?ml|bitbucket-pipelines\.yml)$"
LOCKFILES = r"(^|/)(uv\.lock|poetry\.lock|Pipfile\.lock|pdm\.lock|requirements[\w.-]*\.lock|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?|Cargo\.lock|go\.sum|Gemfile\.lock|composer\.lock|gradle\.lockfile|packages\.lock\.json|flake\.lock|mix\.lock)$"
AGENT_DOCS = r"(^|/)(CLAUDE\.md|AGENTS\.md|llms\.txt|llms-full\.txt|\.cursorrules|\.github/copilot-instructions\.md|GEMINI\.md)$"
README = r"^README(\.\w+)?$"
JS_IMPORT = re.compile(r"""(?:import\s[^'"]*?from\s*|import\s*\(|require\()\s*['"](\.{1,2}/[^'"]+)['"]""")


def _module_of(rel: str) -> str:
    d = posixpath.dirname(rel)
    return d or "."


def _top_level_imports(tree: ast.Module):
    """Imports executed at module load; lazy imports in functions and
    `if TYPE_CHECKING:` blocks don't create load-time cycles."""
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, ast.If):
            if "TYPE_CHECKING" not in ast.dump(node.test):
                stack.extend(node.body + node.orelse)
        elif isinstance(node, ast.Try):
            stack.extend(node.body)


def _python_analysis(repo: Repo, files: List[str]):
    """Return (annotated_functions, total_functions, file-level import edges)."""
    annotated = total = 0
    edges: Set[tuple] = set()
    # Every dotted suffix of a file's path resolves to it, so `src/app/x.py`
    # is found by `import app.x` whatever the source root is.
    by_name: Dict[str, str] = {}
    for f in files:
        parts = f[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        for i in range(len(parts)):
            by_name.setdefault(".".join(parts[i:]), f)

    def resolve(dotted: str):
        parts = dotted.split(".")
        for i in range(len(parts), 0, -1):
            hit = by_name.get(".".join(parts[:i]))
            if hit:
                return hit
        return None

    for f in files:
        try:
            tree = ast.parse(repo.read(f))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total += 1
                args = [a for a in node.args.args if a.arg not in ("self", "cls")]
                if node.returns is not None or any(a.annotation is not None for a in args):
                    annotated += 1
        for node in _top_level_imports(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                if node.level:
                    pkg = f[:-3].split("/")
                    pkg = pkg[: len(pkg) - node.level]
                    base = ".".join(pkg + ([node.module] if node.module else []))
                else:
                    base = node.module or ""
                # `from pkg import sub` may name a submodule; try that first.
                names = ["%s.%s" % (base, a.name) if base else a.name for a in node.names]
            for n in names:
                hit = resolve(n)
                if hit and hit != f:
                    edges.add((f, hit))
    return annotated, total, edges


JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue", ".svelte")


def _js_edges(repo: Repo, files: List[str]) -> Set[tuple]:
    edges = set()
    for f in files:
        for target in JS_IMPORT.findall(repo.read(f)):
            dest = posixpath.normpath(posixpath.join(posixpath.dirname(f), target))
            cands = [dest] + [dest + e for e in JS_EXTS] + [dest + "/index" + e for e in JS_EXTS]
            hit = next((c for c in cands if repo.exists(c)), None)
            if hit and hit != f:
                edges.add((f, hit))
    return edges


def _cycles(edges: Set[tuple]) -> List[List[str]]:
    """Tarjan SCC; return components with more than one node."""
    graph: Dict[str, List[str]] = defaultdict(list)
    for a, b in edges:
        graph[a].append(b)
        graph.setdefault(b, [])
    index, low, stack, on, out = {}, {}, [], set(), []
    counter = [0]

    def strong(v):
        work = [(v, iter(graph[v]))]
        index[v] = low[v] = counter[0]; counter[0] += 1
        stack.append(v); on.add(v)
        while work:
            node, it = work[-1]
            nxt = next(it, None)
            if nxt is None:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[node])
                if low[node] == index[node]:
                    comp = []
                    while True:
                        w = stack.pop(); on.discard(w); comp.append(w)
                        if w == node:
                            break
                    if len(comp) > 1:
                        out.append(sorted(comp))
            elif nxt not in index:
                index[nxt] = low[nxt] = counter[0]; counter[0] += 1
                stack.append(nxt); on.add(nxt)
                work.append((nxt, iter(graph[nxt])))
            elif nxt in on:
                low[node] = min(low[node], index[nxt])

    for v in list(graph):
        if v not in index:
            strong(v)
    return out


@register("legibility", "Change legibility")
def detect(repo: Repo, ctx: Context) -> DimensionResult:
    ev: List[Evidence] = []
    gaps: List[str] = []
    score = 0.0

    src = repo.source_files(include_tests=False)
    tests = [f for f in repo.source_files() if repo.is_test(f)]
    file_tokens = {f: estimate_tokens(repo.read(f)) for f in src}
    src_tokens = sum(file_tokens.values())
    test_tokens = sum(estimate_tokens(repo.read(f)) for f in tests)

    module_tokens: Dict[str, int] = defaultdict(int)
    for f, t in file_tokens.items():
        module_tokens[_module_of(f)] += t
    lang_tokens: Dict[str, int] = defaultdict(int)
    for f, t in file_tokens.items():
        lang_tokens[repo.language(f)] += t

    ctx["source_tokens"] = src_tokens

    if not src:
        return DimensionResult("legibility", "Change legibility", 0,
                               "No source code found.", ev, metrics={"source_tokens": 0},
                               gaps=["Nothing to assess."])

    # -- size / chunkability --
    within = sum(1 for t in module_tokens.values() if t <= MODULE_TOKEN_BUDGET)
    mod_ratio = within / float(len(module_tokens))
    big_files = sorted((t, f) for f, t in file_tokens.items() if t > FILE_TOKEN_BUDGET)
    if mod_ratio >= 0.9 and not big_files:
        score += 1
    elif mod_ratio >= 0.7:
        score += 0.5
    if big_files:
        ev.append(Evidence("oversized-files", "%d files over %dk tokens (largest %d)"
                           % (len(big_files), FILE_TOKEN_BUDGET // 1000, big_files[-1][0]),
                           big_files[-1][1]))
        gaps.append("Split files over %dk tokens; an agent must load them whole to edit safely."
                    % (FILE_TOKEN_BUDGET // 1000))
    biggest_mod = max(module_tokens.items(), key=lambda kv: kv[1])
    if biggest_mod[1] > MODULE_TOKEN_BUDGET:
        ev.append(Evidence("oversized-module", "%d tokens" % biggest_mod[1], biggest_mod[0]))

    # -- tests --
    test_ratio = test_tokens / float(src_tokens) if src_tokens else 0.0
    if test_ratio >= 0.3:
        score += 1
    elif test_ratio >= 0.1:
        score += 0.5
    if test_ratio < 0.3:
        gaps.append("Test/source ratio is %.2f; tests are what make agent edits safe." % test_ratio)
    ev.append(Evidence("tests", "%d test files, test/source token ratio %.2f"
                       % (len(tests), test_ratio),
                       next((t for t in tests if not t.endswith("__init__.py")), None)))

    ci = repo.glob(CI)
    if ci:
        score += 0.5
        ev.append(Evidence("ci", "", ci[0]))
    else:
        gaps.append("Add CI so changes are verified automatically.")

    # -- types --
    py = [f for f in src if repo.language(f) == "python"]
    annotated, total_fn, py_edges = _python_analysis(repo, py) if py else (0, 0, set())
    py_typed_share = annotated / float(total_fn) if total_fn else 0.0
    typed_tokens = sum(t for l, t in lang_tokens.items() if l in STATICALLY_TYPED)
    typed_tokens += int(lang_tokens.get("python", 0) * py_typed_share)
    typed_ratio = typed_tokens / float(src_tokens)
    if typed_ratio >= 0.7:
        score += 1
    elif typed_ratio >= 0.3:
        score += 0.5
    if typed_ratio < 0.7:
        gaps.append("Only ~%d%% of code is statically typed or annotated." % round(typed_ratio * 100))
    if total_fn:
        ev.append(Evidence("python-annotations", "%d/%d functions annotated" % (annotated, total_fn)))

    # -- reproducibility --
    locks = repo.glob(LOCKFILES)
    if locks:
        score += 0.5
        ev.append(Evidence("lockfile", "", locks[0]))
    else:
        gaps.append("Commit a dependency lockfile for reproducible builds.")

    # -- coupling --
    js = [f for f in src if repo.language(f) in ("javascript", "typescript")]
    edges = py_edges | (_js_edges(repo, js) if js else set())
    cycles = _cycles(edges)
    if edges:
        if not cycles:
            score += 0.5
        else:
            worst = max(cycles, key=len)
            ev.append(Evidence("import-cycles", "%d cycles; largest spans %d files"
                               % (len(cycles), len(worst)), worst[0]))
            gaps.append("Break import cycles; they widen the context every change needs.")

    # -- docs for agents --
    readme = repo.glob(README)
    agent_docs = repo.glob(AGENT_DOCS)
    if readme:
        score += 0.25
    if agent_docs:
        score += 0.25
        ev.append(Evidence("agent-docs", "", agent_docs[0]))
    else:
        gaps.append("Add AGENTS.md/CLAUDE.md or llms.txt describing build, test and conventions.")

    level = clamp_level(score * 0.9)
    why = {
        0: "Changing this code safely needs most of it in context and has no safety net.",
        1: "Changes need wide context and are weakly verified.",
        2: "Mostly chunkable, with a partial safety net.",
        3: "Modules fit in context and changes are verified by tests/types/CI.",
        4: "Small modules, strong safety net, reproducible build, documented for agents.",
    }[level]

    fan_out: Dict[str, int] = defaultdict(int)
    for a, _ in edges:
        fan_out[a] += 1
    return DimensionResult(
        "legibility", "Change legibility", level, why, ev,
        metrics={
            "source_files": len(src),
            "source_tokens": src_tokens,
            "test_tokens": test_tokens,
            "test_ratio": round(test_ratio, 2),
            "modules": len(module_tokens),
            "modules_within_budget": round(mod_ratio, 2),
            "largest_module": {"path": biggest_mod[0], "tokens": biggest_mod[1]},
            "largest_file": max(file_tokens.items(), key=lambda kv: kv[1])[0],
            "typed_ratio": round(typed_ratio, 2),
            "import_edges": len(edges),
            "max_fan_out": max(fan_out.values()) if fan_out else 0,
            "import_cycles": len(cycles),
            "languages": {k: v for k, v in sorted(lang_tokens.items(), key=lambda kv: -kv[1])},
        },
        gaps=gaps,
    )
