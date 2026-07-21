# CKT Company Retrieval Tools

## Purpose

The chat application uses normal OpenAI-style native tool calling for company retrieval. The selected chat model plans retrieval, asks for tool calls, receives their results as `role="tool"` messages, performs any needed follow-up calls, and writes the final answer.

Corp Knowledge Tools (CKT) supplies evidence and bounded specialist retrieval only. The Flask/chat process never imports CKT runtime code. Each native tool call is an argv subprocess launched through a CKT façade, so CKT's thin-to-core transport, enterprise authorization, and remote backends remain outside the chat process.

```text
chat model
  -> native tool schema and tool loop
  -> trusted chat handler validates input and builds allow-listed argv
  -> $INTERNAL_TOOLS_PATH/bin/ckt-* façade
  -> local CKT core, or thin -> one SSH hop -> deployed CKT core
  -> stdout returned to the model as a tool result
  -> chat model synthesizes the user answer
```

This is distinct from the deprecated `local/gemini-rag` and `local/gemini-agent` main-model routes. Those paths can remain compatible with persisted settings, but they are not the intended company-retrieval architecture. When the CKT surface is configured, legacy `internal-search` and `internal-kb` registrations are suppressed instead of becoming silent fallbacks.

## Configuration and availability

Set exactly one environment variable before starting Flask:

```bash
export INTERNAL_TOOLS_PATH="$HOME/dev/corp-knowledge-tools"
python server.py
```

The adapter accepts no per-tool root paths. It resolves only these allow-listed executables below `$INTERNAL_TOOLS_PATH/bin`:

- `ckt-jetski-query`
- `ckt-internal-kb`
- `ckt-moma-bm25-read`
- `ckt-system-flow-research`
- `ckt-code-trace`
- `ckt-duckie-retrieval-query`

The CKT group registers only when every listed executable exists and is executable. Availability is evaluated while `code_common.tools` imports, so restart Flask after changing `INTERNAL_TOOLS_PATH` or deploying a new CKT checkout. If the root is unset, the existing legacy host-gated surface remains the compatibility path.

Every CKT subprocess has a hard 120-second outer deadline. The adapter invokes commands with an argv list, not a shell string: model-provided arguments cannot become shell syntax. The adapter does not implement SSH, manage credentials, or log the full user prompt/answer; CKT owns its authorized thin/core transport.

### Deployment caveat

On a thin/macOS installation, a bin wrapper may dispatch to the deployed Cloudtop/core checkout. Deploy the matching CKT revision there before relying on newly added façade commands. A locally present wrapper alone does not prove the remote core understands the command.

## Native tool catalog

| Native tool | CKT argv mapping | Inputs and output | Typical latency |
|---|---|---|---|
| `read_url` | `ckt-jetski-query --json --read <url> ...` | Reads one to eight known internal URLs. Preserves per-read status/output from CKT. | Very Fast, <10s |
| `moma_search` | `ckt-jetski-query --json --moma <query>` | Moma document/team discovery. Use to find URLs and vocabulary. | Very Fast, <10s |
| `moma_bm25_read` | `ckt-moma-bm25-read --timeout 120 [--crawl] [limits] <query> ...` | One to six Moma queries, concurrent reads, BM25-ranked source chunks. Raw evidence, not final synthesis. | Fast, ~15s |
| `yaqs_search` | `ckt-jetski-query --json --yaqs <query>` | Internal engineering Q&A lookup. | Very Fast, <10s |
| `code_search_standard` | `ckt-jetski-query --json --cs [--dir <dir>] <query>` | Deterministic literal Code Search for a known symbol, string, or filter. | Very Fast, <10s |
| `kb_search` | `ckt-internal-kb search <query> -n <count>` | Cached CKT internal-KB evidence; `max_results` is bounded to 1–20. | Very Fast, <10s |
| `system_flow_research` | `ckt-system-flow-research <query>` | Bounded Moma-first, source-grounded system-flow explanation. | Medium Speed, ~20s; 120s tail |
| `code_trace` | `ckt-code-trace [--directory <dir>] <question> <symbol> ...` | One to four deduplicated symbols; parallel literal Code Search; grouped raw results. | Very Fast, <10s |
| `duckie_search` | `ckt-jetski-query --json --duckie <query>` | One focused Duckie grounded response. | Medium Speed, ~45s; 120s tail |
| `ckt_duckie_retrieval` | `ckt-duckie-retrieval-query --query-count <1..6> --timeout 120 <query>` | Multi-lens raw Duckie evidence JSON; no final synthesis in the façade. | Medium Speed, ~60s; 120s tail |

The `--json` flag requests CKT's structured mode for Jetski-backed commands. The adapter does not require JSON to declare success: it preserves successful text output, and canonicalizes output only when stdout is valid JSON. This permits the current façade behavior to evolve without losing usable evidence.

## Retrieval policy and latency

Tool calls are free in monetary terms. Optimize for user wall-clock time and evidence coverage, not for minimizing the number of calls.

