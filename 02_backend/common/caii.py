"""Discover live Cloudera AI Inference (CAII) endpoints at runtime.

Mirrors the pattern in CML_AMP_RAG_Studio (llm-service .../caii): the workspace
domain comes from CDSW_DOMAIN, auth is a bearer token from /tmp/jwt (JSON
access_token or plain text) or a CDP_TOKEN_OVERRIDE env var, and endpoints are
listed via POST {domain}/api/v1alpha1/listEndpoints.

Every function fails soft — returns empty / None on any error — so local dev
(no CDSW_DOMAIN, no token) is unaffected.
"""
import os
import json

DEFAULT_NAMESPACE = "serving-default"
_JWT_PATH = "/tmp/jwt"


def caii_domain() -> str | None:
    return os.environ.get("CDSW_DOMAIN") or None


def _read_token() -> str:
    """Bearer token: CDP_TOKEN_OVERRIDE/CDP_TOKEN env, else /tmp/jwt
    (JSON with access_token, or a plain token)."""
    for key in ("CDP_TOKEN_OVERRIDE", "CDP_TOKEN"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    try:
        with open(_JWT_PATH, encoding="utf-8") as f:
            text = f.read().strip()
    except OSError:
        return ""
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        return str(data.get("access_token") or "").strip()
    return ""


def list_caii_endpoints(timeout: float = 10.0) -> list[dict]:
    """Return [{name, base_url, model}] for the workspace's CAII endpoints.

    base_url is the OpenAI-compatible base (the endpoint url minus the trailing
    /chat/completions). Returns [] when the domain/token is unavailable or the
    call fails."""
    domain = caii_domain()
    token = _read_token()
    if not domain or not token:
        return []
    try:
        import requests
        resp = requests.post(
            f"https://{domain}/api/v1alpha1/listEndpoints",
            headers={"Authorization": f"Bearer {token}"},
            json={"namespace": DEFAULT_NAMESPACE},
            timeout=timeout,
        )
        resp.raise_for_status()
        raw = resp.json().get("endpoints", [])
    except Exception:
        return []

    out: list[dict] = []
    for e in raw:
        name = e.get("name")
        url = e.get("url")
        if not name or not url:
            continue
        base_url = url.removesuffix("/chat/completions")
        out.append({
            "name": name,
            "base_url": base_url,
            "model": e.get("model_name") or e.get("model") or "",
        })
    return out


if __name__ == "__main__":
    if caii_domain():
        eps = list_caii_endpoints()
        print(f"[caii] domain={caii_domain()} — {len(eps)} endpoint(s)")
        for e in eps:
            print(f"  · {e['name']} → {e['base_url']} ({e['model'] or 'model?'})")
    else:
        print("[caii] no CDSW_DOMAIN — skipped (local dev)")
