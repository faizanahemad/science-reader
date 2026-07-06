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
   would you fire — do that" to get a good answer.
2. Preamble tip: `Conversation.py` "Tool Usage Guidance" block (reply() around
   the `tool_awareness_text` construction) conditionally appends an
   `internal_search` bullet when `INTERNAL_SEARCH_AVAILABLE`, repeating the
   same three levers. In `internal_only` mode the entire block is replaced by
   a dedicated version with "weaknesses" and "how to get good results"
   sections covering parallel-within-a-call, parallel-across-calls, and
   multi-round usage.

## Tool API

- Name: `internal_search`; category `search`; non-interactive.
- Parameters:
  - `queries` (required): array of 1–8 self-contained query strings. A bare
    string or a legacy `query` arg is also accepted and normalised.
  - `timeout_seconds` (optional): per-query remote timeout, default 240,
    clamped to 30–600.

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
