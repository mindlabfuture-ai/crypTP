from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml


def _ns(obj):
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in obj.items()})
    return obj


def load_config(path: str | Path = "config.yaml") -> SimpleNamespace:
    with open(path) as f:
        return _ns(yaml.safe_load(f))
