# Clarifications API and Automatic Doubt Generation - Context Document

## Overview
This document provides comprehensive context for implementing two features:
1. **Pre-Message Clarifications API**: Before calling send_message, show a modal with MCQ-style clarification questions (max 3) to understand user intent better
2. **Automatic Doubt Generation**: After reply method completes, automatically generate a shorter, crisp summary as an automatic doubt

---

## Feature 1: Pre-Message Clarifications API

### Goals (Based on Plan)
- Add a **manual "Clarify" button** near send controls (NOT auto-trigger)
- Support auto-trigger based on chat settings UI also
- When manual button clicked or auto trigger enabled, call LLM-backed API to generate up to 3 MCQ questions
- Show these in a modal with options: "Apply", "Apply & Send", "Cancel"
- Append clarifications to the original query in `#messageText`
- The appended text appears in both the user message card and is sent to server

### Key Requirements
- **Manual trigger**: User explicitly clicks "Clarify" button (automatic interception if setting is checked)
- **Fail-open behavior**: If API fails, proceed without clarifications (never block send)
- **API-based**: Server-side LLM call (not UI-side) for consistent auth/rate-limiting
- **Append format**: Stable, clean format like `\n\n[Clarifications]\n- Q: ... A: ...`
- **Apply & Send**: Modal can optionally trigger send immediately after applying

---

### Current Send Message Flow

#### 1. **UI Entry Point** (`interface/common-chat.js`)
**Function**: `sendMessageCallback()` (lines ~2274-2417)

**Current Flow**:
```javascript
function sendMessageCallback() {
    // 1. Get message text
    var messageText = $('#messageText').val();
    
    // 2. Get options/checkboxes
    var options = getOptions('chat-options', 'assistant');
    
    // 3. Parse message for special syntax
    let parsed_message = parseMessageForCheckBoxes(messageText);
    
    // 4. Handle history message IDs, attached claims, referenced claims
    var history_message_ids = []
    var attached_claim_ids = [] // from UI selected claims
    var referenced_claim_ids = [] // from @memory:id syntax
    
    // 5. Call ChatManager.sendMessage
    ChatManager.sendMessage(conversationId, messageText, options, links, search, attached_claim_ids, referenced_claim_ids)
        .then(function (response) {
            // 6. Call renderStreamingResponse
            renderStreamingResponse(response, conversationId, messageText, history_message_ids);
        });
}
```

**📍 EDIT POINT #1**: Insert clarifications check **BEFORE** `ChatManager.sendMessage` is called
- Location: After step 4, before step 5
- Add: Check if clarifications are enabled in settings
- Add: Call clarifications API/function if needed
- Add: Show clarifications modal
- Add: Append answers to messageText
- Then: Proceed with ChatManager.sendMessage

**📍 NO INTERCEPT NEEDED case**: According to the plan, this is a also **manual button trigger**, not an automatic intercept
- The "Clarify" button will have its own click handler
- User clicks "Clarify" → modal appears → user answers → text is appended to `#messageText`
- Then user manually clicks "Send" OR modal has "Apply & Send" button

#### 2. **ChatManager.sendMessage** (`interface/common-chat.js`)
**Function**: `ChatManager.sendMessage()` (lines ~2108-2146)

**Current Flow**:
```javascript
sendMessage: function (conversationId, messageText, checkboxes, links, search, attached_claim_ids, referenced_claim_ids) {
    // 1. Render user's message immediately in UI
    ChatManager.renderMessages(conversationId, [userMessage], ...)
    
    // 2. Build request body
    var requestBody = {
        'messageText': messageText,
        'checkboxes': checkboxes,
        'links': links,
        'search': search,
        'attached_claim_ids': attached_claim_ids,
        'referenced_claim_ids': referenced_claim_ids
    };
    
    // 3. Make fetch request
    let response = fetch('/send_message/' + conversationId, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(requestBody)
    });
    
    return response;
}
```

