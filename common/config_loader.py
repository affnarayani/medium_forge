"""
common/config_loader.py
Centralized configuration loader for json/config.json.
Provides a simple get(key, default) helper used across all scripts.
"""

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "json" / "config.json"
_config_cache = None


def _load_config():
    global _config_cache
    if _config_cache is None:
        if not _CONFIG_PATH.exists():
            _config_cache = {}
        else:
            try:
                with _CONFIG_PATH.open("r", encoding="utf-8") as f:
                    _config_cache = json.load(f)
            except Exception:
                _config_cache = {}
    return _config_cache


def get(key, default=None):
    """Return config value for key, falling back to default."""
    return _load_config().get(key, default)


def reload():
    """Force reload of config from disk."""
    global _config_cache
    _config_cache = None
    return _load_config()