"""
keys.yaml loader utilities.

Why this exists
--------------
This repo uses external LLM/VLM providers through OpenAI-compatible endpoints
and expects credentials to be injected into environment variables.

To keep credential-loading consistent across tools (CLI now, Flask later),
we provide a small helper that:
- loads a YAML mapping from disk
- returns a dict[str, str]
- optionally injects into `os.environ`
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

import yaml


def load_keys_yaml(keys_yaml_path: str) -> Dict[str, str]:
    """
    Load a keys.yaml file into a dict.

    Parameters
    ----------
    keys_yaml_path:
        Path to a YAML file containing a mapping of env var names to secret values.

    Returns
    -------
    Dict[str, str]
        Mapping of key name -> value.
    """

    p = Path(keys_yaml_path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"keys.yaml not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"keys.yaml must be a mapping. Got: {type(data)}")
    out: Dict[str, str] = {}
    for k, v in data.items():
        if k is None:
            continue
        key = str(k).strip()
        if not key:
            continue
        if v is None:
            continue
        out[key] = str(v)
    return out


def inject_keys_into_env(keys: Dict[str, str], *, overwrite: bool = False) -> None:
    """
    Inject keys into environment variables.

    Parameters
    ----------
    keys:
        Mapping of env var name -> value.
    overwrite:
        If False (default), do not overwrite existing env vars.
    """

    for k, v in keys.items():
        if not overwrite and os.environ.get(k):
            continue
        os.environ[k] = v


def load_and_inject_keys_yaml(keys_yaml_path: str, *, overwrite: bool = False) -> Dict[str, str]:
    """
    Load a keys.yaml file and inject into `os.environ`.

    Returns the loaded key mapping for callers that also want to pass the keys
    explicitly to functions.
    """

    keys = load_keys_yaml(keys_yaml_path)
    inject_keys_into_env(keys, overwrite=overwrite)
    return keys