**📍 EDIT POINT #2**: When clarifications are used, update messageText before rendering user message
- The messageText passed here should already include clarifications (from EDIT POINT #1)
- The user message card should show the original query + clarifications

#### 3. **Backend Endpoint** (`endpoints/conversations.py`)
**Route**: `POST /send_message/<conversation_id>` (lines 877-931)

```python
@conversations_bp.route("/send_message/<conversation_id>", methods=["POST"])
@limiter.limit("50 per minute")
@login_required
def send_message(conversation_id: str):
    # 1. Get keys and user details
    keys = keyParser(session)
    email, _name, _loggedin = get_session_identity()
    
    # 2. Get conversation object
    conversation: Conversation = get_conversation_with_keys(state, conversation_id, keys)
    
    # 3. Get query from request
    query = request.json
    
    # 4. Inject pinned claims if any
    conv_pinned_ids = list(state.pinned_claims.get(conversation_id, set()))
    if conv_pinned_ids:
        query["conversation_pinned_claim_ids"] = conv_pinned_ids
    
    # 5. Create streaming response queue
    response_queue: Queue = Queue()
    
    def generate_response():
        for chunk in conversation(query, user_details):  # Calls __call__ which calls reply
            response_queue.put(chunk)
        response_queue.put("<--END-->")
    
    # 6. Stream response
    return Response(run_queue(), content_type="text/plain")
```

**📍 EDIT POINT #3**: Create new endpoint for clarifications
- **New route**: `POST /clarify_intent/<conversation_id>` (as per plan, not `/get_clarifications`)
- **Location**: `endpoints/conversations.py` - add after `send_message` endpoint (after line ~932)
- **Input**: messageText (required), checkboxes (optional), links (optional), search (optional)
- **Output**: JSON with strict schema:
  ```json
  {
      "needs_clarification": bool,
      "questions": [
          {
              "id": "q1",
              "prompt": "What aspect...",
              "options": [
                  {"id": "opt1", "label": "Technical details"},
                  {"id": "opt2", "label": "High-level overview"}
              ]
          }
      ],
      "recommended_append_template": "string (optional)"
  }
  ```
- **Rate limit**: 30/minute
- **Fail-open**: If LLM fails or JSON parse error, return `{"needs_clarification": false, "questions": []}`

#### 4. **Conversation.__call__** (`Conversation.py`)
**Method**: `__call__()` (line 2037-2040)

```python
def __call__(self, query, userData=None):
    logger.info(f"Called conversation reply for chat Assistant with Query: {query}")
    for txt in self.reply(query, userData):
        yield json.dumps(txt)+"\n"
```

**📍 No changes needed** - This just wraps reply method

---

### Clarify Button Placement (Manual Trigger)

**📍 NEW COMPONENT #1**: Add "Clarify" button in `interface/interface.html`

**Location**: Lines 325-346 (near send/stop buttons)

**Current structure**:
```html
<div class="input-group-append" style="margin-left: 5px;">
    <button id="sendMessageButton" class="btn btn-success">
        ➤
    </button>
    <button id="stopResponseButton" class="btn btn-danger" style="display: none; margin-left: 5px;">
        ⏹
    </button>
    <div id="uploadProgressContainer" ...>
    </div>
</div>
<div class="input-group-append" style="margin-right: -25px;margin-left: 5px;">
    <button id="chatSettingsButton" class="btn btn-secondary rounded-pill" title="Chat Settings">
        <i class="fa fa-cogs"></i>
    </button>
</div>
```

**Add after line 331** (after stopResponseButton, before uploadProgressContainer):
```html
<button id="clarifyButton" class="btn btn-info" style="margin-left: 5px;" title="Clarify your question">
    <i class="fa fa-question-circle"></i>
</button>
```

**Bind in `interface/chat.js`** (after line 78, where sendMessageButton is bound):
```javascript
$('#sendMessageButton').on('click', sendMessageCallback);
$('#stopResponseButton').on('click', stopCurrentResponse);
$('#clarifyButton').on('click', function() {
    // Call ClarificationsManager
    if (typeof ClarificationsManager !== 'undefined') {
        var messageText = $('#messageText').val();
        if (!messageText || messageText.trim().length === 0) {
            showToast('Please type a message first', 'warning');
            return;
        }
        ClarificationsManager.requestAndShowClarifications(
            ConversationManager.activeConversationId,
            messageText
        );
    }
});
```

**NO SETTINGS TOGGLE NEEDED**: Per the plan, this is a manual button (always available), not a setting

---

### Clarifications Modal Structure

**📍 NEW COMPONENT #2**: Create clarifications modal in `interface/interface.html`

**Location**: After doubt modals (after line ~1171, before LLM Context Menu at line 1173)

**Structure needed** (based on plan - 3 button modes):
```html
<!-- Clarifications Modal -->
<div id="clarifications-modal" class="modal fade" tabindex="-1" aria-hidden="true" style="z-index: 1070;">
    <div class="modal-dialog modal-lg">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title">
                    <i class="fa fa-question-circle"></i> Clarify Your Question
                </h5>
                <button type="button" class="close" data-dismiss="modal">
                    <span>&times;</span>
                </button>
            </div>
            <div class="modal-body">
                <!-- Loading state -->
                <div id="clarifications-loading" class="text-center" style="display: none;">
                    <div class="spinner-border text-primary" role="status">
                        <span class="sr-only">Loading...</span>
                    </div>
                    <p class="mt-2 text-muted">Analyzing your question...</p>
                </div>
                
                <!-- Error state -->
                <div id="clarifications-error" class="alert alert-warning" style="display: none;">
                    <i class="fa fa-exclamation-triangle"></i> 
                    <span id="clarifications-error-text"></span>
                </div>
                
                <!-- Questions container -->
                <div id="clarifications-questions" style="display: none;">
                    <p class="text-muted mb-3">Please answer these questions to help clarify your intent:</p>
                    <div id="clarifications-questions-list">
                        <!-- MCQ questions will be dynamically rendered here -->
                    </div>
                </div>
                
                <!-- No clarifications needed -->
                <div id="clarifications-not-needed" class="text-center text-muted" style="display: none;">
                    <i class="fa fa-check-circle" style="font-size: 3rem; opacity: 0.3;"></i>
                    <p class="mt-2">Your question is clear!</p>
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-dismiss="modal">
                    <i class="fa fa-times"></i> Cancel
                </button>
                <button type="button" id="clarifications-apply-btn" class="btn btn-primary" style="display: none;">
                    <i class="fa fa-check"></i> Apply
                </button>
                <button type="button" id="clarifications-apply-send-btn" class="btn btn-success" style="display: none;">
                    <i class="fa fa-paper-plane"></i> Apply & Send
                </button>
            </div>
        </div>
    </div>
</div>
```

**📍 NEW COMPONENT #3**: Create clarifications manager JS file `interface/clarifications-manager.js`

**Include in `interface/interface.html`** after doubt-manager.js (line ~2357):
```html
<script src="interface/doubt-manager.js"></script>
<script src="interface/clarifications-manager.js"></script>  <!-- ADD THIS -->
<script src="interface/temp-llm-manager.js"></script>
```

**Structure** (following pattern from DoubtManager and TempLLMManager):
```javascript
const ClarificationsManager = {
    currentConversationId: null,
    currentMessageText: null,
    clarificationQuestions: [],
    userAnswers: {},
    
    /**
     * Main entry point - request clarifications and show modal
     */
    requestAndShowClarifications: function(conversationId, messageText) {
        this.currentConversationId = conversationId;
        this.currentMessageText = messageText;
        this.userAnswers = {};
        
        // Show modal with loading state
        this.showModal('loading');
        
        // Call API
        this.fetchClarifications(conversationId, messageText)
            .then(data => this.handleClarificationsResponse(data))
            .catch(error => this.handleError(error));
    },
    
    /**
     * Call /clarify_intent API
     */
    fetchClarifications: function(conversationId, messageText) {
        return fetch(`/clarify_intent/${conversationId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                messageText: messageText,
                checkboxes: getOptions('chat-options', 'assistant')
            })
        })
        .then(response => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        });
    },
    
    /**
     * Handle API response
     */
    handleClarificationsResponse: function(data) {
        if (!data.needs_clarification || !data.questions || data.questions.length === 0) {
            this.showModal('not-needed');
            setTimeout(() => $('#clarifications-modal').modal('hide'), 1500);
            return;
        }
        
        this.clarificationQuestions = data.questions;
        this.renderQuestions(data.questions);
        this.showModal('questions');
    },
    
    /**
     * Render MCQ questions
     */
    renderQuestions: function(questions) {
        const container = $('#clarifications-questions-list');
        container.empty();
        
        questions.forEach((q, qIdx) => {
            const questionHtml = `
                <div class="mb-4">
                    <h6><strong>Q${qIdx + 1}:</strong> ${this.escapeHtml(q.prompt)}</h6>
                    <div class="ml-3">
                        ${q.options.map((opt, optIdx) => `
                            <div class="form-check">
                                <input class="form-check-input" type="radio" 
                                       name="clarification-q-${q.id}" 
                                       id="clarification-${q.id}-${opt.id}" 
                                       value="${opt.id}">
                                <label class="form-check-label" for="clarification-${q.id}-${opt.id}">
                                    ${this.escapeHtml(opt.label)}
                                </label>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
            container.append(questionHtml);
        });
    },
    
    /**
     * Show modal state (loading, questions, not-needed, error)
     */
    showModal: function(state) {
        $('#clarifications-modal').modal('show');
        $('#clarifications-loading').hide();
        $('#clarifications-questions').hide();
        $('#clarifications-not-needed').hide();
        $('#clarifications-error').hide();
        $('#clarifications-apply-btn').hide();
        $('#clarifications-apply-send-btn').hide();
        
        if (state === 'loading') {
            $('#clarifications-loading').show();
        } else if (state === 'questions') {
            $('#clarifications-questions').show();
            $('#clarifications-apply-btn').show();
            $('#clarifications-apply-send-btn').show();
        } else if (state === 'not-needed') {
            $('#clarifications-not-needed').show();
        } else if (state === 'error') {
            $('#clarifications-error').show();
        }
    },
    
    /**
     * Collect answers from form
     */
    collectAnswers: function() {
        const answers = {};
        this.clarificationQuestions.forEach(q => {
            const selected = $(`input[name="clarification-q-${q.id}"]:checked`).val();
            if (selected) {
                const option = q.options.find(o => o.id === selected);
                answers[q.id] = {
                    question: q.prompt,
                    answer: option ? option.label : selected
                };
            }
        });
        return answers;
    },
    
    /**
     * Build append text from answers
     */
    buildAppendText: function(answers) {
        if (Object.keys(answers).length === 0) return '';
        
        let text = '\n\n[Clarifications]\n';
        Object.values(answers).forEach((qa, idx) => {
            text += `- Q${idx + 1}: ${qa.question}\n`;
            text += `  A: ${qa.answer}\n`;
        });
        return text;
    },
    
    /**
     * Apply clarifications to messageText
     */
    applyToMessageText: function() {
        const answers = this.collectAnswers();
        const appendText = this.buildAppendText(answers);
        
        if (appendText) {
            const currentText = $('#messageText').val();
            $('#messageText').val(currentText + appendText);
            $('#messageText').trigger('input'); // Trigger auto-resize
        }
        
        $('#clarifications-modal').modal('hide');
    },
    
    /**
     * Apply and send immediately
     */
    applyAndSend: function() {
        this.applyToMessageText();
        // Trigger send after modal closes
        setTimeout(() => {
            if (typeof sendMessageCallback === 'function') {
                sendMessageCallback();
            }
        }, 300);
    },
    
    /**
     * Handle error
     */
    handleError: function(error) {
        console.error('Clarifications error:', error);
        $('#clarifications-error-text').text('Failed to get clarifications. You can proceed without them.');
        this.showModal('error');
        setTimeout(() => $('#clarifications-modal').modal('hide'), 3000);
    },
    
    /**
     * Escape HTML
     */
    escapeHtml: function(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },
    
    /**
     * Setup event handlers (call once on page load)
     */
    setupEventHandlers: function() {
        $('#clarifications-apply-btn').on('click', () => this.applyToMessageText());
        $('#clarifications-apply-send-btn').on('click', () => this.applyAndSend());
    }
};

