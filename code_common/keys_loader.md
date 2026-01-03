# `keys_loader.py` — Load `keys.yaml` and inject env vars

VL-ACMS expects provider credentials (e.g., OpenRouter/OpenAI-compatible API keys) to be available in environment variables.

This helper provides a consistent way to:
- load a `keys.yaml` file
- return the mapping
- optionally inject it into `os.environ`

## Expected `keys.yaml` format

```yaml
OPENROUTER_API_KEY: "..."
# Add other keys as needed
# SOME_OTHER_KEY: "..."
```

## Python usage

```python
from keys_loader import load_and_inject_keys_yaml

keys = load_and_inject_keys_yaml("/abs/path/to/keys.yaml")
# keys is a dict[str, str] and os.environ now contains those keys
```

## VL-ACMS CLI usage

The Phase 0 CLI supports:
- `--keys-yaml /abs/path/to/keys.yaml`

Example:

```bash
conda activate acms
python -m vl_acms.cli init-db --db /abs/path/to/vlacms.sqlite3 --keys-yaml /abs/path/to/keys.yaml
```

## Notes
- By default we do **not overwrite** existing environment variables.
- Pass `overwrite=True` in Python if you want to overwrite.

