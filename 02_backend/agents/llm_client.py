import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import time
from typing import Generator
from openai import OpenAI, APIConnectionError, APITimeoutError

from common.config import get_config


_provider_override: str | None = None
# in-memory CAII endpoint pick from the UI: {"base_url": str, "model": str}
_endpoint_override: dict | None = None


def set_provider(provider: str) -> None:
    """Override the active LLM provider at runtime (in-memory, resets on restart)."""
    global _provider_override, _endpoint_override
    _provider_override = provider
    _endpoint_override = None  # switching provider clears any endpoint pick


def set_endpoint(base_url: str, model: str) -> None:
    """Pin a specific (CAII) endpoint base_url + model at runtime (in-memory)."""
    global _endpoint_override
    _endpoint_override = {"base_url": base_url, "model": model}


def _resolve_registered() -> dict | None:
    """Active model registered via the Models view (ops DB), if any.
    Returns {base_url, model, api_key} or None. Fails soft."""
    try:
        from common.db import get_connection
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT model_identifier, api_base, api_key FROM llm_models WHERE is_active=1 LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {"base_url": row["api_base"] or None,
                "model": row["model_identifier"],
                "api_key": row["api_key"] or None}
    except Exception:
        return None


def _make_client() -> tuple[OpenAI, str, dict]:
    """Return (client, model, kwargs). A registered active model (Models view)
    wins; else a UI endpoint pick; else the static provider config."""
    cfg = get_config()["llm"]
    reg = _resolve_registered()
    if reg:
        # A registered model is authoritative — use it exclusively. base_url None
        # means the OpenAI SDK default (api.openai.com); do NOT fall through to the
        # provider config (whose endpoint may be an unresolved placeholder).
        endpoint = reg.get("base_url") or None
        api_key = reg.get("api_key") or "no-key"
        model = reg.get("model")
    else:
        provider = _provider_override or cfg.get("provider", "caii")
        pcfg = cfg.get(provider, {})
        endpoint = (_endpoint_override or {}).get("base_url") or pcfg.get("endpoint")
        api_key = pcfg.get("api_key") or "no-key"
        model = (_endpoint_override or {}).get("model") or pcfg.get("model")

    # CML JWT fallback (only when no explicit key was resolved)
    if not api_key or api_key == "no-key":
        jwt_path = "/tmp/jwt"
        if os.path.exists(jwt_path):
            with open(jwt_path) as f:
                api_key = f.read().strip() or "no-key"

    # Cache one client per (endpoint, api_key) so the 4 parallel workers share a
    # connection pool instead of each opening a fresh TLS handshake at once
    # (concurrent fresh handshakes were dropping ~2 of 4 worker calls).
    cache_key = (endpoint or "", api_key or "")
    client = _client_cache.get(cache_key)
    if client is None:
        client = OpenAI(base_url=endpoint, api_key=api_key, max_retries=3)
        _client_cache[cache_key] = client
    return client, model


_client_cache: dict[tuple, OpenAI] = {}


# Newer OpenAI models (o-series, gpt-5.x) reject `max_tokens` (want
# `max_completion_tokens`) and only allow the default temperature. We flip these
# once on the first 400 and remember, so the other workers don't re-probe.
_token_param = "max_tokens"
_drop_temperature = False


def _create(client, params, attempts: int = 3):
    """Call chat.completions.create, retrying transient connection/timeout errors
    (the 4 workers open OpenAI connections in parallel; one occasionally flaps)."""
    for i in range(attempts):
        try:
            return client.chat.completions.create(**params)
        except (APIConnectionError, APITimeoutError):
            if i == attempts - 1:
                raise
            time.sleep(0.6 * (i + 1))


