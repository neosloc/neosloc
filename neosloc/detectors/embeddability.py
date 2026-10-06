"""Dimension 7 - Embeddability.

Can another system run, configure and compose this one without a human in the
loop? Signals: container image, orchestration/IaC, env-driven config, a
headless entry point, and packaging as a library.
"""
from __future__ import annotations

import re
from typing import List

from ..model import DimensionResult, Evidence, clamp_level
from ..repo import Repo
from .base import Context, register

CHECKS = [
    # (signal, path regex, content regex or None, points)
    ("container-image", r"(^|/)(Dockerfile|Containerfile)(\.[\w.-]+)?$", None, 1.0),
    ("compose", r"(^|/)(docker-)?compose(\.[\w.-]+)?\.ya?ml$", None, 0.5),
    ("helm-chart", r"(^|/)Chart\.yaml$", None, 0.5),
    ("k8s-manifests", r"\.ya?ml$", r"^kind:\s*(Deployment|StatefulSet|Service|CronJob)\b", 0.5),
    ("terraform/pulumi", r"\.tf$|(^|/)Pulumi\.ya?ml$", None, 0.5),
    ("nix/devcontainer", r"(^|/)(flake\.nix|\.devcontainer/devcontainer\.json)$", None, 0.25),
    ("env-template", r"(^|/)\.env[\w.-]*\.(example|sample|template|dist)$|(^|/)\.env\.(example|sample)$", None, 0.5),
    ("config-schema", r"(config|settings|deployment)[\w.-]*\.schema\.json$", None, 0.5),
]
ENV_READ = re.compile(
    r"os\.environ|os\.getenv|getenv\(|process\.env\.|std::env::var|env::var\(|System\.getenv"
    r"|ENV\[|Environment\.GetEnvironmentVariable|\$_ENV\[|env\(['\"]|BaseSettings\b|envconfig"
)
HEADLESS_ENTRY = [
    ("python console script", r"(^|/)(pyproject\.toml|setup\.cfg|setup\.py)$",
     r"\[project\.scripts\]|\[tool\.poetry\.scripts\]|console_scripts|entry_points"),
    ("npm bin", r"(^|/)package\.json$", r"\"bin\"\s*:"),
    ("cargo bin", r"(^|/)src/(main\.rs|bin/[^/]+\.rs)$", None),
    ("go main", r"(^|/)(cmd/[^/]+/)?main\.go$", r"^package main"),
    ("make/just tasks", r"(^|/)(Makefile|justfile|Taskfile\.ya?ml)$", None),
]
LIBRARY = [
    ("python package", r"(^|/)(pyproject\.toml|setup\.py|setup\.cfg)$", r"\[project\]|setup\(|\[metadata\]|\[tool\.poetry\]"),
    ("npm package", r"(^|/)package\.json$", r"\"(main|exports|module|types)\"\s*:"),
    ("rust library", r"(^|/)Cargo\.toml$", r"\[lib\]|\[workspace\]"),
    ("go module", r"(^|/)go\.mod$", None),
    ("maven/gradle artifact", r"(^|/)(pom\.xml|build\.gradle(\.kts)?)$", None),
    ("gem", r"\.gemspec$", None),
    ("composer package", r"(^|/)composer\.json$", r"\"autoload\""),
]


def _match(repo: Repo, path_rx: str, content_rx) -> List[str]:
    paths = repo.glob(path_rx)
    if content_rx is None:
        return paths
    crx = re.compile(content_rx, re.M)
    return [p for p in paths if crx.search(repo.read(p))]


@register("embeddability", "Embeddability")
def detect(repo: Repo, ctx: Context) -> DimensionResult:
    ev: List[Evidence] = []
    gaps: List[str] = []
    score = 0.0
    found = set()

    for signal, prx, crx, pts in CHECKS:
        hits = _match(repo, prx, crx)
        if hits:
            found.add(signal)
            score += pts
            ev.append(Evidence(signal, "%d file(s)" % len(hits), hits[0]))

    env_hits = repo.grep(ENV_READ, repo.source_files(include_tests=False))
    if env_hits:
        found.add("env-config")
        score += 0.5
        ev.append(Evidence("env-config", "%d files read the environment" % len(env_hits),
                           max(env_hits, key=env_hits.get)))

    for name, prx, crx in HEADLESS_ENTRY:
        hits = _match(repo, prx, crx)
        if hits:
            found.add("headless")
            ev.append(Evidence("headless-entry", name, hits[0]))
    if "headless" in found:
        score += 0.5

    for name, prx, crx in LIBRARY:
        hits = _match(repo, prx, crx)
        if hits:
            found.add("library")
            ev.append(Evidence("library-packaging", name, hits[0]))
    if "library" in found:
        score += 0.5

    if "container-image" not in found:
        gaps.append("Provide a container image so it can be run without a bespoke setup.")
    if "env-config" not in found and "env-template" not in found:
        gaps.append("Make configuration injectable via environment variables.")
    if "env-config" in found and "env-template" not in found and "config-schema" not in found:
        gaps.append("Document configuration (.env.example or a config JSON Schema).")
    if not found & {"compose", "helm-chart", "k8s-manifests", "terraform/pulumi"}:
        gaps.append("Ship a compose file, Helm chart or IaC module for composition.")

    level = clamp_level(score * 0.8)
    why = {
        0: "Running it requires manual, undocumented setup.",
        1: "Runnable with some manual work; few deployment artifacts.",
        2: "Containerised or packaged, configurable via environment.",
        3: "Container, env config and composition artifacts available.",
        4: "Fully composable: container, orchestration/IaC, documented config, library form.",
    }[level]
    return DimensionResult("embeddability", "Embeddability", level, why, ev,
                           metrics={"score": round(score, 2), "signals": sorted(found)},
                           gaps=gaps)
