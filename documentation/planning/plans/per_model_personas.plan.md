# Per-Model Personas for Multi-Model Response Tabs

## Motivation & Goal

Today, when a user selects 2+ models ("Main Model" multi-select), the ensemble
path (`Conversation.reply` → `NResponseAgent` → `CallMultipleLLM` →
`common.stream_multiple_models`) broadcasts an **identical** prompt and an
identical system preamble to every model:

```python
# call_llm.py:264-275 (CallMultipleLLM.call_models)
stream_multiple_models(self.keys, self.model_names,
                       [text] * len(self.model_names),   # same prompt
                       system=system, ...)               # same system
```

So all models answer the same question with the same instructions — the only
variety is inter-model variance. We want **deliberate viewpoint diversity**:
bind an optional *persona* to each model row so each tab reflects a distinct
stance (Skeptic, Domain Expert, Pragmatist, Contrarian, …) or a user-authored
custom instruction.

### Decisions locked with the user

1. **UI shape**: Shape 2 — a per-model **grid** (rows of `Model ▾ | Persona ▾ | [custom text] | +/−`).
2. **Persona source**: curated library + a **"Custom…"** free-text escape hatch.
3. **Default**: persona = **None** per row (identical to today's behavior).
4. **Combination rule**: persona text is **appended AFTER** the shared preamble
   (shared base + per-model persona suffix). The global Preamble Options still
   apply to every model.
5. **Duplicate models allowed**: the same model may appear in multiple rows with
   different personas; **each row is its own tab**. `stream_multiple_models`
   already de-dupes repeated model names internally via `model_name_{index}`
   (`common.py:443-448`), so this is safe.
6. **Persistence scope**: **global user default** (persisted like
   `preamble_options` in `chatSettingsState`), NOT per-conversation
   `model_overrides`.
7. **Temperature**: keep the single shared temperature (today's `0.9`) for all
   rows. Personas alone drive the variety; no per-row temperature field in v1.
8. **Single-row grid**: a grid with exactly one row = a **normal single-model
   answer** (1 tab, no ensemble). It is routed to the standard single-model path
   (avoids the `CallMultipleLLM` "needs ≥2 models" guard and today's incidental
   `n_responses=2` duplication).
9. **Grid vs Main Model coexistence**: both controls remain visible. The grid
   **wins when non-empty**; the existing "Main Model" multi-select is the
   **fallback** used when the grid is empty. The grid is NOT pre-seeded from the
   Main Model selection.
   - **Nuance — the override is all-or-nothing, NOT a merge (decided):** when the
     grid has ≥1 valid (non-blank-model) row, `model_name` is **reassigned** to
     the grid's models and the Main Model dropdown value is **discarded** for that
     reply — it is silent, and it is NOT added as an extra baseline tab. When the
     grid is empty (or every row has a blank model), Main Model behaves exactly as
     today. So per reply it's *either* the grid *or* Main Model — never both.
     Row counts: **0 valid rows** → Main Model fallback; **1 valid row** → that
     single grid model answers via the normal single-model path (no ensemble),
     persona folded into the preamble (decision 8); **≥2 valid rows** → ensemble
     forced on, one tab per row, Main Model bypassed.
   - *Rejected alternative — Main Model as an always-on baseline tab alongside the
     grid rows:* not chosen; keeps behavior predictable (fill the grid ⇒ only the
     grid answers). Would be a one-line prepend of the Main Model value to the row
     list if we later want it.
   - **Implementation:** `Conversation.py` — Main Model read at ~9836
     (`checkboxes["main_model"]`), grid override at ~11851–11859
     (`checkboxes["model_personas"]` filtered for non-blank models, then
     `model_name` reassigned).
10. **Row model options**: the per-row Model dropdown is restricted to the
    **same curated option list** shown in the "Main Model" selectpicker today —
    NOT the full `window.ModelCatalog` catalog. (Keeps model choices consistent
    with the rest of the chat UI.)
11. **Starter persona set**: **Skeptic, Domain Expert, Pragmatist, Contrarian,
    ELI5, Creative** — 6 curated personas. Actual prompt texts to be authored
    (concise, 2-4 sentences each) during implementation.
12. **Library location**: a new file **`code_common/personas.py`** (matches
    AGENTS.md "reusable code lives in `code_common/`"), NOT a dict in `common.py`.
13. **Custom persona length cap**: the free-text "Custom…" cell is **capped at
    500 characters** to protect the already-large preamble. Enforce on both the
    UI (input `maxlength`) and the server (truncate/reject over-limit defensively).
14. **Grid placement**: a **collapsible "Advanced: per-model personas" panel**,
    hidden until expanded — keeps the modal uncluttered for users who never use
    personas.

### Full Q&A Log (design conversation)

Recorded verbatim for traceability; each answer maps to a decision above.

- **Q: Shape 1 (global auto-assigned persona list) or Shape 2 (per-model grid) for v1?**
  A: Shape 2 — per-model grid. (→ decision 1)
- **Q: Fixed curated library, user-editable presets, or free-text personas?**
  A: Curated library + a "Custom…" free-text escape hatch. (→ decision 2)
- **Q: Persist per-conversation (like model_overrides) or global user default (like preamble_options)?**
  A: Global user default. (→ decision 6)
- **Q: When a row has a persona, how does it combine with the shared preamble —
  append after / fully replace / prepend before?**
  A: Append AFTER the shared preamble (shared base + persona suffix). (→ decision 4)
- **Q: Can a model appear in multiple grid rows (same model, different personas)?**
  A: Yes — allow duplicates; each row is its own tab. (→ decision 5)
- **Q: What temperature per row — shared / per-row field / auto-spread?**
  A: Keep single shared temperature (0.9) for all rows. (→ decision 7)
- **Q: How should a single-row grid behave (today one model still yields 2 tabs
  via n_responses=2)?**
  A: Single-row grid = normal single-model answer, 1 tab, no ensemble. (→ decision 8)
- **Q: How does the grid relate to the existing Main Model multi-select —
  coexist / replace / pre-seed?**
  A: Coexist; grid wins when non-empty, Main Model is the fallback, no pre-seed. (→ decision 9)
- **Q: Per-row Model dropdown — full model catalog or just the Main Model list?**
  A: Restrict to the same curated Main Model option list shown today. (→ decision 10)
- **Q: Persona library contents — approve starter set / your own list / defer?**
  A: Approve starter set (Skeptic, Domain Expert, Pragmatist, Contrarian, ELI5,
  Creative); author the actual texts during implementation. (→ decision 11)
- **Q: Where should the curated persona library live — code_common/personas.py or a dict in common.py?**
  A: New file `code_common/personas.py`. (→ decision 12)
- **Q: Character limit on the Custom persona text?**
  A: Cap at 500 chars. (→ decision 13)
- **Q: Grid placement — collapsible advanced panel or always-visible sub-row?**
  A: Collapsible "Advanced: per-model personas" panel. (→ decision 14)

### Alternatives Considered But NOT Chosen

Kept here so future readers know these were deliberately weighed and rejected,
not overlooked.

- **Shape 1 — "Persona set" (global multi-select, auto-assigned)**: a single
  extra `selectpicker` next to Main Model; backend round-robins personas over
  selected models. *Rejected*: mapping of persona→model is implicit; less precise
  than the grid. May return as a future "auto-diversify" convenience.
- **Option B (superseded by the grid) — per-model steering boxes only**: inline
  free-text per model without a curated library. *Folded into* the grid's
  "Custom…" cell instead.
- **Option C — unify Compare modal with the tabs** ("add a variant" button on the
  tab strip that appends a rerun tab + pairwise diff). *Deferred*: valuable but a
  larger surface; Compare stays the one-off experiment surface, personas are the
  persisted multi-tab surface. Listed under Deferred.
- **Option D — auto-diversification with no user config** (auto-assign personas +
  temperature spread on any 2+ model run). *Deferred* to keep v1 explicit and
  user-controlled. Listed under Deferred.
- **Persona REPLACES the system preamble** (instead of appending): maximum
  divergence but loses shared formatting/instructions. *Rejected* — decision 4.
- **Persona PREPENDS before the shared preamble**: *Rejected* — decision 4
  (append chosen so shared base is established first, persona refines last).
- **Per-conversation persistence via `model_overrides`**: *Rejected for v1* —
  decision 6 (global default). Left as a Deferred enhancement.
- **Per-row temperature field / auto-spread temperatures**: *Rejected for v1* —
  decision 7.
- **Full model catalog in row dropdowns** (like the Compare modal): *Rejected* —
  decision 10 (restrict to the curated Main Model list).
- **Grid replaces the Main Model multi-select entirely**: *Rejected* — decision 9
  (coexist with fallback), to preserve the simple common case and backward compat.
- **Client-side persona library** (persona texts defined in JS): *Rejected* —
  R7, library lives server-side as the single source of truth; UI sends ids.
- **Putting persona text into the prompt instead of the system**: *Rejected* —
  personas are role/stance instructions, so they belong in `system`; also keeps
  `prompts=[text]*N` unchanged and localizes the change to `system`-as-list.

## Current Architecture (verified)

### Backend chain
- `Conversation.reply()` ensemble branch (`Conversation.py:12096-12151`):
  - When `model_name` is a list → `model_names = model_name` (`:12097-12099`).
  - Builds ONE `prompt` and ONE `preamble` (system).
  - `llm = NResponseAgent(keys, writer_model=model_names, n_responses=2)`.
  - `llm(prompt, images=..., system=preamble, temperature=0.9, stream=True)`.
- `NResponseAgent.__call__` (`agents/search_and_information_agents.py:1102-1179`):
  - Builds `writer_models` list, `llm = CallMultipleLLM(keys, writer_models)`.
  - `llm(text, images, temperature, True, max_tokens, system)`.
- `CallMultipleLLM.call_models` (`call_llm.py:231-...`):
  - `stream_multiple_models(keys, model_names, [text]*N, ..., system=system,
    header_template="Response from {model}")`.
- `stream_multiple_models` (`common.py:290-...`):
  - Already accepts **`prompts` as a list** and **`header_template` as a list**.
  - `system` is currently a **single str** passed to every thread's `CallLLm`
    (`common.py:478-485`). This is the one field that must become list-capable.
  - Wraps each model in `<details><summary>{header}</summary>…</details>`.

### Frontend chain
- Model selection: `#settings-main-model-selector` (modal) / `#main-model-selector`
  (inline), multi-select `selectpicker`. Selection order tracked in
  `window._modelSelectionOrder` (`common.js:6788-6792`).
- Reply payload: `values['main_model']` (string or list) →
  request `checkboxes["main_model"]` → `reply()` `model_name`.
- Settings state: `chatSettingsState.preamble_options` etc., built/loaded/saved
  in `chat.js` (`buildSettingsStateFromControlsOrDefaults` :660,
  `setModalFromState` :729, `getStateFromModal` :864) and read in
  `common.js:getValues()` (~6785).
- Tabs: `common.js:applyModelResponseTabs()` scans `<details>` whose summary
  starts with "Response from" and builds Bootstrap nav-tabs. Tab **label** comes
  from the summary text, i.e. from `header_template`.

## Requirements

- R1. A grid UI to bind an optional persona (curated or custom) to each selected model.
- R2. Personas persist as a global user default alongside existing settings.
- R3. Backend applies `shared_preamble + "\n\n" + persona_text` as the system for
  each model row; rows with no persona use the shared preamble unchanged.
- R4. Duplicate models with distinct personas produce distinct tabs.
- R5. Tab labels reflect the persona, e.g. the summary is
  `"Response from gpt-5.5 · Skeptic"` (the frontend strips the `"Response from "`
  prefix, so the tab reads `"gpt-5.5 · Skeptic"`); rows without a persona keep
  `"Response from {model}"`.
- R6. Zero behavior change when no personas are set (backward compatible).
- R7. Curated persona library is defined **server-side** (single source of truth),
  exposed to the UI via an endpoint; UI only sends persona **ids** (+ custom text).

## Data Model

### New request field (parallel to `main_model`)

`checkboxes["model_personas"]`: ordered list, one entry per grid row:
```json
[
  { "model": "openai/gpt-5.5",            "persona": "skeptic",  "custom_text": "" },
  { "model": "openai/gpt-5.5",            "persona": "custom",   "custom_text": "Argue as a security auditor." },
  { "model": "anthropic/claude-opus-latest","persona": "none",   "custom_text": "" }
]
```

- The grid is the **authoritative** model+persona list when non-empty. When
  present, backend derives `model_names` from the grid rows (in order), NOT from
  `main_model`. `main_model` remains the fallback when the grid is empty/absent
  (full backward compat).
- `persona="none"` (or missing) → no suffix.
- `persona="custom"` → use `custom_text` verbatim.
- otherwise → look up curated persona text server-side by id.

### Curated persona library (server-side)

Define in a new module **`code_common/personas.py`** (decision 12). Each entry:
```python
PERSONA_LIBRARY = {
  "skeptic":       {"label": "Skeptic",        "text": "Adopt a skeptical, red-team stance. ..."},
  "domain_expert": {"label": "Domain Expert",  "text": "Answer as a rigorous domain expert. ..."},
  "pragmatist":    {"label": "Pragmatist",     "text": "Optimize for actionable, practical steps. ..."},
  "contrarian":    {"label": "Contrarian",     "text": "Argue the strongest opposing case. ..."},
  "eli5":          {"label": "ELI5",           "text": "Explain simply, for a beginner. ..."},
  "creative":      {"label": "Creative",       "text": "Take a divergent, imaginative angle. ..."},
}
CUSTOM_PERSONA_MAX_CHARS = 500  # decision 13
```
Starter set = the 6 personas above (decision 11). Keep persona texts concise
(2-4 sentences); they append to an already-large preamble.

## Implementation Tasks (incremental, small chunks)

### Phase 1 — Backend plumbing (system as list)  ✅ DONE

> **Status:** Implemented. `system`-as-list threaded through
> `stream_multiple_models` → `CallMultipleLLM` → `NResponseAgent`; new
> `code_common/personas.py` (library + helpers); tests in
> `tests/test_per_model_personas.py`. Persona-helper test passes on
> `/usr/bin/python3`; all edited files `py_compile` clean. Full multi-model
> streaming tests require the user's `science-reader` env (numpy/more_itertools
> not installable here) — run `python -m pytest tests/test_per_model_personas.py -v`
> in that env to confirm the `stream_multiple_models`/`CallMultipleLLM` paths.

1. **`common.py:stream_multiple_models`** — accept `system` as `Union[str,
   List[str], None]`.
   - Normalize like `header_template` (str → `[system]*N`; validate list length).
   - Pass the per-index system into `run_llm` and thence `CallLLm(...).__call__(
     ..., system=system_i)`.
   - Keep default `system=None` behavior identical.
   - *Pitfall*: `run_llm` closure currently closes over the single `system`;
     thread it through `model_instances` tuple instead (extend the tuple built at
     `common.py:443-448` to carry `system_i`).

2. **`call_llm.py:CallMultipleLLM`** — support per-model systems.
   - `__init__`: no change required, but add optional `systems: List[str] = None`
     stored on the instance, OR accept `systems` in `call_models(...)`.
   - `call_models`: stop hardcoding `[text]*N` for system; pass
     `system=self.systems or system`. Keep `[text]*N` for prompts (personas go in
     system, not prompt — matches decision #4).
   - Backward compat: when `systems` is None, behavior identical to today.

3. **`NResponseAgent`** (`agents/search_and_information_agents.py:1102`) — thread
   `systems` through.
   - Add optional `personas`/`systems` param on `__init__` or `__call__`.
   - Build `CallMultipleLLM(self.keys, self.writer_models, systems=self.systems)`.
   - Build the per-model `header_template` list here too (persona-aware labels).

### Phase 2 — Reply integration  ✅ DONE

> **Status:** Implemented in `Conversation.py`. Persona rows resolved just
> before the `ensemble`/dedup block (~11846): grid overrides Main Model, blank
> rows filtered, single row → scalar model + persona folded into `preamble`
> (routes to the single-model branch, no ensemble), ≥2 rows → forced ensemble
> with duplicates preserved (dedup guarded off when personas active). The
> `NResponseAgent` call builds per-row `systems` (preamble + persona suffix) and
> persona-aware `header_template`, shared `temperature=0.9` unchanged. 7 ad-hoc
> logic checks pass against the real `code_common/personas.py`; `Conversation.py`
> `py_compile` clean. Full path needs the `science-reader` env to import
> `Conversation.py`.

4. **`Conversation.reply` ensemble branch** (`Conversation.py:12096-12151`):
   - Read `model_personas = checkboxes.get("model_personas")`.
   - If non-empty:
     - `model_names = [row["model"] for row in model_personas]` (canonicalize via
       `model_name_to_canonical_name`, matching `:9837-9838`).
     - `systems = [preamble + persona_suffix(row) for row in model_personas]`
       where `persona_suffix` resolves none/custom/curated.
     - `header_template = [header_for_row(row) for row in model_personas]`, i.e.
       `"Response from {model} · <label>"` for persona rows (keeping the
       `"Response from"` prefix the frontend classifier requires) or
       `"Response from {model}"` for none.
   - Else: unchanged (uses `model_names` from `model_name` list).
   - Pass `personas/systems` + `header_template` into `NResponseAgent`.
   - **Temperature (decision 7)**: continue passing the single shared
     `temperature=0.9` (as today, `Conversation.py:12128`) to all rows; do NOT
     add per-row temperature.
   - *Note*: `n_responses` is currently 2; when grid is used, `writer_model` is
     the explicit list so `n_responses` is ignored (list branch at
     `NResponseAgent:1142-1146`). **Single-row grid (decision 8)**: route to the
     normal single-model branch (the `else` at `Conversation.py:12152`) — 1 tab,
     no ensemble — instead of `NResponseAgent`, which would both hit the
     `CallMultipleLLM` <2 guard and reintroduce `n_responses=2` duplication.
     Multi-row grids (≥2 rows) use the explicit list as-is.

5. **Server-side persona resolution helper** — `persona_suffix(row)` +
   `persona_label(row)` in `code_common/personas.py` reading `PERSONA_LIBRARY`.
   Validate `persona` id; unknown id → treat as none (defensive). For
   `persona="custom"`, **truncate `custom_text` to `CUSTOM_PERSONA_MAX_CHARS`
   (500)** server-side (decision 13) before appending.

### Phase 3 — Endpoint for the curated library  ✅ DONE

> **Status:** `GET /persona_catalog` added in `endpoints/conversations.py`
> (mirrors `/model_catalog`: `@limiter.limit("300 per minute")` + `@login_required`),
> returning `{personas:[{id,label}], custom_max_chars:500}` — only id+label, the
> persona prompt text is NOT exposed to the client. CORS rule added in `server.py`
> alongside `/model_catalog` so the extension can reach it too. Note: `model_personas`
> is a global default riding in the reply `checkboxes` (decision 6), NOT a
> per-conversation model_override, so the `set_conversation_settings`/`allowed_keys`
> validator needs no change. Payload shape + JSON-serialization verified ad-hoc;
> both files `py_compile` clean.

6. **`endpoints/conversations.py`** — add `GET /persona_catalog` returning
   `{ personas: [{id, label}], }` from `PERSONA_LIBRARY`. (Mirrors
   `/model_catalog`.) UI populates the persona dropdowns from this.

### Phase 4 — Frontend grid UI  ✅ DONE

> **Status:** Implemented (visual work — awaiting your eyeball).
> - `interface/interface.html`: collapsible "Advanced: per-model personas" panel
>   (decision 14) added under the Model & Agent row, with `#model-personas-grid`
>   and an "Add model" button.
> - `interface/chat.js`: `loadPersonaCatalog` (fetches `/persona_catalog`),
>   `buildPersonaModelOptions` (clones the curated Main Model options —
>   decision 10), `buildPersonaOptions` (None + curated + Custom…),
>   `renderPersonaRow` (model select | persona select | custom text `maxlength`
>   from catalog `custom_max_chars` — decision 13 | remove btn),
>   `populateModelPersonasGrid`, `collectModelPersonasFromGrid` (drops blank-model
>   rows so empty grid falls back — decision 9), and add/remove/custom-toggle
>   handlers. `model_personas` threaded into `buildSettingsStateFromControlsOrDefaults`,
>   `setModalFromState`, `collectSettingsFromModal`.
> - `interface/common.js:getValues()`: emits `values['model_personas']` from
>   `chatSettingsState` (only when non-empty) so it rides in the reply payload
>   `checkboxes` (decision 6).
> - `node --check` clean on both JS files. Per project guidance, heavier
>   lint/tests held until visual review.

7. **`interface/interface.html`** — in the Model & Agent Selection row (~2580),
   add a **"Model Personas"** block (new full-width sub-row under the existing
   columns, or a collapsible panel). Contains:
   - A `#model-personas-grid` container rendering rows dynamically.
   - Each row: model `<select>` (**decision 10**: options = the SAME curated list
     as `#settings-main-model-selector`, reused/cloned — NOT the full
     `window.ModelCatalog`), persona `<select>` (populated from `/persona_catalog`
     + "None" + "Custom…"), a text input (**decision 13**: `maxlength="500"`)
     shown only when persona = Custom, and add(+)/remove(−) buttons.
   - **Decision 14**: the whole block is a **collapsible "Advanced: per-model
     personas" panel**, hidden until expanded.
   - **Decision 9**: the existing "Main Model" multi-select stays visible; the
     grid and it coexist. Empty grid = today's behavior (falls back to
     `#settings-main-model-selector`). The grid is NOT pre-seeded from Main Model.

8. **`interface/chat.js`** — new functions mirroring the preamble pattern:
   - `populateModelPersonasGrid()` — build rows from state; fetch persona catalog.
   - Include `model_personas` in `buildSettingsStateFromControlsOrDefaults`,
     `setModalFromState`, `getStateFromModal`.
   - Row add/remove/duplicate handlers; toggle custom-text visibility.

9. **`interface/common.js:getValues()`** (~6785) — emit
   `values['model_personas']` from `chatSettingsState.model_personas` so it rides
   in the reply payload `checkboxes`.

10. **`interface/common-chat.js`** — no schema change; ensure
    `chatSettingsState.model_personas` is included wherever settings state is
    hydrated/synced.

### Phase 5 — Tab labels & rendering  ✅ DONE

> **Status:** Implemented + ad-hoc verified.
> - **Tab-label flow — a real bug was found and fixed.** `applyModelResponseTabs`
>   (`interface/common.js`) classifies a response `<details>` as a *model* tab
>   ONLY when its `<summary>` starts with `"Response from"` (line ~4145), and an
>   outer gate (~6244) only enters the tab path when the HTML contains
>   `"Response from"`. The original `header_for_row` emitted `"<label> — {model}"`
>   (no such prefix) → persona tabs would NOT be recognized and would be dropped
>   from the tab UI. **Fix:** `header_for_row` now emits
>   `"Response from {model} · <label>"`. The frontend strips the `"Response from "`
>   prefix (line ~4331) to derive the label, so the tab reads `"{model} · <label>"`
>   — persona-aware label with ZERO frontend change and the existing contract
>   preserved. Tests + plan examples updated to the new format.
> - **Cache versions:**
>   - `service-worker.js` `CACHE_VERSION` is a **serve-time placeholder** —
>     `endpoints/static_routes.py:400-405` replaces it with a composite SHA-256
>     hash of all interface JS/CSS at startup, so it **self-invalidates** whenever
>     any asset (incl. these edits) changes. **Do NOT bump it manually** (the
>     original plan step was obsolete).
>   - `common.js` `window.UI_CACHE_VERSION` is **manual** (invalidates the
>     IndexedDB rendered-state snapshots when rendering logic changes). Bumped
>     **v24 → v25** for the persona tab-label change.

11. **`applyModelResponseTabs`** derives labels from summary text; persona-aware
    `header_template` (Phase 2) now keeps the `"Response from "` prefix so it
    flows through unchanged. Tab label = `"{model} · <persona label>"`; TLDR tab
    unaffected.
12. Bump `UI_CACHE_VERSION` (common.js) — DONE. `CACHE_VERSION`
    (service-worker.js) is auto-hashed at serve time; left untouched.

### Phase 6 — Tests & docs  ✅ DONE

> **Status:** Implemented + ad-hoc verified.
> - **Tests** (`tests/test_stream_multiple_models.py`): added
>   `RecordingSystemCallLLm` (records the `system` each model is called with) and
>   3 cases — `test_stream_multiple_models_system_as_list` (list routes a distinct
>   system per model), `_system_str_broadcast` (scalar broadcast, back-compat),
>   `_system_length_mismatch` (list-length ≠ prompt count raises `ValueError`).
>   All registered in `run_all_tests`. The persona-resolution + header-build unit
>   coverage already lives in `tests/test_per_model_personas.py` (Phase 1).
> - **Docs**: `features/multi_model_response_tabs/README.md` gained a "Per-Model
>   Personas" section (UI, library, combination rule, `system`-as-list, resolution,
>   persistence, output format) + Files-Modified rows + a persona testing
>   checklist; `features/conversation_model_overrides/README.md` gained a callout
>   distinguishing global personas from per-conversation overrides;
>   `documentation/README.md` index entry expanded.
> - **Verification (ad-hoc, not suite-green):** `py_compile` clean on the test
>   file; a `hermes-verify-` temp script replicated the exact `common.py:442-450`
>   normalization/validation contract and confirmed list-route, str/None-broadcast,
>   and mismatch-raises — matching the new tests. Full `pytest` still requires the
>   science-reader env (heavy deps): `conda activate science-reader &&
>   python -m pytest tests/test_per_model_personas.py tests/test_stream_multiple_models.py -v`.

