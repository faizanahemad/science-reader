# Internal Search Fast-Path Tools — search_moma, search_yaqs, get_bug, search_code, search_code_standard, ask_internal_kb

## Motivation and background

The existing internal-knowledge tool group (`internal_search`,
`read_internal_page`, `search_local_internal_kb` — see
`internal_search_tool.md`) covers general agentic internal search and a local
BM25 cache. The underlying `jetski-query` wrapper script and `internal-kb`
companion tool were separately extended with **typed fast paths**: several
common internal lookups (Moma docs/people/teams, YAQS Q&A, a specific
Buganizer bug, a codebase question) have their own dedicated, deterministic
binaries on the authorized host that are dramatically cheaper (~1-3s) than
routing through the general agentic CLI (~30-90s+), with equal or better
precision since there's no LLM paraphrasing step. `internal-kb` also grew an
`ask` subcommand that unifies "check the cache, and if it's not good enough,
run one live query" into a single call.

`jetski-query` was later extended again with a SECOND, distinct code-search
fast path: `--code-search`, wrapping the standard regex-indexed `cs` CLI
(`http://go/cs-reference`) — NOT an LLM call, unlike the pre-existing `--code`
(CodeSearch Agent, `cs_agent_cli`). `search_code_standard` exposes this to the
chat model as its own tool, sitting alongside `search_code` (kept unchanged,
still the LLM agent).

This doc specs the 6 new tools that expose those capabilities to the chat
model, following the exact conventions established by the original 3-tool
group.

## Availability gating (host-gated)

All 6 tools shell out to the SAME `jetski-query` script as `internal_search`
(just invoked with its typed `--moma`/`--who`/`--team`/`--yaqs`/`--bug`/
`--code`/`--code-search` flags), so 5 of them ride the existing
`INTERNAL_SEARCH_AVAILABLE` flag with no new script path:

- `search_moma`, `search_yaqs`, `get_bug`, `search_code`,
  `search_code_standard` — gated on `INTERNAL_SEARCH_AVAILABLE`.
- `ask_internal_kb` — additionally gated on `INTERNAL_KB_AVAILABLE` (it calls
  `internal-kb ask`, not `jetski-query` directly), so it requires BOTH flags.

Defined in `code_common/tools.py`, section "Typed fast-path internal tools
(moma/yaqs/bug/code/code-search) + ask_internal_kb", directly below the
`search_local_internal_kb` registration. Each `@register_tool` call is
wrapped in the appropriate `if ... AVAILABLE:` guard, so on hosts without the
scripts these tools are simply absent everywhere (tool menu, smart select,
`request_tools`, manual selector) — same zero-footprint pattern as the
original 3.

## Latency classes (drives tool choice — stated explicitly in each description)

- **Fast/typed tier (~1-3s, no LLM)**: `search_moma`, `search_yaqs`,
  `get_bug`, `search_code_standard`. No agentic fallback inside the script —
  a miss/error means the CALLING MODEL must itself fall back to
  `internal_search`, mirrored in each tool's description with a shared
  `_FASTPATH_NO_FALLBACK_NOTE` suffix. `search_code_standard` is a plain
  regex-indexed CodeSearch query (`go/cs-reference` filter syntax:
  `f:`/`c:`/`func:`/`class:`/`symbol:`/`lang:`/`within:`, etc) — use it when
  you already know a specific symbol/string/pattern.
- **Slow/agentic tier (LLM-backed, comparable to internal_search)**:
  `search_code` — it's itself the CodeSearch AGENT, not a deterministic
  lookup. Its description explicitly warns the model NOT to treat an empty
  result the same as the fast tier's "escalate to internal_search" rule,
  since internal_search has no code access either, and to prefer
  `search_code_standard` first when the question already names a specific
  symbol/string.
- **Hybrid tier (usually fast, sometimes escalates)**: `ask_internal_kb` —
  auto-escalates KB-to-live using the existing BM25 `--skip-score` threshold
  (a cost decision), but always returns a TIER-labeled result (a correctness
  decision left to the calling model, not hidden inside the tool).

