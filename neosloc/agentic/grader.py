"""Grounding: check an agent's answer against the implementation.

The agent may only have seen the docs; the grader always sees everything. A
step is grounded when the thing it names exists: the HTTP route is declared
(or in the contract), the CLI program and its flags exist, the env vars are
read somewhere, the symbol is defined. With a live instance, HTTP steps must
also have been exercised successfully.
"""
from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from ..repo import Repo
from ..specs import find_specs
from .workspace import HttpCall

PARAM_RE = re.compile(r"\{[^}/]+\}|<[^>/]+>|:[A-Za-z_]\w*|\[[^\]/]+\]|\$\{[^}]+\}")
DYNAMIC_SEG = re.compile(r"^(\d+|[0-9a-f]{8}-[0-9a-f-]{27,}|[0-9a-f]{24,})$", re.I)
ROUTE_STRING = re.compile(r"""['"`](\^?/?[A-Za-z0-9_{}<>:\[\]$./-]*)['"`]""")
FLAG_RE = re.compile(r"(?<![\w-])(--[A-Za-z][\w-]*)")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
LAUNCHERS = {"python", "python3", "-m", "npx", "pnpm", "yarn", "npm", "bunx", "uv", "poetry", "pipx",
             "run", "exec", "sudo", "env", "bundle", "go", "cargo", "dotnet", "java", "-jar", "php"}


def normalize_path(path: str) -> str:
    path = re.sub(r"^\w+://[^/]+", "", path.strip()).split("?", 1)[0].split("#", 1)[0]
    path = path.lstrip("^").rstrip("$")
    path = PARAM_RE.sub("{}", path)
    segs = [("{}" if DYNAMIC_SEG.match(s) else s) for s in path.strip("/").split("/") if s]
    return "/" + "/".join(segs)


@dataclass
class Grade:
    grounded: int = 0
    checked: int = 0
    problems: List[str] = field(default_factory=list)


