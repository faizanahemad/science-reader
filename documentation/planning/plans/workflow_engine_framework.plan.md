---
name: Workflow Engine Framework
overview: >
  A self-contained, embeddable workflow execution engine that enables users to define, run, and
  manage multi-step LLM workflows for deep research, iterative document writing, and Q&A compilation.
  Workflows consist of steps (LLM calls, tool-only calls, user input checkpoints, LLM judge
  evaluations, sub-workflows) organized as chains, loops, or parallel groups. A shared mutable state
  (JSON object + markdown scratch pad) flows between steps. The engine supports pause/resume,
  user guidance injection, step-level debug inspection, retry/skip/revert, and automatic checkpointing
  for crash recovery. It runs standalone (own Flask server + CLI) or embedded in the main chat app
  via adapter pattern. Pre-built templates (Deep Research, Document Writer, Q&A Research) ship
  with the system and are clone-and-customizable. Workflows are also exposed as MCP tools for
  external agent consumption.

goals:
  - Build a lightweight, self-contained workflow execution engine in workflow_engine/ that can run standalone or be embedded in the existing Flask chat app.
  - Support step types: llm, tool_only, user_input, judge, sub_workflow, loop, parallel_group.
  - Implement mutable shared state (JSON state object + markdown scratch pad) that persists across steps and loop iterations.
  - Support loops with LLM judge stop conditions (natural language criteria) and/or fixed iteration counts.
  - Support parallel step groups with per-step output_key isolation and markdown pad locking.
  - Support workflow composition (chaining workflows, nesting up to depth 3).
  - Enable user interaction during execution: pause, guidance injection, ask_clarification reuse, retry/skip/revert steps.
  - Checkpoint execution state to disk after every step for crash recovery and cross-device resume.
  - Provide real-time UI updates via SSE with one-time polling fallback for cross-tab/device load.
  - Ship 3 pre-built clone-and-customizable templates (Deep Research, Document Writer, Q&A Research).
  - Expose workflows as MCP tools with async start + poll interface.
  - Support up to 3 concurrent workflow runs per user (configurable).
  - Keep the workflow UI fully decoupled from the main chat UI for reusability in other projects.

design_decisions:
  - Engine location: Self-contained workflow_engine/ at project root. Own Flask blueprint, models, executors, adapters, templates, tests.
  - Deployment modes: (1) Standalone Flask server on configurable port + CLI mode. (2) Embedded in main Flask app via blueprint import.
  - LLM access: Adapter pattern. Abstract LLMAdapter interface. Main app provides CallLLmAdapter. Standalone provides DirectOpenAIAdapter.
  - Tool access: When embedded, steps use the existing TOOL_REGISTRY from code_common/tools.py. When standalone, a StandaloneToolAdapter provides basic tool capabilities.
  - Storage: Own configurable storage directory (workflow_storage/ by default). SQLite for user workflows + run history. JSON files for pre-built templates shipped with code.
  - Auth: No auth on localhost (standalone). Optional API key for remote access. Session auth when embedded in main app.
  - Run IDs: wfr_YYYYMMDD_XXXX format (timestamp + 4-char random hex). Sortable, readable, unique.
  - No conversation binding: Workflows are standalone entities. Access global docs, memory, PKB, MCP tools via tool registry — not tied to any conversation.
  - Output destination: Workflow output lives in the workflow panel. User manually exports to artefact, global doc, file download, or clipboard.
  - Template syntax: {{state.field_name}} for referencing state in prompt templates.
  - Concurrency: Max 3 concurrent runs per user (configurable). Enforced by engine.
  - No Airflow/Dagster: Custom lightweight engine. Airflow/Dagster are batch-oriented with no concept of user-in-the-loop interactive pauses, mutable shared state, or real-time streaming to browser.
  - Scratch pad architecture: JSON state (structured data, flow control, debug info) + markdown pad (accumulating draft document). Both persist, both user-editable in debug view.
  - Loop architecture: Loop body can be single step or sub-workflow of steps. Judge sees full scratchpad + latest output + original goal + current state.
  - Parallel execution: Explicit parallel_group step type. Each child step writes its own output_key. Markdown pad is locked during parallel execution (append-only optimization deferred to later).
  - Composability: Workflow B inherits state from workflow A when chained. Steps can invoke sub-workflows (nesting). Max depth 3, configurable.
  - Error handling: Auto-retry with backoff → skip → halt and ask user. Never silently abort.
  - Real-time UI: SSE for streaming step events. One-time polling API for cross-tab/device state load.
  - UI location: Right drawer overlay + /workflows standalone route + pop-out window. UI module fully decoupled from main chat UI.
  - Step editor: Nested/indented tree for loops and parallel groups.
  - Workflow trigger: Sidebar panel button + /workflow chat command. Both open the workflow panel.
  - MCP exposure: Workflows as MCP tools. Async start returns run_id. Caller polls status/result.
  - Templates: 3 pre-built (Deep Research, Doc Writer, Q&A). JSON files. Clone-and-customize. Freeform prompt launch with optional parameters.
  - History: Keep last N runs per user (configurable, default 20). Auto-cleanup of older runs.
  - Clarification UI: Reuse existing Bootstrap modal pattern (tool-call-manager style). Modular so it works in other systems too.

