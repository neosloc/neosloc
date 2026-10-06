"""Discovery and light parsing of machine-readable interface contracts.

No YAML dependency: OpenAPI paths are extracted from JSON by parsing and from
YAML by indentation, which is enough to count and diff operations.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional, Set

from .repo import Repo

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}

OPENAPI_MARK = re.compile(r"""^\s*["']?(openapi|swagger)["']?\s*:\s*["']?[23]\.""", re.M)
ASYNCAPI_MARK = re.compile(r"""^\s*["']?asyncapi["']?\s*:""", re.M)
GRAPHQL_MARK = re.compile(r"\b(type\s+(Query|Mutation)|schema\s*\{)")
PROTO_SERVICE = re.compile(r"^\s*service\s+\w+\s*\{", re.M)
PROTO_RPC = re.compile(r"^\s*rpc\s+\w+\s*\(", re.M)
JSON_SCHEMA_MARK = re.compile(r'"\$schema"\s*:\s*"https?://json-schema\.org')


@dataclass
class Spec:
    kind: str           # openapi | asyncapi | graphql | protobuf | jsonschema
    path: str
    operations: Set[str] = field(default_factory=set)  # "METHOD /path" or rpc names
    deprecated: int = 0


def openapi_operations(text: str, path: str) -> Optional[Set[str]]:
    """Return {"GET /x", ...} or None if `text` is not parseable as OpenAPI."""
    if path.endswith(".json"):
        try:
            doc = json.loads(text)
        except ValueError:
            return None
        paths = doc.get("paths") if isinstance(doc, dict) else None
        if not isinstance(paths, dict):
            return set()
        ops = set()
        for p, item in paths.items():
            if isinstance(item, dict):
                for m in item:
                    if m.lower() in HTTP_METHODS:
                        ops.add("%s %s" % (m.upper(), p))
        return ops
    return _yaml_openapi_operations(text)


def _yaml_openapi_operations(text: str) -> Set[str]:
    ops: Set[str] = set()
    in_paths = False
    path_indent = None
    current = None
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 0:
            in_paths = stripped.startswith("paths:")
            path_indent = None
            current = None
            continue
        if not in_paths:
            continue
        key = stripped.split(":", 1)[0].strip("'\"")
        if path_indent is None and key.startswith("/"):
            path_indent = indent
        if indent == path_indent and key.startswith("/"):
            current = key
        elif current and path_indent is not None and indent > path_indent \
                and key.lower() in HTTP_METHODS and stripped.endswith(":"):
            ops.add("%s %s" % (key.upper(), current))
    return ops


def find_specs(repo: Repo) -> List[Spec]:
    specs: List[Spec] = []
    for rel in repo.files:
        if repo.is_test(rel):
            continue  # fixtures describe test inputs, not this system's contract
        low = rel.lower()
        if low.endswith((".yaml", ".yml", ".json")):
            text = repo.read(rel)
            head = text[:4000]
            if OPENAPI_MARK.search(head):
                ops = openapi_operations(text, rel) or set()
                specs.append(Spec("openapi", rel, ops, _count_deprecated(text)))
            elif ASYNCAPI_MARK.search(head):
                specs.append(Spec("asyncapi", rel))
            elif low.endswith(".json") and JSON_SCHEMA_MARK.search(head):
                specs.append(Spec("jsonschema", rel))
        elif low.endswith((".graphql", ".graphqls", ".gql")):
            text = repo.read(rel)
            if GRAPHQL_MARK.search(text):
                fields = set(re.findall(r"^\s+(\w+)\s*[(:]", text, re.M))
                specs.append(Spec("graphql", rel, fields, text.count("@deprecated")))
        elif low.endswith(".proto"):
            text = repo.read(rel)
            if PROTO_SERVICE.search(text):
                rpcs = set(m.group(0).split()[1].rstrip("(") for m in PROTO_RPC.finditer(text))
                specs.append(Spec("protobuf", rel, rpcs, text.count("deprecated = true")))
    return specs


def _count_deprecated(text: str) -> int:
    return len(re.findall(r"""["']?deprecated["']?\s*:\s*true""", text))