// Initialize on page load
$(document).ready(function() {
    ClarificationsManager.setupEventHandlers();
});
```

---

### Backend Implementation for Clarifications

**📍 NEW ENDPOINT**: `POST /get_clarifications/<conversation_id>`

**File**: `endpoints/conversations.py`

**Location**: After `send_message` endpoint

**Structure**:
```python
@conversations_bp.route("/get_clarifications/<conversation_id>", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def get_clarifications(conversation_id: str):
    """
    Analyze user message and generate clarification questions if needed.
    
    Request JSON:
    - messageText: str
    - checkboxes: dict (optional)
    
    Response JSON:
    - needs_clarification: bool
    - questions: list[dict] (if needs_clarification=true)
        - question: str
        - options: list[str]  # MCQ options
    """
    pass
```

**📍 NEW METHOD**: `Conversation.get_clarifications()`

**File**: `Conversation.py`

**Location**: Near `clear_doubt()` method (after line ~4217)

**Purpose**:
- Analyze user query
- Determine if clarification is needed (check for ambiguity, vague terms, multiple interpretations)
- Generate 1-3 MCQ questions with 2-4 options each
- Return structured data

**Prompt structure**:
```
Analyze this user query: "{query}"

Determine if clarification is needed. The query needs clarification if:
- It's ambiguous or has multiple interpretations
- Key details are missing
- The intent or desired output format is unclear

If clarification is needed, generate 1-3 multiple choice questions (max 3) to clarify the user's intent. Each question should have 2-4 options.

Return JSON:
{
    "needs_clarification": true/false,
    "questions": [
        {
            "question": "What aspect are you most interested in?",
            "options": ["Technical details", "High-level overview", "Practical examples", "Comparison with alternatives"]
        }
    ]
}
```

---

## Feature 2: Automatic Doubt Generation ("Auto Takeaways")

### Goals (Based on Plan)
- After `/send_message` streaming completes (server-side background task)
- Automatically generate "Auto takeaways" - short, crisp summary
- **No preamble**, key takeaways (3-6 bullets), actionables (0-5), important facts
- Target: 120-250 words
- Save as root doubt with `doubt_text = "Auto takeaways"` (for dedup)
- **No schema change initially** - use doubt_text for identification
- **Persist silently** - do NOT auto-open doubts modal
- Skip if persist_or_not is disabled

---

### Current Reply Completion Flow

#### 1. **Streaming Response Completion** (`interface/common-chat.js`)
**Function**: `renderStreamingResponse()` - `done` branch (lines 960-1077)

**Current Flow**:
```javascript
if (done) {
    // 1. Reset UI state
    $('#messageText').prop('working', false);
    $('#stopResponseButton').hide();
    $('#sendMessageButton').show();
    currentStreamingController = null;
    
    // 2. Hide status div
    var statusDiv = card.find('.status-div');
    statusDiv.hide();
    
    // 3. Final rendering
    renderInnerContentAsMarkdown(last_elem_to_render, ...);
    
    // 4. Set up voting
    initialiseVoteBank(card, answer, ...);
    
    // 5. Run mermaid diagrams
    mermaid.run({...});
    
    // 6. Add scroll-to-top button
    window.addScrollToTopButton(card, ...);
    
    // 7. Setup event handlers
    setupStreamingCardEventHandlers(card, response_message_id);
    
    // 8. Call next question suggestions
    setTimeout(function() {
        renderNextQuestionSuggestions(conversationId);
    }, 500);
    
    return;
}
```

**📍 NO FRONTEND TRIGGER NEEDED**: Per the plan, auto-doubt generation happens **server-side** in the background task

#### 2. **Backend `/send_message` Endpoint** (`endpoints/conversations.py`)
**Route**: `POST /send_message/<conversation_id>` (lines 877-931)

**Current structure**:
```python
@conversations_bp.route("/send_message/<conversation_id>", methods=["POST"])
def send_message(conversation_id: str):
    # ... setup ...
    
    @copy_current_request_context
    def generate_response():
        for chunk in conversation(query, user_details):
            response_queue.put(chunk)
        response_queue.put("<--END-->")
        conversation.clear_cancellation()
        # 📍 EDIT POINT #9: ADD AUTO-DOUBT GENERATION HERE
    
    _future = get_async_future(generate_response)
    
    # ... streaming response ...
```

**📍 EDIT POINT #9**: Add auto-doubt generation **after streaming completes** in `generate_response()`
- Location: After `conversation.clear_cancellation()` (line ~916)
- Add async/background task to:
  1. Check if `persist_or_not` was enabled in query
  2. Get last assistant message from `conversation.get_field("messages")`
  3. Check if auto-doubt already exists (dedup)
  4. Generate takeaways using LLM
  5. Save via `database.doubts.add_doubt(...)`
- Wrap in try/except to prevent failures from affecting streaming
- Use `get_async_future()` to run non-blocking

---

### Automatic Doubt Implementation (Server-Side)

**📍 NO NEW ENDPOINT NEEDED**: Auto-doubt generation happens inline in `/send_message` background task

**📍 NEW HELPER FUNCTION**: Add in `endpoints/conversations.py` (after send_message route)

**Structure**:
```python
def _generate_auto_takeaways_for_message(
    conversation: Conversation,
    conversation_id: str,
    user_email: str,
    users_dir: str,
    logger: logging.Logger
) -> None:
    """
    Generate and persist auto-takeaways for the last assistant message.
    
    This runs asynchronously after streaming completes.
    Failures are logged but don't affect the user's experience.
    
    Process:
    1. Get last assistant message from conversation.get_field("messages")
    2. Check for existing auto-doubt (dedup via doubt_text == "Auto takeaways")
    3. Generate takeaways using LLM (non-streaming)
    4. Persist via database.doubts.add_doubt()
    """
    try:
        # Get messages
        messages = conversation.get_field("messages")
        if not messages or len(messages) == 0:
            logger.info(f"No messages found for auto-doubt generation in {conversation_id}")
            return
        
        # Find last assistant message
        last_assistant_msg = None
        for msg in reversed(messages):
            if msg.get("sender") == "model":
                last_assistant_msg = msg
                break
        
        if not last_assistant_msg:
            logger.info(f"No assistant message found for auto-doubt in {conversation_id}")
            return
        
        message_id = last_assistant_msg.get("message_id")
        answer_text = last_assistant_msg.get("text", "")
        
        if not message_id or not answer_text:
            logger.warning(f"Invalid message data for auto-doubt in {conversation_id}")
            return
        
        # Check for existing auto-doubt (dedup)
        from database.doubts import get_doubts_for_message
        existing_doubts = get_doubts_for_message(
            conversation_id=conversation_id,
            message_id=message_id,
            user_email=user_email,
            users_dir=users_dir,
            logger=logger
        )
        
        # Check if auto-doubt already exists
        for doubt in existing_doubts:
            if doubt.get("doubt_text") == "Auto takeaways":
                logger.info(f"Auto-doubt already exists for message {message_id}")
                return
        
        # Generate takeaways
        takeaways_text = _generate_takeaways_text(conversation, answer_text)
        
        if not takeaways_text or len(takeaways_text.strip()) == 0:
            logger.warning(f"Failed to generate takeaways for message {message_id}")
            return
        
        # Persist as doubt
        from database.doubts import add_doubt
        doubt_id = add_doubt(
            conversation_id=conversation_id,
            user_email=user_email,
            message_id=message_id,
            doubt_text="Auto takeaways",
            doubt_answer=takeaways_text,
            parent_doubt_id=None,
            users_dir=users_dir,
            logger=logger
        )
        
        logger.info(f"Created auto-doubt {doubt_id} for message {message_id}")
        
    except Exception as e:
        logger.error(f"Error generating auto-doubt: {e}", exc_info=True)
        # Don't raise - failures should be silent


def _generate_takeaways_text(conversation: Conversation, answer_text: str) -> str:
    """
    Generate takeaways text using LLM.
    
    Returns crisp summary with:
    - Key takeaways (3-6 bullets)
    - Actionables (0-5 bullets)
    - Important facts
    
    Target: 120-250 words, no preamble.
    """
    from call_llm import CallLLm
    
    prompt = f"""Create a concise summary of the following answer for quick reference.

Original Answer:
{answer_text[:4000]}  # Truncate very long answers

Create a summary with these sections:
1. **Key Takeaways**: 3-6 bullet points of the most important information
2. **Actionables**: 0-5 specific actions the user can take (only if applicable)
3. **Important Facts**: Any critical details to remember

Requirements:
- NO preamble or introduction
- Start directly with content
- Use bullet points
- Be crisp and direct
- Target 120-250 words
- Stay on topic
- Use markdown formatting

Generate the summary now:"""
    
    try:
        api_keys = conversation.get_api_keys()
        # Use cheap/fast model for summaries
        from base import VERY_CHEAP_LLM
        llm = CallLLm(api_keys, model_name=VERY_CHEAP_LLM[0], use_gpt4=False, use_16k=False)
        
        takeaways = llm(prompt, images=[], temperature=0.3, stream=False, max_tokens=500)
        return takeaways
        
    except Exception as e:
        logger.error(f"Error calling LLM for takeaways: {e}")
        return ""
```

**Call from `generate_response()`** in `/send_message` (line ~916):
```python
@copy_current_request_context
def generate_response():
    for chunk in conversation(query, user_details):
        response_queue.put(chunk)
    response_queue.put("<--END-->")
    conversation.clear_cancellation()
    
    # Generate auto-doubt in background (don't block)
    if query.get("checkboxes", {}).get("persist_or_not", True):
        get_async_future(
            _generate_auto_takeaways_for_message,
            conversation,
            conversation_id,
            email,
            state.users_dir,
            logger
        )
```

**File**: `Conversation.py`

**Location**: Near `clear_doubt()` method

**Purpose**:
- Get the target message (the assistant's answer)
- Generate a crisp summary with:
  - Key takeaways (bullet points)
  - Actionable items
  - Important facts to remember
  - No preamble or off-topic content
- Return the summary text

**Prompt structure**:
```
You are creating a quick reference summary of the following answer.

Original Answer:
{answer_text}

Create a concise summary that includes:
1. **Key Takeaways**: 3-5 bullet points of the most important points
2. **Actionable Items**: Specific actions the user can take (if applicable)
3. **Important Facts**: Critical information to remember

Requirements:
- Be crisp and direct, no preamble
- Stay on topic, ignore tangential content
- Use bullet points for clarity
- Keep it short (200-300 words max)
- Focus on what the user needs to know and do

Format your response in markdown with clear sections.
```

**Storage** (Per Plan - NO SCHEMA CHANGE INITIALLY):
- Use existing `DoubtsClearing` table AS-IS
- **Identification via doubt_text**: Use `doubt_text = "Auto takeaways"` as stable marker
- **Deduplication**: Check if root doubt with `doubt_text == "Auto takeaways"` exists before creating
- Fields:
  - `doubt_text`: **"Auto takeaways"** (exact string for dedup and identification)
  - `doubt_answer`: The generated takeaways markdown
  - `is_root_doubt`: True
  - `parent_doubt_id`: None
  
**📍 NO DATABASE MIGRATION NEEDED** (initially)

**Future enhancement**: Could add `is_automatic` column later for cleaner querying, but for MVP we use `doubt_text` matching

---

### Automatic Doubt in UI

**Display considerations**:
1. **Show in doubt list?** Yes, with special styling/badge (different icon)
2. **Show automatically?** NO - per plan, persist silently (user opens "Show doubts" to see it)
3. **Allow follow-up doubts?** Yes, same as regular doubts
4. **Identification**: Check `doubt_text === "Auto takeaways"` to detect auto-doubts

**📍 EDIT POINT #10** (Optional Enhancement): Update doubt rendering in `interface/doubt-manager.js`

**Function**: `renderDoubtsOverview()` (starting around line 62)

**Changes** (optional styling enhancement):
- Check if `doubt.doubt_text === "Auto takeaways"` to identify auto-doubts
- Add special styling: different icon (📝 instead of 💭), badge, or highlight
- Optionally sort auto-doubts to top

**Example enhancement**:
```javascript
renderDoubtsOverview: function(doubts) {
    const content = $('#doubts-overview-content');
    content.empty();
    
    // Separate auto-doubts from manual doubts
    const autoDoubts = doubts.filter(d => d.doubt_text === "Auto takeaways");
    const manualDoubts = doubts.filter(d => d.doubt_text !== "Auto takeaways");
    
    // Render auto-doubts first with special styling
    if (autoDoubts.length > 0) {
        content.append('<h6 class="text-muted mt-2 mb-3">📝 Quick Summary</h6>');
        autoDoubts.forEach(doubt => {
            this.renderDoubtCard(doubt, true); // true = is_auto
        });
    }
    
    // Then render manual doubts
    if (manualDoubts.length > 0) {
        if (autoDoubts.length > 0) {
            content.append('<hr class="my-3">');
        }
        content.append('<h6 class="text-muted mt-2 mb-3">💭 Your Doubts</h6>');
        manualDoubts.forEach(doubt => {
            this.renderDoubtCard(doubt, false); // false = not_auto
        });
    }
},

renderDoubtCard: function(doubt, is_auto) {
    // Add badge or styling if is_auto
    const badge = is_auto ? '<span class="badge badge-info ml-2">Auto</span>' : '';
    // ... rest of rendering ...
}
```

**Note**: This UI enhancement is **optional**. The existing doubt rendering will work fine - auto-doubts will just appear as regular doubts with text "Auto takeaways".

---

## Summary of Edit Points (Aligned with Plan)

### For Feature 1: Clarifications API (Manual Trigger)

**Frontend**:
1. **New Component #1**: `interface/interface.html` line ~331 - Add "Clarify" button near send/stop buttons
2. **New Component #2**: `interface/interface.html` line ~1171 - Add clarifications modal HTML
3. **New Component #3**: Create `interface/clarifications-manager.js` - Manager for clarifications flow
4. **Script Include**: `interface/interface.html` line ~2357 - Include clarifications-manager.js after doubt-manager.js
5. **Button Handler**: `interface/chat.js` line ~79 - Bind click handler for clarifyButton

**Backend**:
6. **New Endpoint**: `endpoints/conversations.py` line ~932 - Add `POST /clarify_intent/<conversation_id>`
7. **Prompt Logic**: In clarify_intent endpoint - LLM call with strict JSON output, fail-open behavior
8. **Validation**: Request validation (messageText required), response capping (max 3 questions, 2-5 options)

**NO Settings Toggle**: Manual button (always available), not a configurable setting

### For Feature 2: Automatic Doubt Generation (Server-Side)

**Backend Only** (No Frontend Changes):
9. **Edit Point #9**: `endpoints/conversations.py` line ~916 - Add auto-doubt generation in `generate_response()` after streaming completes
10. **New Helper**: `endpoints/conversations.py` - Add `_generate_auto_takeaways_for_message()` function
11. **New Helper**: `endpoints/conversations.py` - Add `_generate_takeaways_text()` function for LLM call
12. **Deduplication**: Check for existing doubt with `doubt_text == "Auto takeaways"` before creating
13. **Persistence**: Use `database.doubts.add_doubt()` with `doubt_text="Auto takeaways"`, `parent_doubt_id=None`

**Optional Frontend Enhancement**:
14. **Edit Point #10** (optional): `interface/doubt-manager.js` - Add special styling for auto-doubts in `renderDoubtsOverview()`

**NO Database Migration**: Use `doubt_text` matching for identification (no schema change needed)

---

## Additional Considerations (From Plan)

### Clarifications API
- **Model**: Use cheap/fast model (same as "next question suggestions")
- **Output**: Strict JSON parsing with bounded enforcement (≤3 questions, 2-5 options each)
- **Timeout**: 5-10 second timeout on API call
- **Fail-Open**: NEVER block user - if API fails, show error toast and proceed
- **Rate Limiting**: 30 requests/minute via Flask-Limiter
- **Validation**: Empty messageText returns 400; LLM failures return `{needs_clarification: false, questions: []}`

### Auto-Doubt Generation
- **Model**: Use `VERY_CHEAP_LLM[0]` for cost efficiency
- **Target Length**: 120-250 words, strict no-preamble format
- **Timing**: Runs in background AFTER streaming completes (non-blocking)
- **Dedup**: Check for existing "Auto takeaways" doubt before creating
- **Gating**: Only run if `persist_or_not` is enabled in query
- **Error Isolation**: Failures logged but NEVER affect user's streaming experience
- **Message Identification**: Get last assistant message from `conversation.get_field("messages")` with `sender == "model"`

### User Experience
- **Clarifications**: Explicit user action (click button), 3 modal actions (Cancel, Apply, Apply & Send)
- **Auto-Doubt**: Silent persistence, user discovers via "Show doubts" button
- **No Auto-Open**: Auto-doubt never opens modal automatically
- **Follow-ups**: Both features work with existing doubt threading (parent_doubt_id)

---

## Dependencies and Related Files

### Key Files to Review:
- `endpoints/conversations.py` - Send message endpoint
- `endpoints/doubts.py` - Doubt clearing endpoints
- `database/doubts.py` - Doubt database operations
- `Conversation.py` - Main conversation logic
- `interface/common-chat.js` - Chat UI and streaming
- `interface/chat.js` - Settings management
- `interface/doubt-manager.js` - Doubt UI management
- `interface/interface.html` - Modal structures

### Similar Patterns to Follow:
- **Doubt clearing flow** (`clear_doubt` endpoint + UI) - for automatic doubt
- **Temporary LLM actions** (`TempLLMManager`) - for clarifications LLM call pattern
- **Settings management** (persist_or_not, use_memory_pad) - for clarifications toggle
- **Modal structure** (doubt modals, hint modal, solution modal) - for clarifications modal

---

## Next Steps for Implementation (Following Plan Milestones)

### Milestone A — Clarifications (Server)
1. **A1**: Define `/clarify_intent` endpoint contract (request/response JSON, validation rules)
2. **A2**: Implement endpoint in `endpoints/conversations.py` with:
   - Auth/permission checks (login_required)
   - LLM call with strict JSON parsing
   - Bounded output (≤3 questions, 2-5 options)
   - Fail-open behavior
3. **A3**: Add docstrings explaining purpose, inputs, outputs, failure behavior

### Milestone B — Clarifications (UI, Manual Trigger)
4. **B1**: Add Clarify button in `interface/interface.html` near send controls
5. **B2**: Add clarifications modal HTML with loading/questions/error states
6. **B3**: Create `interface/clarifications-manager.js` with:
   - `requestAndShowClarifications()`
   - `fetchClarifications()`
   - `renderQuestions()`
   - `buildAppendText()`
   - `applyToMessageText()` and `applyAndSend()`
7. **B4**: Include script in interface.html and bind button handler

### Milestone C — Auto-Doubt (Server, Persisted + Silent)
8. **C1**: Implement `_generate_takeaways_text()` helper with consistent prompt
9. **C2**: Implement `_generate_auto_takeaways_for_message()` helper with:
   - Message retrieval from `conversation.get_field("messages")`
   - Dedup check via `get_doubts_for_message()`
   - LLM call and persistence
10. **C3**: Hook into `/send_message` completion via `get_async_future()` after streaming
11. **C3**: Add error isolation (try/except, logging only)

### Milestone D — Docs + Verification
12. **D1**: Update `endpoints/external_api.md` with `/clarify_intent` and auto-doubt behavior note
13. **D2**: Create manual test checklist (see below)

---

## Manual Test Checklist (From Plan)

### Clarifications Feature:
**Happy Path**:
- [ ] 1. Type a vague question (e.g., "explain AI")
- [ ] 2. Click "Clarify" button → modal opens with loading spinner
- [ ] 3. Modal shows 1-3 MCQ questions with 2-5 options each
- [ ] 4. Select answers for all questions
- [ ] 5. Click "Apply" → modal closes, #messageText contains appended clarifications in format `[Clarifications]\n- Q: ... A: ...`
- [ ] 6. Click "Send" → user message card shows original + clarifications
- [ ] 7. Server receives full messageText with clarifications

**Apply & Send**:
- [ ] 8. Type question, click "Clarify", answer questions
- [ ] 9. Click "Apply & Send" → clarifications applied AND message sent immediately

**No Clarifications Needed**:
- [ ] 10. Type very specific question (e.g., "What is 2+2?")
- [ ] 11. Click "Clarify" → modal shows "Your question is clear!" and auto-closes

**Error Handling**:
- [ ] 12. Network failure or API error → modal shows error message, can close and proceed
- [ ] 13. Empty messageText → clicking "Clarify" shows warning toast, modal doesn't open

### Automatic Doubt Feature:
**Happy Path**:
- [ ] 1. Send a message with `persist_or_not` enabled (default)
- [ ] 2. Wait for streaming response to complete
- [ ] 3. After ~2-5 seconds (background processing), check backend logs for "Created auto-doubt"
- [ ] 4. Click "Show doubts" button on assistant message
- [ ] 5. Doubts modal opens showing "Auto takeaways" doubt with crisp summary
- [ ] 6. Summary has: Key Takeaways (bullets), Actionables (bullets), Important Facts
- [ ] 7. Summary is 120-250 words, NO preamble

**Deduplication**:
- [ ] 8. Refresh page and click "Show doubts" on same message
- [ ] 9. Only ONE "Auto takeaways" doubt exists (no duplicates)

**Persist Gating**:
- [ ] 10. Send message with `persist_or_not` disabled
- [ ] 11. No auto-doubt generated (check logs)

**Error Isolation**:
- [ ] 12. Simulate LLM failure (disconnect, bad key)
- [ ] 13. Streaming still works, user experience unaffected
- [ ] 14. Error logged but not shown to user

**Follow-ups**:
- [ ] 15. Open "Auto takeaways" doubt, ask a follow-up question
- [ ] 16. Follow-up persists with `parent_doubt_id` pointing to auto-doubt

---

## Quick Reference: Key Code Locations

### Files to Create (New):
1. `interface/clarifications-manager.js` - Clarifications UI manager (similar to doubt-manager.js)

### Files to Modify:

#### `interface/interface.html`:
- **Line ~331**: Add Clarify button after stopResponseButton
- **Line ~1171**: Add clarifications modal HTML
- **Line ~2357**: Include `<script src="interface/clarifications-manager.js"></script>`

#### `interface/chat.js`:
- **Line ~79**: Bind clarifyButton click handler

#### `endpoints/conversations.py`:
- **Line ~932**: Add `POST /clarify_intent/<conversation_id>` endpoint
- **Line ~916**: Modify `generate_response()` to call auto-doubt generation after streaming
- **After line ~932**: Add helper functions:
  - `_generate_auto_takeaways_for_message()`
  - `_generate_takeaways_text()`

#### `endpoints/external_api.md`:
- Add documentation for `/clarify_intent` endpoint
- Note about "Auto takeaways" appearing in doubts

#### `interface/doubt-manager.js` (Optional):
- **Line ~62**: Enhance `renderDoubtsOverview()` to style auto-doubts differently

### Key Functions/Methods:
- `ClarificationsManager.requestAndShowClarifications()` - Entry point for clarifications
- `ClarificationsManager.fetchClarifications()` - API call
- `ClarificationsManager.applyToMessageText()` - Append to #messageText
- `_generate_auto_takeaways_for_message()` - Auto-doubt generation
- `_generate_takeaways_text()` - LLM call for takeaways

### API Endpoints:
- **New**: `POST /clarify_intent/<conversation_id>` - Get clarification questions
- **Existing**: `POST /send_message/<conversation_id>` - Modified to trigger auto-doubt in background
- **Existing**: `GET /get_doubts/<conversation_id>/<message_id>` - Used to fetch auto-doubts

### Database:
- **NO CHANGES** - Use existing `DoubtsClearing` table
- **Dedup Key**: `doubt_text = "Auto takeaways"`

---

## Implementation Priority

### Must-Have (MVP):
1. Clarifications button + modal + manager.js
2. `/clarify_intent` endpoint with fail-open behavior
3. Auto-doubt generation in background after streaming
4. Deduplication logic for auto-doubts

### Nice-to-Have (Post-MVP):
1. Special styling for auto-doubts in UI
2. `is_automatic` column in database (cleaner than text matching)
3. Settings toggle to disable auto-doubts
4. Analytics/logging for clarifications usage

### Can Skip Initially:
1. Clarifications history/caching
2. Custom clarification templates per domain
3. Auto-doubt regeneration/editing
4. Clarifications A/B testing

---


