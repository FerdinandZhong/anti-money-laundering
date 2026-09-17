"""Load the small, versioned AML semantic contract from repository YAML."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEMANTIC_ROOT = PROJECT_ROOT / "semantic"


def _load_yaml(name: str) -> dict[str, Any]:
    with (SEMANTIC_ROOT / name).open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Semantic contract {name} must contain a mapping")
    return value


@lru_cache(maxsize=1)
def semantic_model() -> dict[str, Any]:
    return _load_yaml("aml_semantic_model.ossie.yaml")


@lru_cache(maxsize=1)
def ontology() -> dict[str, Any]:
    return _load_yaml("aml_ontology.yaml")


@lru_cache(maxsize=1)
def context_registry() -> dict[str, Any]:
    return _load_yaml("aml_context_registry.yaml")


def clear_cache() -> None:
    """Test/dev helper for reloading edited semantic files."""
    semantic_model.cache_clear()
    ontology.cache_clear()
    context_registry.cache_clear()
