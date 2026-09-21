"""Load the small, versioned AML semantic contract from repository YAML."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEMANTIC_ROOT = PROJECT_ROOT / "semantic"


def contract_sources() -> list[dict[str, str]]:
    """Publish only the three checked-in semantic contracts, never arbitrary files."""
    contracts = [
        ("aml_semantic_model.ossie.yaml", "Ossie-style AML semantic model",
         "Our AML example: datasets, fields, relationships, metrics and AI guidance. Not an official or validated native Ossie contract."),
        ("aml_ontology.yaml", "AML ontology extension",
         "Our business concepts, synonyms, relations and claim constraints."),
        ("aml_context_registry.yaml", "AML investigation-context extension",
         "Our investigation intents, permitted concepts and interpretation limits."),
    ]
    return [{"filename": filename, "title": title, "description": description,
             "content": (SEMANTIC_ROOT / filename).read_text(encoding="utf-8")}
            for filename, title, description in contracts]


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