## Tool specs

### `search_moma`

Consolidates `jetski-query`'s `--moma`/`--who`/`--team` fast paths into one
tool with a `mode` enum, mirroring `internal-kb`'s own collapse of all three
into a single `source_type="moma"` for per-type KB TTL.

- Params: `mode` (enum `search`/`who`/`team`, required), `query` (string,
  required).
- Handler `handle_search_moma`: maps mode to the right jetski-query flag
  (`--moma`/`--who`/`--team`) and runs it via the shared `_run_fastpath`
  helper (45s local timeout).

### `search_yaqs`

- Params: `query` (string, required).
- Handler `handle_search_yaqs`: runs `jetski-query --yaqs "<query>"`.

### `get_bug`

- Params: `bug_id` (string, required — validated as `^\d+$` before shelling
  out; a non-numeric ID is rejected immediately with a message pointing the
  model at `internal_search` for topic/keyword bug search instead of
  round-tripping to the remote script).
- Handler `handle_get_bug`: runs `jetski-query --bug <bug_id>`.
- Description notes bugs use a shorter 3-day local-KB TTL (vs 7/30 days for
  moma/yaqs/others) since bug status changes often — prefer this live tool
  over a cached KB hit when currency matters.

### `search_code`

- Params: `query` (string, required), `dir` (string, optional — scope to a
  subpackage/path), `timeout_seconds` (int, default 60, clamped 30-300).
- Handler `handle_search_code`: runs `jetski-query --code "<query>" [--dir
  <dir>]` via `_run_fastpath` with `timeout_s=timeout_seconds + 30` local
  headroom.
- Explicitly NOT part of the "no fallback needed, just escalate to
  internal_search" framing — it's itself an LLM agent (`cs_agent_cli`, the
  CodeSearch Agent).
- Description now explicitly steers the model to `search_code_standard`
  first when the question names a specific symbol/string it already knows.

### `search_code_standard`

- Params: `query` (string, required — `go/cs-reference` filter syntax, e.g.
  `func:calculateTotal` or `f:foo\.py c:"deprecated = true"`), `dir` (string,
  optional — scope to a subpackage/path, folded into the query as an extra
  `f:<dir>` restrict by the underlying `jetski-query --code-search` fast
  path).
- Handler `handle_search_code_standard`: runs `jetski-query --code-search
  "<query>" [--dir <dir>]` via `_run_fastpath` (default 45s local timeout —
  no `timeout_seconds` param, unlike `search_code`, since the underlying `cs`
  CLI call is deterministic and fast, ~1-3s).
- Standard, regex-indexed Code Search (the internal `cs` CLI, NOT an LLM
  call) — deterministic, no paraphrasing, returns raw `file:line: snippet`
  matches. Part of the "no fallback needed" fast tier alongside
  `search_moma`/`search_yaqs`/`get_bug` (shares `_FASTPATH_NO_FALLBACK_NOTE`).
- Description explicitly steers the model to `search_code` (the agent)
  instead for conceptual/reasoning-shaped questions ("how does X work").

### `ask_internal_kb`