class Grader:
    def __init__(self, repo: Repo, route_files: Optional[List[str]] = None):
        self.repo = repo
        self.src = repo.source_files(include_tests=False)
        self.spec_ops: Set[tuple] = set()
        for s in find_specs(repo):
            if s.kind == "openapi":
                for op in s.operations:
                    m, p = op.split(" ", 1)
                    self.spec_ops.add((m, normalize_path(p)))
        self.route_templates: Set[str] = set()
        for f in route_files or []:
            for line in repo.read(f).splitlines():
                for lit in ROUTE_STRING.findall(line):
                    if lit.strip("/^$") and not lit.startswith("."):
                        self.route_templates.add(normalize_path(lit))
        self._all_text = None

    # ---- helpers -----------------------------------------------------------

    def _text(self) -> str:
        if self._all_text is None:
            files = self.src + self.repo.manifests() + self.repo.config_files() + self.repo.doc_files()
            self._all_text = "\n".join(self.repo.read(f) for f in dict.fromkeys(files))
        return self._all_text

    def _code_text(self) -> str:
        return "\n".join(self.repo.read(f) for f in self.src + self.repo.config_files())

    @staticmethod
    def _suffix_match(candidate: str, template: str) -> bool:
        c = candidate.strip("/").split("/")
        t = template.strip("/").split("/")
        if not t or t == [""] or len(t) > len(c):
            return False
        return all(a == b or b == "{}" or a == "{}" for a, b in zip(c[-len(t):], t))

    # ---- step checks -------------------------------------------------------

    def http(self, method: Optional[str], path: Optional[str], live: Optional[List[HttpCall]]) -> Optional[str]:
        if not path:
            return "http step without a path"
        cand = normalize_path(path)
        method = (method or "").upper()
        in_spec = any((not method or m == method) and self._suffix_match(cand, p) for m, p in self.spec_ops)
        in_code = any(self._suffix_match(cand, t) for t in self.route_templates)
        if not (in_spec or in_code):
            return "%s %s is not a declared route" % (method or "?", path)
        if live is not None:
            ok = [c for c in live if self._suffix_match(normalize_path(c.path), cand)
                  and (not method or c.method == method)]
            if not ok:
                return "%s %s was never exercised against the live instance" % (method or "?", path)
        return None

    def cli(self, command: Optional[str]) -> Optional[str]:
        if not command:
            return "cli step without a command"
        try:
            words = shlex.split(command.splitlines()[0])
        except ValueError:
            words = command.split()
        if not words:
            return "empty command"
        if words[0] == "docker" or words[:2] == ["docker-compose"]:
            ok = self.repo.glob(r"(^|/)(Dockerfile|Containerfile|(docker-)?compose[\w.-]*\.ya?ml)$")
            return None if ok else "docker command but no Dockerfile/compose file"
        if words[0] in ("make", "just"):
            target = words[1] if len(words) > 1 else None
            mk = self.repo.glob(r"(^|/)(Makefile|justfile)$")
            if not mk:
                return "%s command but no %s" % (words[0], "Makefile" if words[0] == "make" else "justfile")
            if target and not re.search(r"^%s\s*:" % re.escape(target), self.repo.read(mk[0]), re.M):
                return "no %s target %r" % (words[0], target)
            return None
        program = next((w for w in words if w not in LAUNCHERS and not w.startswith("-")
                        and "=" not in w), None)
        if program is None:
            return "could not identify the program in %r" % command
        text = self._text()
        base = posixpath.basename(program.replace("\\", "/"))
        stem = posixpath.splitext(base)[0]
        known = (self.repo.exists(program.lstrip("./")) or any(posixpath.basename(f) == base for f in self.repo.files)
                 or re.search(r"""(^|[\s"'\[])%s\s*=|['"]%s['"]\s*:""" % (re.escape(stem), re.escape(stem)),
                              "\n".join(self.repo.read(m) for m in self.repo.manifests()), re.M)
                 or any(f.split("/")[0] == stem or ("/%s/" % stem) in ("/" + f) for f in self.src))
        if not known:
            return "program %r is not provided by this repository" % program
        missing = [fl for fl in FLAG_RE.findall(command) if fl not in text]
        if missing:
            return "flags not found in the code: %s" % ", ".join(missing)
        return None

    def library(self, symbol: Optional[str]) -> Optional[str]:
        if not symbol:
            return "library step without a symbol"
        name = re.split(r"[.:/#]", symbol.strip().rstrip("()"))[-1]
        if not name:
            return "unparseable symbol %r" % symbol
        rx = re.compile(r"\b(def|class|function|func|fn|const|let|var|interface|type|struct|trait|export\s+\w+)\s+"
                        r"(\([^)]*\)\s*)?%s\b|\b%s\s*[:=]\s*(function|\(|async)" % (re.escape(name), re.escape(name)))
        if not any(rx.search(self.repo.read(f)) for f in self.src):
            return "symbol %r is not defined in the code" % symbol
        return None

    def env(self, names: List[str]) -> Optional[str]:
        names = [n for n in names if ENV_NAME.match(n)]
        if not names:
            return None
        code = self._code_text()
        missing = [n for n in names if n not in code]
        return "not read by the code: %s" % ", ".join(missing) if missing else None

    # ---- whole answer ------------------------------------------------------

    def grade(self, answer: Dict, live: Optional[List[HttpCall]] = None) -> Grade:
        g = Grade()
        for step in answer.get("steps", []):
            kind = step.get("kind")
            checks = []
            if kind == "http":
                checks.append(self.http(step.get("method"), step.get("path"), live))
            elif kind == "cli":
                checks.append(self.cli(step.get("command")))
            elif kind == "library":
                checks.append(self.library(step.get("symbol")))
            elif kind == "config" and not step.get("env_vars"):
                checks.append("config step names no settings")
            if step.get("env_vars"):
                checks.append(self.env(step["env_vars"]))
            if not checks:
                continue  # "other" steps can't be verified; they neither help nor hurt
            g.checked += 1
            errors = [c for c in checks if c]
            if errors:
                g.problems.extend(errors)
            else:
                g.grounded += 1
        missing = [p for p in answer.get("evidence", []) if not self.repo.exists(p.lstrip("./").split(":")[0])]
        if missing:
            g.problems.append("cited files do not exist: %s" % ", ".join(missing[:3]))
        return g
