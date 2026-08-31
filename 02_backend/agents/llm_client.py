import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

from typing import Generator
from openai import OpenAI

from common.config import get_config


def _make_client() -> tuple[OpenAI, str, dict]:
    """Return (client, model, kwargs) from config."""
    cfg = get_config()["llm"]
    provider = cfg.get("provider", "caii")
    pcfg = cfg[provider]
    endpoint = pcfg["endpoint"]
    api_key = pcfg.get("api_key") or "no-key"

    # CML JWT fallback
    if not api_key or api_key == "no-key":
        jwt_path = "/tmp/jwt"
        if os.path.exists(jwt_path):
            with open(jwt_path) as f:
                api_key = f.read().strip() or "no-key"

    client = OpenAI(base_url=endpoint, api_key=api_key)
    model = pcfg["model"]
    kwargs = {
        "temperature": cfg.get("temperature", 0.1),
        "max_tokens": cfg.get("max_tokens", 4096),
    }
    return client, model, kwargs


def chat(messages: list[dict], stream: bool = False) -> "str | Generator":
    """
    Send messages to the configured LLM. Returns full string or token generator.
    Reads config from get_config()["llm"]. Uses openai-compatible /v1/chat/completions.
    If stream=False: return response text string.
    If stream=True: yield token strings as they arrive.
    """
    client, model, kwargs = _make_client()

    if not stream:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
            **kwargs,
        )
        return resp.choices[0].message.content or ""

    def _gen() -> Generator:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            **kwargs,
        )
        for chunk in resp:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    return _gen()
