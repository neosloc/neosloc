"""Provider-neutral tool-calling conversations.

Every evaluator role (probe, judge, review) runs the same loop over a
`Conversation`: send a turn, get text and tool calls back, return tool
results. Two backends implement it:

- `anthropic:<model>` uses the official anthropic SDK (optional extra).
- `openrouter:<vendor/model>` speaks OpenRouter's OpenAI-compatible HTTP API with
  the standard library, so any of its tool-capable models can be an evaluator.

A model spec without a prefix is Anthropic when it starts with "claude-" and
OpenRouter when it contains a "/".
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Shared types


@dataclass
class ToolCall:
    id: str
    name: str
    input: Any            # parsed arguments, or None when they weren't valid JSON
    error: Optional[str] = None


@dataclass
class Turn:
    text: str
    calls: List[ToolCall]
    stop: str             # tool_use | end_turn | max_tokens | refusal
    usage: Dict[str, int]
    cost: Optional[float]


class AuthFailure(Exception):
    """Credentials missing or rejected: every call would fail the same way."""


class Budget:
    """A spending cap shared by every model call in a run."""

    def __init__(self, max_usd: float):
        self.max_usd = max_usd
        self.spent = 0.0
        self.unpriced_calls = 0

    def charge(self, cost: Optional[float]) -> None:
        if cost is None:
            self.unpriced_calls += 1
        else:
            self.spent += cost

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.max_usd


def empty_usage() -> Dict[str, int]:
    return {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0}


def parse_spec(spec: str) -> Tuple[str, str]:
    spec = spec.strip()
    if ":" in spec.split("/", 1)[0]:
        provider, model = spec.split(":", 1)
    elif spec.startswith("claude-"):
        provider, model = "anthropic", spec
    elif "/" in spec:
        provider, model = "openrouter", spec
    else:
        raise ValueError("can't tell the provider of %r; write anthropic:<model> or openrouter:<vendor/model>" % spec)
    if provider not in ("anthropic", "openrouter"):
        raise ValueError("unknown provider %r (anthropic or openrouter)" % provider)
    return provider, model


# ---------------------------------------------------------------------------
# Anthropic

ANTHROPIC_PRICES = {  # USD per million tokens: input, output, cache read (writes: 1.25x input)
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000


def anthropic_cost(model: str, usage: Dict[str, int]) -> Optional[float]:
    price = ANTHROPIC_PRICES.get(model)
    if price is None:
        return None
    pin, pout, pread = price
    return (usage["input_tokens"] * pin + usage["cache_creation_input_tokens"] * pin * 1.25
            + usage["cache_read_input_tokens"] * pread + usage["output_tokens"] * pout) / 1e6


def _block_dict(b: Any) -> Dict:
    if isinstance(b, dict):
        return b
    if hasattr(b, "model_dump"):
        return b.model_dump(mode="json", exclude_none=True)
    return dict(vars(b))


class AnthropicConversation:
    def __init__(self, backend: "AnthropicBackend", system: str, tools: List[dict]):
        self.b, self.system, self.tools = backend, system, tools
        self.messages: List[Dict] = []

    def send_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def send_tool_results(self, results: List[Tuple[str, str, bool]]) -> None:
        self.messages.append({"role": "user", "content": [
            dict({"type": "tool_result", "tool_use_id": i, "content": out}, **({"is_error": True} if err else {}))
            for i, out, err in results]})

    def next(self) -> Turn:
        kwargs = dict(model=self.b.model, max_tokens=MAX_TOKENS, tools=self.tools, messages=self.messages,
                      system=[{"type": "text", "text": self.system}],
                      output_config={"effort": self.b.effort}, cache_control={"type": "ephemeral"})
        try:
            if self.b.fallbacks:
                resp = self.b.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                resp = self.b.client.messages.create(**kwargs)
        except Exception as e:
            name = type(e).__name__
            if name in ("AuthenticationError", "PermissionDeniedError") or (
                    isinstance(e, TypeError) and "authentication method" in str(e)):
                raise AuthFailure(str(e))
            raise
        u = getattr(resp, "usage", None)
        usage = {k: int(getattr(u, k, 0) or 0) for k in empty_usage()} if u is not None else empty_usage()
        if resp.stop_reason == "refusal":
            return Turn("", [], "refusal", usage, anthropic_cost(self.b.model, usage))
        self.messages.append({"role": "assistant", "content": resp.content})
        calls = [ToolCall(b.id, b.name, b.input) for b in resp.content if getattr(b, "type", None) == "tool_use"]
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text")
        stop = {"tool_use": "tool_use", "max_tokens": "max_tokens"}.get(resp.stop_reason, "end_turn")
        return Turn(text, calls, stop, usage, anthropic_cost(self.b.model, usage))

    def dump(self) -> List[Dict]:
        out = []
        for m in self.messages:
            c = m["content"]
            out.append({"role": m["role"], "content": c if isinstance(c, str) else [_block_dict(b) for b in c]})
        return out


@dataclass
class AnthropicBackend:
    model: str
    effort: str = "medium"
    fallbacks: bool = True
    client: Any = None
    provider: str = "anthropic"

    def __post_init__(self):
        if self.client is None:
            try:
                import anthropic
            except ImportError:
                raise SystemExit(
                    "neosloc: anthropic models need the anthropic SDK (Python >= 3.10):\n"
                    "  pip install 'neosloc[agentic]'\n"
                    "or use an OpenRouter model (openrouter:<vendor/model>), which needs no extra package.")
            self.client = anthropic.Anthropic()

    @property
    def label(self) -> str:
        return "anthropic:" + self.model

    def conversation(self, system: str, tools: List[dict]) -> AnthropicConversation:
        return AnthropicConversation(self, system, tools)


# ---------------------------------------------------------------------------
# OpenRouter

OPENROUTER_URL = "https://openrouter.ai/api/v1"
APP_HEADERS = {"HTTP-Referer": "https://github.com/sirmmo/neosloc", "X-Title": "neosloc"}
_MODEL_CACHE: Dict[str, Dict] = {}


def _http_json(url: str, payload: Optional[dict], headers: Dict[str, str], timeout: float = 600) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers=dict(headers, **({"Content-Type": "application/json"} if data else {})))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def openrouter_models(base_url: str = OPENROUTER_URL) -> Dict[str, Dict]:
    if base_url not in _MODEL_CACHE:
        listing = _http_json(base_url + "/models", None, APP_HEADERS, timeout=60)
        _MODEL_CACHE[base_url] = {m["id"]: m for m in listing.get("data", [])}
    return _MODEL_CACHE[base_url]


def _openai_tool(tool: dict) -> dict:
    # `strict` is left out: not every routed provider accepts strict schemas.
    # Arguments are validated locally instead (see validate()).
    return {"type": "function", "function": {"name": tool["name"], "description": tool.get("description", ""),
                                             "parameters": tool["input_schema"]}}


class OpenRouterConversation:
    def __init__(self, backend: "OpenRouterBackend", system: str, tools: List[dict]):
        self.b = backend
        self.tools = [_openai_tool(t) for t in tools]
        self.messages: List[Dict] = [{"role": "system", "content": system}]

    def send_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def send_tool_results(self, results: List[Tuple[str, str, bool]]) -> None:
        for i, out, err in results:
            self.messages.append({"role": "tool", "tool_call_id": i, "content": ("Error: " if err and not out.startswith("Error") else "") + out})

    def next(self) -> Turn:
        body = {"model": self.b.model, "messages": self.messages, "tools": self.tools,
                "tool_choice": "auto", "max_tokens": MAX_TOKENS}
        if self.b.effort and "reasoning" in self.b.supported:
            body["reasoning"] = {"effort": self.b.effort}
        data = self.b.post("/chat/completions", body)
        if "error" in data and not data.get("choices"):
            raise RuntimeError("OpenRouter error: %s" % data["error"])
        choice = data["choices"][0]
        msg = choice.get("message") or {}
        u = data.get("usage") or {}
        usage = empty_usage()
        usage["input_tokens"] = int(u.get("prompt_tokens") or 0)
        usage["output_tokens"] = int(u.get("completion_tokens") or 0)
        cached = int(((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
        usage["cache_read_input_tokens"] = cached
        usage["input_tokens"] -= min(cached, usage["input_tokens"])
        cost = u.get("cost")
        cost = float(cost) if cost is not None else self.b.estimate_cost(usage)
        reason = choice.get("finish_reason") or choice.get("native_finish_reason") or "stop"
        if reason == "content_filter":
            return Turn("", [], "refusal", usage, cost)
        if reason == "error":
            raise RuntimeError("OpenRouter provider error: %s" % (data.get("error") or msg))
        # Keep the assistant message as returned (incl. reasoning_details) so
        # reasoning carries across tool calls.
        keep = {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls", "reasoning_details")}
        keep["role"] = "assistant"
        self.messages.append(keep)
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
                calls.append(ToolCall(tc.get("id", ""), fn.get("name", ""), args))
            except ValueError as e:
                calls.append(ToolCall(tc.get("id", ""), fn.get("name", ""), None, "arguments were not valid JSON: %s" % e))
        stop = "tool_use" if calls else ("max_tokens" if reason == "length" else "end_turn")
        return Turn(msg.get("content") or "", calls, stop, usage, cost)

    def dump(self) -> List[Dict]:
        return self.messages


@dataclass
class OpenRouterBackend:
    model: str
    effort: str = "medium"
    api_key: Optional[str] = None
    base_url: str = OPENROUTER_URL
    provider: str = "openrouter"
    supported: List[str] = field(default_factory=list)
    pricing: Dict[str, float] = field(default_factory=dict)
    retries: int = 3

    def __post_init__(self):
        self.api_key = self.api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise AuthFailure("OPENROUTER_API_KEY is not set")
        try:
            info = openrouter_models(self.base_url).get(self.model)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise SystemExit("neosloc: could not reach OpenRouter to look up %s: %s" % (self.model, e))
        if info is None:
            raise SystemExit("neosloc: OpenRouter has no model %r (see https://openrouter.ai/models)" % self.model)
        self.supported = info.get("supported_parameters") or []
        if "tools" not in self.supported:
            raise SystemExit("neosloc: %s does not support tool calling on OpenRouter; pick a model that does"
                             % self.model)
        self.pricing = {k: float(v) for k, v in (info.get("pricing") or {}).items()
                        if k in ("prompt", "completion", "input_cache_read") and v not in (None, "")}

    @property
    def label(self) -> str:
        return "openrouter:" + self.model

    def estimate_cost(self, usage: Dict[str, int]) -> Optional[float]:
        if "prompt" not in self.pricing:
            return None
        return (usage["input_tokens"] * self.pricing["prompt"]
                + usage["cache_read_input_tokens"] * self.pricing.get("input_cache_read", self.pricing["prompt"])
                + usage["output_tokens"] * self.pricing.get("completion", 0.0))

    def post(self, path: str, body: dict) -> dict:
        headers = dict(APP_HEADERS, Authorization="Bearer " + self.api_key)
        delay = 2.0
        for attempt in range(self.retries + 1):
            try:
                return _http_json(self.base_url + path, body, headers)
            except urllib.error.HTTPError as e:
                with e:
                    detail = e.read(2000).decode("utf-8", errors="replace")
                if e.code in (401, 403):
                    raise AuthFailure("OpenRouter rejected the key (%d): %s" % (e.code, detail))
                if e.code == 402:
                    raise AuthFailure("OpenRouter account has insufficient credits: %s" % detail)
                if e.code in (408, 429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise RuntimeError("OpenRouter HTTP %d: %s" % (e.code, detail))
            except (urllib.error.URLError, OSError) as e:
                if attempt < self.retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise RuntimeError("OpenRouter unreachable: %s" % e)
        raise RuntimeError("unreachable")

    def conversation(self, system: str, tools: List[dict]) -> OpenRouterConversation:
        return OpenRouterConversation(self, system, tools)


def make_backend(spec: str, effort: str = "medium", fallbacks: bool = True):
    provider, model = parse_spec(spec)
    try:
        if provider == "anthropic":
            return AnthropicBackend(model, effort, fallbacks)
        return OpenRouterBackend(model, effort)
    except AuthFailure as e:
        raise SystemExit("neosloc: %s" % e)


# ---------------------------------------------------------------------------
# Argument validation (OpenRouter tools aren't strict, so check locally)

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int,
          "number": (int, float), "null": type(None)}


def validate(schema: dict, value: Any, where: str = "input") -> Optional[str]:
    """Check `value` against the JSON-schema subset our tool schemas use."""
    types = schema.get("type")
    if types is not None:
        types = types if isinstance(types, list) else [types]
        ok = any(isinstance(value, _TYPES[t]) and not (t in ("integer", "number") and isinstance(value, bool))
                 for t in types)
        if not ok:
            return "%s should be %s" % (where, " or ".join(types))
    if "enum" in schema and value not in schema["enum"]:
        return "%s should be one of %s" % (where, ", ".join(map(str, schema["enum"])))
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                return "%s is missing %r" % (where, k)
        props = schema.get("properties", {})
        for k, v in value.items():
            if k in props:
                err = validate(props[k], v, "%s.%s" % (where, k))
                if err:
                    return err
            elif schema.get("additionalProperties") is False:
                return "%s has unexpected field %r" % (where, k)
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            err = validate(schema["items"], v, "%s[%d]" % (where, i))
            if err:
                return err
    return None
