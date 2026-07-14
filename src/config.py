"""Configuration loader — lazy-loaded via Config class.

Usage:
    from config import Config
    port = Config.settings["mqtt"]["broker_port"]
    t_min = Config.thresholds["temperature"]["min"]

All dicts are loaded from disk on first access and cached thereafter.
Call Config.reload() to force a re-read from disk at runtime.
"""

import json
import os

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH   = os.path.join(_BASE, "config", "settings.json")
THRESHOLDS_PATH = os.path.join(_BASE, "config", "thresholds.json")


def load_settings() -> dict:
    with open(SETTINGS_PATH) as f:
        return json.load(f)


def load_thresholds() -> dict:
    with open(THRESHOLDS_PATH) as f:
        return json.load(f)


def save_thresholds(thresholds: dict) -> None:
    with open(THRESHOLDS_PATH, "w") as f:
        json.dump(thresholds, f, indent=2)


class _ConfigMeta(type):
    """Metaclass that exposes lazy-loaded settings/thresholds as class-level
    properties so callers write ``Config.settings["mqtt"]`` (no parentheses)."""

    _settings:   dict | None = None
    _thresholds: dict | None = None

    @property
    def settings(cls) -> dict:
        if cls._settings is None:
            cls._settings = load_settings()
        return cls._settings

    @property
    def thresholds(cls) -> dict:
        if cls._thresholds is None:
            cls._thresholds = load_thresholds()
        return cls._thresholds


class Config(metaclass=_ConfigMeta):
    """Lazy-loaded configuration accessor.

    Access ``Config.settings`` and ``Config.thresholds`` from anywhere;
    data is loaded on first access and cached.  Call ``Config.reload()``
    to flush the cache and re-read from disk.
    """

    @classmethod
    def reload(cls) -> None:
        """Discard cached config so the next access re-reads from disk."""
        cls._settings = None
        cls._thresholds = None


# ── Backward-compatible module-level aliases (eager, loaded at import) ──────
SETTINGS   = load_settings()
THRESHOLDS = load_thresholds()