1. **Round 1:** issue independent Very Fast calls in parallel: `kb_search`, `moma_search`, `read_url`, `yaqs_search`, `code_search_standard`, and `code_trace` average under 10 seconds. `moma_bm25_read` is Fast at about 15 seconds and is appropriate in the opening wave when ranked multi-page evidence is needed.
2. **Round 2+:** inspect returned URLs, symbols, terminology, claims, and gaps. Then issue targeted reads, verification, deeper retrieval, re-use Fast tools with refined queries, or use one or more Medium Speed tools in parallel where they answer distinct remaining questions.
3. **Medium Speed tools:** `system_flow_research` averages about 20 seconds, `duckie_search` about 45 seconds, and `ckt_duckie_retrieval` about 60 seconds. Their 120-second tails are a latency consideration, not a prohibition: use them when their specialized evidence or synthesis improves coverage.
4. **Depth:** normally use at least two retrieval rounds before synthesizing a non-trivial internal answer. A single round is acceptable only when a narrow question is directly and fully answered by an immediately found or read page. If the user signals urgency or asks for a shorter answer, reduce the number of rounds or choose a faster tool mix.

Independent non-interactive tool calls in one model response execute in parallel in the application tool loop. CKT tools can themselves run concurrent work (for example, BM25 page reads, code-trace symbol searches, or multi-lens Duckie retrieval), so avoid assuming that one tool call corresponds to one backend request.

Raw evidence results are material for the chat model to assess and synthesize. Do not present a result as complete if evidence is thin, partial, stale, contradictory, or only answers one facet of a broad question.

## Tool modes and UI

The settings modal exposes a **Company Retrieval (CKT; host-gated)** group in Manual Selection. Each option is present in the UI so a saved/manual selection can request it; server-side registration still determines whether the handler is available.

- **Internal Search Only** exposes only the 10 CKT tools when CKT is configured. No web/document/general tools are made available in that mode.
- **Manual** exposes exactly the selected registered tool names.
- **Smart Select** asks the selector model to choose relevant tools. Tool descriptions carry latency tiers; the selector is prompted to prefer Very Fast discovery tools for the opening selection and include Medium Speed tools when their task shape is relevant.
- **Hybrid** adds `request_tools`, allowing the model to load additional registered tools after an initial selection.
- **Tiered** does not force all CKT tools into every ordinary completion. This avoids unnecessary tool-schema tokens; `request_tools`, Manual, Internal Search Only, Smart, and Hybrid make the surface available where appropriate.
- **Doubt clearing** and temporary LLM actions receive the CKT workflow guidance when CKT is configured. They permit enough iterations for a recon and a follow-up retrieval hop.

## Failure and partial-result semantics

The adapter returns a normal tool result on zero exit with nonempty stdout. It intentionally preserves stdout from a nonzero exit as partial evidence and attaches an error telling the model to inspect that partial result. This matters for composite façades that can retrieve some evidence before a deadline or backend failure.

| Condition | Model-visible behavior |
|---|---|
| Root unset, binary missing, or binary not executable | Tool group is not registered, or a direct call returns a clear unavailable error. |
| Invalid/missing tool argument | Handler returns a validation error without starting a subprocess. |
| Outer 120-second timeout | Handler returns `<tool> timed out after 120s.` No legacy-model/tool fallback occurs. |
| Nonzero exit with stdout | Stdout is returned as partial result plus an incomplete-result error. |
| Nonzero exit without stdout | Tool error contains exit code and a bounded stderr tail. |
| Valid JSON stdout | The adapter compacts the JSON for the model; non-JSON output remains text. |

The chat model should use a failure or partial result as a signal to refine/retry with another appropriate source, not as evidence that the underlying company information does not exist.

## Implementation map

- `code_common/ckt_internal_tools.py`
  - Single-root resolver and executable allow-list.
  - Bounded native input normalization and argv construction.
  - Uniform 120-second subprocess timeout, stdout/stderr handling, and JSON compaction.
- `code_common/tools.py`
  - Conditional CKT registration and native OpenAI schemas.
  - CKT tool descriptions, latency-aware Smart Select guidance, and reusable workflow prompt policy.
  - Legacy internal adapters are disabled when `INTERNAL_TOOLS_PATH` is set.
- `Conversation.py`
  - Resolves CKT names for `internal_only`.
  - Injects the CKT latency/parallel/multi-hop policy into normal chat, Internal Search Only, doubt clearing, and temporary-action tool loops.
- `interface/interface.html`
  - CKT Manual Selection group and Internal Search Only label.
- `tests/test_ckt_internal_tools.py`
  - Availability, argv contracts, argument bounds, timeout/error behavior, and workflow-policy text coverage.

## Verification and operations

Focused unit verification:

```bash
./.venv/bin/python -m pytest tests/test_ckt_internal_tools.py -q
./.venv/bin/python -m py_compile code_common/ckt_internal_tools.py code_common/tools.py Conversation.py
```

A configured-root registration smoke check:

```bash
INTERNAL_TOOLS_PATH="$HOME/dev/corp-knowledge-tools" \
  ./.venv/bin/python - <<'PY'
from code_common.ckt_internal_tools import CKT_INTERNAL_TOOL_NAMES
from code_common.tools import CKT_INTERNAL_TOOLS_AVAILABLE, TOOL_REGISTRY
assert CKT_INTERNAL_TOOLS_AVAILABLE
assert all(TOOL_REGISTRY.get_tool(name) for name in CKT_INTERNAL_TOOL_NAMES)
print("CKT tools registered:", ", ".join(sorted(CKT_INTERNAL_TOOL_NAMES)))
PY
```

For a live thin-path smoke test, first deploy the matching CKT revision to the core. Then use a short factual prompt in Manual or Internal Search Only mode, confirm a tool status/result event, and confirm that the normal selected chat model produces the synthesis. Keep test prompts and captured evidence free of credentials or sensitive user data.
