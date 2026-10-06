# neosloc: ignore (detection vocabulary, not usage)
"""Dimension 6 - Agent ergonomics.

Given a surface exists, how forgiving and self-explanatory is it for an
automated caller? Machine-readable errors, safe retries, predictable
pagination, explicit rate limits, validation, dry-runs, and docs for agents.
"""
from __future__ import annotations

from ..model import DimensionResult
from .base import Context, register
from .signals import Signal, level_from, score_signals

SIGNALS = [
    Signal("problem-details", "code+deps",
           r"application/problem\+json|ProblemDetail|problem_details|rfc[ -]?(7807|9457)|http-problem", 1.0,
           "Return errors as RFC 9457 problem+json (type, title, detail) so agents can branch on them.",
           group="errors"),
    Signal("error-envelope", "code",
           r"exception_handler|@ControllerAdvice|@ExceptionHandler|errorHandler|ErrorResponse\b|"
           r"APIException|HttpException|setErrorHandler|ProblemJSON", 0.5, group="errors"),
    Signal("validation", "code+deps",
           r"\b(pydantic|marshmallow|serializers\.|zod|joi|yup|class-validator|ajv|jsonschema|"
           r"go-playground/validator|validator\.v\d|@Valid)\b", 0.5,
           "Validate requests against a schema so errors name the offending field."),
    Signal("idempotency", "code", r"idempotency[-_ ]?key|Idempotency-Key|idempotent", 0.75,
           "Accept Idempotency-Key on writes so agents can retry safely."),
    Signal("pagination", "code",
           r"\bcursor\b|next_page|page_size|PageNumberPagination|CursorPagination|LimitOffsetPagination|"
           r"paginat|Link:\s*<|rel=\"next\"", 0.5,
           "Paginate list endpoints consistently (cursor-based, with next links)."),
    Signal("rate-limit-headers", "code+deps",
           r"X-RateLimit|RateLimit-(Limit|Remaining|Reset)|Retry-After|slowapi|django-ratelimit|"
           r"express-rate-limit|rate-limiter-flexible|throttle_classes|golang\.org/x/time/rate", 0.5,
           "Expose rate limits (RateLimit-*/Retry-After) so agents can back off."),
    Signal("dry-run", "code", r"dry[-_ ]?run|validate_only|--check\b|preview_only", 0.5),
    Signal("conditional-requests", "code", r"\bETag\b|If-Match|If-None-Match", 0.25),
    Signal("agent-docs", "path", r"(^|/)(llms(-full)?\.txt|\.well-known/ai-plugin\.json|AGENTS\.md)$", 0.5,
           "Publish llms.txt (or equivalent) pointing agents at the contract and usage docs."),
]
WHY = {
    0: "No programmatic surface, or one that gives agents nothing to recover with.",
    1: "Basic structure; agents must guess at errors, retries and limits.",
    2: "Errors and lists are predictable; retries and limits are implicit.",
    3: "Structured errors, validation, pagination and safe-retry or limit signalling.",
    4: "Designed for automated callers: standard errors, idempotency, limits, dry-run, agent docs.",
}


@register("ergonomics", "Agent ergonomics")
def detect(repo, ctx: Context) -> DimensionResult:
    if not ctx.get("has_surface"):
        return DimensionResult("ergonomics", "Agent ergonomics", 0, WHY[0], [],
                               metrics={"score": 0, "signals": []},
                               gaps=["Ergonomics only matter once a programmatic surface exists."])
    score, ev, found, gaps = score_signals(repo, ctx, SIGNALS)
    level = level_from(score, (0.5, 1.5, 2.5, 3.75))
    return DimensionResult("ergonomics", "Agent ergonomics", level, WHY[level], ev,
                           metrics={"score": round(score, 2), "signals": sorted(found)},
                           gaps=gaps if level < 4 else [])