def _completion(client, model, messages, stream: bool, tools=None):
    global _token_param, _drop_temperature
    cfg = get_config()["llm"]
    params = {"model": model, "messages": messages, "stream": stream,
              _token_param: cfg.get("max_tokens", 4096)}
    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"
    if not _drop_temperature:
        params["temperature"] = cfg.get("temperature", 0.1)
    try:
        return _create(client, params)
    except Exception as e:
        msg = str(e).lower()
        changed = False
        if "max_completion_tokens" in msg or ("max_tokens" in msg and "unsupported" in msg):
            # Deterministic (NOT a toggle): the 4 workers share this global and run
            # in parallel — toggling would let one thread flip it back and re-send
            # the rejected param. This error only ever means "use max_completion_tokens".
            tok = params.pop("max_tokens", None)
            if tok is None:
                tok = params.pop("max_completion_tokens", None)
            _token_param = "max_completion_tokens"
            params["max_completion_tokens"] = tok
            changed = True
        if "temperature" in msg and any(k in msg for k in ("unsupported", "does not support", "only the default", "only supports")):
            params.pop("temperature", None)
            _drop_temperature = True
            changed = True
        if not changed:
            raise
        return _create(client, params)


def probe(base_url: str | None, model: str, api_key: str | None) -> tuple[bool, str]:
    """One-off connectivity test for a registered model row: sends a 1-token
    chat and returns (True, reply) on success or (False, "<ErrorType>: <msg>")."""
    try:
        client = OpenAI(base_url=base_url or None, api_key=api_key or "no-key", timeout=15, max_retries=0)
        # Route through _completion so the max_tokens→max_completion_tokens /
        # temperature shim applies — otherwise gpt-5.x/o-series report a false 400
        # and a genuinely-working model looks broken.
        resp = _completion(client, model, [{"role": "user", "content": "reply OK"}], stream=False)
        return True, (resp.choices[0].message.content or "OK")
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def chat_with_tools(messages: list[dict], tools: list[dict], execute,
                    max_iters: int = 4, on_event=None) -> str:
    """OpenAI-compatible tool-calling loop for the verification worker.

    `tools` are OpenAI tool schemas; `execute(name, args) -> str` runs a tool and
    returns its text result; `on_event(name, args, result)` (optional) is called
    per tool call so the caller can surface progress. Loops until the model stops
    requesting tools or `max_iters` is hit, then returns the final assistant text.

    # ponytail: needs a tool-calling-capable model. Any failure in the loop
    # (e.g. a 400 rejecting `tools`) falls back to one plain chat() with no tools
    # and returns that — the worker then reports no verdicts, never errors.
    """
    import json
    client, model = _make_client()
    msgs = list(messages)
    try:
        for _ in range(max_iters):
            resp = _completion(client, model, msgs, stream=False, tools=tools)
            m = resp.choices[0].message
            calls = getattr(m, "tool_calls", None)
            if not calls:
                return m.content or ""
            msgs.append({
                "role": "assistant",
                "content": m.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in calls
                ],
            })
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = execute(c.function.name, args)
                text = result if isinstance(result, str) else json.dumps(result, default=str)
                if on_event:
                    on_event(c.function.name, args, text)
                msgs.append({"role": "tool", "tool_call_id": c.id, "content": text})
        # Hit the iteration cap — ask once more with no tools for a final answer.
        return _completion(client, model, msgs, stream=False).choices[0].message.content or ""
    except Exception:  # noqa: BLE001 — tools unsupported / loop failure → plain chat
        try:
            return _completion(client, model, messages, stream=False).choices[0].message.content or ""
        except Exception:
            return ""


def chat(messages: list[dict], stream: bool = False) -> "str | Generator":
    """
    Send messages to the configured LLM. Returns full string or token generator.
    Reads config from get_config()["llm"]. Uses openai-compatible /v1/chat/completions.
    If stream=False: return response text string.
    If stream=True: yield token strings as they arrive.
    """
    client, model = _make_client()

    if not stream:
        resp = _completion(client, model, messages, stream=False)
        return resp.choices[0].message.content or ""

    def _gen() -> Generator:
        resp = _completion(client, model, messages, stream=True)
        for chunk in resp:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    return _gen()
