---
name: LLM Tool-Calling Framework
overview: >
  Add native tool-calling support to the main LLM pipeline so the model can autonomously invoke tools
  (ask clarification, web search, code execution, document lookup, etc.) mid-response. When the LLM
  emits a tool call, the server executes it (or requests user input for interactive tools), feeds the
  result back, and the LLM continues — in a multi-step agentic loop. Text already streamed stays
  visible; interactive tools show a modal on top. User controls via master toggle + per-tool settings.
goals:
  - Enable the main LLM to use OpenAI-native tool calling (via OpenRouter) to invoke registered tools mid-response.
  - Build a generic tool registry in code_common/tools.py that any part of the codebase can extend.
  - Support multi-step agentic loops (LLM can chain N tool calls before producing final text).
  - Support interactive tools (e.g., ask_clarification) that pause the LLM, show a UI modal, collect user input, and resume.
  - Support server-side tools (e.g., web_search) that execute silently and feed results back without user interaction.
  - Provide user control via a master "Enable Tool Use" toggle and per-tool toggles in chat settings.
  - Coexist with the existing /clarify slash command and auto-clarify checkbox (those remain pre-send; this is mid-response).
design_decisions:
  - Tool calling mechanism: Native OpenAI `tools` parameter via OpenRouter (structured, reliable).
  - Stream behavior: Text already streamed stays visible. Interactive tools show modal on top. LLM resumes after.
  - Code modification: Modify existing call_chat_model() / call_llm() in-place (with backward-compatible defaults).
  - Tool registry location: code_common/tools.py
  - Tool call loop: Multi-step agentic loop (LLM can chain multiple tool calls before final text).
  - Interactive tool UX: Extend existing Bootstrap modal pattern from clarifications-manager.js.
  - User control: Master toggle + per-tool toggles in chat settings.
architecture_notes: |
  ## Current Call Stack (no tools)
  
  ```
  Conversation.reply()
    → prompt = prompts.chat_slow_reply_prompt.format(...)     # line 8765
    → preamble = self.get_preamble(...)                       # line 5846
    → llm = CallLLm(keys, model_name=...)                     # line 9203 (project root call_llm.py:54)
    → main_ans_gen = llm(prompt, images=..., system=preamble, temperature=0.3, stream=True)  # line 9232
    → for chunk in main_ans_gen: yield {"text": chunk, ...}   # line ~9350+
  ```
  
  CallLLm.__call__()                          # call_llm.py:89
    → _cc_call_llm()                          # code_common/call_llm.py:884
      → call_with_stream(call_chat_model, stream, model, text, images, temp, system, keys)
        → call_chat_model()                   # code_common/call_llm.py:383
          → client.chat.completions.create(model, messages, temperature, stream=True, timeout=60)
          → _extract_text_from_openai_response(response)   # line 358 — ONLY reads delta.content
  
  ## Proposed Call Stack (with tools)
  
  ```
  Conversation.reply()
    → tools_config = self._get_enabled_tools(checkboxes)
    → if tools_config:
        → Use new tool-aware call path (agentic loop)
        → Yield text chunks AND tool events via the same JSON-lines stream
      else:
        → Existing path (unchanged)
  ```
  
  ## Streaming Protocol Extension
  
  Current JSON-line events:
    {"text": "...", "status": "..."}           — text chunk
    {"message_ids": {...}}                     — persistence IDs
  
  New JSON-line events:
    {"type": "tool_call", "tool_id": "...", "tool_name": "...", "tool_input": {...}}  — LLM wants to call a tool
    {"type": "tool_status", "tool_id": "...", "status": "executing"|"waiting_for_user"|"completed"}
    {"type": "tool_result", "tool_id": "...", "result_summary": "..."}   — brief summary for UI display
    {"type": "tool_input_request", "tool_id": "...", "ui_schema": {...}} — interactive tool needs user input
  
  ## Thread Synchronization for Interactive Tools
  
  send_message endpoint uses a Queue-based bridge (background thread → main thread → HTTP).
  For interactive tools:
    1. Background thread yields {"type": "tool_input_request", ...} into the queue
    2. UI receives it, shows modal, user fills in
    3. UI POSTs to /tool_response/<conversation_id>/<tool_id>
    4. Endpoint stores response in a thread-safe dict (AppState.tool_responses)
    5. Background thread polls tool_responses dict with timeout
    6. Background thread feeds result to LLM, continues loop

files_affected:
  - code_common/call_llm.py: Modify call_chat_model(), _extract_text_from_openai_response(), call_llm() to support tools param and parse tool_calls from response.
  - code_common/tools.py: NEW FILE — Tool registry, tool definitions, tool executor, base classes.
  - call_llm.py (project root): Modify CallLLm.__call__() to pass tools through.
  - Conversation.py: Add agentic tool loop in reply(), preamble injection for tool awareness, _get_enabled_tools() helper.
  - endpoints/conversations.py: Add /tool_response endpoint, tool_responses storage in AppState, pass tool config to Conversation.
  - interface/interface.html: Add master toggle + per-tool checkboxes in settings, tool-call modal HTML.
  - interface/chat.js: Settings persistence for tool toggles, model override for tool-calling model.
  - interface/common-chat.js: Extend renderStreamingResponse() to handle tool_call events, show modals, POST tool responses.
  - interface/tool-call-manager.js: NEW FILE — UI manager for tool interactions (extend clarifications-manager.js pattern).
  - interface/common.js: Read tool settings from getOptions().

risks_and_alternatives:
  - RISK: OpenRouter may not pass `tools` param to all models. Some models may not support tool calling.
    MITIGATION: Validate model supports tools before enabling. Fall back to no-tools path gracefully.
  - RISK: Multi-step agentic loop could run forever (LLM keeps calling tools).
    MITIGATION: Hard cap at N iterations (configurable, default 5). After cap, force text response.
  - RISK: Interactive tool timeout — user walks away, background thread blocks forever.
    MITIGATION: 60-second timeout per interactive tool call. On timeout, feed "user did not respond" to LLM.
  - RISK: Thread-safe tool_responses dict could have race conditions.
    MITIGATION: Use threading.Lock or threading.Event for synchronization.
  - ALTERNATIVE: Instead of modifying call_chat_model in-place, we could create new wrapper functions.
    DECISION: In-place modification chosen for simplicity. tools=None default preserves backward compatibility.
  - ALTERNATIVE: Text-based tool detection (regex on LLM output) instead of native API.
    DECISION: Native API chosen for reliability. All models go through OpenRouter which supports OpenAI tool format.