files_affected:
  # New files (workflow_engine/ module)
  - workflow_engine/__init__.py: Module init, version, public API exports.
  - workflow_engine/__main__.py: Entry point for standalone mode (python -m workflow_engine). Supports 'serve' and 'run' subcommands.
  - workflow_engine/models.py: Data models — WorkflowDefinition, StepDefinition, WorkflowRun, RunState, StepResult, CheckpointData.
  - workflow_engine/engine.py: Core execution engine — WorkflowEngine class. Step dispatch, loop control, parallel execution, state management, checkpointing.
  - workflow_engine/executors.py: Step executor implementations — LLMStepExecutor, ToolOnlyExecutor, UserInputExecutor, JudgeExecutor, SubWorkflowExecutor.
  - workflow_engine/state.py: SharedState class — JSON state + markdown pad management, locking, merge strategies, template rendering.
  - workflow_engine/adapters.py: Abstract interfaces (LLMAdapter, ToolAdapter, StorageAdapter, EventBus) + concrete adapters for standalone and embedded modes.
  - workflow_engine/events.py: Event types and SSE event bus — StepStarted, StepCompleted, StepFailed, UserInputRequested, WorkflowCompleted, etc.
  - workflow_engine/checkpointing.py: Checkpoint save/load, crash recovery, run history management.
  - workflow_engine/storage.py: SQLite schema for workflow definitions + run history. JSON template loader.
  - workflow_engine/endpoints.py: Flask blueprint with /workflows/* REST API + /workflow_events/<run_id> SSE endpoint.
  - workflow_engine/cli.py: CLI interface for 'run' subcommand (non-interactive workflow execution with stdout output).
  - workflow_engine/templates/: Directory containing pre-built workflow template JSON files.
  - workflow_engine/templates/deep_research.json: Deep Research template definition.
  - workflow_engine/templates/document_writer.json: Document Writer template definition.
  - workflow_engine/templates/qa_research.json: Q&A Research template definition.
  - workflow_engine/config.py: Configuration dataclass — storage paths, limits, defaults, adapter selection.
  - workflow_engine/errors.py: Custom exception hierarchy — WorkflowError, StepError, StateError, CheckpointError.
  - workflow_engine/tests/: Test directory.

  # New UI files
  - interface/workflow-panel.js: Decoupled workflow panel UI module — step editor, run view, debug view, state inspector. Factory pattern like createFileBrowser().
  - interface/workflow-panel.css: Standalone CSS for workflow panel (no dependencies on main app styles beyond Bootstrap 4.6).
  - interface/workflow-standalone.html: Standalone HTML page served at /workflows route. Loads workflow-panel.js independently.

  # Modified files (main app integration)
  - server.py: Register workflow_engine blueprint when embedded. Pass AppState adapter config.
  - interface/interface.html: Add workflow drawer container div, trigger button in navbar, /workflow chat command handler.
  - interface/interface.js: Drawer toggle logic, pop-out window handler.
  - interface/common-chat.js: /workflow chat command detection and dispatch.
  - interface/style.css: Drawer overlay CSS (position, z-index, transitions).
  - interface/service-worker.js: Add workflow-panel.js and workflow-panel.css to precache. Bump CACHE_VERSION.
  - mcp_server/workflows.py: New MCP tool registrations for workflow start/status/result. Located in mcp_server/ (not workflow_engine/) to follow existing MCP server pattern.
  - code_common/tools.py: Register workflow tools in TOOL_REGISTRY (when embedded).

risks_and_alternatives:
  - RISK: Long-running workflows (up to 60 min) may hit HTTP/SSE connection timeouts behind nginx.
    MITIGATION: SSE endpoint uses long-lived connection with periodic keepalive pings. Nginx proxy_read_timeout already set to 3600s. If SSE disconnects, frontend reconnects and uses polling API for missed events.
  - RISK: Concurrent workflows (up to 3 per user) could strain server resources (threads, memory, API rate limits).
    MITIGATION: Each workflow run uses a single thread (sequential step execution within a run). Parallel steps within a workflow use ThreadPoolExecutor with bounded workers. Total thread count per workflow is bounded at max_parallel_steps (default 5). Rate limiting per user via existing Flask-Limiter.
  - RISK: Checkpoint files could grow large for long workflows with large scratch pads.
    MITIGATION: Checkpoints store state diffs (delta from previous checkpoint) for runs beyond 10 steps. Full snapshot every 10 steps. Configurable max scratchpad size (default 100KB markdown, 50KB JSON).
  - RISK: Template syntax {{state.field}} could conflict with Jinja2 or other template engines.
    MITIGATION: Use custom template renderer (not Jinja2). Simple regex-based substitution for {{state.*}} and {{config.*}} patterns. No complex logic in templates — keep it to variable substitution only.
  - RISK: Nested workflow depth (up to 3) could create confusing state inheritance and debugging.
    MITIGATION: Each nesting level gets a namespaced state prefix (e.g., state.parent.field vs state.field). Debug view shows nesting breadcrumb. Hard depth limit enforced in engine.
  - RISK: Markdown pad locking during parallel steps could create bottlenecks.
    MITIGATION: Phase 1 uses simple lock (mutex). Future optimization: append-only mode for parallel steps (no lock needed for appends). Full edit/delete only in sequential steps.
  - RISK: MCP async poll pattern could miss workflow completion if external agent stops polling.
    MITIGATION: Completed workflow results are persisted and available via get_workflow_result() indefinitely (until history cleanup). No expiry on poll results.
  - RISK: Standalone mode needs its own LLM API key management.
    MITIGATION: Standalone config file (workflow_engine_config.json) with api_keys section. Adapter reads from config. When embedded, adapter reads from main app's keys infrastructure.
  - ALTERNATIVE: Use LangGraph for the execution engine instead of custom.
    DECISION: Custom engine chosen. LangGraph adds heavy dependency (langchain ecosystem), doesn't natively support user-in-the-loop pause/resume, and its state model (TypedDict) is less flexible than our JSON+markdown dual state. Our engine is ~500-800 lines of core logic vs pulling in an entire framework.
  - ALTERNATIVE: Use WebSocket instead of SSE for real-time updates.
    DECISION: SSE chosen. Unidirectional (server→client) is sufficient for step events. WebSocket already used for terminal but adds complexity. SSE auto-reconnects natively in browsers. User actions (pause, guidance, skip) go through REST endpoints, not the event stream.
  - ALTERNATIVE: Store workflow state in Redis for faster access and built-in expiry.
    DECISION: File-based + SQLite chosen to match existing codebase patterns and avoid new infrastructure dependency. Redis could be added later as a StorageAdapter if needed.

todos:
  # ─────────────────────────────────────────────
  # PHASE 1: Core Engine Infrastructure
  # ─────────────────────────────────────────────

  - id: p1-models
    content: |
      Create `workflow_engine/models.py` with all core data models:
      
      1. `StepType` enum: LLM, TOOL_ONLY, USER_INPUT, JUDGE, SUB_WORKFLOW, LOOP, PARALLEL_GROUP.
      
      2. `StepDefinition` dataclass:
         - id: str (unique within workflow)
         - title: str
         - step_type: StepType
         - prompt_template: str | None ({{state.field}} syntax)
         - system_prompt: str | None
         - model_override: str | None (per-step model selection)
         - tools_enabled: list[str] | None (tool category whitelist)
         - output_key: str | list[str] (where in JSON state to write result)
         - debug_keys: list[str] | None (extra state keys to capture for debug)
         - accumulator_keys: dict[str, str] | None (keys that accumulate across iterations: {key: 'append'|'merge'|'replace'})
         - write_to_scratchpad: bool (whether step output also appends to markdown pad)
         - scratchpad_instruction: str | None (how to write to scratchpad: 'append', 'replace_section', 'prepend')
         - temperature: float (default 0.7)
         - max_tokens: int | None
         - timeout_seconds: int (default 120)
         - retry_config: RetryConfig | None
         - children: list[StepDefinition] | None (for LOOP and PARALLEL_GROUP types)
         - loop_config: LoopConfig | None (for LOOP type)
         - judge_config: JudgeConfig | None (for JUDGE type)
         - sub_workflow_id: str | None (for SUB_WORKFLOW type)
         - user_input_config: UserInputConfig | None (for USER_INPUT type)
         - tool_name: str | None (for TOOL_ONLY type — which tool to invoke)
         - tool_args_template: dict | None (for TOOL_ONLY — args with {{state.field}} substitution)
      
      3. `LoopConfig` dataclass:
         - max_iterations: int (hard cap)
         - judge_step_id: str | None (reference to a JUDGE step that evaluates stop condition)
         - judge_criteria: str | None (natural language stop condition for auto-generated judge)
         - iteration_key: str (state key for current iteration count, default '_loop_iteration')
      
      4. `JudgeConfig` dataclass:
         - criteria: str (natural language evaluation criteria)
         - inputs: list[str] (state keys to include in judge prompt)
         - output_key: str (where to store judge verdict, default '_judge_verdict')
         - pass_value: str (what verdict means 'continue', default 'continue')
         - fail_value: str (what verdict means 'stop', default 'stop')
      
      5. `UserInputConfig` dataclass:
         - prompt: str (what to ask the user)
         - input_type: str ('text', 'choice', 'confirm', 'clarification')
         - options: list[str] | None (for 'choice' type)
         - required: bool (default True)
         - timeout_seconds: int (default 300)
      
      6. `RetryConfig` dataclass:
         - max_retries: int (default 3)
         - backoff_seconds: list[float] (default [2, 5, 15])
         - retry_on: list[str] (exception types: ['timeout', 'rate_limit', 'server_error'])
      
      7. `WorkflowDefinition` dataclass:
         - workflow_id: str
         - name: str
         - description: str
         - version: int
         - steps: list[StepDefinition]
         - initial_state: dict | None
         - initial_scratchpad: str | None
         - input_schema: dict | None (JSON Schema for launch parameters)
         - created_by: str (user email or 'system')
         - created_at: str (ISO timestamp)
         - updated_at: str (ISO timestamp)
         - is_template: bool
         - template_source: str | None (template ID if cloned)
         - tags: list[str] | None
         - max_runtime_seconds: int (default 3600)
         - nesting_depth_limit: int (default 3)
      
      8. `StepResult` dataclass:
         - step_id: str
         - step_title: str
         - status: str ('completed', 'failed', 'skipped', 'retried', 'waiting_for_user')
         - output: any
         - error: str | None
         - started_at: str
         - completed_at: str | None
         - duration_seconds: float | None
         - llm_model_used: str | None
         - tokens_used: dict | None ({prompt_tokens, completion_tokens, total_tokens})
         - tool_calls: list[dict] | None
         - state_before: dict | None (if debug mode)
         - state_after: dict | None (if debug mode)
         - scratchpad_diff: str | None (if debug mode)
         - resolved_prompt: str | None (if debug mode)
         - raw_llm_output: str | None (if debug mode)
         - retry_count: int (default 0)
      
      9. `RunStatus` enum: PENDING, RUNNING, PAUSED, WAITING_FOR_USER, COMPLETED, FAILED, CANCELLED.
      
      10. `WorkflowRun` dataclass:
          - run_id: str (wfr_YYYYMMDD_XXXX format)
          - workflow_id: str
          - workflow_name: str
          - user_email: str
          - status: RunStatus
          - current_step_id: str | None
          - current_step_index: int
          - total_steps: int
          - state: dict (current JSON state)
          - scratchpad: str (current markdown pad)
          - step_results: list[StepResult]
          - original_prompt: str
          - user_guidance: str | None
          - started_at: str
          - updated_at: str
          - completed_at: str | None
          - error: str | None
          - debug_mode: bool
          - nesting_depth: int (0 = top level)
          - parent_run_id: str | None
      
      11. `CheckpointData` dataclass:
          - run_id: str
          - step_index: int
          - step_id: str
          - state_snapshot: dict
          - scratchpad_snapshot: str
          - step_results_so_far: list[StepResult]
          - timestamp: str
          - run_status: RunStatus
      
      All models serializable to/from JSON via to_dict()/from_dict(). No Pydantic dependency.
      
      File: `workflow_engine/models.py`
    status: pending

  - id: p1-config
    content: |
      Create `workflow_engine/config.py` with engine configuration:
      
      1. `WorkflowEngineConfig` dataclass:
         - storage_dir: str (default 'workflow_storage')
         - db_name: str (default 'workflows.db')
         - templates_dir: str (default 'workflow_engine/templates')
         - max_concurrent_runs_per_user: int (default 3)
         - default_max_runtime_seconds: int (default 3600)
         - default_step_timeout_seconds: int (default 120)
         - default_nesting_depth_limit: int (default 3)
         - default_max_loop_iterations: int (default 20)
         - max_scratchpad_size_bytes: int (default 102400 — 100KB)
         - max_state_size_bytes: int (default 51200 — 50KB)
         - checkpoint_interval: int (default 1)
         - full_snapshot_interval: int (default 10)
         - history_retention_count: int (default 20)
         - sse_keepalive_seconds: int (default 15)
         - host: str (default '127.0.0.1')
         - port: int (default 5050)
         - api_key: str | None
         - debug_mode_default: bool (default False)
         - log_level: str (default 'INFO')
      
      2. `load_config(path: str | None) -> WorkflowEngineConfig`:
         Loads from JSON file, env vars, or defaults.
      
      File: `workflow_engine/config.py`
    status: pending

  - id: p1-errors
    content: |
      Create `workflow_engine/errors.py` with exception hierarchy:
      WorkflowEngineError (base), WorkflowNotFoundError, WorkflowRunNotFoundError,
      StepExecutionError (with step_id, step_title, original_error, retry_count),
      StepTimeoutError, StateError, CheckpointError, ConcurrencyLimitError,
      NestingDepthError, WorkflowCancelledError, UserInputTimeoutError.
      
      File: `workflow_engine/errors.py`
    status: pending

  - id: p1-state-manager
    content: |
      Create `workflow_engine/state.py` with SharedState class:
      
      SharedState manages both JSON state and markdown scratchpad with thread-safe access.
      
      Key features:
      - get/set/update/delete/has/keys for JSON state
      - snapshot()/restore() for checkpointing
      - Scratchpad: get/append/replace/replace_section/prepend/clear
      - Template rendering: render_template() substitutes {{state.key}}, {{config.key}},
        {{scratchpad}}, {{scratchpad | last_n_lines(N)}}. Simple regex, not Jinja2.
      - Accumulator support: accumulate(key, value, mode='append'|'merge'|'replace')
      - Debug: diff(previous_snapshot), get_debug_snapshot(debug_keys)
      - Size enforcement: validate_sizes()
      - Locking: RLock for thread safety, acquire_scratchpad_lock() context manager
        for parallel step scratchpad access
      
      File: `workflow_engine/state.py`
    status: pending
    dependencies:
      - p1-models
      - p1-errors

  - id: p1-adapters
    content: |
      Create `workflow_engine/adapters.py` with abstract interfaces and concrete adapters:
      
      Abstract interfaces (ABCs):
      - LLMAdapter: call(), call_with_tools()
      - ToolAdapter: execute(tool_name, args, context) -> ToolCallResult, list_tools() -> List[ToolDefinition], get_tool_categories() -> Dict[str, List[str]]. Mirrors TOOL_REGISTRY interface from code_common/tools.py.
      - StorageAdapter: save/load checkpoint, save/load run, list/delete runs, cleanup
      - EventBus: emit(), subscribe() -> Generator, unsubscribe()
      - UserInteractionAdapter: request_input(), submit_input(), request_clarification()
      
      Standalone adapters:
      - DirectOpenAIAdapter(LLMAdapter): uses openai package, reads keys from config
      - StandaloneToolAdapter(ToolAdapter): basic tools (web_search, file_read/write); returns ToolCallResult with error handling similar to tool-calling framework
      - FileStorageAdapter(StorageAdapter): JSON files in storage_dir/runs/{run_id}/
      - InMemoryEventBus(EventBus): threading.Event + queue.Queue per subscriber
      - CLIUserInteractionAdapter(UserInteractionAdapter): stdin/stdout for CLI mode
      
      Embedded adapters:
      - CallLLmAdapter(LLMAdapter): wraps existing CallLLm
      - ToolRegistryAdapter(ToolAdapter): wraps TOOL_REGISTRY from code_common/tools.py (48 tools, 8 categories). Accepts LLM tool_calls dict format, invokes @register_tool handlers, wraps ToolCallResult, supports interactive tools (ask_clarification) via threading.Event pattern
      - AppStorageAdapter(StorageAdapter): uses subdirectory under main app storage/
      - WebEventBus(EventBus): SSE-formatted events
      - WebUserInteractionAdapter(UserInteractionAdapter): threading.Event + shared dict
        (same pattern as existing tool_response_store)
      
      File: `workflow_engine/adapters.py`
    status: pending
    dependencies:
      - p1-models
      - p1-errors

  - id: p1-events
    content: |
      Create `workflow_engine/events.py` with event types and event bus:
      
      WorkflowEvent base + concrete types: WorkflowStarted, StepStarted, StepCompleted,
      StepFailed, StepSkipped, StepRetrying, UserInputRequested, UserInputReceived,
      UserGuidanceReceived, LoopIterationStarted, LoopIterationCompleted,
      ParallelGroupStarted, ParallelGroupCompleted, WorkflowPaused, WorkflowResumed,
      WorkflowCompleted, WorkflowFailed, WorkflowCancelled, ScratchpadUpdated,
      StateUpdated, CheckpointSaved, DebugInfo.
      
      InMemoryEventBus implementation with thread-safe subscriber queues, keepalive,
      and format_sse() helper.
      
      File: `workflow_engine/events.py`
    status: pending
    dependencies:
      - p1-models

  - id: p1-storage
    content: |
      Create `workflow_engine/storage.py` with SQLite schema and storage operations:
      
      Tables: WorkflowDefinitions, WorkflowRuns.
      
      Classes:
      - WorkflowStorage: CRUD for definitions (save/get/list/delete/clone) and
        runs (save/get/list/count_active/delete/cleanup_old_runs).
      - TemplateLoader: load JSON templates from disk, sync to DB.
      - FileCheckpointStore: save/load/list/cleanup checkpoint JSON files.
      
      File: `workflow_engine/storage.py`
    status: pending
    dependencies:
      - p1-models
      - p1-config

  # ─────────────────────────────────────────────
  # PHASE 2: Execution Engine
  # ─────────────────────────────────────────────

  - id: p2-executors
    content: |
      Create `workflow_engine/executors.py` with step executor implementations:
      
      Base: StepExecutor ABC with execute(step, state, context) -> StepResult.
      ExecutionContext: run_id, user_email, llm_adapter, tool_adapter, user_interaction,
        event_bus, config, debug_mode, nesting_depth, engine_ref.
      
      Implementations:
      1. LLMStepExecutor: render template, call LLM, optionally with tools (mini
         agentic loop within step, max 3 tool rounds). Write to output_key, scratchpad,
         accumulators. Capture debug info.
      2. ToolOnlyExecutor: render tool_args_template, execute tool, write to output_key.
      3. UserInputExecutor: emit event, call user_interaction.request_input(), block
         until response or timeout.
      4. JudgeExecutor: build judge prompt from criteria + state inputs, call LLM,
         parse 'continue'/'stop' verdict.
      5. SubWorkflowExecutor: load sub-workflow, check nesting depth, create child run
         with inherited state, execute recursively, merge results back.
      
      File: `workflow_engine/executors.py`
    status: pending
    dependencies:
      - p1-state-manager
      - p1-adapters
      - p1-events

  - id: p2-engine-core
    content: |
      Create `workflow_engine/engine.py` with the core WorkflowEngine class:
      
      Constructor takes config + all adapters.
      
      Core methods:
      - execute_workflow(): load definition, check concurrency, init state, create run,
        dispatch to _execute_steps(), handle completion/error/cancel.
      - _execute_steps(): iterate steps, check pause/cancel flags, inject guidance,
        checkpoint, dispatch to executor, handle retry/skip/halt.
      - _execute_loop(): init iteration counter, execute children per iteration,
        evaluate judge, break on stop verdict or max iterations.
      - _execute_parallel_group(): ThreadPoolExecutor with bounded workers, each child
        gets state copy, writes own output_key, scratchpad locked.
      
      Control methods: pause(), resume(), cancel(), inject_guidance(), retry_step(),
        skip_step(), revert_to_step().
      
      Run lifecycle: _active_runs dict with thread, state, pause_event, cancel_flag
        per run. Runs execute in background threads.
      
      Recovery: recover_run() loads checkpoint and resumes. recover_all() on startup.
      
      File: `workflow_engine/engine.py`
    status: pending
    dependencies:
      - p2-executors
      - p1-storage

  - id: p2-checkpointing
    content: |
      Create `workflow_engine/checkpointing.py` with checkpoint logic:
      
      CheckpointManager: should_checkpoint(), save_checkpoint() (full or delta),
      load_and_restore() (reconstruct from base + deltas), cleanup_run_checkpoints().
      
      Delta format: state_diff (added/modified/deleted keys) + full scratchpad +
      new step_results only. Full snapshot every N steps.
      
      File: `workflow_engine/checkpointing.py`
    status: pending
    dependencies:
      - p1-storage
      - p1-state-manager

  # ─────────────────────────────────────────────
  # PHASE 3: REST API & SSE Endpoints
  # ─────────────────────────────────────────────

  - id: p3-endpoints
    content: |
      Create `workflow_engine/endpoints.py` with Flask blueprint:
      
      Definition CRUD: GET/POST /definitions, GET/PUT/DELETE /definitions/<id>,
        POST /definitions/<id>/clone.
      
      Run lifecycle: POST /runs (start), GET /runs (list), GET /runs/<id>,
        GET /runs/<id>/state, DELETE /runs/<id>.
      
      Run control: POST /runs/<id>/pause, /resume, /cancel, /guidance, /input,
        /retry, /skip, /revert. PUT /runs/<id>/state (manual edit, paused only).
      
      SSE: GET /runs/<id>/events (text/event-stream, keepalive every 15s).
      
      Debug: GET /runs/<id>/checkpoints, GET /runs/<id>/checkpoints/<step_index>.
      
      UI: GET /ui (serves workflow-standalone.html).
      
      Auth: @auth_required when embedded, API key check when standalone.
      
      File: `workflow_engine/endpoints.py`
    status: pending
    dependencies:
      - p2-engine-core
      - p1-events

  - id: p3-standalone-server
    content: |
      Create `workflow_engine/__init__.py`, `__main__.py`, `cli.py`:
      
      __init__.py: version, create_engine() factory, create_blueprint() factory.
      __main__.py: argparse for 'serve' and 'run' subcommands.
      cli.py: serve() starts Flask on config port. run() executes workflow synchronously
        with CLIUserInteractionAdapter, prints events to stdout, writes output to file.
      
      File: `workflow_engine/__init__.py`, `workflow_engine/__main__.py`, `workflow_engine/cli.py`
    status: pending
    dependencies:
      - p3-endpoints
      - p1-config

  # ─────────────────────────────────────────────
  # PHASE 4: Pre-built Templates
  # ─────────────────────────────────────────────

  - id: p4-template-deep-research
    content: |
      Create `workflow_engine/templates/deep_research.json`:
      
      Iterative web research workflow. Steps:
      1. plan_research (LLM): break goal into research questions
      2. research_loop (LOOP, max 5 iterations):
         a. search_step (LLM + tools: web_search, jina, perplexity)
         b. synthesize_step (LLM): merge findings into scratchpad
         c. evaluate_step (LLM): assess coverage, gaps, quality
         d. user_checkpoint (USER_INPUT): show summary, ask satisfaction
         e. decide_continue (JUDGE): stop if user satisfied or 90%+ coverage
      3. final_polish (LLM): format, citations, executive summary
      
      File: `workflow_engine/templates/deep_research.json`
    status: pending
    dependencies:
      - p1-models

  - id: p4-template-doc-writer
    content: |
      Create `workflow_engine/templates/document_writer.json`:
      
      Iterative document writing with user review. Steps:
      1. create_outline (LLM)
      2. user_review_outline (USER_INPUT)
      3. refine_outline (LLM, conditional)
      4. draft_loop (LOOP, max 10):
         a. select_section (LLM)
         b. draft_section (LLM + tools: web_search, doc_lookup)
         c. progress_check (LLM)
         d. user_review (USER_INPUT)
         e. review_judge (JUDGE)
      5. final_edit (LLM)
      
      File: `workflow_engine/templates/document_writer.json`
    status: pending
    dependencies:
      - p1-models

  - id: p4-template-qa-research
    content: |
      Create `workflow_engine/templates/qa_research.json`:
      
      Multi-question research workflow. Steps:
      1. parse_questions (LLM): extract discrete questions
      2. user_confirm_questions (USER_INPUT)
      3. finalize_questions (LLM)
      4. research_questions (PARALLEL_GROUP): one LLM+tools child per question
      5. compile_answers (LLM): format Q&A document
      6. user_review_answers (USER_INPUT)
      7. refinement_loop (LOOP, max 3): re-research flagged answers
      8. final_format (LLM)
      
      File: `workflow_engine/templates/qa_research.json`
    status: pending
    dependencies:
      - p1-models

  # ─────────────────────────────────────────────
  # PHASE 5: Main App Integration
  # ─────────────────────────────────────────────

  - id: p5-main-app-integration
    content: |
      Integrate workflow engine into main Flask app:
      
      1. server.py: import create_engine/create_blueprint, create embedded adapters
         (CallLLmAdapter, ToolRegistryAdapter, AppStorageAdapter, WebEventBus,
         WebUserInteractionAdapter), register blueprint, sync templates on startup.
      
      2. Embedded adapters: CallLLmAdapter wraps existing CallLLm. ToolRegistryAdapter
         wraps TOOL_REGISTRY. WebUserInteractionAdapter uses threading.Event pattern.
      
      3. Auth: @auth_required from endpoints.ext_auth.
      
      File: `server.py`, `workflow_engine/adapters.py`
    status: pending
    dependencies:
      - p3-standalone-server

  - id: p5-mcp-tools
    content: |
      Register workflow operations as MCP tools:
      
      Tools: workflow_start, workflow_status, workflow_result, workflow_list,
        workflow_cancel, workflow_guidance, workflow_templates.
      
      Category: 'workflows' (default OFF in tool settings).
      Async model: start returns run_id, caller polls status/result.
      
      File: `mcp_server/workflows.py` (follows existing MCP server pattern in `mcp_server/`)
    status: pending
    dependencies:
      - p5-main-app-integration

  - id: p5-chat-command
    content: |
      Add /workflow chat command:
      
      1. common-chat.js: detect /workflow [template] [prompt], prevent normal send,
         open workflow drawer, pre-select template and prompt if provided.
      
      2. interface.html: add toolbar button (#open-workflow-panel), drawer container div.
      
      3. interface.js: drawer toggle, keyboard shortcut.
      
      File: `interface/common-chat.js`, `interface/interface.html`, `interface/interface.js`
    status: pending
    dependencies:
      - p5-main-app-integration

  - id: p5-deprecate-ext-workflows
    content: |
      Deprecate existing extension workflows system:
      
      1. `database/ext_workflows.py`: Add deprecation docstring at top of file.
         Add deprecation warning log on every function call.
      2. `endpoints/ext_workflows.py`: Add deprecation notice in response headers
         (`X-Deprecated: true, X-Deprecated-Message: Use /workflows API instead`).
         Log deprecation warning on every request.
      3. No data migration. Extension workflows were simple CRUD for step definitions
         ({title, prompt}) with no execution history or state.
      4. Plan to remove after workflow engine has been stable for 1+ month.
      
      File: `database/ext_workflows.py`, `endpoints/ext_workflows.py`
    status: pending
    dependencies:
      - p5-main-app-integration

  # ─────────────────────────────────────────────
  # PHASE 6: UI — Workflow Panel
  # ─────────────────────────────────────────────

  - id: p6-workflow-panel-js
    content: |
      Create `interface/workflow-panel.js` — decoupled workflow UI module:
      
      Factory: createWorkflowPanel(instanceId, config) returns object with public API.
      Config: apiBase, container, onExport callback, getAuthHeaders.
      All CSS classes use .wfp-* prefix. No main app JS dependencies beyond jQuery + Bootstrap.
      
      Views:
      1. List View: templates + user workflows, CRUD actions, recent runs.
      2. Launch View: workflow preview, freeform prompt textarea, Run/Debug buttons.
      3. Run View: status header, step timeline (vertical list with status indicators),
         current step detail, scratchpad preview, action buttons (pause/resume/cancel/
         guidance), inline user input form when waiting.
      4. Debug View: per-step inspector (resolved prompt, raw output, tool calls,
         state diff, scratchpad diff, timing). State editor, scratchpad editor,
         revert/retry/skip per step.
      5. Editor View: nested/indented step tree, inline edit forms per step, drag-drop
         reorder, add/indent/outdent steps, loop/parallel config.
      
      SSE: EventSource to /workflows/runs/{run_id}/events. Polling fallback on disconnect.
      
      Public API: init(), showList(), launchWorkflow(id, prompt), showRun(runId), destroy().
      
      File: `interface/workflow-panel.js`
    status: pending
    dependencies:
      - p3-endpoints

  - id: p6-workflow-panel-css
    content: |
      Create `interface/workflow-panel.css` with .wfp-* prefixed classes:
      Container, header, step timeline, step nodes (states: running/completed/failed/
      waiting), scratchpad preview, state editor, drawer styles, nested step indentation,
      status badges. Responsive: full-width on mobile.
      
      File: `interface/workflow-panel.css`
    status: pending

  - id: p6-workflow-standalone-html
    content: |
      Create `interface/workflow-standalone.html` — standalone page at /workflows/ui.
      Loads Bootstrap 4.6, jQuery, workflow-panel.css, workflow-panel.js.
      Single container div + init script. No main app dependencies.
      
      File: `interface/workflow-standalone.html`
    status: pending
    dependencies:
      - p6-workflow-panel-js
      - p6-workflow-panel-css

  - id: p6-drawer-integration
    content: |
      Integrate drawer into main app:
      1. interface.html: drawer container, trigger button, CSS/JS links.
      2. interface.js: panel init, drawer toggle, pop-out handler.
      3. style.css: drawer overlay (z-index 1060, transitions).
      4. service-worker.js: precache new files, bump CACHE_VERSION.
      
      File: `interface/interface.html`, `interface/interface.js`, `interface/style.css`, `interface/service-worker.js`
    status: pending
    dependencies:
      - p6-workflow-panel-js
      - p6-workflow-panel-css
      - p5-chat-command

  # ─────────────────────────────────────────────
  # PHASE 7: Documentation & Testing
  # ─────────────────────────────────────────────

  - id: p7-tests
    content: |
      Create tests in `workflow_engine/tests/`:
      test_models.py, test_state.py, test_engine.py, test_checkpointing.py,
      test_endpoints.py, test_templates.py. All use mock adapters.
      
      File: `workflow_engine/tests/`
    status: pending
    dependencies:
      - p3-standalone-server

  - id: p7-documentation
    content: |
      Create documentation:
      1. workflow_engine/README.md: overview, quick start, API reference, template guide.
      2. documentation/features/workflow_engine/README.md: feature docs for main app.
      3. Update documentation/README.md and chat_app_capabilities.md.
      
      File: `workflow_engine/README.md`, `documentation/features/workflow_engine/README.md`
    status: pending
    dependencies:
      - p7-tests

---

## Background and Motivation

The application currently supports single-turn and multi-turn chat conversations where users send messages and receive LLM responses. For more complex tasks — deep research, iterative document writing, structured Q&A compilation — users must manually orchestrate multiple messages, keep track of intermediate results, and guide the LLM step by step. This is tedious, error-prone, and doesn't leverage the LLM's ability to follow structured plans.

The tool-calling framework (see `llm_tool_calling_framework.plan.md`) enables the LLM to invoke tools mid-response in an agentic loop. But this loop is limited to a single response turn — the LLM calls tools, gets results, and continues within one HTTP request/response cycle. It cannot span multiple user interactions, persist state across server restarts, or execute long-running multi-step plans that take 5-60 minutes.

The workflow engine addresses this gap. It provides:

1. **Structured multi-step execution**: Define a sequence of steps (LLM calls, tool invocations, user checkpoints, quality judges) that execute automatically with shared state flowing between them.

2. **Interactive loops**: Research and writing tasks are inherently iterative. The engine supports while-loops with LLM judge stop conditions ("stop when coverage is above 90%") and user checkpoints ("are you satisfied with the results?").

3. **Persistent state**: A dual-state architecture (JSON object for structured data + markdown pad for the accumulating document) persists across steps, loop iterations, and even server restarts via automatic checkpointing.

4. **User-in-the-loop**: Unlike batch workflow systems (Airflow, Dagster), this engine is designed for interactive use. Users can pause execution, inject guidance, retry failed steps, skip steps, revert to previous states, and edit the state/scratchpad directly.

5. **Standalone and embeddable**: The engine runs as its own Flask server (for standalone use or integration with other systems) or embeds into the main chat app as a blueprint. An adapter pattern decouples the engine from any specific LLM provider, tool system, or storage backend.

6. **MCP exposure**: Pre-built and user-defined workflows are exposed as MCP tools, allowing external coding assistants (OpenCode, Claude Code) to trigger deep research or document writing workflows programmatically.

### Relationship to Existing Systems

**Tool-calling framework** (`code_common/tools.py`, `_run_tool_loop` in `Conversation.py`) — **IMPLEMENTED**:
The tool-calling framework is fully implemented (48 tools across 8 categories, see `documentation/features/tool_calling/README.md` and plan at `documentation/planning/plans/llm_tool_calling_framework.plan.md`). The workflow engine builds on top of it — individual LLM steps can invoke tools via the ToolAdapter, which wraps the existing `TOOL_REGISTRY` from `code_common/tools.py` when embedded. The workflow engine is a higher-level orchestrator — it manages multi-step plans, not individual tool calls. A single workflow step might internally run a mini agentic loop (LLM -> tool -> result -> LLM) for up to 3 rounds, but the workflow engine controls the overall step sequence, state flow, and user interactions.

**Extension workflows** (`database/ext_workflows.py`, `endpoints/ext_workflows.py`):
The existing extension workflow system is a simple CRUD for step definitions (`{title, prompt}`). It has no execution engine, no state management, no loops, no user interaction. The new workflow engine fully supersedes this system. **Decision: Deprecate `ext_workflows` — no data migration.** The existing extension workflow tables and endpoints will be marked as deprecated and eventually removed. Users will create new workflow definitions in the new system.

**Agent framework** (`agents/base_agent.py`, `AgentWorkflow`):
The existing `AgentWorkflow` class is a stub that was never implemented. The various agents (`WebSearchWithAgent`, `DocumentEditingAgent`, `InterviewSimulatorAgent`) each implement their own ad-hoc multi-step patterns using `concurrent.futures` and manual state tracking. The workflow engine provides a unified framework that these patterns can be expressed in. Existing agents will be usable as tools within workflow steps, not replaced.

**LangChain/LangGraph** (`other_agents/basic_pipe.py`, `general_research_agent_v1.py`):
The codebase has experimental LangChain-based agents using `@chain` decorators and `MessageGraph`. These are prototype experiments, not production infrastructure. The workflow engine takes inspiration from LangGraph's state-graph concept (TypedDict state + node functions + conditional edges) but implements it as a lightweight custom engine without the LangChain dependency. This is intentional: LangChain adds a heavy dependency tree, doesn't natively support user-in-the-loop pause/resume, and its state model is less flexible than our JSON+markdown dual state.

### Prerequisites

The following systems must be in place before workflow engine implementation begins:

1. **LLM Tool-Calling Framework** (Status: **IMPLEMENTED**)
   - Plan: `documentation/planning/plans/llm_tool_calling_framework.plan.md`
   - Feature docs: `documentation/features/tool_calling/README.md`
   - Key dependency: `TOOL_REGISTRY` singleton in `code_common/tools.py` (48 tools, 8 categories)
   - The workflow engine's `ToolRegistryAdapter` wraps this registry when running in embedded mode
   - **Key classes reused from tool-calling**: `ToolContext` (conversation_id, user_email, keys, conversation_summary, recent_messages), `ToolCallResult` (tool_id, tool_name, result, error, needs_user_input, ui_schema), `@register_tool` decorator for extensible tool registration. The `LLMStepExecutor` wraps `ToolRegistry.execute()` with fail-open error handling and result truncation (max 4000 chars).
   - The streaming protocol extensions (`tool_call`, `tool_status`, `tool_result`, `tool_input_request` event types) established by the tool-calling framework inform the workflow engine's own SSE event design

2. **Existing Flask infrastructure** (Status: **IN PLACE**)
   - Flask app with blueprint registration (`server.py`)
   - Session auth (`@auth_required` from `endpoints/ext_auth`)
   - Flask-Limiter rate limiting
   - `CallLLm` wrapper in `call_llm.py` (used by `CallLLmAdapter`)
   - `AppState` pattern for shared server state
   - jQuery + Bootstrap 4.6 frontend with existing sidebar, drawer, and modal patterns

3. **Extension workflows deprecation** (Status: **TO BE DEPRECATED**)
   - `database/ext_workflows.py` and `endpoints/ext_workflows.py` will be deprecated
   - No data migration — these are simple CRUD step definitions with no execution history
   - Deprecation notice added to existing endpoints; removal scheduled after workflow engine is stable

---

## Requirements

### Functional Requirements

- **FR-1: Workflow Definition CRUD**: Users can create, read, update, delete, and clone workflow definitions. Each definition specifies a name, description, ordered list of steps (with nesting for loops and parallel groups), initial state, initial scratchpad content, and configuration options.

- **FR-2: Step Types**: The system supports 7 step types: `LLM` (call an LLM with a rendered prompt template, optionally with tools), `TOOL_ONLY` (execute a tool directly with templated arguments), `USER_INPUT` (pause and request input from user), `JUDGE` (evaluate loop stop condition via NL criteria), `SUB_WORKFLOW` (invoke another workflow as nested sub-workflow), `LOOP` (repeat child steps until judge stops or max iterations), `PARALLEL_GROUP` (execute child steps concurrently).

- **FR-3: Shared Mutable State**: All steps share a mutable state: a JSON object for structured data (step outputs, metadata, flow control, debug info) + a markdown pad (accumulating draft document). Both persist across steps and loop iterations. Accessible via `{{state.field_name}}` and `{{scratchpad}}`.

- **FR-4: Template Rendering**: Prompt templates support `{{state.field_name}}`, `{{config.key}}`, `{{scratchpad}}`, `{{scratchpad | last_n_lines(N)}}`, and `{{state.field | default('fallback')}}`. Simple regex substitution, not Jinja2.

- **FR-5: Loop Execution**: Loops execute child steps repeatedly. Stop conditions: fixed iteration count, LLM judge verdict (NL criteria against full scratchpad + latest output + original goal + current state), or both (whichever triggers first). Loop body can be single step or sub-workflow.

- **FR-6: Parallel Execution**: Parallel groups execute child steps concurrently via ThreadPoolExecutor. Each child writes to its own `output_key` (str or list). Markdown pad locked during parallel execution. Future optimization: append-only mode without lock.

- **FR-7: User Interaction**: Pause/Resume, Guidance Injection (-> `state.user_guidance`), Step-level Input (USER_INPUT steps), Model-decided Input (ask_clarification tool via ToolAdapter), Retry/Skip/Revert.

- **FR-8: Per-Step Configuration**: model_override, tools_enabled, output_key (str or list), debug_keys, accumulator_keys (append/merge/replace modes), write_to_scratchpad, scratchpad_instruction (append/replace_section/prepend), temperature, max_tokens, timeout_seconds, retry_config.

- **FR-9: Workflow Composition**: Chaining (state inheritance), Nesting (sub-workflow steps, depth limit 3 configurable). Sub-workflows inherit parent state (deep copy) and merge results back.

- **FR-10: Checkpointing and Recovery**: Checkpoint after every step (configurable). Full snapshots every 10 steps, delta checkpoints between. Server restart resumes RUNNING workflows from latest checkpoint.

- **FR-11: Standalone Mode**: `python -m workflow_engine serve` (Flask server on port 5050) and `python -m workflow_engine run <workflow> --prompt '...'` (CLI). Uses DirectOpenAIAdapter and StandaloneToolAdapter.

- **FR-12: Embedded Mode**: Registers as Flask blueprint under `/workflows`. Uses CallLLmAdapter, ToolRegistryAdapter, WebUserInteractionAdapter. Session auth.

- **FR-13: Pre-built Templates**: Deep Research (iterative search+synthesize loop with user checkpoints and LLM judge), Document Writer (outline -> draft sections -> review loop), Q&A Research (parse questions -> parallel research -> compile -> refine). JSON files, clone-and-customize.

- **FR-14: MCP Exposure**: Async start + poll: workflow_start -> run_id, workflow_status, workflow_result, workflow_list, workflow_cancel, workflow_guidance, workflow_templates.

- **FR-15: Concurrency Control**: Max 3 concurrent runs per user (configurable). HTTP 429 if exceeded.

- **FR-16: Real-time UI Updates**: SSE at `/workflows/runs/{run_id}/events`. One-time polling fallback for cross-tab/device. Keepalive every 15s.

- **FR-17: Workflow Panel UI**: Decoupled module (workflow-panel.js). Views: List, Launch, Run (step timeline + scratchpad preview), Debug (per-step inspector + state/scratchpad editor), Editor (nested tree). Right drawer + `/workflows/ui` route + pop-out window.

- **FR-18: History**: Last 20 runs per user (configurable), browseable. Auto-cleanup of older runs.

- **FR-19: Output Export**: Scratchpad + state live in workflow panel. Export to: clipboard, file download, artefact, global doc (via callbacks).

- **FR-20: Debug Mode**: Captures resolved prompt, raw LLM output, tool calls, state diff, scratchpad changes, timing, token usage. Without debug: only tool calls and JSON step output.

### Non-Functional Requirements

- **NFR-1: Self-contained Module**: `workflow_engine/` has no imports from main app. All external dependencies via adapter interfaces. Reusable in other projects.

- **NFR-2: Backward Compatibility**: Additive only. No changes to existing chat, tool calling, agents, or other features.

- **NFR-3: Performance**: Single thread for sequential steps. ThreadPoolExecutor (max 5 workers) for parallel groups. Non-blocking checkpoint I/O.

- **NFR-4: Durability**: Survives server restarts. Checkpoints to disk after every step. Mean runtime 5-20 min, max ~60 min.

- **NFR-5: Error Resilience**: Auto-retry (3 retries, 2/5/15s backoff) -> skip -> halt and ask user. Never silently abort.

- **NFR-6: State Size Limits**: JSON state 50KB, scratchpad 100KB (configurable). StateError on exceed.

- **NFR-7: Concurrency Safety**: threading.RLock on SharedState. Scratchpad lock for parallel steps. Key-level isolation for JSON state in parallel.

- **NFR-8: UI Decoupling**: workflow-panel.js + workflow-panel.css have zero main app JS dependencies. jQuery 3.x + Bootstrap 4.6 only. `.wfp-*` CSS prefix.

- **NFR-9: API Consistency**: JSON request/response, json_error() structured errors, standard HTTP status codes.

- **NFR-10: SSE Reliability**: 15s keepalive, auto-reconnect, polling fallback. Subscriber cleanup on disconnect.

- **NFR-11: Token Tracking**: Per-step and per-run token counts. Visible in debug view.

- **NFR-12: Logging**: Python logging module. INFO for step execution, ERROR for failures, DEBUG for prompts/outputs. Logger: `workflow_engine.*`.

---

## Expected User Experience

### UX Flow 1: Deep Research via Sidebar Panel

1. User clicks the workflow icon in the navbar (or presses Ctrl+Shift+W).
2. Right drawer slides open showing the List View with templates and saved workflows.
3. User clicks "Deep Research" template.
4. Launch View appears: shows template description, step preview, and a freeform prompt textarea.
5. User types: "Research the current state of quantum computing in 2026, focusing on error correction, commercial applications, and major players."
6. User clicks "Run" (or "Run in Debug Mode" for full inspection).
7. Drawer switches to Run View. Step timeline appears on the left:
   - `plan_research` — running (spinner).
8. After ~10 seconds, step completes (green check). Scratchpad preview shows the research plan.
9. `research_loop` starts. First iteration:
   - `search_step` — running. Status: "Searching the web..."
   - `synthesize_step` — running. Scratchpad preview updates with findings.
   - `evaluate_step` — completes. Shows "Coverage: 40%, Gaps: error correction details, commercial timeline."
   - `user_checkpoint` — **WAITING**. Modal appears: "Here's a summary of the research so far: [evaluation]. Are you satisfied? (yes/no/guidance)"
10. User types: "No, dig deeper into IBM and Google's error correction approaches specifically." Submits.
11. Loop continues with user guidance injected. Search focuses on IBM and Google error correction.
12. After 3 iterations, evaluation shows 85% coverage. User responds "yes" to checkpoint.
13. `final_polish` runs, produces formatted research document.
14. Run View shows "COMPLETED" badge. Scratchpad shows the final document.
15. User clicks "Export" dropdown → "Copy to Clipboard" (or "Save as Global Doc" or "Download as MD").

### UX Flow 2: Document Writer via Chat Command

1. User types in chat input: `/workflow document-writer Write a comprehensive business plan for an AI consulting startup`
2. Workflow drawer opens automatically with Document Writer template pre-selected and prompt pre-filled.
3. User clicks "Run".
4. `create_outline` runs, produces a detailed outline.
5. `user_review_outline` pauses — modal appears with the outline, asking for approval.
6. User modifies the outline slightly and approves.
7. `draft_loop` begins. Each iteration drafts one section:
   - Section "Executive Summary" being drafted...
   - Section "Market Analysis" being drafted (uses web_search tool to find market data)...
   - After 3 sections, `user_review` asks for feedback.
8. User pauses the workflow (clicks "Pause" button). Reads through the current draft.
9. User clicks "Inject Guidance": types "The market analysis section needs more specific numbers. Also add a competitor comparison table."
10. User clicks "Resume". The next iteration incorporates the guidance.
11. After all sections are complete, `final_edit` produces the polished document.
12. User exports to a global document.

### UX Flow 3: Q&A Research with Parallel Execution

1. User launches Q&A Research template with:
   ```
   What are the best practices for deploying LLMs in production?
   How do you handle prompt injection attacks?
   What's the cost comparison between self-hosted and API-based LLMs?
   How do you evaluate LLM output quality systematically?
   ```
2. `parse_questions` identifies 4 discrete questions. `user_confirm_questions` asks for confirmation.
3. User confirms.
4. `research_questions` runs as PARALLEL_GROUP: 4 concurrent search+synthesis tasks.
   Step timeline shows all 4 running simultaneously with individual spinners.
5. As each completes, it turns green. The 4th one (evaluation) takes longer due to web search.
6. All complete. `compile_answers` merges into a formatted Q&A document.
7. `user_review_answers` asks if any questions need deeper research.
8. User says "Question 3 needs more specific pricing data from 2026."
9. `refinement_loop` runs: re-researches question 3 with focused search.
10. Final document compiled. User downloads as markdown file.

### UX Flow 4: Debug Mode

1. User launches "Deep Research" with debug mode enabled.
2. Step timeline shows additional detail per step:
   - Each step node is expandable.
   - Clicking a completed step shows: resolved prompt, raw LLM output, tool calls, state before/after (JSON diff), scratchpad changes (markdown diff), timing, tokens.
3. User notices the synthesize step produced poor output.
4. User clicks "Revert to Step 2" (search_step). State is restored from checkpoint.
5. User opens the state editor. Modifies `state.current_focus` to be more specific.
6. User clicks "Resume from here". The search re-runs with modified state.
7. Better results. User continues normally.

### UX Flow 5: MCP Workflow Invocation

1. An external agent (OpenCode/Claude Code) calls the MCP tool:
   ```
   workflow_start(workflow_name="deep-research", prompt="Research React Server Components best practices")
   ```
2. Returns: `{run_id: "wfr_20260303_a3b8", status: "RUNNING"}`.
3. Agent polls: `workflow_status(run_id="wfr_20260303_a3b8")`.
4. Returns: `{status: "WAITING_FOR_USER", current_step: "user_checkpoint", prompt: "Are you satisfied?"}`.
5. Agent injects guidance: `workflow_guidance(run_id="wfr_20260303_a3b8", guidance="Continue, focus on streaming patterns")`.
6. Agent polls again: `{status: "RUNNING", current_step: "search_step", progress: "60%"}`.
7. Eventually: `workflow_result(run_id="wfr_20260303_a3b8")`.
8. Returns: `{status: "COMPLETED", scratchpad: "# Research: React Server Components...\n\n...", state: {...}}`.

### UX Flow 6: Server Restart Recovery

1. User starts a Deep Research workflow. It's on iteration 3 of the research loop.
2. Server crashes or is restarted.
3. On startup, the engine calls `recover_all(user_email)`.
4. Finds 1 run with status=RUNNING. Loads latest checkpoint (after synthesize_step of iteration 3).
5. Resumes execution from evaluate_step of iteration 3.
6. User reconnects to `/workflows/ui` (or the drawer). Panel does a GET /workflows/runs/{run_id} to load current state, then opens SSE for live updates.
7. Workflow continues as if nothing happened. User sees the step timeline with iterations 1-3 completed and iteration 3 continuing.

### UX Flow 7: Standalone CLI Execution

1. User runs: `python -m workflow_engine run deep-research --prompt "Research quantum error correction" --output research.md`
2. Engine loads config from `workflow_engine_config.json`, creates standalone adapters.
3. Step events print to stdout:
   ```
   [12:30:01] Starting: plan_research
   [12:30:12] Completed: plan_research (11s, 1.2K tokens)
   [12:30:12] Starting: research_loop (iteration 1/5)
   [12:30:12]   Starting: search_step
   [12:30:18]   Completed: search_step (6s, 800 tokens)
   ...
   [12:30:45]   User input needed: Are you satisfied with the research?
   [12:30:45]   > no, focus more on surface codes
   ...
   [12:35:22] Completed: final_polish (8s, 2.1K tokens)
   [12:35:22] Workflow completed. Total: 5m 21s, 15.4K tokens.
   [12:35:22] Output written to: research.md
   ```
4. `research.md` contains the final scratchpad content (the polished research document).

---

## Architecture Overview

### Deployment Modes

```
STANDALONE MODE:
  python -m workflow_engine serve
  +----------------------------------+
  | workflow_engine Flask (port 5050) |
  |                                  |
  | DirectOpenAIAdapter  --> OpenAI  |
  | StandaloneToolAdapter            |
  | FileStorageAdapter               |
  | InMemoryEventBus                 |
  | CLIUserInteractionAdapter (CLI)  |
  | WebUserInteractionAdapter (web)  |
  +----------------------------------+

EMBEDDED MODE:
  python server.py (main app, port 5000)
  +-------------------------------------+
  | Main Flask App                      |
  |                                     |
  | /chat, /clarify, etc.               |
  | /workflows/* (workflow blueprint)   |
  |                                     |
  | CallLLmAdapter  --> CallLLm         |
  | ToolRegistryAdapter --> TOOL_REG    |
  | AppStorageAdapter                   |
  | WebEventBus                         |
  | WebUserInteractionAdapter           |
  +-------------------------------------+
```

### Adapter Pattern

The engine core (`engine.py`, `executors.py`, `state.py`) has ZERO knowledge of how LLMs are called, how tools work, where data is stored, or how users interact. All external concerns are abstracted behind 5 adapter interfaces:

1. **LLMAdapter**: Call an LLM. Could be OpenAI direct, OpenRouter via CallLLm, Anthropic, local model, etc.
2. **ToolAdapter**: Execute a tool. Could be TOOL_REGISTRY, MCP, custom functions, etc.
3. **StorageAdapter**: Save/load state. Could be files, SQLite, Redis, S3, etc.
4. **EventBus**: Emit events. Could be in-memory queues, Redis pub/sub, WebSocket, etc.
5. **UserInteractionAdapter**: Request user input. Could be CLI stdin, HTTP modal, Slack bot, etc.

This makes the engine truly portable. To use it in a different project:
```python
from workflow_engine import create_engine
from my_project import MyLLMAdapter, MyToolAdapter

engine = create_engine(
    llm_adapter=MyLLMAdapter(api_key="..."),
    tool_adapter=MyToolAdapter(),
)
run = engine.execute_workflow("deep-research", "user@example.com", "Research topic X")
```

### Execution Model

Each workflow run executes in a **single background thread** (sequential step execution). This is intentional:

- Simplifies state management (no concurrent writes to shared state from sequential steps).
- Makes debugging deterministic (steps execute in order).
- Parallel groups are the explicit mechanism for concurrency (bounded ThreadPoolExecutor within the run's thread).
- Control operations (pause, cancel, guidance) use thread-safe flags and events.
- Control operations (pause, cancel, guidance) use thread-safe flags and events.

### LLM Steps with Mini-Agentic Loop

When an LLM step has `tools_enabled: true`, the `LLMStepExecutor` implements a mini agentic loop inspired by the tool-calling framework:

1. **Iteration cycle** (max 5 iterations):
   - Render prompt template with current state and scratchpad
   - Call LLM with `tools` parameter (OpenAI API format via TOOL_REGISTRY)
   - If LLM returns tool calls (`finish_reason == "tool_calls"`):
     - Extract tool call objects: `[{tool_id, tool_name, arguments}]`
     - For each tool: invoke `ToolAdapter.execute(tool_name, args, ToolContext)` → `ToolCallResult`
     - **Interactive tools** (e.g., `ask_clarification`): wait for user input via `threading.Event` pattern (same as `/tool_response` endpoint), 60s timeout
     - **Server-side tools**: execute silently, capture result (max 4000 chars after truncation)
     - Build continuation message: `[{role: "tool", tool_call_id: ..., content: result}]`
     - Append to messages array, loop iteration++
   - If LLM returns text only: break loop, capture output to `step[output_key]`
   - On iteration 5 (final): force `tool_choice="none"` to prevent infinite loops

2. **Error handling** (fail-open design):
   - Tool execution errors → include error message in tool result, LLM decides how to proceed
   - Timeout on interactive tool → "User did not respond within timeout period" message
   - Tool truncation → append `"... [result truncated]"` so LLM knows output was capped
   - Never crash the workflow: all exceptions caught and wrapped in ToolCallResult.error

3. **State integration**:
   - All tool results are fed back to the same LLM within the same step (not persisted to state until step ends)
   - Final LLM response (after tool loop terminates) is written to `step[output_key]`
   - Tool calls and results are optionally logged to debug output (if debug mode enabled)

4. **Streaming protocol**:
   - Step executor emits new event types for tool activity:
     - `ToolCallStarted`: LLM requested a tool
     - `ToolExecuting`: tool invocation in progress
     - `ToolCompleted`: tool returned result
     - `ToolError`: tool failed (error included)
     - `ToolModalRequested`: interactive tool needs user input (pause streaming)
   - Events flow through workflow engine's EventBus → JSON-lines to client

5. **Tool context**:
   - `ToolContext` includes: `run_id`, `user_email`, `conversation_id` (when embedded), `keys` (API credentials), `recent_messages` (workflow messages, not conversation history)
   - Enables tools to access workflow context without coupling to Conversation.py

**Key difference from single-turn tool-calling**: A workflow LLM step's mini loop persists over the step's lifetime only. Once the step completes (tool loop terminates), the next step sees the final text output, not the tool call history.
### State Flow

```
User Prompt
    |
    v
+-- SharedState ---+
| JSON: {           |     +-- Step 1 (LLM) --+
|   original_goal,  | --> | Reads state       |
|   _run_id,        |     | Renders template  |
|   _workflow_name   |     | Calls LLM         |
| }                 | <-- | Writes output_key |
| Scratchpad: ""    |     +-------------------+
+-------------------+
    |
    v
+-- SharedState ---+
| JSON: {           |     +-- Step 2 (TOOL) --+
|   original_goal,  | --> | Reads state       |
|   step1_output,   |     | Renders tool args |
|   _run_id          |     | Executes tool     |
| }                 | <-- | Writes output_key |
| Scratchpad:       |     +-------------------+
|   "## Section 1"  |
+-------------------+
    |
    v
    ... (more steps) ...
    |
    v
+-- SharedState ---+
| JSON: {all keys}  |     +-- CHECKPOINT --+
| Scratchpad:       | --> | Save to disk   |
|   "# Final Doc"   |     +----------------+
+-------------------+
```

---

## Features Summary

The Workflow Engine Framework provides the following capabilities:

### Core Execution
- **Multi-step workflow execution**: Define and run ordered sequences of LLM calls, tool invocations, user checkpoints, and quality judges
- **7 step types**: LLM, TOOL_ONLY, USER_INPUT, JUDGE, SUB_WORKFLOW, LOOP, PARALLEL_GROUP
- **Loop execution with stop conditions**: While-loops with LLM judge evaluation (natural language criteria), fixed iteration caps, or both
- **Parallel step groups**: Concurrent execution of independent steps via ThreadPoolExecutor with output key isolation
- **Workflow composition**: Chain workflows (state inheritance) and nest workflows as sub-steps (depth limit 3, configurable)
- **Shared mutable state**: JSON state object + markdown scratch pad flowing between all steps
- **Template rendering**: `{{state.field}}`, `{{config.key}}`, `{{scratchpad}}`, `{{scratchpad | last_n_lines(N)}}` in prompts
- **Accumulator support**: Keys that accumulate across loop iterations (append/merge/replace modes)

### User Interaction
- **Pause/resume**: User can pause execution at any point and resume later
- **Guidance injection**: User can inject free-text guidance that the next step sees in `state.user_guidance`
- **User input steps**: Configurable checkpoint steps that pause and ask the user for input (text, choice, confirm, clarification)
- **Model-decided input**: LLM steps can invoke the `ask_clarification` tool mid-step to request ad-hoc user input
- **Retry/skip/revert**: Per-step error recovery — retry a failed step, skip it, or revert state to a previous step
- **State/scratchpad editing**: In debug mode, directly edit JSON state or markdown pad while paused

### Persistence and Recovery
- **Automatic checkpointing**: State snapshot after every step (configurable interval)
- **Delta checkpoints**: State diffs between full snapshots to save storage (full snapshot every 10 steps)
- **Crash recovery**: On server restart, automatically resume RUNNING workflows from latest checkpoint
- **Run history**: Last 20 runs per user (configurable) with auto-cleanup of older runs
- **Workflow definition versioning**: Each workflow definition has a `version` field (integer, auto-incremented on save). Run records capture the version used. Templates ship with version 1; user modifications increment version. This enables audit trails and future version comparison, but there is no automatic rollback or migration between versions — definitions are immutable JSON snapshots at each version.

### Deployment Modes
- **Standalone Flask server**: `python -m workflow_engine serve` on configurable port (default 5050)
- **Standalone CLI**: `python -m workflow_engine run <workflow> --prompt '...'` for headless/scripted execution
- **Embedded blueprint**: Register as Flask blueprint under `/workflows` in the main chat app
- **Adapter pattern**: 5 abstract interfaces (LLMAdapter, ToolAdapter, StorageAdapter, EventBus, UserInteractionAdapter) decouple the engine from any specific infrastructure

### Real-time Updates
- **SSE event stream**: `/workflows/runs/{run_id}/events` with text/event-stream content type
- **15-second keepalive pings**: Prevents proxy/nginx timeout on idle connections
- **Auto-reconnect**: Frontend EventSource reconnects on disconnect, fetches missed events via polling API
- **Polling fallback**: One-time GET for cross-tab/device state load without SSE

### Pre-built Templates
- **Deep Research**: Iterative web research with search → synthesize → evaluate → user checkpoint → judge loop (max 5 iterations)
- **Document Writer**: Outline → user review → draft sections loop → final edit (max 10 iterations)
- **Q&A Research**: Parse questions → parallel research per question → compile → user review → refinement loop (max 3 iterations)
- **Clone-and-customize**: Templates are JSON files that users clone to create their own customized workflows

### Integration
- **MCP exposure**: Workflows available as MCP tools (async start + poll pattern) for external agents (OpenCode, Claude Code)
- **Tool calling integration**: LLM steps can use the full 48-tool TOOL_REGISTRY when embedded, or basic standalone tools when running independently
- **Chat command**: `/workflow [template] [prompt]` in chat input opens the workflow panel with pre-selected template
- **Export options**: Scratchpad/results exportable to clipboard, file download, artefact, or global document

### UI
- **Decoupled workflow panel**: `workflow-panel.js` + `workflow-panel.css` with `.wfp-*` CSS prefix, zero main app JS dependencies beyond jQuery + Bootstrap 4.6
- **Right drawer overlay**: Slides open from right side of main app, z-index 1060
- **Standalone page**: `/workflows/ui` route for independent access
- **Pop-out window**: Open workflow panel in its own browser window
- **Step timeline**: Vertical step list with status indicators (running/completed/failed/waiting)
- **Debug view**: Per-step inspector showing resolved prompt, raw LLM output, tool calls, state diff, scratchpad diff, timing, token usage
- **Step editor**: Nested/indented tree view for creating and editing workflows with loops and parallel groups

### Monitoring and Observability
- **Per-step timing**: Duration in seconds for every step execution
- **Token tracking**: Per-step and per-run token counts (prompt_tokens, completion_tokens, total_tokens)
- **Run status tracking**: Real-time status (PENDING → RUNNING → PAUSED/WAITING_FOR_USER → COMPLETED/FAILED/CANCELLED)
- **Step-level error capture**: Failed steps record the exception, retry count, and state at failure
- **Debug mode**: Opt-in per-run flag that captures resolved prompts, raw LLM outputs, state diffs, and scratchpad diffs for every step

---

## API Endpoints Reference

All endpoints are served under the `/workflows` blueprint prefix. When embedded, the full path is `/workflows/*`. When standalone, these are the root paths.

### Authentication

| Mode | Auth Mechanism |
|------|---------------|
| Standalone (localhost) | No auth required |
| Standalone (remote) | `X-API-Key` header checked against `config.api_key` |
| Embedded | `@auth_required` decorator (session cookie auth from main app) |

### Rate Limiting

All rate limits are per-user (identified by session/API key). Enforced via Flask-Limiter when embedded, custom middleware when standalone.

| Endpoint Group | Rate Limit | Rationale |
|---------------|-----------|-----------|
| Definition CRUD (`GET/POST/PUT/DELETE /definitions/*`) | 60/min | Standard CRUD, prevent abuse |
| Run lifecycle (`POST /runs`, `DELETE /runs/*`) | 20/min | Starting/deleting runs is expensive |
| Run control (`POST /runs/*/pause,resume,cancel,guidance,input,retry,skip,revert`) | 60/min | Interactive actions, should be responsive |
| Run state read (`GET /runs/*`, `GET /runs/*/state`) | 120/min | Polling, needs to be fast |
| SSE (`GET /runs/*/events`) | 10/min | Long-lived connections, rate limit connection establishment |
| State mutation (`PUT /runs/*/state`) | 10/min | Manual state edits (paused only), rare |
| Debug/checkpoints (`GET /runs/*/checkpoints/*`) | 30/min | Debugging aid, moderate frequency |
| Template listing (`GET /templates`) | 60/min | Read-only, lightweight |

### Workflow Definition Endpoints

#### `GET /definitions`
List all workflow definitions for the current user, including system templates.

**Query parameters:**
- `include_templates` (bool, default `true`): Include system templates in response
- `tags` (string, comma-separated): Filter by tags

**Response** `200`:
```json
{
  "definitions": [
    {
      "workflow_id": "wf_deep_research",
      "name": "Deep Research",
      "description": "Iterative web research with LLM judge",
      "version": 1,
      "is_template": true,
      "template_source": null,
      "created_by": "system",
      "created_at": "2026-03-01T00:00:00Z",
      "updated_at": "2026-03-01T00:00:00Z",
      "tags": ["research", "web"],
      "step_count": 7,
      "has_loops": true,
      "has_parallel": false
    }
  ]
}
```

#### `POST /definitions`
Create a new workflow definition.

**Request body:**
```json
{
  "name": "My Custom Research",
  "description": "Custom research workflow",
  "steps": [
    {
      "id": "step_1",
      "title": "Plan Research",
      "step_type": "llm",
      "prompt_template": "Break the following goal into research questions: {{state.original_goal}}",
      "output_key": "research_plan",
      "write_to_scratchpad": true,
      "temperature": 0.7
    }
  ],
  "initial_state": {},
  "initial_scratchpad": "",
  "input_schema": {
    "type": "object",
    "properties": {
      "original_goal": {"type": "string", "description": "Research topic"}
    },
    "required": ["original_goal"]
  },
  "tags": ["research", "custom"]
}
```

**Validations:**
- `name` required, 1-200 chars
- `steps` required, non-empty array
- Each step must have `id` (unique within workflow), `title`, `step_type` (valid enum value)
- `step_type`-specific fields validated: LOOP must have `loop_config` or `children`, JUDGE must have `judge_config`, SUB_WORKFLOW must have `sub_workflow_id`, USER_INPUT must have `user_input_config`, TOOL_ONLY must have `tool_name`
- `output_key` required for LLM, TOOL_ONLY, JUDGE steps
- Nested depth validated against `max_nesting_depth` (default 3)
- `input_schema` must be valid JSON Schema if provided

**Response** `201`:
```json
{
  "workflow_id": "wf_a3b8c9d2",
  "name": "My Custom Research",
  "version": 1,
  "created_at": "2026-03-03T12:00:00Z"
}
```

**Errors:**
- `400` — Validation error (missing fields, invalid step types, schema violations)
- `409` — Name already exists for this user

#### `GET /definitions/<workflow_id>`
Get full workflow definition with all step details.

**Response** `200`: Full `WorkflowDefinition` JSON.

**Errors:**
- `404` — Workflow not found

#### `PUT /definitions/<workflow_id>`
Update workflow definition. Increments `version` automatically.

**Request body:** Same as POST (partial updates accepted — only provided fields are updated).

**Validations:** Same as POST, plus:
- Cannot modify `is_template` or `template_source`
- Cannot update a definition that has RUNNING workflows (must pause/cancel them first)

**Response** `200`:
```json
{
  "workflow_id": "wf_a3b8c9d2",
  "version": 2,
  "updated_at": "2026-03-03T13:00:00Z"
}
```

**Errors:**
- `404` — Workflow not found
- `409` — Has active runs

#### `DELETE /definitions/<workflow_id>`
Delete workflow definition and all associated run history.

**Response** `200`: `{"deleted": true}`

**Errors:**
- `404` — Workflow not found
- `409` — Has active runs (must cancel first)

#### `POST /definitions/<workflow_id>/clone`
Clone a workflow definition (typically a template) as a new user-owned definition.

**Request body:**
```json
{
  "name": "My Deep Research Copy",
  "description": "Customized deep research"
}
```

**Response** `201`:
```json
{
  "workflow_id": "wf_new_id",
  "name": "My Deep Research Copy",
  "version": 1,
  "template_source": "wf_deep_research",
  "created_at": "2026-03-03T14:00:00Z"
}
```

### Workflow Run Endpoints

#### `POST /runs`
Start a new workflow run.

**Request body:**
```json
{
  "workflow_id": "wf_deep_research",
  "prompt": "Research the current state of quantum computing in 2026",
  "parameters": {
    "original_goal": "Research quantum computing in 2026"
  },
  "debug_mode": false
}
```

**Validations:**
- `workflow_id` required, must exist
- `prompt` required, non-empty string
- `parameters` validated against `input_schema` if the workflow definition has one
- Concurrent run count checked: returns 429 if user already has `max_concurrent_runs_per_user` (default 3) active runs

**Response** `201`:
```json
{
  "run_id": "wfr_20260303_a3b8",
  "workflow_id": "wf_deep_research",
  "workflow_name": "Deep Research",
  "status": "RUNNING",
  "started_at": "2026-03-03T12:30:00Z"
}
```

**Errors:**
- `400` — Validation error
- `404` — Workflow not found
- `429` — Concurrent run limit exceeded: `{"error": "Maximum 3 concurrent runs. Cancel or wait for existing runs to complete.", "active_runs": [...]}`

#### `GET /runs`
List runs for the current user.

**Query parameters:**
- `status` (string): Filter by status (RUNNING, COMPLETED, FAILED, etc.)
- `workflow_id` (string): Filter by workflow
- `limit` (int, default 20): Max results
- `offset` (int, default 0): Pagination offset

**Response** `200`:
```json
{
  "runs": [
    {
      "run_id": "wfr_20260303_a3b8",
      "workflow_id": "wf_deep_research",
      "workflow_name": "Deep Research",
      "status": "RUNNING",
      "current_step_id": "search_step",
      "current_step_index": 3,
      "total_steps": 7,
      "started_at": "2026-03-03T12:30:00Z",
      "updated_at": "2026-03-03T12:32:15Z",
      "debug_mode": false
    }
  ],
  "total": 5,
  "limit": 20,
  "offset": 0
}
```

#### `GET /runs/<run_id>`
Get full run details including step results.

**Response** `200`:
```json
{
  "run_id": "wfr_20260303_a3b8",
  "workflow_id": "wf_deep_research",
  "workflow_name": "Deep Research",
  "status": "RUNNING",
  "current_step_id": "search_step",
  "current_step_index": 3,
  "total_steps": 7,
  "original_prompt": "Research quantum computing in 2026",
  "user_guidance": null,
  "started_at": "2026-03-03T12:30:00Z",
  "updated_at": "2026-03-03T12:32:15Z",
  "completed_at": null,
  "error": null,
  "debug_mode": false,
  "step_results": [
    {
      "step_id": "plan_research",
      "step_title": "Plan Research",
      "status": "completed",
      "started_at": "2026-03-03T12:30:01Z",
      "completed_at": "2026-03-03T12:30:12Z",
      "duration_seconds": 11.2,
      "tokens_used": {"prompt_tokens": 450, "completion_tokens": 380, "total_tokens": 830}
    }
  ]
}
```

**Errors:**
- `404` — Run not found

#### `GET /runs/<run_id>/state`
Get current shared state (JSON state + scratchpad).

**Response** `200`:
```json
{
  "state": {
    "original_goal": "Research quantum computing in 2026",
    "research_plan": ["question 1", "question 2"],
    "_run_id": "wfr_20260303_a3b8",
    "_workflow_name": "Deep Research",
    "_loop_iteration": 2
  },
  "scratchpad": "## Research: Quantum Computing\n\n### Findings\n..."
}
```

#### `PUT /runs/<run_id>/state`
Manually edit the shared state. Only allowed when run is PAUSED.

**Request body:**
```json
{
  "state": {"key": "value"},
  "scratchpad": "updated markdown content"
}
```

**Validations:**
- Run must be in PAUSED status
- `state` must be valid JSON object
- `state` size must not exceed `max_state_size_bytes` (default 50KB)
- `scratchpad` size must not exceed `max_scratchpad_size_bytes` (default 100KB)

**Response** `200`: `{"updated": true}`

**Errors:**
- `404` — Run not found
- `409` — Run is not paused
- `413` — State or scratchpad exceeds size limit

#### `DELETE /runs/<run_id>`
Delete a run and its checkpoints. Only allowed for completed/failed/cancelled runs.

**Response** `200`: `{"deleted": true}`

**Errors:**
- `404` — Run not found
- `409` — Run is still active (must cancel first)

### Run Control Endpoints

All control endpoints return the updated run status.

#### `POST /runs/<run_id>/pause`
Pause a running workflow. The current step completes, then execution halts.

**Response** `200`: `{"status": "PAUSED", "paused_at_step": "search_step"}`

**Errors:**
- `404` — Run not found
- `409` — Run is not in RUNNING status

#### `POST /runs/<run_id>/resume`
Resume a paused workflow from where it stopped.

**Response** `200`: `{"status": "RUNNING", "resuming_from_step": "search_step"}`

**Errors:**
- `404` — Run not found
- `409` — Run is not in PAUSED status

#### `POST /runs/<run_id>/cancel`
Cancel a running or paused workflow. Sets status to CANCELLED.

**Response** `200`: `{"status": "CANCELLED"}`

**Errors:**
- `404` — Run not found
- `409` — Run is already completed/failed/cancelled

#### `POST /runs/<run_id>/guidance`
Inject user guidance into a running or paused workflow.

**Request body:**
```json
{
  "guidance": "Focus more on error correction approaches by IBM and Google"
}
```

**Validations:**
- `guidance` required, non-empty string, max 5000 chars
- Run must be RUNNING or PAUSED

**Response** `200`: `{"guidance_set": true, "will_apply_at": "next_step"}`

#### `POST /runs/<run_id>/input`
Submit user input for a USER_INPUT step that is waiting.

**Request body:**
```json
{
  "input": {
    "response": "yes",
    "additional_notes": "Also look into surface codes"
  }
}
```

**Validations:**
- Run must be in WAITING_FOR_USER status
- `input` required, non-empty

**Response** `200`: `{"input_received": true, "status": "RUNNING"}`

**Errors:**
- `404` — Run not found
- `409` — Run is not waiting for user input

#### `POST /runs/<run_id>/retry`
Retry the most recently failed step.

**Response** `200`: `{"status": "RUNNING", "retrying_step": "search_step"}`

**Errors:**
- `404` — Run not found
- `409` — No failed step to retry

#### `POST /runs/<run_id>/skip`
Skip the most recently failed step and continue.

**Response** `200`: `{"status": "RUNNING", "skipped_step": "search_step", "next_step": "synthesize_step"}`

**Errors:**
- `404` — Run not found
- `409` — No failed step to skip

#### `POST /runs/<run_id>/revert`
Revert workflow state to a previous step's checkpoint.

**Request body:**
```json
{
  "to_step_index": 2
}
```

**Validations:**
- Run must be PAUSED or FAILED
- `to_step_index` must be a valid completed step index with a checkpoint

**Response** `200`: `{"status": "PAUSED", "reverted_to_step": "search_step", "step_index": 2}`

### SSE Event Stream

#### `GET /runs/<run_id>/events`
Server-Sent Events stream for real-time workflow updates.

**Content-Type**: `text/event-stream`

**Event types:**

| Event | Data Fields | When |
|-------|------------|------|
| `workflow_started` | `run_id`, `workflow_name`, `total_steps` | Run begins |
| `step_started` | `step_id`, `step_title`, `step_index`, `step_type` | Step execution begins |
| `step_completed` | `step_id`, `step_title`, `status`, `duration_seconds`, `tokens_used`, `output_preview` | Step finishes successfully |
| `step_failed` | `step_id`, `step_title`, `error`, `retry_count`, `will_retry` | Step fails |
| `step_skipped` | `step_id`, `step_title`, `reason` | Step is skipped |
| `step_retrying` | `step_id`, `step_title`, `retry_count`, `max_retries`, `backoff_seconds` | Step retry triggered |
| `user_input_requested` | `step_id`, `prompt`, `input_type`, `options` | USER_INPUT step waiting |
| `user_input_received` | `step_id` | User submitted input |
| `user_guidance_received` | `guidance_preview` | Guidance injected |
| `loop_iteration_started` | `loop_step_id`, `iteration`, `max_iterations` | Loop iteration begins |
| `loop_iteration_completed` | `loop_step_id`, `iteration`, `judge_verdict` | Loop iteration ends |
| `parallel_group_started` | `group_step_id`, `child_count` | Parallel group begins |
| `parallel_group_completed` | `group_step_id`, `results_summary` | Parallel group ends |
| `workflow_paused` | `paused_at_step` | User paused |
| `workflow_resumed` | `resuming_from_step` | User resumed |
| `workflow_completed` | `run_id`, `total_duration_seconds`, `total_tokens`, `scratchpad_preview` | Run completed |
| `workflow_failed` | `run_id`, `error`, `failed_at_step` | Run failed |
| `workflow_cancelled` | `run_id` | Run cancelled |
| `scratchpad_updated` | `preview` (last 200 chars) | Scratchpad changed |
| `state_updated` | `changed_keys` | JSON state changed |
| `checkpoint_saved` | `step_index`, `checkpoint_type` (full/delta) | Checkpoint written |
| `debug_info` | `step_id`, `resolved_prompt`, `raw_output`, `state_diff`, `scratchpad_diff` | Debug mode only |
| `keepalive` | `timestamp` | Every 15 seconds |

**Example SSE stream:**
```
event: workflow_started
data: {"run_id": "wfr_20260303_a3b8", "workflow_name": "Deep Research", "total_steps": 7}

event: step_started
data: {"step_id": "plan_research", "step_title": "Plan Research", "step_index": 0, "step_type": "llm"}

event: step_completed
data: {"step_id": "plan_research", "step_title": "Plan Research", "status": "completed", "duration_seconds": 11.2, "tokens_used": {"total_tokens": 830}}

event: keepalive
data: {"timestamp": "2026-03-03T12:30:25Z"}
```

### Debug Endpoints

#### `GET /runs/<run_id>/checkpoints`
List all checkpoints for a run.

**Response** `200`:
```json
{
  "checkpoints": [
    {"step_index": 0, "step_id": "plan_research", "timestamp": "2026-03-03T12:30:12Z", "type": "full"},
    {"step_index": "1", "step_id": "search_step", "timestamp": "2026-03-03T12:30:18Z", "type": "delta"}
  ]
}
```

#### `GET /runs/<run_id>/checkpoints/<step_index>`
Get a specific checkpoint's full state.

**Response** `200`: Full `CheckpointData` JSON (state snapshot + scratchpad + step results so far).

### Template Endpoints

#### `GET /templates`
List available pre-built templates.

**Response** `200`:
```json
{
  "templates": [
    {
      "workflow_id": "wf_deep_research",
      "name": "Deep Research",
      "description": "Iterative web research with LLM judge stop condition",
      "step_count": 7,
      "estimated_runtime": "5-20 min",
      "input_schema": {"type": "object", "properties": {"original_goal": {"type": "string"}}}
    }
  ]
}
```

### Error Response Format

All error responses follow a consistent JSON structure:
```json
{
  "error": "Human-readable error message",
  "error_code": "VALIDATION_ERROR",
  "details": {"field": "steps[0].step_type", "message": "Invalid step type: 'invalid'"}
}
```

**Standard error codes:**
- `VALIDATION_ERROR` (400) — Invalid request payload
- `NOT_FOUND` (404) — Resource not found
- `CONFLICT` (409) — Operation not allowed in current state
- `RATE_LIMITED` (429) — Rate limit exceeded
- `CONCURRENCY_LIMIT` (429) — Too many concurrent runs
- `SIZE_EXCEEDED` (413) — State or scratchpad size limit exceeded
- `INTERNAL_ERROR` (500) — Unexpected server error

### MCP Tool Interface

When exposed as MCP tools (via `mcp_server/workflows.py`), the following tools are registered:

| MCP Tool | Maps To | Description |
|----------|---------|-------------|
| `workflow_templates` | `GET /templates` | List available workflow templates |
| `workflow_start` | `POST /runs` | Start a workflow run, returns `run_id` |
| `workflow_status` | `GET /runs/<run_id>` | Get current run status and progress |
| `workflow_result` | `GET /runs/<run_id>/state` | Get final state and scratchpad |
| `workflow_list` | `GET /runs` | List active and recent runs |
| `workflow_cancel` | `POST /runs/<run_id>/cancel` | Cancel a running workflow |
| `workflow_guidance` | `POST /runs/<run_id>/guidance` | Inject guidance into a running workflow |

**MCP usage pattern** (external agent):
```
1. workflow_templates() → choose template
2. workflow_start(workflow_id, prompt) → get run_id
3. Loop: workflow_status(run_id) → check status
   - If WAITING_FOR_USER: workflow_guidance(run_id, guidance) or wait
   - If RUNNING: continue polling (5-10 second intervals)
4. workflow_result(run_id) → get final output
```

---

## Workflow Versioning

Workflow definitions are versioned to provide audit trails and reproducibility.

- **Version field**: `WorkflowDefinition.version` is an integer, starting at 1
- **Auto-increment**: Every `PUT /definitions/<id>` increments the version
- **System templates**: Ship with version 1, immutable (users clone to customize)
- **Clone versioning**: Cloned workflows start at version 1 with `template_source` recording the original
- **Run records**: `WorkflowRun` captures `workflow_id` and the definition snapshot at time of execution — the run always uses the definition as it existed when the run started, even if the definition is later updated
- **No automatic migration**: If a workflow definition format changes (e.g., new fields added to `StepDefinition`), new fields get default values. Old definitions are forward-compatible. The JSON format is designed to be additive-only — new optional fields with sensible defaults, never removing or renaming existing fields
- **No rollback**: There is no version rollback mechanism. Users who want to go back to a previous version should clone the run's captured definition snapshot

The template JSON format is designed to be stable and robust:
- All fields have explicit defaults (temperature: 0.7, timeout: 120, max_tokens: null, etc.)
- New fields are always optional with defaults — old templates work without modification
- Step types are extensible (new types can be added without breaking existing ones)
- `input_schema` uses standard JSON Schema for validation, which is inherently forward-compatible

---

## Monitoring and Observability

### Logging

The workflow engine uses Python's standard `logging` module with the `workflow_engine` logger hierarchy:

| Logger | Level | Content |
|--------|-------|---------|
| `workflow_engine.engine` | INFO | Run start/complete/fail, step transitions, pause/resume/cancel |
| `workflow_engine.engine` | ERROR | Step failures, checkpoint errors, adapter errors |
| `workflow_engine.engine` | DEBUG | Resolved prompts, raw LLM outputs, state snapshots (verbose) |
| `workflow_engine.executors` | INFO | Step execution start/complete with timing |
| `workflow_engine.executors` | ERROR | Step execution failures with stack traces |
| `workflow_engine.state` | WARNING | State/scratchpad size approaching limits (>80% of max) |
| `workflow_engine.checkpointing` | INFO | Checkpoint save/load operations |
| `workflow_engine.storage` | INFO | DB operations, template sync |
| `workflow_engine.endpoints` | INFO | API request/response logging (standard Flask) |

### Metrics (In-Memory)

The engine tracks operational metrics accessible via `GET /runs/<run_id>` and in step results:

- **Per-step**: `duration_seconds`, `tokens_used` (prompt/completion/total), `retry_count`, `status`
- **Per-run**: `total_duration_seconds` (computed), `total_tokens` (computed sum), `step_count`, `steps_completed`, `steps_failed`, `steps_skipped`
- **Per-user**: Active run count (used for concurrency enforcement)

### Health Check

#### `GET /health` (standalone mode only)

**Response** `200`:
```json
{
  "status": "ok",
  "version": "0.1.0",
  "active_runs": 2,
  "total_runs_completed": 47,
  "uptime_seconds": 3600,
  "storage_dir": "workflow_storage",
  "db_size_bytes": 524288
}
```

### Alerting Conditions

The engine logs ERROR-level messages for conditions that may need attention:

| Condition | Log Level | Message Pattern |
|-----------|-----------|----------------|
| Workflow running longer than `max_runtime_seconds` | ERROR | `Workflow {run_id} exceeded max runtime ({seconds}s)` |
| Step failed after all retries exhausted | ERROR | `Step {step_id} failed permanently after {n} retries: {error}` |
| Checkpoint write failure | ERROR | `Failed to save checkpoint for {run_id} at step {step_index}: {error}` |
| State size exceeding 80% of limit | WARNING | `State size {current_size} approaching limit {max_size}` |
| Scratchpad size exceeding 80% of limit | WARNING | `Scratchpad size {current_size} approaching limit {max_size}` |
| Crash recovery triggered | WARNING | `Recovering {n} interrupted runs from checkpoints` |
| SSE subscriber disconnected during run | INFO | `SSE subscriber disconnected for run {run_id}, {n} remaining` |

### Debug Mode

When a run is started with `debug_mode: true`:
- Every step captures: resolved prompt (with all `{{state.*}}` substitutions applied), raw LLM output (full response text), full state snapshot before and after, scratchpad content before and after, all tool calls and their results
- This data is included in `StepResult` fields: `state_before`, `state_after`, `scratchpad_diff`, `resolved_prompt`, `raw_llm_output`
- Debug data is available via `GET /runs/<run_id>` (in step_results) and in `debug_info` SSE events
- Debug mode increases storage usage significantly — checkpoint files include full state snapshots at every step rather than deltas
- Without debug mode: only `step_id`, `status`, `duration_seconds`, `tokens_used`, `tool_calls`, and JSON output are captured per step

## Implementation Order Summary

```
Phase 1: Core Engine Infrastructure (workflow_engine/)
  p1-models              -> Data models (StepDefinition, WorkflowRun, etc.)
  p1-config              -> Configuration dataclass
  p1-errors              -> Exception hierarchy
  p1-state-manager       -> SharedState class (depends: p1-models, p1-errors)
  p1-adapters            -> Abstract interfaces + concrete adapters (depends: p1-models, p1-errors)
  p1-events              -> Event types + InMemoryEventBus (depends: p1-models)
  p1-storage             -> SQLite schema + storage ops (depends: p1-models, p1-config)

Phase 2: Execution Engine
  p2-executors           -> Step executor implementations (depends: p1-state, p1-adapters, p1-events)
  p2-engine-core         -> WorkflowEngine class (depends: p2-executors, p1-storage)
  p2-checkpointing       -> Checkpoint logic (depends: p1-storage, p1-state)

Phase 3: REST API & SSE Endpoints
  p3-endpoints           -> Flask blueprint (depends: p2-engine, p1-events)
  p3-standalone-server   -> __init__, __main__, cli (depends: p3-endpoints, p1-config)

Phase 4: Pre-built Templates
  p4-template-deep-research     -> Deep Research JSON (depends: p1-models)
  p4-template-doc-writer        -> Document Writer JSON (depends: p1-models)
  p4-template-qa-research       -> Q&A Research JSON (depends: p1-models)

Phase 5: Main App Integration
  p5-main-app-integration -> server.py + embedded adapters (depends: p3-standalone)
  p5-mcp-tools            -> MCP tool registration (depends: p5-integration)
  p5-chat-command          -> /workflow chat command + UI hooks (depends: p5-integration)
  p5-deprecate-ext-workflows -> Deprecate ext_workflows endpoints (depends: p5-integration)

Phase 6: UI - Workflow Panel
  p6-workflow-panel-js     -> Decoupled UI module (depends: p3-endpoints)
  p6-workflow-panel-css    -> Standalone CSS (no dependencies)
  p6-workflow-standalone-html -> Standalone page (depends: p6-js, p6-css)
  p6-drawer-integration   -> Main app drawer (depends: p6-js, p6-css, p5-chat-command)

Phase 7: Documentation & Testing
  p7-tests                -> Test suite (depends: p3-standalone)
  p7-documentation         -> Docs (depends: p7-tests)
```

## Dependency Graph (critical path)

```
p1-models
  -> p1-config
  -> p1-errors
  -> p1-state-manager <--- p1-models + p1-errors
  -> p1-adapters <--- p1-models + p1-errors
  -> p1-events <--- p1-models
  -> p1-storage <--- p1-models + p1-config
  -> p2-executors <--- p1-state + p1-adapters + p1-events
    -> p2-engine-core <--- p2-executors + p1-storage
      -> p3-endpoints <--- p2-engine + p1-events
        -> p3-standalone-server <--- p3-endpoints + p1-config
          -> p5-main-app-integration
            -> p5-mcp-tools
            -> p5-chat-command
            -> p5-deprecate-ext-workflows
              -> p6-drawer-integration <--- p6-js + p6-css + p5-chat-command
          -> p7-tests
            -> p7-documentation

p1-models (independent)
  -> p4-template-deep-research
  -> p4-template-doc-writer
  -> p4-template-qa-research

p3-endpoints (independent)
  -> p6-workflow-panel-js

(no dependencies)
  -> p6-workflow-panel-css
```

## Parallelizable Work

These can be done in parallel:
- p1-config + p1-errors (both depend only on nothing or p1-models)
- p1-state-manager + p1-adapters + p1-events + p1-storage (all depend on p1-models, independent of each other)
- p2-executors + p2-checkpointing (both depend on Phase 1, independent of each other)
- p4-template-* (all 3 templates, independent of each other, only need p1-models)
- p5-mcp-tools + p5-chat-command + p5-deprecate-ext-workflows (all depend on p5-integration)
- p6-workflow-panel-js + p6-workflow-panel-css (independent)
- p6-workflow-standalone-html + p6-drawer-integration (independent after p6-js + p6-css)

## Consolidated Decision Reference

| # | Area | Decision | Rationale |
|---|------|----------|-----------|
| 1 | Module location | `workflow_engine/` at project root | Self-contained, own Flask blueprint |
| 2 | Deployment | Standalone Flask + CLI + Embedded blueprint | Maximum flexibility |
| 3 | LLM access | Adapter pattern (LLMAdapter ABC) | Decoupled from any specific provider |
| 4 | Tool access | ToolAdapter wrapping TOOL_REGISTRY (embedded) | Reuses 48 existing tools |
| 5 | Storage | Own dir + SQLite + JSON templates | Matches codebase patterns |
| 6 | Auth | No auth localhost + optional API key | Simple for dev, secure for remote |
| 7 | Run IDs | `wfr_YYYYMMDD_XXXX` | Sortable, readable |
| 8 | Conversation binding | None (standalone entity) | Access global docs/PKB via tools |
| 9 | Output | Lives in panel until user exports | User controls destination |
| 10 | Template syntax | `{{state.field}}` | Simple, familiar |
| 11 | Concurrency | Max 3 per user | Configurable |
| 12 | No Airflow/Dagster | Custom engine | User-in-the-loop, mutable state, streaming |
| 13 | Scratch pad | JSON state + markdown pad | Structured data + accumulating document |
| 14 | Loop body | Single step or sub-workflow | Flexible |
| 15 | Judge inputs | Full scratchpad + latest + goal + state | Comprehensive evaluation |
| 16 | Parallel steps | Explicit parallel_group | Each writes own output_key, MD pad locked |
| 17 | Composability | State inheritance, nesting depth 3 | Configurable |
| 18 | Error handling | Retry -> skip -> halt and ask user | Never silently abort |
| 19 | Real-time UI | SSE + polling fallback | Lightweight, reliable |
| 20 | UI location | Right drawer + /workflows route + pop-out | Fully decoupled |
| 21 | Step editor | Nested/indented tree | Visual hierarchy for loops/groups |
| 22 | Workflow trigger | Panel button + /workflow chat command | Both entry points |
| 23 | MCP | Async start + poll | Non-blocking for external agents |
| 24 | Templates | 3 pre-built, clone-and-customize, JSON | Freeform prompt launch |
| 25 | History | Last 20 runs per user | Auto-cleanup |
| 26 | Clarification UI | Reuse existing modal pattern | Consistent, modular |
| 27 | Standalone server | Flask + CLI (both modes) | Server for UI, CLI for automation |
| 28 | Definitions storage | SQLite + JSON templates | Best of both |
| 29 | Separate tab | /workflows route + pop-out window | Both |
| 30 | Code folder | `workflow_engine/` | Parallel to `mcp_server/` |
| 31 | ext_workflows | Deprecate, no migration | Simple CRUD with no execution history |
| 32 | Versioning | Integer version, auto-increment on save | Audit trail, run snapshot |
| 33 | MCP file location | `mcp_server/workflows.py` | Follows existing MCP server pattern |
| 34 | Rate limiting | Per-user, per-endpoint-group | See Rate Limiting table |
| 35 | Monitoring | Logger hierarchy + per-step metrics + health check | Standard Python logging, no external deps |
