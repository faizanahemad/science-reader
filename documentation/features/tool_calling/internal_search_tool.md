# Internal Search Tool (`internal_search`) — host-gated company-internal search

## Motivation and background

Some environments have a company-internal AI/knowledge CLI that is only
reachable from an authorized host (e.g. over SSH from a managed laptop). A
local wrapper script runs one or many queries against it (multiple queries
execute in parallel remotely over a single session; interactive auth such as a
security-key touch is typically needed only for the first connection, after
which a persistent connection is reused).

Such internal AI backends tend to be slow one-shot answerers (~30–90s per
query, sometimes minutes) that often skimp on detail and may cite stale
internal pages. The goal of this tool is to let THIS app's orchestration (the
main chat model with its agentic tool loop) drive it: decompose questions into
multiple parallel queries, then do follow-up rounds to deepen thin answers —
instead of relying on a single shallow pass.

> See also `internal_search_fastpath_tools.md` for 6 additional tools
> (`search_moma`, `search_yaqs`, `get_bug`, `search_code`, `search_code_standard`, `ask_internal_kb`)
> that extend this same host-gated group with typed, mostly non-agentic fast
> paths (~1-3s) plus a KB-first/live-fallback single-question tool.

The tool must exist ONLY when the app runs on a host that has the wrapper
script. Other deployments (e.g. cloud) cannot reach the internal system, so
the tool must be entirely absent there (not just failing).

## Availability gating (host-gated)