todos:
  # ─────────────────────────────────────────────
  # PHASE 1: Core Infrastructure (code_common/)
  # ─────────────────────────────────────────────

  - id: p1-tool-registry
    content: |
      Create `code_common/tools.py` with the tool registry framework:
      
      1. `ToolDefinition` dataclass: name, description, parameters (JSON Schema), handler callable,
         is_interactive (bool), category (str).
      2. `ToolRegistry` class: register(tool_def), get_tool(name), get_openai_tools_param(enabled_names) → list of
         OpenAI-format tool dicts, execute(name, args, context) → result string.
      3. `ToolCallResult` dataclass: tool_id, tool_name, result (str), error (str|None), needs_user_input (bool),
         ui_schema (dict|None for interactive tools).
      4. `ToolContext` dataclass: conversation_id, user_email, keys, conversation_summary, recent_messages —
         passed to tool handlers so they have context.
      5. Global `TOOL_REGISTRY = ToolRegistry()` singleton.
      6. Decorator `@register_tool(name, description, parameters, is_interactive, category)` for easy registration.
      
      DO NOT register any actual tools yet — just the framework.
      
      File: `code_common/tools.py`
    status: pending

  - id: p1-builtin-tools-define
    content: |
      Register initial built-in tools in `code_common/tools.py` (definitions + handler stubs):
      
      1. `ask_clarification` — Interactive tool. LLM calls this when user said "ask me questions" or when
         ambiguity detected. Parameters: { questions: [{ prompt: str, options: [str] }] }.
         Handler: returns ToolCallResult with needs_user_input=True and ui_schema containing the questions.
         Category: "clarification".
      
      2. `web_search` — Server-side tool. Performs a web search using existing search infrastructure.
         Parameters: { query: str, num_results?: int }.
         Handler: calls existing web search function from agents/search_and_information_agents.py or
         the existing web search flow used in Conversation.reply().
         Category: "search".
      
      3. `document_lookup` — Server-side tool. Searches conversation documents or global docs.
         Parameters: { query: str, doc_scope: "conversation"|"global"|"all" }.
         Handler: uses existing DocIndex/GlobalDoc search infrastructure.
         Category: "documents".
      
      Each handler receives a ToolContext and returns a ToolCallResult.
      The ask_clarification handler does NOT execute anything — it returns needs_user_input=True
      so the agentic loop knows to pause and wait for user input.
      
      File: `code_common/tools.py`
    status: pending
    dependencies:
      - p1-tool-registry

  - id: p1-call-chat-model-tools
    content: |
      Modify `call_chat_model()` in `code_common/call_llm.py` (line 383) to accept and pass `tools`:
      
      1. Add `tools=None` parameter to function signature.
      2. When `tools` is not None, pass `tools=tools` to `client.chat.completions.create()`.
      3. Also add `tool_choice=None` parameter (pass through when set; allows "auto", "required", "none",
         or specific tool forcing).
      
      DO NOT change `_extract_text_from_openai_response` yet — that's a separate task.
      
      This task is purely about passing the tools param through to the API.
      
      File: `code_common/call_llm.py`, function `call_chat_model()` at line 383.
      Specifically modify the `client.chat.completions.create()` call at line 458.
    status: pending
    dependencies:
      - p1-tool-registry

  - id: p1-extract-tool-calls
    content: |
      Modify `_extract_text_from_openai_response()` in `code_common/call_llm.py` (line 358) to also
      yield tool call events alongside text chunks.
      
      Current behavior: yields only `str` (text chunks from delta.content).
      New behavior: yields `str` for text OR `dict` for tool calls.
      
      When streaming, tool calls arrive incrementally in `delta.tool_calls`:
      ```
      chunk.choices[0].delta.tool_calls = [
        { index: 0, id: "call_abc", function: { name: "web_search", arguments: "" } },
      ]
      # ... next chunks accumulate arguments:
      chunk.choices[0].delta.tool_calls = [
        { index: 0, function: { arguments: '{"quer' } },
      ]
      chunk.choices[0].delta.tool_calls = [
        { index: 0, function: { arguments: 'y": "python"}' } },
      ]
      ```
      
      Implementation:
      1. Maintain an accumulator dict: `pending_tool_calls = {}` keyed by index.
      2. When `delta.tool_calls` is present, accumulate: id, function.name, function.arguments (string concat).
      3. When `finish_reason == "tool_calls"` (or stream ends), yield each accumulated tool call as a dict:
         `{"type": "tool_call", "id": call_id, "function": {"name": name, "arguments": args_json}}`.
      4. Continue yielding text from `delta.content` as before (str type).
      
      Callers can now distinguish: `isinstance(chunk, str)` → text, `isinstance(chunk, dict)` → tool call.
      
      IMPORTANT: Existing callers that only expect str will need the call_llm/call_with_stream layer
      to filter tool calls when tools=None (backward compat). Handle in p1-call-llm-passthrough.
      
      File: `code_common/call_llm.py`, function `_extract_text_from_openai_response()` at line 358.
    status: pending
    dependencies:
      - p1-call-chat-model-tools

  - id: p1-call-llm-passthrough
    content: |
      Modify `call_llm()` in `code_common/call_llm.py` (line 884) and `call_with_stream()` (line 275)
      to pass `tools` and `tool_choice` through:
      
      1. Add `tools=None, tool_choice=None` params to `call_llm()`.
      2. Pass them through to `call_with_stream()` → `call_chat_model()`.
      3. In `call_with_stream()`: when `tools is None`, filter out any dict items from the generator
         (only yield str). This ensures backward compatibility — existing callers that don't pass tools
         never see tool_call dicts.
      4. When `tools is not None`, yield both str and dict items from the generator.
      
      Also modify `CallLLm.__call__()` in project-root `call_llm.py` (line 89):
      1. Add `tools=None, tool_choice=None` to __call__ signature.
      2. Pass them through to `_cc_call_llm()`.
      3. When tools is not None and stream=True, do NOT wrap result in stream_text_with_math_formatting
         (math formatting only applies to text, not tool call dicts). Instead, apply math formatting
         only to str items in the generator, pass dict items through unchanged.
      
      File: `code_common/call_llm.py` (call_llm, call_with_stream) and `call_llm.py` (CallLLm.__call__).
    status: pending
    dependencies:
      - p1-extract-tool-calls

  - id: p1-unit-tests
    content: |
      Add tests in `code_common/test_call_llm.py` for the tool-calling additions:
      
      1. Test that call_llm() with tools=None behaves identically to before (backward compat).
      2. Test that _extract_text_from_openai_response correctly accumulates streaming tool calls
         and yields them as dicts.
      3. Test ToolRegistry: register, get_tool, get_openai_tools_param, execute.
      4. Test ToolDefinition validation (required fields, JSON Schema for parameters).
      5. Mock the OpenAI streaming response to simulate a tool call + text interleave.
      
      File: `code_common/test_call_llm.py` (extend existing).
    status: pending
    dependencies:
      - p1-call-llm-passthrough

  # ─────────────────────────────────────────────
  # PHASE 2: Agentic Loop in Conversation.reply()
  # ─────────────────────────────────────────────

  - id: p2-tool-settings-backend
    content: |
      Add tool-use settings support on the backend:
      
      1. In `Conversation.reply()` (or a helper), read tool settings from query checkboxes:
         - `enable_tool_use` (bool, master toggle)
         - `enabled_tools` (list of tool category names, e.g., ["clarification", "search", "documents"])
      
      2. Add helper method `_get_enabled_tools(self, checkboxes)` to Conversation class:
         - If `enable_tool_use` is False → return None.
         - Otherwise, get enabled tool categories from `enabled_tools`.
         - Call TOOL_REGISTRY.get_openai_tools_param(enabled_names) → list of OpenAI tool dicts.
         - Return the list (or None if empty).
      
      3. This does NOT change the reply flow yet — just adds the settings reading infrastructure.
      
      File: `Conversation.py`
    status: pending
    dependencies:
      - p1-call-llm-passthrough

  - id: p2-agentic-loop
    content: |
      Implement the agentic tool loop in `Conversation.reply()`, replacing the single CallLLm call
      with a loop that handles tool calls:
      
      Current flow (line ~9203-9238):
      ```python
      llm = CallLLm(...)
      main_ans_gen = llm(prompt, images=..., system=preamble, temperature=0.3, stream=True)
      ```
      
      New flow (when tools are enabled):
      ```python
      tools_config = self._get_enabled_tools(checkboxes)
      if tools_config:
          # Agentic loop
          for chunk in self._run_tool_loop(
              prompt=prompt, preamble=preamble, images=images,
              model_name=model_name, tools=tools_config,
              max_iterations=5,
              tool_response_store=tool_response_store,  # from endpoint
          ):
              yield chunk  # yields {"text": ...} or {"type": "tool_call", ...} etc.
      else:
          # Existing path (unchanged)
          llm = CallLLm(...)
          main_ans_gen = llm(prompt, ...)
      ```
      
      Implement `_run_tool_loop()` as a generator method on Conversation:
      
      1. First call: llm(prompt, tools=tools_config, stream=True) → generator of str|dict.
      2. Consume generator. Yield text chunks as {"text": chunk, "status": "..."}.
      3. If a tool_call dict is received:
         a. Yield {"type": "tool_call", "tool_id": ..., "tool_name": ..., "tool_input": ...} to UI.
         b. Look up tool in TOOL_REGISTRY.
         c. If tool.is_interactive:
            - Yield {"type": "tool_input_request", "tool_id": ..., "ui_schema": ...}.
            - Block: wait for user input via tool_response_store (with 60s timeout).
            - On timeout: result = "User did not respond within timeout."
         d. If not interactive: execute tool handler synchronously. Result = handler output.
         e. Yield {"type": "tool_result", "tool_id": ..., "result_summary": truncated_result}.
         f. Build messages array for continuation:
            - Original messages + assistant message with tool_calls + tool result message.
         g. Call LLM again with messages + tools (continuation).
         h. Repeat from step 2 (loop).
      4. Hard cap: after max_iterations tool calls, force the LLM to respond without tools
         (set tool_choice="none" on the final call).
      5. If no tool calls in a round, the loop exits naturally (LLM produced text-only response).
      
      IMPORTANT: The messages array for continuation must use the OpenAI tool-call format:
      ```
      messages = [
          ...original_messages,
          {"role": "assistant", "content": partial_text, "tool_calls": [...]},
          {"role": "tool", "tool_call_id": "call_abc", "content": "tool result"},
          ...
      ]
      ```
      This means we need to switch from simple text prompt to messages-mode for the continuation calls.
      The first call can still use simple mode; continuations must use messages mode.
      
      File: `Conversation.py` — new method `_run_tool_loop()` + modifications to `reply()` around line 9203.
    status: pending
    dependencies:
      - p2-tool-settings-backend
      - p1-builtin-tools-define

  - id: p2-tool-response-store
    content: |
      Add thread-safe tool response storage for interactive tools:
      
      1. In `endpoints/conversations.py`, add to AppState (or a module-level dict):
         ```python
         # {tool_id: threading.Event} for signaling, {tool_id: result_data} for data
         tool_response_events: dict[str, threading.Event] = {}
         tool_response_data: dict[str, dict] = {}
         tool_response_lock = threading.Lock()
         ```
      
      2. Add endpoint `POST /tool_response/<conversation_id>/<tool_id>`:
         - Receives JSON body: { "response": { ... user's answers ... } }
         - Stores in tool_response_data[tool_id] under lock.
         - Sets tool_response_events[tool_id] event to unblock the waiting background thread.
         - Returns 200 OK.
      
      3. Add helper function `wait_for_tool_response(tool_id, timeout=60)`:
         - Creates Event, stores in tool_response_events.
         - Waits on Event with timeout.
         - On success: pops and returns tool_response_data[tool_id].
         - On timeout: returns None (caller handles as "no response").
         - Cleanup: removes event and data entries.
      
      4. Pass the wait function (or the store reference) into Conversation._run_tool_loop()
         via the query dict or a dedicated parameter (e.g., query["_tool_response_waiter"]).
      
      File: `endpoints/conversations.py`
    status: pending
    dependencies:
      - p2-agentic-loop

  - id: p2-preamble-tool-awareness
    content: |
      When tools are enabled, inject tool-awareness text into the system preamble:
      
      1. In `Conversation.get_preamble()` (line 5846) or in `reply()` after preamble is built,
         append a tool-awareness section when tools_config is not None:
         
         ```
         ## Available Tools
         You have access to the following tools that you can invoke during your response:
         {list of enabled tool names and descriptions}
         
         Use tools when:
         - The user explicitly asks you to ask clarifying questions or says "ask me questions".
         - You need to search the web for current information.
         - You need to look up content from the user's documents.
         
         Do NOT use tools when:
         - The user's request is clear and you can answer directly.
         - The information is already in the conversation context.
         
         When you invoke a tool, the conversation will pause briefly while the tool executes.
         For interactive tools (like ask_clarification), the user will be prompted for input.
         ```
      
      2. The exact text of tool descriptions comes from TOOL_REGISTRY (each ToolDefinition has a description).
      
      3. This is additive — the existing preamble is unchanged; tool text is appended only when tools are on.
      
      File: `Conversation.py` — in or near `get_preamble()` or in `reply()` before the LLM call.
    status: pending
    dependencies:
      - p2-tool-settings-backend

  # ─────────────────────────────────────────────
  # PHASE 3: UI — Settings & Stream Handling
  # ─────────────────────────────────────────────

  - id: p3-settings-html
    content: |
      Add tool-use settings checkboxes to the chat settings modal in `interface/interface.html`:
      
      1. In the settings checkbox grid (around line 2090-2170), add a new row:
         ```html
         <div class="col-md-3">
           <div class="form-check mb-2">
             <input class="form-check-input" id="settings-enable_tool_use" type="checkbox">
             <label class="form-check-label" for="settings-enable_tool_use">Enable Tools</label>
           </div>
         </div>
         ```
      
      2. Add a collapsible per-tool section (shown only when master toggle is on):
         ```html
         <div id="tool-use-options" class="mt-2" style="display: none;">
           <small class="text-muted mb-1 d-block">Enabled tools:</small>
           <div class="form-check form-check-inline">
             <input class="form-check-input" id="settings-tool-clarification" type="checkbox" checked>
             <label class="form-check-label" for="settings-tool-clarification">Clarification</label>
           </div>
           <div class="form-check form-check-inline">
             <input class="form-check-input" id="settings-tool-web-search" type="checkbox" checked>
             <label class="form-check-label" for="settings-tool-web-search">Web Search</label>
           </div>
           <div class="form-check form-check-inline">
             <input class="form-check-input" id="settings-tool-doc-lookup" type="checkbox" checked>
             <label class="form-check-label" for="settings-tool-doc-lookup">Doc Lookup</label>
           </div>
         </div>
         ```
      
      3. Add a tool-call interaction modal (similar to clarifications-modal at line 1586):
         ```html
         <div id="tool-call-modal" class="modal fade" tabindex="-1" style="z-index: 1082;">
           <!-- Loading, questions/form, error, result states -->
         </div>
         ```
      
      File: `interface/interface.html`
    status: pending
    dependencies:
      - p2-agentic-loop

  - id: p3-settings-js
    content: |
      Wire up tool-use settings in JavaScript:
      
      1. In `chat.js` `buildSettingsStateFromControlsOrDefaults()` (line 586):
         Add `enable_tool_use`, `enabled_tools` (object of bools) to state.
      
      2. In `chat.js` `setModalFromState()` (line 614):
         Set checkbox states from stored state.
      
      3. In `chat.js` `collectSettingsFromModal()` (line 696):
         Read checkbox states into settings object.
      
      4. In `common.js` `getOptions()` (around line 4255):
         Add `enable_tool_use` and `enabled_tools` to the options object.
      
      5. Toggle visibility of per-tool options when master toggle changes:
         ```javascript
         $('#settings-enable_tool_use').on('change', function() {
             $('#tool-use-options').toggle($(this).is(':checked'));
         });
         ```
      
      6. Pass tool settings to the send_message payload via checkboxes in `common-chat.js`.
      
      Files: `interface/chat.js`, `interface/common.js`, `interface/common-chat.js`
    status: pending
    dependencies:
      - p3-settings-html

  - id: p3-tool-call-manager-js
    content: |
      Create `interface/tool-call-manager.js` — UI manager for mid-stream tool interactions:
      
      Design: Extend the pattern from `clarifications-manager.js` but for mid-stream tool calls.
      
      ```javascript
      const ToolCallManager = {
          activeToolCalls: {},  // {tool_id: {tool_name, tool_input, resolve_fn}}
          
          // Called by renderStreamingResponse when a tool_input_request event arrives.
          handleToolInputRequest(conversationId, toolId, toolName, uiSchema) {
              // 1. Show #tool-call-modal with appropriate form based on toolName.
              // 2. For ask_clarification: render MCQ questions (reuse clarifications rendering logic).
              // 3. For future tools: render appropriate form.
              // 4. On user submit: POST to /tool_response/{conversationId}/{toolId}.
              // 5. Close modal.
          },
          
          // Called by renderStreamingResponse when a tool_call event arrives (informational).
          showToolCallStatus(toolId, toolName, status) {
              // Update status indicator in the streaming response area.
              // E.g., "Searching the web for..." or "Asking clarification..."
          },
          
          // Called by renderStreamingResponse when a tool_result event arrives.
          showToolResult(toolId, resultSummary) {
              // Brief inline indicator that tool completed.
          },
          
          submitToolResponse(conversationId, toolId, responseData) {
              return fetch(`/tool_response/${conversationId}/${toolId}`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ response: responseData })
              });
          },
          
          setupEventHandlers() { ... }
      };
      ```
      
      File: `interface/tool-call-manager.js` (new file).
      Also: add `<script src="interface/tool-call-manager.js"></script>` in `interface.html`.
    status: pending
    dependencies:
      - p3-settings-html

  - id: p3-stream-handler-extension
    content: |
      Extend `renderStreamingResponse()` in `interface/common-chat.js` (around line 1072)
      to handle the new tool-call JSON-line event types:
      
      Currently, the stream parser does:
      ```javascript
      part = JSON.parse(buffer.slice(0, boundary));
      answer += part['text'];
      statusDiv.html(part['status']);
      ```
      
      Add handling for tool events:
      ```javascript
      if (part['type'] === 'tool_call') {
          // Informational: LLM is calling a tool.
          ToolCallManager.showToolCallStatus(part['tool_id'], part['tool_name'], 'calling');
      } else if (part['type'] === 'tool_input_request') {
          // Interactive: need user input.
          ToolCallManager.handleToolInputRequest(
              conversationId, part['tool_id'], part['tool_name'], part['ui_schema']
          );
      } else if (part['type'] === 'tool_status') {
          ToolCallManager.showToolCallStatus(part['tool_id'], part['tool_name'], part['status']);
      } else if (part['type'] === 'tool_result') {
          ToolCallManager.showToolResult(part['tool_id'], part['result_summary']);
      } else {
          // Existing handling: text + status.
          answer += part['text'] || '';
          if (part['status']) statusDiv.html(part['status']);
      }
      ```
      
      IMPORTANT: The stream does NOT pause during tool execution. The background thread pauses
      (waiting for tool result), but the HTTP connection stays open. The UI simply doesn't receive
      new chunks until the tool completes and the LLM resumes. This means no special pause/resume
      logic is needed in the stream reader — it just naturally blocks on `reader.read()`.
      
      File: `interface/common-chat.js`, function `renderStreamingResponse()`.
    status: pending
    dependencies:
      - p3-tool-call-manager-js

  # ─────────────────────────────────────────────
  # PHASE 4: Integration & Polish
  # ─────────────────────────────────────────────

  - id: p4-tool-handlers-implement
    content: |
      Implement actual tool handlers (beyond stubs):
      
      1. `ask_clarification` handler:
         - Returns ToolCallResult with needs_user_input=True.
         - ui_schema contains the questions array from the LLM's tool call arguments.
         - After user responds, returns formatted clarification text (same format as existing
           [Clarifications] block) that gets fed back to the LLM.
      
      2. `web_search` handler:
         - Reuse existing search infrastructure. Look at how `Conversation.reply()` currently
           does web search (search agents from `agents/search_and_information_agents.py`).
         - Execute search, format results, return as ToolCallResult.
         - Keep result under 4000 chars to avoid context bloat.
      
      3. `document_lookup` handler:
         - Reuse existing DocIndex.get_short_answer() or similar.
         - Search conversation docs or global docs based on doc_scope param.
         - Return relevant excerpts as ToolCallResult.
      
      File: `code_common/tools.py` (handler implementations).
    status: pending
    dependencies:
      - p2-agentic-loop
      - p2-tool-response-store
      - p3-stream-handler-extension

  - id: p4-messages-mode-continuation
    content: |
      Implement proper messages-mode continuation for multi-step tool loops:
      
      The first LLM call in the loop uses simple mode (text prompt + system).
      After a tool call, we must switch to messages mode because the OpenAI API requires:
      ```
      messages = [
          {"role": "system", "content": preamble},
          {"role": "user", "content": prompt},
          {"role": "assistant", "content": partial_text, "tool_calls": [
              {"id": "call_abc", "type": "function", "function": {"name": "...", "arguments": "..."}}
          ]},
          {"role": "tool", "tool_call_id": "call_abc", "content": "tool result text"},
      ]
      ```
      
      In `_run_tool_loop()`:
      1. After the first call, capture all text and tool_calls emitted by the LLM.
      2. Build the messages array for continuation.
      3. Use CallLLm with messages= param (messages mode, supported since code_common/call_llm.py:892).
      4. For the continuation call, do NOT re-include the full prompt — it's already in messages[1].
      
      Handle edge case: LLM calls multiple tools in parallel (OpenAI can emit multiple tool_calls
      in one response). All must be executed before continuing.
      
      File: `Conversation.py` — within `_run_tool_loop()`.
    status: pending
    dependencies:
      - p2-agentic-loop

  - id: p4-service-worker-cache
    content: |
      Update `interface/service-worker.js` to include `tool-call-manager.js` in the precache list.
      Also bump `CACHE_VERSION`.
      
      File: `interface/service-worker.js`
    status: pending
    dependencies:
      - p3-tool-call-manager-js

  - id: p4-coexistence-test
    content: |
      Verify coexistence with existing clarification features:
      
      1. /clarify slash command should still work as before (pre-send, lightweight).
      2. Auto-clarify checkbox should still work as before.
      3. Tool-based clarification (ask_clarification tool) is a separate mid-response flow.
      4. If both auto-clarify AND tool_use are enabled, auto-clarify fires first (pre-send),
         and tool_use is available during the response.
      5. No feature conflicts or double-triggering.
      
      Manual test checklist:
      - [ ] /clarify with tool_use OFF → existing behavior.
      - [ ] /clarify with tool_use ON → existing behavior (pre-send still works).
      - [ ] "ask me questions about my request" with tool_use ON → LLM invokes ask_clarification tool.
      - [ ] "ask me questions about my request" with tool_use OFF → LLM just asks in text (no tool).
      - [ ] Web search tool: "what's the latest news on X" with search tool enabled.
      - [ ] Multi-step: LLM calls web_search, then ask_clarification, then responds.
      - [ ] Timeout: user doesn't respond to clarification → LLM continues after 60s.
      - [ ] Max iterations: LLM keeps calling tools → capped at 5, then forced text response.
    status: pending
    dependencies:
      - p4-tool-handlers-implement
      - p4-messages-mode-continuation

  # ─────────────────────────────────────────────
  # PHASE 5: Documentation
  # ─────────────────────────────────────────────

  - id: p5-docs-update
    content: |
      Update documentation:
      
      1. Create `documentation/features/tool_calling/README.md`:
         - Feature overview, user-facing behavior, settings, available tools.
         - Architecture: tool registry, agentic loop, interactive tool flow.
         - API: /tool_response endpoint, tool event JSON-line format.
         - Files modified and created.
         - How to add new tools (developer guide).
      
      2. Update `documentation/README.md` to reference the new feature docs.
      
      3. Update `documentation/product/behavior/chat_app_capabilities.md` to mention tool calling.
      
      4. Add inline docstrings to all new functions and classes.
    status: pending
    dependencies:
      - p4-coexistence-test
---

## Background and Motivation

This application already has a clarification flow: the `/clarify` slash command and the auto-clarify checkbox. Both are **pre-send** mechanisms -- they fire before the user's message reaches the main LLM. A separate lightweight LLM call generates clarifying questions, the user answers them in a modal, and the answers are appended to the message text as a `[Clarifications]` block before the main LLM ever sees it.

This works well for catching ambiguity upfront, but it has a fundamental limitation: the main LLM itself has **no mechanism to ask structured questions and wait for answers**. If a user writes "help me plan my trip, ask me clarifying questions," the LLM can only write questions as plain text in its response. The user then has to manually compose a follow-up message with answers, losing the conversational thread and forcing a second full LLM call.

With tool calling, the LLM can detect that the user wants structured clarification and invoke the `ask_clarification` tool mid-response. This pauses the streaming output, shows a Bootstrap modal with MCQ questions (reusing the same UI pattern as the existing clarification modal), collects the user's answers, and feeds them back to the LLM as a tool result -- all within a **single response turn**. The text the LLM already streamed stays visible in the chat; the modal appears on top; and when the user submits, the LLM continues with the clarified context.

Beyond clarification, tool calling enables the LLM to autonomously decide it needs more information mid-response. Today, if a user wants web search results incorporated into a response, they must enable the web search checkbox **before** sending. With tool calling, the LLM can reason that it needs current information and invoke `web_search` on its own, without the user having pre-configured anything. Similarly, the LLM can invoke `document_lookup` to search the user's uploaded documents when it realizes it needs specific content.

This transforms the application from a "configure then send" model to a truly **agentic** model where the LLM reasons about what it needs and acts on it. The user still has control (master toggle + per-tool toggles), but the LLM gains autonomy within those bounds.

The feature is designed to be **extensible**. New tools can be added by creating a `ToolDefinition` and registering it in the `ToolRegistry` -- no changes to the core `call_llm` infrastructure are needed. This makes tool calling a foundation for future capabilities: code execution, image generation, API calls, structured data extraction, and more.

---

## Requirements

### Functional Requirements

- **FR-1**: The system shall support OpenAI-native tool calling via the `tools` parameter through OpenRouter. Tool definitions follow the OpenAI function-calling JSON Schema format.

- **FR-2**: When the LLM emits a `tool_calls` entry in its streaming response, the server shall detect it (by accumulating incremental `delta.tool_calls` chunks), execute the tool (or request user input for interactive tools), and feed the result back to the LLM as a `role: tool` message.

- **FR-3**: The LLM shall be able to chain multiple tool calls in sequence (agentic loop) before producing a final text response, up to a configurable maximum number of iterations (default 5). Each iteration consists of: LLM response with tool call(s), tool execution, result fed back, LLM continues.

- **FR-4**: Interactive tools (e.g., `ask_clarification`) shall pause the LLM stream, send a `tool_input_request` event to the client via the JSON-lines stream, display a Bootstrap modal to collect user input, and resume the LLM with the user's response submitted via `POST /tool_response/<conversation_id>/<tool_id>`.

- **FR-5**: Server-side tools (e.g., `web_search`, `document_lookup`) shall execute without user interaction and feed results back to the LLM silently. The UI receives only a `tool_status` event for display purposes.

- **FR-6**: Users shall control tool availability via a master "Enable Tools" toggle and per-tool category toggles (Clarification, Web Search, Doc Lookup) in the chat settings modal. When the master toggle is off, no `tools` parameter is sent to the API.

- **FR-7**: Tool calling shall coexist with the existing `/clarify` slash command and auto-clarify checkbox without conflicts. Pre-send clarification fires first; tool-based clarification is available during the response. Both can be enabled simultaneously.

- **FR-8**: The initial tool set shall include: `ask_clarification` (interactive, category "clarification"), `web_search` (server-side, category "search"), and `document_lookup` (server-side, category "documents").

- **FR-9**: All tool events shall be streamed to the UI via the existing JSON-lines streaming protocol (`{"text": ...}` lines over HTTP) with new event types: `tool_call`, `tool_status`, `tool_result`, and `tool_input_request`.

- **FR-10**: The tool registry shall be extensible. New tools can be added by creating a `ToolDefinition` dataclass and calling `TOOL_REGISTRY.register()` (or using the `@register_tool` decorator), with no changes to the core `call_llm` infrastructure or the agentic loop.

### Non-Functional Requirements

- **NFR-1: Backward compatibility** -- All existing callers of `call_llm()` / `CallLLm` that do not pass `tools` must see identical behavior. The `tools=None` default path is unchanged. When `tools` is `None`, `call_with_stream()` filters out any dict items from the generator, ensuring only `str` chunks are yielded.

- **NFR-2: Fail-open** -- Any tool execution error (handler exception, malformed arguments, unknown tool name) shall not crash the response. The LLM receives an error message as the tool result (e.g., "Tool execution failed: <error>") and continues generating text.

- **NFR-3: Interactive tool timeout** -- 60-second maximum wait for user input on interactive tools. The background thread uses `threading.Event.wait(timeout=60)`. On timeout, the LLM receives "User did not respond within timeout" as the tool result and continues with its best attempt.

- **NFR-4: Iteration safety** -- Hard cap of 5 tool call rounds to prevent infinite loops. After the cap is reached, the final LLM call is made with `tool_choice="none"` to force a text-only response.

- **NFR-5: Thread safety** -- Tool response storage uses `threading.Event` for signaling and `threading.Lock` for data access. The HTTP request thread (receiving the user's tool response via POST) and the background generation thread (waiting for the response) synchronize through `AppState.tool_response_events` and `AppState.tool_response_data`.

- **NFR-6: Performance** -- Tool calling overhead shall not affect non-tool-use conversations. The `tools=None` code path passes through `call_chat_model()` without any additional parameters to the API. No extra objects are allocated, no extra checks are performed.

- **NFR-7: Tool result size** -- Tool results fed back to the LLM shall be capped at 4000 characters to avoid context window bloat. Results exceeding this limit are truncated with a "[truncated]" suffix.

---

## Expected User Experience

### UX Flow 1: User asks LLM to ask clarifying questions (tool-based clarification)

1. User has "Enable Tools" on with "Clarification" tool enabled in the chat settings modal.
2. User types: "Help me write a business plan for a coffee shop. Ask me clarifying questions first."
3. User clicks Send.
4. The LLM starts streaming text into the chat: "I'd be happy to help! Let me ask a few questions to tailor the business plan..."
5. The LLM invokes the `ask_clarification` tool with 3 MCQ questions (e.g., "What is your target market?", "What is your budget range?", "What city/region?").
6. The text already streamed stays visible in the chat card.
7. A Bootstrap modal pops up over the chat with the questions, rendered in the same style as the existing clarification modal (radio buttons for each option, a submit button at the bottom).
8. User selects answers and clicks "Submit".
9. The modal closes. A status indicator in the chat shows "Processing clarification..."
10. The LLM receives the user's answers as a tool result and continues streaming the business plan, now tailored to the user's specific answers.
11. The entire flow happened within a single response turn -- no need for a follow-up message. The chat shows one user message and one assistant message.

### UX Flow 2: LLM autonomously uses web search mid-response

1. User has "Enable Tools" on with "Web Search" tool enabled.
2. User asks: "What are the latest developments in quantum computing this month?"
3. The LLM starts streaming: "Let me look up the latest developments..."
4. The LLM invokes the `web_search` tool with query "quantum computing developments March 2026".
5. A status indicator in the chat card shows "Searching the web..." (no modal -- this is a server-side tool).
6. The search executes server-side using the existing search agent infrastructure from `agents/search_and_information_agents.py`.
7. Search results (capped at 4000 characters) are fed back to the LLM as a tool result.
8. The LLM continues streaming with current, sourced information incorporated into its response.
9. The user sees a seamless response that includes up-to-date information. The brief "Searching the web..." status was the only visible indication that a tool was used.

### UX Flow 3: Multi-step tool chain

1. User asks: "Research the top 3 competitors for my business and ask me questions about my unique value proposition."
2. The LLM starts streaming an introduction, then invokes `web_search` with a query about the user's industry competitors.
3. Status indicator shows "Searching the web..." briefly.
4. Search results are fed back. The LLM processes them and then invokes `ask_clarification` with questions about the user's specific business ("What is your primary product/service?", "What differentiates you from competitors?", "What is your pricing strategy?").
5. A modal appears with the questions. The user answers and submits.
6. The LLM receives both the search results and the user's answers, then continues streaming a comprehensive competitive analysis tailored to the user's business.
7. Each tool invocation appeared as a brief status update in the chat. The final response is a single, coherent assistant message.

### UX Flow 4: Tool calling disabled or not available

1. User has "Enable Tools" OFF in settings, or is using a model that does not support tool calling.
2. User types: "Ask me clarifying questions about my request."
3. The LLM responds normally with questions written as plain text in its response (existing behavior, unchanged).
4. The user must send a follow-up message with answers (existing behavior).
5. No change from the current experience. The `tools` parameter is simply not sent to the API.

### UX Flow 5: Interactive tool timeout

1. User triggers a flow where the LLM invokes the `ask_clarification` tool.
2. The modal appears with questions.
3. The user gets distracted and does not respond for 60 seconds.
4. The modal remains visible on screen, but the backend's `threading.Event.wait(timeout=60)` expires.
5. The LLM receives "User did not respond within timeout" as the tool result and continues generating its response with its best attempt based on available context.
6. The response completes normally. The modal can be dismissed. The user can always clarify in a follow-up message.

---

## Relationship to Existing Clarification System

The application has three distinct clarification mechanisms. Understanding how they relate is critical for avoiding conflicts and for communicating the feature to users.

**`/clarify` slash command = PRE-SEND clarification.**
The user types `/clarify` before their message (or the message starts with `/clarify`). Before the message is sent to the main LLM, a separate lightweight LLM call (`clarify_intent_model`, configurable per conversation) generates clarifying questions. The `ClarificationsManager` in `interface/clarifications-manager.js` shows these in a modal. The user's answers are formatted as a `[Clarifications]` block and appended to the original message text. The main LLM then sees the clarified message. Endpoint: `POST /clarify_intent`.

**Auto-clarify checkbox = PRE-SEND clarification.**
Same mechanism as `/clarify`, but fires automatically when the user clicks Send (if the checkbox is enabled). The lightweight LLM decides whether clarification is needed. If not needed, the message is sent directly. If needed, the same modal flow occurs. This is controlled by the `forceClarify` flag in the send payload.

**`ask_clarification` tool = MID-RESPONSE clarification.**
The main LLM decides during its response that it needs clarification. It invokes the `ask_clarification` tool via the OpenAI tool calling API. The questions come from the main LLM itself (not a separate call). The user's answers are fed back as a `role: tool` message in the conversation's messages array. The LLM continues generating with the clarified context. This is handled by the new `ToolCallManager` in `interface/tool-call-manager.js`.

**These are complementary, not competing:**

- Pre-send clarification catches ambiguity BEFORE the LLM starts working. It is a lightweight, fast check that prevents wasted computation.
- Tool-based clarification lets the LLM ask for information it realizes it needs WHILE working on the response. It is a deeper, context-aware mechanism.
- Both can be enabled simultaneously. Pre-send fires first (during the send flow, before the main LLM call). Tool-based is available during the response (if the LLM decides to use it).
- The UI uses the same Bootstrap modal pattern for consistency. Both show MCQ-style questions with radio buttons and a submit button.
- The existing `clarifications-manager.js` handles pre-send flows. The new `tool-call-manager.js` handles mid-response flows. They share UI patterns but are completely separate code paths with no shared state.

---

## Current System Architecture (Before This Feature)

A brief summary of the relevant architecture, for context when reading the implementation tasks.

**LLM Call Stack:**
`Conversation.reply()` (line 6338 in `Conversation.py`) builds the prompt and preamble, then calls `CallLLm` (line 54 in project-root `call_llm.py`). `CallLLm.__call__()` delegates to `call_llm()` (line 884 in `code_common/call_llm.py`), which calls `call_with_stream()` (line 275), which calls `call_chat_model()` (line 383). `call_chat_model()` creates an OpenAI client pointed at OpenRouter and calls `client.chat.completions.create(model, messages, temperature, stream=True, timeout=60)`. The streaming response is parsed by `_extract_text_from_openai_response()` (line 358), which yields `str` chunks from `delta.content`.

**Streaming Protocol:**
The HTTP response uses a JSON-lines format. `Conversation.__call__()` (line 4707) wraps `reply()` and yields `json.dumps(chunk) + "\n"` for each dict. The endpoint in `endpoints/conversations.py` uses a Queue-based bridge: a background thread runs the Conversation generator and puts chunks into a Queue; the main thread reads from the Queue and streams to the HTTP response. The UI reads with `ReadableStream.getReader()` in `renderStreamingResponse()` (line 1072 in `interface/common-chat.js`), parsing each JSON line and extracting `text` and `status` fields.

**Settings:**
The chat settings modal in `interface/interface.html` contains checkboxes for various features. State is persisted via `chat.js` to `localStorage` (per-conversation settings). Checkboxes are read in `common.js` `getOptions()` and passed in the `send_message` payload as the `checkboxes` dict. The backend reads these from `query["checkboxes"]` in `Conversation.reply()`.

**No Existing Tool Support:**
`call_chat_model()` only passes `model`, `messages`, `temperature`, `stream`, and `timeout` to the OpenAI API. There is no `tools` parameter. `_extract_text_from_openai_response()` only reads `delta.content` -- it does not check for `delta.tool_calls`. If the API returned tool calls today, they would be silently ignored.

---

## Detailed Phase Breakdown

This section provides a readable narrative walkthrough of each implementation phase. The specific tasks and their dependencies are defined in the YAML front matter above; this prose explains the reasoning, challenges, and key decisions for each phase.

### Phase 1 -- Core Infrastructure

Phase 1 builds the foundation that every subsequent phase depends on. The work is entirely in `code_common/` and the project-root `call_llm.py` -- no UI changes, no Conversation changes.

The first task (`p1-tool-registry`) creates `code_common/tools.py` with the `ToolRegistry` class, `ToolDefinition` dataclass, and supporting types. This is a standalone module with no dependencies on the rest of the codebase. The registry provides `get_openai_tools_param()` which converts registered tools into the OpenAI `tools` format (list of `{type: "function", function: {name, description, parameters}}` dicts). A global `TOOL_REGISTRY` singleton and a `@register_tool` decorator make registration ergonomic.

The second task (`p1-builtin-tools-define`) registers the three initial tools (`ask_clarification`, `web_search`, `document_lookup`) with their JSON Schema parameter definitions and handler stubs. The handlers are intentionally stubbed at this point -- actual implementations come in Phase 4. This separation ensures the registry framework can be tested independently of handler logic.

The third task (`p1-call-chat-model-tools`) modifies `call_chat_model()` at line 383 in `code_common/call_llm.py` to accept `tools=None` and `tool_choice=None` parameters and pass them through to `client.chat.completions.create()`. This is a minimal, backward-compatible change: when `tools` is `None`, the API call is identical to before.

The fourth task (`p1-extract-tool-calls`) is the most technically challenging in Phase 1. It modifies `_extract_text_from_openai_response()` at line 358 to handle streaming tool calls. When the OpenAI API streams a tool call, it arrives incrementally: the first chunk contains the tool call `id` and `function.name`; subsequent chunks append to `function.arguments` (a JSON string built up character by character). The function must maintain a `pending_tool_calls` accumulator dict keyed by index, concatenate argument fragments, and yield the complete tool call as a `dict` when `finish_reason == "tool_calls"`. Text chunks (`delta.content`) continue to be yielded as `str`. Callers distinguish the two via `isinstance(chunk, str)` vs `isinstance(chunk, dict)`.

The fifth task (`p1-call-llm-passthrough`) threads the `tools` and `tool_choice` parameters through the full call stack: `CallLLm.__call__()` in `call_llm.py` (line 54) to `call_llm()` (line 884) to `call_with_stream()` (line 275) to `call_chat_model()`. The critical backward-compatibility measure is in `call_with_stream()`: when `tools is None`, it filters out any `dict` items from the generator, ensuring existing callers that only expect `str` chunks never see tool call dicts. When `tools is not None`, both `str` and `dict` items pass through. Additionally, `CallLLm.__call__()` must skip `stream_text_with_math_formatting` for `dict` items (math formatting only applies to text).

The sixth task (`p1-unit-tests`) adds tests for all of the above: backward compatibility (tools=None path unchanged), streaming tool call accumulation, registry CRUD, and a mock OpenAI streaming response that interleaves text and tool calls.

### Phase 2 -- Agentic Loop

Phase 2 is the heart of the feature. It adds the `_run_tool_loop()` generator method to `Conversation` and the supporting infrastructure for interactive tool responses.

The key design decision is that `_run_tool_loop()` is a **generator**. It must be a generator (not a regular function) because the Conversation streaming architecture requires yielding chunks to the HTTP response as they are produced. The method yields `dict` chunks (text events, tool events, status events) that `Conversation.__call__()` serializes to JSON lines. This means the agentic loop -- which may involve multiple LLM calls, tool executions, and user interactions -- is expressed as a single generator that the HTTP streaming infrastructure consumes naturally.

The loop works as follows: (1) Make the first LLM call with `tools=tools_config`. (2) Consume the generator, yielding text chunks to the stream. (3) If a tool call dict arrives, yield a `tool_call` event to the UI, look up the tool in the registry, and either execute it (server-side) or wait for user input (interactive). (4) Build the OpenAI messages array for continuation (original messages + assistant message with `tool_calls` + `role: tool` result message). (5) Call the LLM again with the messages array. (6) Repeat until the LLM produces a text-only response or the iteration cap is reached.

The thread synchronization challenge for interactive tools is significant. The background thread (running the generator) must pause and wait for user input that arrives via a separate HTTP POST request. The solution uses `threading.Event` for signaling and a shared dict for data transfer, protected by `threading.Lock`. The `wait_for_tool_response()` helper creates an Event, waits on it with a 60-second timeout, and returns the response data (or `None` on timeout). The `/tool_response` endpoint stores the data and sets the Event.

The messages-mode continuation requirement (`p4-messages-mode-continuation`, technically Phase 4 but conceptually part of the loop) is important: the first LLM call can use simple mode (text prompt + system), but continuation calls after a tool result MUST use messages mode because the OpenAI API requires the `role: assistant` message with `tool_calls` followed by `role: tool` result messages. The `_run_tool_loop()` method builds this messages array incrementally as the loop progresses.

The preamble injection task (`p2-preamble-tool-awareness`) appends tool-awareness instructions to the system prompt when tools are enabled. This tells the LLM what tools are available, when to use them, and when not to. The text is generated dynamically from the `ToolRegistry` so it stays in sync with registered tools.

### Phase 3 -- UI Changes

Phase 3 is the user-facing layer. It adds settings controls, creates the tool call manager, and extends the stream handler.

The settings HTML (`p3-settings-html`) adds a master "Enable Tools" checkbox to the settings modal's checkbox grid, plus a collapsible per-tool section that appears when the master toggle is on. Each tool category (Clarification, Web Search, Doc Lookup) gets its own checkbox. A tool-call interaction modal (similar to the existing clarifications modal at line 1586 in `interface.html`) is added for interactive tool responses.

The settings JavaScript (`p3-settings-js`) wires up persistence in `chat.js` (the same `buildSettingsStateFromControlsOrDefaults` / `setModalFromState` / `collectSettingsFromModal` pattern used by all other settings). The `getOptions()` function in `common.js` is extended to include `enable_tool_use` and `enabled_tools` in the options payload sent to the server.

The new `tool-call-manager.js` (`p3-tool-call-manager-js`) follows the same pattern as `clarifications-manager.js` but handles mid-stream tool interactions. Its key methods are: `handleToolInputRequest()` (shows the modal with questions when an interactive tool needs input), `showToolCallStatus()` (updates a status indicator in the chat for server-side tools), `showToolResult()` (brief inline indicator that a tool completed), and `submitToolResponse()` (POSTs the user's answers to `/tool_response`). For `ask_clarification`, the modal renders MCQ questions using the same rendering logic as the clarification modal, ensuring visual consistency.

The stream handler extension (`p3-stream-handler-extension`) modifies `renderStreamingResponse()` in `interface/common-chat.js` (line 1072) to recognize the new JSON-line event types (`tool_call`, `tool_input_request`, `tool_status`, `tool_result`) and dispatch to `ToolCallManager` methods. Existing `text` + `status` handling is unchanged (falls through to the `else` branch). An important architectural note: the HTTP stream does NOT pause during tool execution. The background thread pauses (waiting for the tool result), but the HTTP connection stays open. The UI's `reader.read()` simply blocks naturally until new data arrives. No special pause/resume logic is needed.

### Phase 4 -- Integration and Polish

Phase 4 connects all the pieces and implements the actual tool handler logic.

The tool handler implementations (`p4-tool-handlers-implement`) replace the Phase 1 stubs with real logic. The `ask_clarification` handler returns a `ToolCallResult` with `needs_user_input=True` and the questions from the LLM's tool call arguments as the `ui_schema`. After the user responds, the formatted answers are returned as the tool result (using the same `[Clarifications]` format as the existing system for consistency). The `web_search` handler reuses the existing search agent infrastructure from `agents/search_and_information_agents.py`, executing a search and formatting results within the 4000-character cap. The `document_lookup` handler reuses `DocIndex.get_short_answer()` or similar methods to search conversation documents or global documents based on the `doc_scope` parameter.

The messages-mode continuation task (`p4-messages-mode-continuation`) implements the proper OpenAI messages array building for multi-step loops. After the first LLM call, the method captures all text and tool calls emitted, builds the continuation messages array (`system` + `user` + `assistant` with `tool_calls` + `tool` results), and uses `CallLLm` in messages mode for subsequent calls. An edge case to handle: the LLM may emit multiple tool calls in parallel (multiple entries in `tool_calls`), all of which must be executed before continuing.

The service worker cache update (`p4-service-worker-cache`) adds `tool-call-manager.js` to the precache list in `interface/service-worker.js` and bumps `CACHE_VERSION`.

The coexistence test (`p4-coexistence-test`) is a manual test checklist verifying that `/clarify`, auto-clarify, and tool-based clarification all work correctly both independently and in combination. Key scenarios: `/clarify` with tools off (unchanged behavior), `/clarify` with tools on (pre-send still works, tools available during response), tool-based clarification with `/clarify` off, timeout behavior, and iteration cap behavior.

### Phase 5 -- Documentation

Phase 5 keeps the documentation in sync with the implementation. A new `documentation/features/tool_calling/README.md` covers the feature overview, user-facing behavior, settings, available tools, architecture (registry, agentic loop, interactive flow), API reference (`/tool_response` endpoint, tool event JSON-line format), files modified and created, and a developer guide for adding new tools. The main `documentation/README.md` and `documentation/product/behavior/chat_app_capabilities.md` are updated to reference the new feature. All new functions and classes receive inline docstrings.

## Implementation Order Summary

```
Phase 1: Core Infrastructure (code_common/)
  p1-tool-registry          → Tool registry framework
  p1-builtin-tools-define   → Initial tool definitions + handler stubs
  p1-call-chat-model-tools  → Pass tools param to OpenAI API
  p1-extract-tool-calls     → Parse tool_calls from streaming response
  p1-call-llm-passthrough   → Pass tools through full call stack
  p1-unit-tests             → Tests for all of the above

Phase 2: Agentic Loop in Conversation.reply()
  p2-tool-settings-backend  → Read tool settings from checkboxes
  p2-agentic-loop           → _run_tool_loop() generator method
  p2-tool-response-store    → Thread-safe interactive tool response storage + endpoint
  p2-preamble-tool-awareness → Inject tool descriptions into system prompt

Phase 3: UI — Settings & Stream Handling
  p3-settings-html          → Checkboxes + modal HTML
  p3-settings-js            → Settings persistence in JS
  p3-tool-call-manager-js   → NEW tool-call-manager.js
  p3-stream-handler-extension → Extend renderStreamingResponse()

Phase 4: Integration & Polish
  p4-tool-handlers-implement → Actual handler implementations
  p4-messages-mode-continuation → Multi-step messages array building
  p4-service-worker-cache   → Cache new JS file
  p4-coexistence-test       → Manual test checklist

Phase 5: Documentation
  p5-docs-update            → Feature docs, API docs, developer guide
```

## Dependency Graph (critical path)

```
p1-tool-registry
  → p1-builtin-tools-define
  → p1-call-chat-model-tools
    → p1-extract-tool-calls
      → p1-call-llm-passthrough
        → p1-unit-tests
        → p2-tool-settings-backend
          → p2-agentic-loop ←─── p1-builtin-tools-define
            → p2-tool-response-store
            → p2-preamble-tool-awareness
            → p3-settings-html
              → p3-settings-js
              → p3-tool-call-manager-js
                → p3-stream-handler-extension
                  → p4-tool-handlers-implement ←─── p2-tool-response-store
                    → p4-coexistence-test ←─── p4-messages-mode-continuation
                      → p5-docs-update
```

## Parallelizable Work

These can be done in parallel:
- p1-builtin-tools-define + p1-call-chat-model-tools (both depend only on p1-tool-registry)
- p2-preamble-tool-awareness + p2-tool-response-store (both depend on p2-agentic-loop)
- p3-settings-html + p3-settings-js (UI work, independent of backend once p2 is done)
- p4-tool-handlers-implement + p4-messages-mode-continuation (both depend on p2 but not each other)

---

## MCP Server Tools Integration (Added)

### Background

The project already has an MCP server (`mcp_server/`) that exposes 45 tools via the MCP protocol for external coding assistants (OpenCode, Claude Code). These tools provide rich functionality: web search, document lookup, PKB queries, code execution, artefact management, conversation memory, and prompt management.

To maximize the LLM's capabilities, ALL MCP tools are also registered in the `code_common/tools.py` tool registry, allowing the main LLM to invoke them mid-response through the native tool-calling framework.

### Tool Categories (8 total)

| Category | Module | Tools | Default | Notes |
|----------|--------|-------|---------|-------|
| `clarification` | (built-in) | ask_clarification | ON | Interactive, pauses for user input |
| `search` | mcp_app.py | web_search, perplexity_search, jina_search, deep_search, jina_read_page, read_link | ON | Web search and page reading |
| `documents` | docs.py | document_lookup + 9 MCP doc tools | ON | Conversation and global doc search |
| `pkb` | pkb.py | 10 tools (search, get, add, edit, resolve, pin, etc.) | OFF | Personal Knowledge Base |
| `memory` | conversation.py | 7 tools (memory pad, history, user detail, preferences) | OFF | Conversation memory access |
| `code_runner` | code_runner_mcp.py | run_python_code | OFF | Sandboxed Python execution (120s timeout) |
| `artefacts` | artefacts.py | 8 tools (list, create, get, update, delete, propose/apply edits) | OFF | File management within conversations |
| `prompts` | prompts_actions.py | 5 tools (list, get, create, update, temp_llm_action) | OFF | Saved prompts and LLM actions |

**Total: 48 tools** (3 original + 45 MCP)

### Hierarchical UI Controls

The settings modal provides a hierarchical toggle system:
1. **Master toggle**: "Enable Tools" — turns all tool calling on/off
2. **Per-category toggles**: Each of the 8 categories can be enabled/disabled independently
3. Categories `clarification`, `search`, and `documents` default to ON when master is enabled
4. Categories `pkb`, `memory`, `code_runner`, `artefacts`, `prompts` default to OFF (opt-in)

This ensures:
- Basic tool calling (search, docs, clarification) works with minimal configuration
- Advanced tools (code execution, PKB writes, artefact management) require explicit opt-in
- Users can fine-tune which tool categories the LLM has access to
- Token usage is controlled — fewer enabled categories = smaller `tools` parameter

### Safety Considerations

- **Write operations** (artefacts_create, artefacts_delete, pkb_add_claim, etc.) are marked with "(write operation)" in their descriptions so the LLM understands the implications
- **Code execution** has a 120-second timeout and runs in a sandboxed environment
- **Max iterations cap** (5 rounds) prevents infinite tool-calling loops
- **Interactive tool timeout** (60 seconds) prevents indefinite blocking
- **Default-OFF for advanced categories** prevents accidental use of powerful tools

### Implementation Notes

- Tool handlers in `code_common/tools.py` are currently stubs returning "not yet implemented"
- Real implementations will call the same underlying Python functions as the MCP server tools
- `user_email` and `conversation_id` come from `ToolContext`, NOT from the LLM's tool call arguments
- `model_name` is handled internally, NOT exposed as a tool parameter
- The tool registry auto-generates OpenAI-format tool schemas from the registered definitions
- Categories map to UI checkbox IDs: `settings-tool-{category}` (e.g., `settings-tool-pkb`)