- Params: `query` (string, required — single focused question, NOT a list;
  decomposition into multiple angles is `internal_search`'s job), `skip_score`
  (float, default -3.0 — passthrough to `internal-kb ask --skip-score`),
  `no_live` (bool, default False — KB-only, never escalate), `full` (bool,
  default False — untruncated chunk).
- Handler `handle_ask_internal_kb`: runs `internal-kb ask "<query>"
  --skip-score <N> [--no-live] [--full]` via `_run_fastpath` (210s timeout to
  cover the possible live-fallback branch, which costs about as much as one
  `internal_search` query).
- **Tier labeling**: `internal-kb ask` prints either `[KB hit, score ..., ...
  from: ...]` (cache path) or `[live answer]` (fallback fired). The handler
  detects which and prepends one of:
  - `[TIER: cache-hit — this is a CACHED excerpt, possibly stale. ...]`
  - `[TIER: live-single-shot — ONE live query, escalated because the cache
    had no good match. This is a first-round answer ONLY, not
    internal_search's multi-round decompose+critique+deepen workflow. ...]`
  - A short-answer warning (`body_len < 200` chars) is appended when the tier
    note fires, nudging the model toward `internal_search` if the answer
    looks thin.
  - This directly encodes the escalation-criterion brainstorm resolution: the
    tool automates the cheap COST decision (whether to fire a live query) but
    never automates the CORRECTNESS decision (whether the returned answer
    is deep enough) — that judgment call stays with the calling model, fed
    by the tier label + thinness heuristic, same philosophy as
    `search_local_internal_kb`'s existing "fall back NOW" marker.

## Wiring (mirrors the original 3-tool group exactly)

- **`TIER_1_TOOLS` / `_TIER_1_BASE` / `DOUBT_DEFAULT_TOOLS`** appends in
  `code_common/tools.py`, directly below the `search_local_internal_kb`
  append block: `search_moma`/`search_yaqs`/`get_bug`/`search_code`/
  `search_code_standard` gated on `INTERNAL_SEARCH_AVAILABLE`;
  `ask_internal_kb` gated on BOTH `INTERNAL_SEARCH_AVAILABLE` and
  `INTERNAL_KB_AVAILABLE`.
- **Hybrid mode force-append** in `Conversation._get_enabled_tools()`
  (`hybrid` branch): all 5 fast-path tools force-included alongside
  `internal_search`/`read_internal_page` when `INTERNAL_SEARCH_AVAILABLE`;
  `ask_internal_kb` force-included when both flags are set. Smart selection
  can never drop them, same as the original 3.
- **`internal_only` tool mode**: `enabled_names` now includes
  `search_moma`/`search_yaqs`/`get_bug`/`search_code`/`search_code_standard`
  unconditionally (same gate as `internal_search`) and
  `search_local_internal_kb`/`ask_internal_kb` when `INTERNAL_KB_AVAILABLE`.
  Group grew from 3 tools to up to 9.
- **Doubt-clearing / temp-LLM-action surfaces** (`Conversation.py`, the two
  sites that build `tool_names` for those flows independent of the general
  tools toggle): both now include the 5 fast-path tools unconditionally
  (host-gated) and `search_local_internal_kb`/`ask_internal_kb` when the KB
  script exists — same treatment as `internal_search`/`read_internal_page`
  already had. Compact workflow-hint constants
  `FASTPATH_TOOLS_WORKFLOW_HINT` and `ASK_INTERNAL_KB_WORKFLOW_HINT` (in
  `code_common/tools.py`, same style as `INTERNAL_SEARCH_WORKFLOW_HINT` /
  `READ_INTERNAL_PAGE_WORKFLOW_HINT` / `SEARCH_LOCAL_INTERNAL_KB_WORKFLOW_HINT`)
  are appended to the system prompt on those surfaces when the relevant
  tools are present.
- **Tool-awareness preamble** (`Conversation.reply()`, the block that injects
  `## Tool Usage Guidance` when tools are active): both the `internal_only`
  branch and the general branch now describe all 6 new tools, their latency
  classes, and fallback rules (or lack thereof), alongside the existing
  bullets for the original 3.
- **`interface/interface.html`**:
  - New `<optgroup label="Internal Search (host-gated)">` in the manual-mode
    `#settings-tool-selector` with all 9 tools (`internal_search`,
    `read_internal_page`, `search_local_internal_kb`, `ask_internal_kb`,
    `search_moma`, `search_yaqs`, `get_bug`, `search_code`,
    `search_code_standard`). NOTE: prior to the original change, the
    original 3 host-gated tools were entirely ABSENT from the
    manual-selector dropdown (they only ever appeared via
    hybrid/tiered/internal_only force-append or smart selection) — that
    optgroup fixed that gap for the whole group.
  - The `internal_only` `<option>`'s `title` tooltip updated to list all 9
    tools.

## Manual mode note

Manual mode enables tools purely by name (`enabled_tools` list from the
selector, or category-checkbox expansion) — none of the fast-path tools are
`selected` by default in the optgroup (matching the pattern for other
non-default-on tools like PKB), so a user in manual mode must explicitly
check them, or use hybrid/tiered/internal_only/smart modes where they are
force-included whenever the host scripts exist.

## Files modified (search_code_standard addition)

- `~/.local/bin/jetski-query` — new `--code-search` fast path (standard `cs`
  CLI, non-agentic), `CS_BIN`/`CS_MAX_RESULTS` env overrides, `fp_type`
  tagging (`codesearch`), header docs/usage updated.
- `~/.local/bin/internal-kb` — `codesearch` added to
  `DEFAULT_TTL_DAYS_BY_TYPE` (30d, same as `code`) and SOURCE TYPES doc.
- `code_common/tools.py` — `_SEARCH_CODE_STANDARD_DESCRIPTION`,
  `handle_search_code_standard`, `search_code_standard` `@register_tool`
  call; `search_code` description updated to steer toward the new tool
  first; `TIER_1_TOOLS`/`_TIER_1_BASE`/`DOUBT_DEFAULT_TOOLS` appends;
  `FASTPATH_TOOLS_WORKFLOW_HINT` updated.
- `Conversation.py` — all 5 call sites that previously hardcoded the
  `search_moma`/`search_yaqs`/`get_bug`/`search_code` fast-path tuple/list
  (internal_only mode, hybrid force-append, doubt-clearing tool-name/hint
  assembly x2, tool-awareness preamble x2) now also include
  `search_code_standard`.
- `gemini-agent-query` (`gaq/tools.py`, `gaq/prompts/system.md`,
  `tests/test_core.py`) — sibling `_h_code_search_standard` handler +
  `code_search_standard` tool registration wrapping
  `backends.call_jetski_fastpath("--code-search", ...)` (the existing
  generic fastpath wrapper needed no changes); system prompt and test
  updated.
- `interface/interface.html` — new `search_code_standard` `<option>` in the
  manual-selector optgroup; `internal_only` option tooltip updated.
- `google-internal-agent-tools` skill — documented `--code-search` alongside
  `--code`.

## Files modified (original 3-tool group)

- `code_common/tools.py` — new section: 5 description constants, shared
  `_run_fastpath` helper, 5 handler functions, 5 `@register_tool`
  registrations (4 gated on `INTERNAL_SEARCH_AVAILABLE`, 1 additionally on
  `INTERNAL_KB_AVAILABLE`), `TIER_1_TOOLS`/`_TIER_1_BASE`/`DOUBT_DEFAULT_TOOLS`
  appends, 2 new compact workflow-hint constants.
- `Conversation.py` — `_get_enabled_tools()` (`internal_only` and `hybrid`
  branches), doubt-clearing tool-name/hint assembly, temp-LLM-action
  tool-name/hint assembly, tool-awareness preamble (`internal_only` branch
  and general branch).
- `interface/interface.html` — new manual-selector optgroup, updated
  `internal_only` option tooltip.

## Verification

`python3 -m py_compile code_common/tools.py Conversation.py` — passes. Live
exercise of the fast-path binaries (`--moma`/`--who`/`--team`/`--yaqs`/
`--bug`/`--code`/`--code-search`) and `internal-kb ask`'s live-fallback
branch requires the authorized host's SSH access; `--code-search` was
verified LIVE via SSH to `faizan-001.c.googlers.com` (`cs -n
--max_num_results=N "func:calculateTotal"` and with a `--dir` scope, both
returning real matches in ~2s) at the `jetski-query` script level. The rest
(`--moma`/`--who`/`--team`/`--yaqs`/`--bug`/`--code`) were previously
verified at the script level (see
`~/.local/share/internal-kb/docs/knowledge-tools-plan.md` and the
`google-internal-agent-tools` skill) — not re-testable in this sandbox; the
app-side registration/wiring was verified via compile checks and manual
review of each call site against the existing pattern. `gaq`'s pytest suite
(34 tests) passes with the new tool registered.

See also: `internal_search_tool.md` for the original 3-tool group this
extends.