Defined in `code_common/tools.py` (section "Internal search via a local
user-provided script"):

- `INTERNAL_SEARCH_SCRIPT_PATH` — env override, default
  `~/.local/bin/internal-search`.
- `INTERNAL_SEARCH_AVAILABLE` — True only when that script exists and is
  executable, AND env `INTERNAL_SEARCH_DISABLED` is not set to `1/true/yes`.
- The `@register_tool` registration itself is wrapped in
  `if INTERNAL_SEARCH_AVAILABLE:` — when False the tool is never registered,
  so it is automatically absent from every mode, the UI tool menu, the smart
  select menu, and the `request_tools` loadable list. No other code path needs
  a check. This is the first conditionally-registered tool in the registry;
  reuse the same pattern (gate at registration, expose an `*_AVAILABLE` flag)
  for future host-dependent tools.

## Script contract

The wrapper script is user-provided and NOT part of this repo. It must:

- Accept `-t <seconds>` (per-query remote timeout) followed by 1+ query
  strings as positional args.
- Run the queries (in parallel if it supports it) and print labeled per-query
  answers to stdout (e.g. `===== Query N (exit R): ... =====` headers).
- Exit non-zero if one or more queries failed (per-query status in headers).
- Handle any TTY/auth/session plumbing internally — the tool just runs it as
  a subprocess with `capture_output=True`.
- `--read <url> [url2 ...]` mode: this app's `read_internal_page` tool calls
  the wrapper with `--read`, expecting the same labeled-block output format.
  The wrapper is free to implement `--read` however it likes internally — in
  the user's actual wrapper (`jetski-query`, not in this repo), `--read`
  tries a fast native no-LLM page renderer first (~2-3s flat) and only falls
  back per-URL to a slower LLM-based read for URLs the renderer can't handle;
  this app-side tool contract is unaffected either way since the output
  format and exit-code semantics stay identical. See skill `ssh-remote-cli`
  for the wrapper-side implementation details.

## Always-on behaviour (Hybrid and Tiered modes)

When available, the tool is always exposed, mirroring `request_tools`:

- Tiered mode: appended to both `TIER_1_TOOLS` and `_TIER_1_BASE` in
  `code_common/tools.py` (just below their definitions), so it is present in
  the static list and always survives adaptive (usage-history) selection.
- Hybrid mode: force-appended after `_select_relevant_tools()` in
  `Conversation._get_enabled_tools()` (Conversation.py, hybrid branch, next to
  the `request_tools` append), guarded by `INTERNAL_SEARCH_AVAILABLE`.
- Smart/manual modes: reachable like any other `search`-category tool
  (smart selection, category checkbox, or `request_tools`), but not forced.

## "Internal Search Only" tool mode (`internal_only`)

Added because in hybrid mode the model would sometimes reach for
`perplexity_search`/`web_search` even when asked to use internal search. The
UI select `#settings-tool_mode` (interface/interface.html) has an "Internal
Search Only" option (value `internal_only`). Backend behaviour in
`Conversation._get_enabled_tools()`:

- Exposes exactly `["internal_search"]` — no selection LLM call, no
  `request_tools`, and the artefact auto-include is skipped for this mode.
- If `INTERNAL_SEARCH_AVAILABLE` is False (other hosts), returns None (no
  tools) with a warning log, so the mode degrades to plain chat.
- The tool-awareness preamble block in `reply()` swaps in a dedicated
  guidance text for this mode: only one tool exists, do not mention/attempt
  others, decompose into 2-5 parallel queries, multi-round follow-ups.

No JS changes were needed: `chat.js`/`common.js` pass `tool_mode` through
verbatim and compute `enable_tool_use` as `val !== 'none'`, which is correct
for `internal_only`.

## Prompt guidance

Two layers tell the main model how to use it well:

1. Tool description (goes to the model verbatim via the OpenAI `tools`
   parameter): states it is the ONLY source for internal/proprietary systems,
   lists the limitations (slow one-shot, skimps on detail, stale pages), and
   instructs three parallelism/depth levers: pass 2–5 self-contained
   differently-angled queries in one call (parallel remotely, 5 queries ≈
   cost of 1), issue several internal_search tool calls in the same response
   (executed concurrently by the tool loop), and a MANDATORY MULTI-ROUND
   WORKFLOW: (1) recon round, (2) self-critique against a staff-level
   senior-engineer ramp-up quality bar (architecture/design rationale,
   components and interactions, config/APIs, operational concerns, team/doc/
   code pointers, best practice — "first-round answers almost never meet this
   bar"), (3) deepening rounds ("what other queries would an expert fire?"),
   (4) only then synthesize — so the user gets the deep answer on the FIRST
   response without prompting for more. Explicitly notes there is no call
   budget. This workflow was distilled from a real session where the user had
   to manually prompt "does this meet staff-level depth? what other queries
   would you fire — do that" to get a good answer. When `INTERNAL_KB_AVAILABLE`
   is True, both `internal_search`'s and `read_internal_page`'s descriptions
   (and their compact `*_WORKFLOW_HINT` variants) open/append a "SPEED TIP"
   line instructing the model to probe `search_local_internal_kb` FIRST and
   only fall back to the live (slow) tools when the cache is empty, thin,
   off-topic, or too stale — added 2026-07 alongside the 180s default
   timeout change, since a cache hit avoids paying the live round-trip
   latency entirely.
2. Preamble tip: `Conversation.py` "Tool Usage Guidance" block (reply() around
   the `tool_awareness_text` construction) conditionally appends an
   `internal_search` bullet when `INTERNAL_SEARCH_AVAILABLE`, repeating the
   same three levers plus the same KB-first speed tip when
   `INTERNAL_KB_AVAILABLE`. In `internal_only` mode the entire block is
   replaced by a dedicated version with "weaknesses" and "how to get good
   results" sections covering parallel-within-a-call, parallel-across-calls,
   multi-round usage, and (when available) a "search_local_internal_kb (cheap
   first probe)" section instructing the model to probe the cache first and
   fall back to the live tools rather than stopping at a marginal cache hit.

## Tool API

- Name: `internal_search`; category `search`; non-interactive.
- Parameters:
  - `queries` (required): array of 1–8 self-contained query strings. A bare
    string or a legacy `query` arg is also accepted and normalised.
  - `timeout_seconds` (optional): per-query remote timeout, default 180,
    clamped to 30–600. Lowered from 240 (2026-07) after observing hard
    queries that make the remote jetski CLI chase CNS/fileutil artifacts and
    eventually die with "Error: timeout waiting for response" around
    240–300s wall time regardless of the requested `-t` — a shorter local
    default surfaces that failure to the caller sooner instead of blocking
    the whole agent loop for up to `240+120=360s` per call.

## Handler implementation (`handle_internal_search`, code_common/tools.py)

1. Validates/normalises queries (trims, drops blanks, caps at 8).
2. Runs `subprocess.run([INTERNAL_SEARCH_SCRIPT_PATH, "-t", str(timeout_s)]
   + queries)` with a local timeout of `timeout_s + 120` (session overhead
   margin). The script handles auth, remote parallelism, and per-query
   labeling.
3. Post-processing: strips `\r`, drops SSH noise lines ("Shared connection
   to ...", "Connection to ..."), returns via `_truncate_result` (50K cap).
4. Errors (never raises): empty queries, local timeout (with hint that the
   first connection may need an interactive auth touch), script missing,
   non-zero exit with no output (includes stderr tail). Non-zero exit WITH
   output returns the output plus a note pointing at per-query exit codes.

## Failure modes and operational notes

- If the underlying connection needs interactive auth (e.g. a security-key
  touch on first connect), calls can time out until that is done once
  out-of-band.
- Answers may be stale or shallow; the orchestrating model is instructed to
  do multiple rounds. Callers reviewing transcripts should expect several
  `internal_search` calls per internal question — that is by design.
- Conversations using this tool may contain company-internal content and
  should not be synced to non-approved infrastructure; the host-only gating
  is also the compliance boundary.

## Verification (2026-07-06)

- Import with script present: registered, in `TIER_1_TOOLS` and
  `_TIER_1_BASE`, OpenAI param generation OK.
- `INTERNAL_SEARCH_SCRIPT_PATH=/nonexistent`: not registered, absent from
  tier lists.
- `INTERNAL_SEARCH_DISABLED=1`: not available.
- Validation errors for empty/blank queries return proper `ToolCallResult`
  errors through `TOOL_REGISTRY.execute`.
- Real end-to-end: 2 parallel queries via `TOOL_REGISTRY.execute` returned
  correct labeled answers in ~20s with ssh noise stripped.

## Files modified

- `code_common/tools.py` — gating constants, description, handler,
  conditional registration, tier-list appends.
- `Conversation.py` — hybrid-mode force-append in `_get_enabled_tools()`;
  conditional `internal_search` bullet in the tool-awareness preamble.
- The wrapper script itself is external and not in this repo.

## Companion tool: `search_local_internal_kb` (added 2026-07-07)

A third tool in the same internal-knowledge group: instant local search over
a knowledge base of previously-fetched internal answers/pages (a separate
local script, default `~/.local/bin/internal-kb`, SQLite FTS5/BM25 — the
wrapper script's cache layer feeds it automatically).

Intention and limitations (encoded in the tool description so the model
self-polices):

- INTENTION: cheapest first probe (<1s, no network) for any internal topic;
  a cache hit saves 30–90s per live query. Also recalls facts looked up in
  past sessions.
- LIMITATIONS: only contains what was previously fetched on this machine
  (sparse coverage — no results ≠ doesn't exist internally); entries expire
  after ~30 days and may be stale; BM25 keyword retrieval over raw text
  chunks, not an AI answer.
- MANDATORY FALLBACK RULE: if KB results are empty, thin, off-topic, or
  possibly stale for a recency-sensitive question, the model must fall back
  to `internal_search` / `read_internal_page` in the same turn. The handler
  reinforces this in-band: an all-miss result appends a "fall back NOW"
  marker; a hit appends a "cached excerpts, deepen if marginal" reminder.

Gating and wiring:

- Own gate: `INTERNAL_KB_AVAILABLE` (script at `INTERNAL_KB_SCRIPT_PATH`,
  env-overridable; `INTERNAL_KB_DISABLED=1` kill switch). Independent of
  `INTERNAL_SEARCH_AVAILABLE` — either script can exist without the other.
- Same group treatment everywhere the other two tools are wired:
  `TIER_1_TOOLS` + `_TIER_1_BASE` + `DOUBT_DEFAULT_TOOLS` appends
  (code_common/tools.py), hybrid-mode force-append and `internal_only` mode
  inclusion (`Conversation._get_enabled_tools()`), tool-awareness preamble
  bullet + dedicated `internal_only` guidance section (reply()), compact
  `SEARCH_LOCAL_INTERNAL_KB_WORKFLOW_HINT` on the doubt-clearing and
  temp-LLM-action surfaces, and the `internal_only` option tooltip in
  interface/interface.html.

Tool API: `queries` (1–8 keyword-style strings; string/`query` normalised),
`max_results_per_query` (1–10, default 5), `full` (bool — untruncated chunks
instead of 1200-char previews). Handler runs `internal-kb search -n N
[--full] <query>` per query (30s local timeout each), labels sections
`## KB query: ...`, treats the script's exit-1-with-"no results" as a clean
miss (not an error), and never raises.

Verification (2026-07-07, script present): registration + all three tier
lists + OpenAI param generation OK; live hit returned chunk with
`===== [score] (age d old) from:` header; hit+miss mix labeled correctly
with no spurious error; all-miss appended the fallback nudge; empty args
error; string query + `full` + `max_results_per_query` accepted;
`py_compile` clean on both files.
