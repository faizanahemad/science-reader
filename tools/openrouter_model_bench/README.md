# OpenRouter multi-model hard bench

Reusable gauntlet comparing models on **speed**, **ability**, and **formatting**.
Produces scoreboard tables (markdown + JSON) under `results/` (gitignored).

**stdlib only** for the hot path (`client.py` uses `urllib`). Optional: PyYAML for nicer
`models.yaml` parsing; a small built-in parser works if PyYAML is missing.

## Auth — never put the key in the invoker or git

Do **not** pass the key on the CLI if the shell history is shared. Do **not** commit
keys. The runner resolves the key in this order:

1. `--api-key` CLI flag (discouraged; only for one-off scripts)
2. Env `OPENROUTER_API_KEY` (preferred)
3. Env `OR_API_KEY`
4. Repo `.vscode/launch.json` — first `"OPENROUTER_API_KEY": "..."` string match
   (works with JSONC / trailing comments). Launch configs used by
   `run_server.sh` / VS Code debug already hold this; the key is **gitignored**.

### Recommended: export once for the shell

```bash
# Pull from local launch.json without printing the secret
export OPENROUTER_API_KEY="$(python3 - <<'PY'
import re
from pathlib import Path
text = Path('.vscode/launch.json').read_text()
m = re.search(r'"OPENROUTER_API_KEY"\s*:\s*"([^"]+)"', text)
if not m:
    raise SystemExit('OPENROUTER_API_KEY not found in .vscode/launch.json')
print(m.group(1), end='')
PY
)"
# sanity without leaking: length only
python3 -c 'import os; k=os.environ["OPENROUTER_API_KEY"]; print(f"key_ok len={len(k)} prefix={k[:7]}...")'
```

Or if you already have it in the environment (server debug launch, direnv, etc.):

```bash
echo ${#OPENROUTER_API_KEY}   # non-zero
```

Never:

```bash
# BAD — lands in shell history / process list
export OPENROUTER_API_KEY=sk-or-v1-...
python -m tools.openrouter_model_bench.run --api-key 'sk-or-v1-...'
```

## Quick start

```bash
# from repo root
conda activate science-reader   # project env if you use it

# key via env or auto from .vscode/launch.json (see Auth above)
python -m tools.openrouter_model_bench.run

# or only a subset of models.yaml keys
python -m tools.openrouter_model_bench.run --models gemini-3.1-lite,mercury-2 --tag smoke
```

Outputs (all under `tools/openrouter_model_bench/results/`, **gitignored**):

| file | purpose |
|---|---|
| `hardbench_<utc>[_tag]_results.json` | raw per-call texts + check detail |
| `hardbench_<utc>[_tag]_summary.json` | per-model aggregates |
| `hardbench_<utc>[_tag]_report.md` | scoreboard tables |
| `latest_report.md` / `latest_summary.json` | always-updated pointers |

## Layout

```
tools/openrouter_model_bench/
  models.yaml     # registry (id + reasoning extras)
  prompts.py      # hard pack (13 prompts, binary checks)
  scoring.py      # JSON / CSV / python-exec helpers
  client.py       # OpenRouter stdlib client + key load
  report.py       # scoreboard markdown
  run.py          # CLI
  results/        # gitignored run artifacts (+ keep .gitignore)
  README.md
```

## Add / select models

### Edit `models.yaml`

```yaml
models:
  - key: my-label          # short column header
    id: provider/model-name
    extra:
      reasoning:
        effort: none       # preferred non-reasoning when API allows
      include_reasoning: false
    notes: "optional"
    # enabled: false
```

### CLI only (`--add`, repeatable)

```bash
python -m tools.openrouter_model_bench.run \
  --models gemini-3.1-lite \
  --add 'g35|google/gemini-3.5-flash|{"reasoning":{"effort":"minimal"},"include_reasoning":false}' \
  --add 'merc|inception/mercury-2|{"include_reasoning":false}' \
  --tag myrun
```

`--add` format: `key|openrouter_model_id|json_extra`  
`json_extra` may be `{}`.

## Filters / flags

```bash
python -m tools.openrouter_model_bench.run --list-prompts
python -m tools.openrouter_model_bench.run --categories speed,formatting
python -m tools.openrouter_model_bench.run --prompts A2_code_fix_exec,F1_nested_json_schema
python -m tools.openrouter_model_bench.run --serial-models   # one model at a time per prompt
python -m tools.openrouter_model_bench.run --timeout 180
python -m tools.openrouter_model_bench.run --out-dir /tmp/bench_out
```

## Hard pack (v0.1) — 13 prompts

**Speed**
- `S1_ping` — exact `OK` (×3 latency samples)
- `S2_medium_list` — zero-padded `01`..`20` lines

**Ability**
- `A1_trap_math` — two-train meet time → `ANSWER: 137`
- `A2_code_fix_exec` — merge intervals + coverage, **executed**
- `A3_sql_window` — multi-constraint ANSI SQL + windows
- `A4_bugfix_and_patch` — case/space anagram, **executed**
- `A5_nested_instructions` — multi-step transform (empty after filter → `OUT::END`)
- `A6_reading_trap` — distractor numbers in passage → `55`

**Formatting**
- `F1_nested_json_schema` — nested types, sorted tags, participant order
- `F2_csv_only` — sorted CSV, two-decimal prices, no markdown table
- `F3_md_strict_report` — H1 / `---` / 2 H2 / table / numbered list / `EOF` / word band
- `F4_frontmatter_yaml` — YAML front matter + two scoped paragraphs
- `F5_multi_block_labels` — CHOICE / BECAUSE / RISKS / METRICS

## Scoring notes

- Code ability is graded by **executing** returned Python, not string match.
- Models that burn `max_tokens` on hidden `reasoning_tokens` and return empty
  content fail those prompts (common with diffusion / some reasoner endpoints).
  Raise `max_tokens` in `prompts.py` if you need a fairer second look.
- Gemini 3.5 Flash rejects `reasoning.effort=none` on OpenRouter; use `minimal`.
- Latency is full HTTP wall time (provider queue included).
- Reports mark winners (quality %, ping mean, all-task mean, cost).

## Adding a prompt

1. Append via `_reg({...})` in `prompts.py`.
2. Use deterministic `checks: {name: lambda text: bool}`.
3. Reuse helpers in `scoring.py`.
4. Keep checks binary so tables stay comparable across runs and models.

## Dependencies

- Python 3.10+ recommended; 3.9 often fine.
- Network access to `https://openrouter.ai`.
- No package install required for the runner itself.
- Optional: `pyyaml` for full `models.yaml` features (fallback parser covers the schema used here).
