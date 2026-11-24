"""Configuration loading for AI Over Coffee."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

VALID_KINDS = {"company", "research", "industry"}


def project_root() -> Path:
    """Project root: $AOC_HOME if set, else two levels above this file's package."""
    env = os.environ.get("AOC_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


def load_config(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    cfg = _load_yaml(root / "config" / "config.yaml")
    local = root / "config" / "config.local.yaml"
    if local.exists():
        cfg = deep_merge(cfg, _load_yaml(local))
    return cfg


def validate_sources(sources: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for src in sources:
        sid = src.get("id")
        if not sid or not isinstance(sid, str):
            raise ValueError(f"source without a valid id: {src!r}")
        if sid in seen:
            raise ValueError(f"duplicate source id: {sid}")
        seen.add(sid)
        if not src.get("name"):
            raise ValueError(f"source {sid}: missing name")
        if src.get("kind") not in VALID_KINDS:
            raise ValueError(f"source {sid}: kind must be one of {sorted(VALID_KINDS)}")
        rel = src.get("reliability", 3)
        if not isinstance(rel, int) or not 1 <= rel <= 5:
            raise ValueError(f"source {sid}: reliability must be an integer 1..5")
        for field in ("feed_url", "homepage"):
            url = src.get(field)
            if url is not None and not str(url).startswith(("http://", "https://")):
                raise ValueError(f"source {sid}: {field} must be an http(s) URL or null")


def load_sources(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or project_root()
    data = _load_yaml(root / "config" / "sources.yaml")
    sources = data.get("sources")
    if not isinstance(sources, list):
        raise ValueError("config/sources.yaml must contain a 'sources' list")
    validate_sources(sources)
    return sources


def db_path(cfg: dict[str, Any] | None = None, root: Path | None = None) -> Path:
    root = root or project_root()
    cfg = cfg or load_config(root)
    rel = cfg.get("paths", {}).get("database", "data/aoc.db")
    p = Path(rel)
    return p if p.is_absolute() else root / p
