"""What the probing agent may see and do: read-only repo tools, an optional
HTTP tool against a running instance, and the submit tool.

Scope "docs" is what an outside integrator gets: documentation, contracts,
manifests, deployment files and examples, but no implementation. Scope
"source" adds the implementation; comparing the two measures how much the
documentation alone carries.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..repo import Repo
from ..specs import find_specs

MAX_LIST = 300
MAX_LINES = 400
MAX_MATCHES = 60
MAX_BODY = 6000
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

DOCS_EXTRA = re.compile(
    r"(^|/)(\.env[\w.-]*\.(example|sample|template)|[\w.-]*\.schema\.json|Dockerfile[\w.-]*|"
    r"(docker-)?compose[\w.-]*\.ya?ml|Makefile|justfile|Chart\.yaml|values\.ya?ml|llms(-full)?\.txt|"
    r"openapi[\w.-]*\.(ya?ml|json)|swagger[\w.-]*\.(ya?ml|json)|[\w.-]+\.(graphql|gql|proto))$"
)
EXAMPLE_DIR = re.compile(r"(^|/)(examples?|samples?)/")


def docs_scope(repo: Repo) -> List[str]:
    keep = set(repo.doc_files()) | set(repo.manifests())
    keep |= {s.path for s in find_specs(repo)}
    keep |= {f for f in repo.files if DOCS_EXTRA.search(f) or EXAMPLE_DIR.search(f)}
    return sorted(f for f in keep if repo.read(f))


def _nullable(t: str) -> Dict[str, Any]:
    return {"type": [t, "null"]}


STEP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "description", "method", "path", "command", "symbol", "env_vars"],
    "properties": {
        "kind": {"type": "string", "enum": ["http", "cli", "library", "config", "other"]},
        "description": {"type": "string"},
        "method": _nullable("string"),
        "path": _nullable("string"),
        "command": _nullable("string"),
        "symbol": _nullable("string"),
        "env_vars": {"type": "array", "items": {"type": "string"}},
    },
}

SUBMIT_TOOL = {
    "name": "submit_result",
    "description": (
        "Submit your final answer for the task. Call it exactly once, when done. Each step must be "
        "concrete: http steps need method and path; cli steps the full command; library steps the "
        "importable symbol; config steps the environment variable or setting names. The answer is "
        "checked against the implementation, so cite only what you found."),
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["feasible", "summary", "steps", "evidence", "confidence"],
        "properties": {
            "feasible": {"type": "boolean",
                         "description": "False if this system offers no way to do the task."},
            "summary": {"type": "string"},
            "steps": {"type": "array", "items": STEP_SCHEMA},
            "evidence": {"type": "array", "items": {"type": "string"},
                         "description": "Repository paths that support the answer."},
            "confidence": {"type": "number"},
        },
    },
}

READ_TOOLS = [
    {
        "name": "list_files",
        "description": "List readable files (path and approximate size in tokens). Optionally filter "
                       "by a case-insensitive regex on the path.",
        "strict": True,
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["pattern"],
                         "properties": {"pattern": _nullable("string")}},
    },
    {
        "name": "read_file",
        "description": "Read a file with line numbers, %d lines at a time." % MAX_LINES,
        "strict": True,
        "input_schema": {"type": "object", "additionalProperties": False,
                         "required": ["path", "start_line"],
                         "properties": {"path": {"type": "string"}, "start_line": _nullable("integer")}},
    },
    {
        "name": "search",
        "description": "Search readable files with a case-insensitive regex. Returns path:line: text, "
                       "up to %d matches. Optionally restrict to paths matching path_regex." % MAX_MATCHES,
        "strict": True,
        "input_schema": {"type": "object", "additionalProperties": False,
                         "required": ["regex", "path_regex"],
                         "properties": {"regex": {"type": "string"}, "path_regex": _nullable("string")}},
    },
]

HTTP_TOOL = {
    "name": "http_request",
    "description": "Send an HTTP request to the running instance under test. Use a path relative to "
                   "its base URL. Credentials configured by the operator are added automatically.",
    "strict": True,
    "input_schema": {
        "type": "object", "additionalProperties": False,
        "required": ["method", "path", "headers", "body"],
        "properties": {
            "method": {"type": "string", "enum": ["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"]},
            "path": {"type": "string"},
            "headers": {"type": "array", "items": {"type": "string"},
                        "description": "Header lines, e.g. 'Content-Type: application/json'."},
            "body": _nullable("string"),
        },
    },
}


class ToolError(Exception):
    pass


@dataclass
class HttpCall:
    method: str
    path: str
    status: int
    content_type: str = ""


@dataclass
class Workspace:
    repo: Repo
    scope: str  # "docs" | "source"
    base_url: Optional[str] = None
    allow_writes: bool = False
    auth_headers: Dict[str, str] = field(default_factory=dict)
    http_log: List[HttpCall] = field(default_factory=list)

    def __post_init__(self):
        if self.scope == "docs":
            self.visible = docs_scope(self.repo)
        else:
            self.visible = [f for f in self.repo.files if self.repo.read(f)]
        self._visible_set = set(self.visible)

    def tools(self) -> List[dict]:
        tools = list(READ_TOOLS)
        if self.base_url:
            tools.append(HTTP_TOOL)
        tools.append(SUBMIT_TOOL)
        return tools

    def describe(self) -> str:
        what = ("the project's documentation, contracts, manifests, deployment files and examples, "
                "but not its implementation" if self.scope == "docs"
                else "the whole repository, implementation included")
        s = "You can read %s (%d files)." % (what, len(self.visible))
        if self.base_url:
            s += (" A running instance is reachable through http_request%s."
                  % ("" if self.allow_writes else "; only GET, HEAD and OPTIONS are permitted"))
        return s

    # ---- tool execution ----------------------------------------------------

    def run(self, name: str, args: Dict[str, Any]) -> str:
        fn = {"list_files": self._list, "read_file": self._read, "search": self._search,
              "http_request": self._http}.get(name)
        if fn is None or (name == "http_request" and not self.base_url):
            raise ToolError("unknown tool %r" % name)
        return fn(**args)

    def _regex(self, pattern: Optional[str]):
        if not pattern:
            return None
        try:
            return re.compile(pattern, re.I)
        except re.error as e:
            raise ToolError("invalid regex: %s" % e)

    def _list(self, pattern: Optional[str]) -> str:
        rx = self._regex(pattern)
        files = [f for f in self.visible if not rx or rx.search(f)]
        lines = ["%s  (~%d tok)" % (f, len(self.repo.read(f)) // 4) for f in files[:MAX_LIST]]
        if len(files) > MAX_LIST:
            lines.append("... %d more; narrow the pattern" % (len(files) - MAX_LIST))
        return "\n".join(lines) or "no files match"

    def _read(self, path: str, start_line: Optional[int]) -> str:
        path = path.lstrip("./")
        if path not in self._visible_set:
            raise ToolError("not readable in this scope: %s" % path)
        lines = self.repo.read(path).splitlines()
        start = max(1, start_line or 1)
        chunk = lines[start - 1:start - 1 + MAX_LINES]
        out = "\n".join("%d\t%s" % (i, l) for i, l in enumerate(chunk, start))
        end = start - 1 + len(chunk)
        if end < len(lines):
            out += "\n[lines %d-%d of %d; read on with start_line=%d]" % (start, end, len(lines), end + 1)
        return out or "(empty)"

    def _search(self, regex: str, path_regex: Optional[str]) -> str:
        rx = self._regex(regex)
        prx = self._regex(path_regex)
        out = []
        for f in self.visible:
            if prx and not prx.search(f):
                continue
            for i, line in enumerate(self.repo.read(f).splitlines(), 1):
                if rx.search(line):
                    out.append("%s:%d: %s" % (f, i, line.strip()[:200]))
                    if len(out) >= MAX_MATCHES:
                        return "\n".join(out) + "\n[match limit reached; narrow the search]"
        return "\n".join(out) or "no matches"

    def _http(self, method: str, path: str, headers: List[str], body: Optional[str]) -> str:
        method = method.upper()
        if method not in SAFE_METHODS and not self.allow_writes:
            raise ToolError("%s is not permitted in this run (read-only)" % method)
        parsed = urllib.parse.urlsplit(path)
        if parsed.scheme or parsed.netloc:
            raise ToolError("use a path relative to the base URL, not an absolute URL")
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        req = urllib.request.Request(url, method=method,
                                     data=body.encode("utf-8") if body is not None else None)
        for h in headers:
            if ":" in h:
                k, v = h.split(":", 1)
                req.add_header(k.strip(), v.strip())
        for k, v in self.auth_headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status, rh, data = resp.status, resp.headers, resp.read(MAX_BODY + 1)
        except urllib.error.HTTPError as e:
            with e:
                status, rh, data = e.code, e.headers, e.read(MAX_BODY + 1)
        except (urllib.error.URLError, OSError) as e:
            raise ToolError("request failed: %s" % e)
        ctype = rh.get("Content-Type", "")
        self.http_log.append(HttpCall(method, parsed.path or "/", status, ctype))
        keep = [h for h in rh.keys() if h.lower() in (
            "content-type", "location", "link", "retry-after", "etag", "www-authenticate")
            or h.lower().startswith(("x-ratelimit", "ratelimit"))]
        text = data[:MAX_BODY].decode("utf-8", errors="replace")
        if len(data) > MAX_BODY:
            text += "\n[truncated]"
        return "HTTP %d\n%s\n\n%s" % (status, "\n".join("%s: %s" % (h, rh[h]) for h in keep), text)
