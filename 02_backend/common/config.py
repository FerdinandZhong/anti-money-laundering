import os
import yaml
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_config: dict | None = None


def get_config() -> dict:
    global _config
    if _config is None:
        _dotenv = os.path.join(PROJECT_ROOT, ".env")
        if os.path.exists(_dotenv):
            load_dotenv(_dotenv)
        _cfg_path = os.path.join(PROJECT_ROOT, "config", "config.yaml")
        with open(_cfg_path) as f:
            _config = yaml.safe_load(f)
        _resolve_workspace_domain(_config)
    return _config


def _resolve_workspace_domain(cfg: dict) -> None:
    """Substitute the <workspace-domain> placeholder in LLM endpoints with the
    CML-provided CDSW_DOMAIN at runtime, so the demo works without hand-editing
    config.yaml on the workbench. No-op locally (placeholder simply stays)."""
    domain = os.environ.get("CDSW_DOMAIN")
    if not domain:
        return
    for provider, pcfg in (cfg.get("llm") or {}).items():
        if isinstance(pcfg, dict) and isinstance(pcfg.get("endpoint"), str):
            pcfg["endpoint"] = pcfg["endpoint"].replace("<workspace-domain>", domain)
    wb = cfg.get("workbench")
    if isinstance(wb, dict) and isinstance(wb.get("host"), str):
        wb["host"] = wb["host"].replace("<workspace-domain>", domain)


def get_db_path() -> str:
    cfg = get_config()
    raw = cfg.get("data", {}).get("db_path", "data/aml.db")
    if os.path.isabs(raw):
        return raw
    return os.path.join(PROJECT_ROOT, raw)
