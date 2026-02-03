# Model Catalog API (Internal)

Returns the deduped list of model names available for dropdowns plus the current default mappings.

Base path: `/`

## Endpoint

- `GET /model_catalog`
  - Response:

```json
{
  "models": ["..."],
  "defaults": {
    "summary_model": "...",
    "tldr_model": "...",
    "artefact_propose_edits_model": "...",
    "doubt_clearing_model": "...",
    "context_action_model": "...",
    "doc_long_summary_model": "...",
    "doc_long_summary_v2_model": "...",
    "doc_short_answer_model": "..."
  }
}
```

## Implementation Details

- Model list is deduped from:
  - `VERY_CHEAP_LLM`
  - `CHEAP_LLM`
  - `EXPENSIVE_LLM`
  - `CHEAP_LONG_CONTEXT_LLM`
  - `LONG_CONTEXT_LLM`
- Defaults are built from the current code defaults used by each feature.

## Notes

- Used by the Model Overrides modal to populate dropdowns.
- The UI includes a “Default (recommended)” entry which means “use the code default.”
