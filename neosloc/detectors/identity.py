# neosloc: ignore (detection vocabulary, not usage)
"""Dimension 4 - Identity.

Can a machine act on this system with its own, narrowly-scoped identity?
Signals: token auth for the API, OAuth2/OIDC, scopes or fine-grained
permissions, service accounts / API keys as managed objects, SCIM, SAML,
and security schemes declared in the contract.
"""
from __future__ import annotations

from ..model import DimensionResult
from .base import Context, register
from .signals import Signal, level_from, score_signals

SIGNALS = [
    Signal("token-auth", "code+deps",
           r"\b(pyjwt|jsonwebtoken|python-jose|jose|jwt|golang-jwt|TokenAuthentication|HTTPBearer|"
           r"APIKeyHeader|X-API-Key|Authorization:\s*Bearer|BearerAuth|passport-http-bearer|"
           r"knox|simplejwt|sanctum)\b", 1.0,
           "Accept token-based auth (bearer/API key) for programmatic clients."),
    Signal("oauth-oidc", "code+deps",
           r"\b(authlib|oauthlib|django-oauth-toolkit|oauth2_provider|social[-_]auth|allauth|"
           r"passport-oauth2|next-auth|@auth/core|openid-client|oidc|openid|keycloak|"
           r"spring-security-oauth2|golang\.org/x/oauth2|go-oidc|omniauth|doorkeeper|laravel/passport|"
           r"ory|authentik|fusionauth|auth0|cognito)\b", 1.0,
           "Support OAuth2/OIDC so integrations get delegated, revocable access."),
    Signal("scopes-permissions", "code",
           r"\bscopes?\s*[=:\[]|Security\([^)]*scopes|@PreAuthorize|permission_classes|has_perm\(|"
           r"@RolesAllowed|casbin|cancancan|pundit|\brbac\b|authorize\(", 0.5,
           "Scope tokens/permissions so an integration can't do everything a user can."),
    Signal("service-accounts", "code",
           r"service[_ ]?account|personal[_ ]?access[_ ]?token|class\s+Api[_]?Key\b|api_keys?\s*=|"
           r"ApiToken\b|machine[_ ]user", 0.5,
           "Model API keys/service accounts as managed, rotatable objects."),
    Signal("scim", "code+deps", r"\bscim\b", 0.5),
    Signal("saml", "code+deps", r"\b(python3-saml|pysaml2|passport-saml|saml2?|onelogin)\b", 0.25),
    Signal("spec-security-schemes", "config", r"securitySchemes\s*:|\"securitySchemes\"", 0.5),
]
WHY = {
    0: "No machine identity: integrations would have to borrow a user's session.",
    1: "Basic programmatic authentication exists.",
    2: "Token auth plus either delegation (OAuth/OIDC) or scoping.",
    3: "Delegated, scoped machine access.",
    4: "Delegated, scoped access with managed machine identities and provisioning (SCIM).",
}


@register("identity", "Identity")
def detect(repo, ctx: Context) -> DimensionResult:
    score, ev, found, gaps = score_signals(repo, ctx, SIGNALS)
    level = level_from(score, (0.5, 1.5, 2.5, 3.5))
    if not ctx.get("has_surface"):
        level = min(level, 1)
    return DimensionResult("identity", "Identity", level, WHY[level], ev,
                           metrics={"score": round(score, 2), "signals": sorted(found)},
                           gaps=gaps if level < 4 else [])
