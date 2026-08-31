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
    return _config


def get_db_path() -> str:
    cfg = get_config()
    raw = cfg.get("data", {}).get("db_path", "data/aml.db")
    if os.path.isabs(raw):
        return raw
    return os.path.join(PROJECT_ROOT, raw)