13. **Tests**:
    - `tests/test_stream_multiple_models.py`: add a case passing `system` as a
      list of length N; assert each model receives its own system (mock CallLLm).
    - New: reply-level test that a 2-row grid with distinct personas yields 2
      tabs with persona labels (or a focused unit test on the persona-resolution
      helper + header build).
14. **Docs**: update
    `documentation/features/multi_model_response_tabs/README.md` (persona flow),
    `documentation/features/conversation_model_overrides/README.md` (note personas
    are global, not per-conversation), and `documentation/README.md` index.

## Backward Compatibility

- No `model_personas` in payload → identical to today.
- `system` remains `str`-accepting everywhere; list is purely additive.
- Single-row grid → route to normal single-model path (avoid `CallMultipleLLM`
  <2 guard).
- Old persisted settings without `model_personas` → grid renders empty → fallback.

## Open / Deferred

- Per-conversation persona overrides (could later live in `model_overrides`).
- Persona presets ("save this grid as a preset").
- Auto-diversify default (assign personas automatically when 2+ models chosen).
- A synthesis/merge tab reconciling viewpoints (CallMultipleLLM already has a
  `merge` path at `call_llm.py:303-320`).

## Files To Touch

Backend:
- `common.py` — `stream_multiple_models` system-as-list.
- `code_common/personas.py` — **new**: `PERSONA_LIBRARY`, `CUSTOM_PERSONA_MAX_CHARS`, `persona_suffix()`, `persona_label()`.
- `call_llm.py` — `CallMultipleLLM` per-model systems.
- `agents/search_and_information_agents.py` — `NResponseAgent` systems + header list.
- `Conversation.py` — ensemble branch persona resolution (`~12096-12151`).
- `endpoints/conversations.py` — `/persona_catalog`.

Frontend:
- `interface/interface.html` — personas grid.
- `interface/chat.js` — grid build/load/save + state keys.
- `interface/common.js` — `getValues()` emits `model_personas`; verify tab labels.
- `interface/common-chat.js` — state hydration.
- `interface/rendered-state-manager.js`, `interface/service-worker.js` — cache version bump.

Tests/docs:
- `tests/test_stream_multiple_models.py` (+ new reply/persona test).
- `documentation/features/multi_model_response_tabs/README.md`
- `documentation/features/conversation_model_overrides/README.md`
- `documentation/README.md`
