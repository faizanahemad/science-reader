# Multi-Model Response Tabs

## Overview

The Multi-Model Response Tabs feature provides a tabbed interface for displaying responses when multiple LLM models are queried simultaneously, or when a single model response is long enough to generate a TLDR summary. This improves readability by organizing multiple model outputs or lengthy responses into a clean, navigable tab structure.

## Table of Contents

1. [Feature Purpose](#feature-purpose)
2. [Architecture Overview](#architecture-overview)
3. [Backend Implementation](#backend-implementation)
4. [Frontend Implementation](#frontend-implementation)
5. [Data Flow](#data-flow)
6. [Key Components](#key-components)
7. [TLDR Generation](#tldr-generation)
8. [Tab Rendering Logic](#tab-rendering-logic)
9. [Reload Handling](#reload-handling)
10. [CSS and Styling](#css-and-styling)
11. [Implementation Notes](#implementation-notes)
12. [Files Modified](#files-modified)

---

## Feature Purpose

### Goals

1. **Multi-Model Comparison**: When users select multiple models in settings, each model's response is displayed in its own tab for easy comparison.
2. **TLDR for Long Responses**: When a response exceeds ~1000 words, a separate TLDR summary is generated and displayed in its own tab.
3. **Clean UI**: Avoid cluttering the chat view with collapsible `<details>` blocks by presenting them as organized tabs.
4. **Persistence**: Tab content must survive page reloads and maintain state.

### When Tabs Are Shown

Tabs are rendered when ANY of these conditions are met:
- Multiple models responded (e.g., user selected 2+ models in settings)
- A single model response has an associated TLDR summary
- Preserved TLDR content exists from a previous render (reload scenario)

---

## Architecture Overview

### Backend (Python)

- Multi-model responses stream from `common.py:stream_multiple_models(...)`.
- Each model response chunk is wrapped in a `<details>` block whose `<summary>` is `Response from {model}`.
- Long single-model answers may append TLDR markup from `Conversation.py`:
  - `---` separator
  - `<answer_tldr> ... </answer_tldr>` wrapper containing a `<details>` summary.
- On persistence, `Conversation.persist_current_turn()` can inject the `<answer_tldr>` block into the stored assistant `message.text` so TLDR survives reload/history (`PERSIST_TLDR_IN_SAVED_ANSWER_TEXT=true`).

### Transport

- The `/send_message/<conversation_id>` endpoint streams newline-delimited JSON chunks.
- The `text` field contains HTML-ish tags (`<details>`, `<answer_tldr>`, `---`) embedded in markdown.

### Frontend (JavaScript)

- `interface/common-chat.js` accumulates streaming text and repeatedly calls `renderInnerContentAsMarkdown(...)`.
- `interface/common.js:renderInnerContentAsMarkdown(...)`:
  - strips `<answer>` wrappers
  - converts `<answer_tldr>` tags into `<div data-answer-tldr="true">...` so TLDR is discoverable
  - renders markdown to HTML
  - calls `applyModelResponseTabs(...)`
  - updates the Table of Contents

### Tab UI Builder

- `interface/common.js:applyModelResponseTabs(...)`:
  - scans for model `<details>` blocks (`summary` starts with `Response from`)
  - scans for TLDR sources (`[data-answer-tldr]`, or fallback TLDR `<details>`)
  - builds a Bootstrap `.nav-tabs` + `.tab-content` UI
  - clones content into tab panes and hides source render containers so the answer does not appear twice
  - preserves TLDR content when rebuilding tabs on reload/showMore

---

## Backend Implementation

### Multi-Model Streaming (`common.py`)

Location: `common.py:291-500+`

The `stream_multiple_models()` function handles parallel execution of multiple LLM models:

```python
def stream_multiple_models(
    keys,
    model_names,
    prompts,
    images=[],
    temperature=0.7,
    max_tokens=None,
    system=None,
    collapsible_headers=True,
    header_template: Union[str, List[str]] = "Response from {model}",
):
```

**Key Behavior:**
1. Runs multiple models in parallel using threads
2. Uses a message queue for coordinated streaming
3. Yields responses one model at a time (sequential presentation)
4. Wraps each model's output in a collapsible `<details>` block with header "Response from {model}"

**Output Format:**
```html
<details open>
<summary>Response from claude-3-opus</summary>
...model response content...
</details>

<details>
<summary>Response from gpt-4</summary>
...model response content...
</details>
```

### TLDR Generation (`Conversation.py`)

Location: `Conversation.py:6815-6880`

When a response exceeds the word count threshold (~1000 words), a TLDR summary is automatically generated:

```python
# Condition: Response word count > threshold
if answer_word_count > ANSWER_WORD_COUNT_THRESHOLD_FOR_TLDR:
    answer += "<answer_tldr>\n"
    
    # Generate TLDR using a fast/cheap model
    tldr_model = self.get_model_override("tldr_model", CHEAP_LONG_CONTEXT_LLM[0])
    tldr_llm = CallLLm(self.get_api_keys(), model_name=tldr_model, ...)
    
    # Wrap in collapsible
    tldr_wrapped = collapsible_wrapper(
        tldr_stream,
        header="📝 TLDR Summary (Quick Read)",
        show_initially=False,
        add_close_button=True,
    )
    
    answer += tldr_wrapped
    answer += "\n</answer_tldr>\n"
```

**Output Format:**
```html
<answer_tldr>
<details>
<summary>📝 TLDR Summary (Quick Read)</summary>
...summary content...
</details>
</answer_tldr>
```

#### TLDR Persistence (History + Reload)

By default, TLDR is also persisted into the stored assistant message text so it survives history reloads.

- Env flag: `PERSIST_TLDR_IN_SAVED_ANSWER_TEXT` (default: `true`)
- Code path: `Conversation.persist_current_turn()` injects an `<answer_tldr>...</answer_tldr>` block into `message.text` if the response has `answer_tldr` but the tag is not already present.

This matters because the UI re-renders history from `message.text` and does not reliably reconstruct TLDR from metadata alone.

---

## Frontend Implementation

### Main Rendering Pipeline

Location: `interface/common.js:2165-2760`

The `renderInnerContentAsMarkdown()` function is the main entry point for rendering assistant messages:

```javascript
function renderInnerContentAsMarkdown(jqelem, callback, continuous, html, immediate_callback) {
    // 1. Mark element as tabs root
    elem_to_render_in.attr('data-model-tabs-root', 'true');
    
    // 2. Convert <answer_tldr> tags to data attributes
    html = html.replace(/<\s*answer_tldr\s*>/gi, '<div data-answer-tldr="true">')
               .replace(/<\s*\/\s*answer_tldr\s*>/gi, '</div>');
    
    // 3. Convert markdown to HTML
    // 4. Write to DOM
    
    // 5. Apply model response tabs
    try {
        applyModelResponseTabs(elem_to_render_in);
    } catch (e) {
        console.warn('Model tabs render failed:', e);
    }
}
```

### Tab Construction Function

Location: `interface/common.js` (`applyModelResponseTabs()`)

The `applyModelResponseTabs()` function is the core of the tabbed interface.

Important implementation note (Feb 2026):
- The function scopes to the message body container (`.chat-card-body`) so it can hide *all* sibling render containers.
- This is required to make single-model+TLDR behave like multi-model (prevent duplicate main answer showing above/below tabs).

```javascript
function applyModelResponseTabs(elem_to_render_in) {
    // 1. Find the root element (scope to the message body)
    var $root = elem_to_render_in ? $(elem_to_render_in) : $(document);
    var $chatBody = $root.closest('.chat-card-body');
    if ($chatBody.length > 0) {
        $root = $chatBody;
    }
    
    // 2. Generate unique ID for tab group
    var rootId = $root.attr('id') || $root.attr('data-model-tabs-id');
    if (!rootId) {
        rootId = 'model-tabs-root-' + Date.now().toString(36) + Math.random().toString(36).substr(2, 6);
        $root.attr('data-model-tabs-id', rootId);
    }
    
    // 3. Find existing tab container (for updates/reloads)
    // Prefer direct child of `.chat-card-body`.
    var $existingContainer = $root.children('.model-tabs-container').first();
    if ($existingContainer.length === 0) {
        $existingContainer = $root.find('.model-tabs-container').first();
    }
    
    // 4. Preserve state from existing container
    var activeTabKey = $existingContainer.find('.nav-link.active').attr('data-tab-key') || '';
    var scrollTop = $existingContainer.find('.tab-content').scrollTop();
    
    // 5. Scan for model response blocks and TLDR
    var $detailsBlocks = $root.find('details').not('.section-details').not('.model-tabs-container details');
    var $tldrWrapper = $root.find('[data-answer-tldr]').first();
    
    // ... continue with tab building logic
}
```

---

## Data Flow

### Initial Response (Streaming)

```
1. User sends message with multiple models selected
2. Backend streams response chunks:
   - Model 1 response wrapped in <details>Response from model1</details>
   - Model 2 response wrapped in <details>Response from model2</details>
   - TLDR (if long) wrapped in <answer_tldr><details>...</details></answer_tldr>
3. Frontend receives chunks in common-chat.js
4. renderInnerContentAsMarkdown() is called (continuous=true during streaming)
5. applyModelResponseTabs() transforms <details> blocks into Bootstrap tabs
6. User sees tabbed interface with model tabs + optional TLDR tab
```

### Page Reload Flow

```
1. User reloads page
2. ChatManager.renderMessages() loads messages from server
3. For each message:
   a. renderInnerContentAsMarkdown() is called (continuous=false)
   b. applyModelResponseTabs() runs
   c. PROBLEM: Original <details> blocks are in DOM
   d. PROBLEM: After first render, <answer_tldr> was removed from DOM
   e. SOLUTION: Preserve TLDR content from existing tab container before rebuild
```

---

## Key Components

### DOM Elements

| Element | Purpose |
|---------|---------|
| `.model-tabs-container` | Main container wrapping the tab UI |
| `.nav.nav-tabs` | Bootstrap tab navigation |
| `.nav-link` | Individual tab button |
| `.tab-content` | Container for all tab panes |
| `.tab-pane` | Individual tab content pane |
| `.model-tab-body` | Content wrapper inside each pane |
| `[data-answer-tldr]` | Wrapper div for TLDR content |
| `[data-model-tabs-hidden]` | Attribute marking hidden original `<details>` |
| `[data-model-tabs-id]` | Unique ID for the tab group root |
| `[data-tab-key]` | Identifier for each tab (used to restore active tab) |

### Tab Types

| Type | Key Pattern | Label | Source |
|------|-------------|-------|--------|
| `model` | `model-{idx}-{name}` | Model name or "Main" | `<details>` with "Response from" summary |
| `tldr` | `tldr` | "TLDR" | `[data-answer-tldr]` div or preserved content |
| `main` | `main` | "Main" | Main content when only TLDR exists |

### Key JavaScript Variables

| Variable | Purpose |
|----------|---------|
| `hasTldrWrapper` | True if `[data-answer-tldr]` element exists with meaningful content (>10 chars) |
| `preservedTldrContent` | Cloned TLDR content from existing tab container (for reload scenarios) |
| `tldrContentClone` | The validated, cloned TLDR content to put in the tab |
| `actuallyHasTldrContent` | **Final validated flag** - true only if TLDR has meaningful content |
| `shouldBuildTabs` | Whether to build the tab UI (depends on `actuallyHasTldrContent` for TLDR cases) |
| `modelDetails` | Array of model response `<details>` blocks |
| `tldrDetails` | Array of TLDR `<details>` blocks (found by "tldr" in summary) |

---

## Tab Rendering Logic

### Decision Tree (Updated Feb 2026)

The decision to build tabs now uses **validated** TLDR content via `actuallyHasTldrContent`:

```javascript
// STEP 1: Validate TLDR content first (before deciding on tabs)
var tldrContentClone = /* ... clone and validate TLDR ... */;
var actuallyHasTldrContent = tldrContentClone !== null && hasMeaningfulContent(tldrContentClone);

// STEP 2: Determine if tabs should be built using validated content
var shouldBuildTabs = false;

if (modelDetails.length > 1) {
    // Multiple models = always show tabs (one per model)
    shouldBuildTabs = true;
} else if (modelDetails.length === 1 && actuallyHasTldrContent) {
    // Single model WITH meaningful TLDR = show tabs (Main + TLDR)
    shouldBuildTabs = true;
} else if (modelDetails.length === 0 && actuallyHasTldrContent) {
    // No model details but has meaningful TLDR = show tabs (Main + TLDR)
    shouldBuildTabs = true;
}
```

**Key Change**: The old checks (`tldrDetails.length > 0 || hasTldrWrapper || preservedTldrContent !== null`) have been replaced with `actuallyHasTldrContent`, which requires content to have at least 10 characters of actual text.

### Tab Building Process

1. **Scan for Model Responses**: Find all `<details>` blocks with summary text starting with "Response from"
2. **Scan for TLDR**: Find `[data-answer-tldr]` elements or `<details>` with "TLDR" in summary
3. **Preserve Existing State**: If rebuilding, save active tab and scroll position
4. **Preserve TLDR Content**: Clone TLDR content before clearing container (with `hasMeaningfulContent()` validation)
5. **VALIDATE TLDR Content**: Check all potential TLDR sources with `hasMeaningfulContent()` - set `actuallyHasTldrContent`
6. **Decide on Tabs**: Use `actuallyHasTldrContent` to determine if TLDR tab should be added
7. **Create Tab Structure**: Build Bootstrap nav-tabs with unique IDs
8. **Clone Content**: Clone content from source elements into tab panes
9. **Hide/Remove Originals**: Hide model `<details>` blocks; remove TLDR sources only if content was captured
10. **Restore State**: Restore active tab and scroll position

---

## Reload Handling

### The Problem

On page reload, the following sequence occurs:
1. `renderInnerContentAsMarkdown()` runs with saved message text
2. `applyModelResponseTabs()` finds existing `.model-tabs-container`
3. Container is emptied and rebuilt
4. **Issue**: The original `$tldrWrapper` (`[data-answer-tldr]`) was removed from DOM after first render
5. **Result**: TLDR tab is empty because source is gone

### The Solution

**Step 1**: Preserve TLDR content before clearing the existing container (with meaningful content validation):

```javascript
// Location: interface/common.js lines ~1803-1816

var preservedTldrContent = null;
if ($existingContainer.length > 0) {
    var $existingTldrPane = $existingContainer.find('[id$="-pane-tldr"]').first();
    if ($existingTldrPane.length > 0) {
        var $existingTldrBody = $existingTldrPane.find('.model-tab-body').first();
        // Only preserve if there's meaningful content, not just empty tags like <strong></strong>
        if ($existingTldrBody.length > 0 && hasMeaningfulContent($existingTldrBody)) {
            preservedTldrContent = $existingTldrBody.clone(true, true);
        }
    }
}
```

**Step 2**: Validate and clone TLDR content with meaningful content checks:

```javascript
// Location: interface/common.js lines ~1822-1848

var tldrContentClone = null;
if (hasTldrWrapper) {
    // Fresh TLDR from server response - verify meaningful content
    var $tldrInnerDetails = $tldrWrapper.find('details').first();
    if ($tldrInnerDetails.length > 0 && hasMeaningfulContent($tldrInnerDetails)) {
        tldrContentClone = $tldrInnerDetails.clone(true, true);
    } else if (hasMeaningfulContent($tldrWrapper)) {
        tldrContentClone = $tldrWrapper.clone(true, true);
    }
} else if (tldrDetails.length > 0 && hasMeaningfulContent(tldrDetails[0].element)) {
    tldrContentClone = tldrDetails[0].element.clone(true, true);
} else if (preservedTldrContent !== null) {
    // Use preserved content (already verified to have meaningful content)
    tldrContentClone = preservedTldrContent;
}

// Final validation
var actuallyHasTldrContent = tldrContentClone !== null && hasMeaningfulContent(tldrContentClone);
```

**Step 3**: Only add TLDR tab if content is validated:

```javascript
if (actuallyHasTldrContent) {
    tabItems.push({ key: 'tldr', label: 'TLDR', type: 'tldr' });
}
```

### `showMore()` interaction

`showMore(..., as_html=true)` rebuilds the message DOM into `.less-text` + `.more-text`. Because this can remove earlier tab UI/hiding state, `showMore()` re-invokes `applyModelResponseTabs()` on the rebuilt content.

Relevant code:
- `interface/common.js:showMore()` calls `applyModelResponseTabs(moreText)` after rebuild and after expand.

### Snapshot + service worker invalidation

This feature is sensitive to cached DOM snapshots and cached JS:
- `interface/rendered-state-manager.js` stores conversation DOM snapshots in IndexedDB keyed by `window.UI_CACHE_VERSION`.
- `interface/service-worker.js` caches UI assets keyed by `CACHE_VERSION`.

When changing tab behavior, bump both together.

## Further Reading

- `documentation/features/multi_model_response_tabs/TAB_BASED_RENDERING_IMPLEMENTATION.md`
- `documentation/features/multi_model_response_tabs/EMPTY_TLDR_FIX_CONTEXT.md`

---

## CSS and Styling

The feature uses Bootstrap 4.6 nav-tabs classes. No custom CSS file is required.

**Bootstrap Classes Used:**
- `.nav`, `.nav-tabs`, `.nav-item`, `.nav-link`
- `.tab-content`, `.tab-pane`, `.fade`, `.show`, `.active`

**Custom Classes:**
- `.model-tabs-container`: Main wrapper for styling hooks
- `.model-tab-body`: Content wrapper inside each pane

**Inline Styling:**
The tab container inherits styling from the parent card-body. Specific styling can be added via:
```css
.model-tabs-container {
    /* Custom styles */
}
.model-tabs-container .nav-tabs {
    /* Tab navigation styles */
}
.model-tabs-container .tab-pane {
    /* Tab pane styles */
}
```

---

## Implementation Notes

### Helper Function: `hasMeaningfulContent()`

Validates that an element has actual text content, not just empty HTML tags like `<strong></strong>`. This is critical for preventing empty TLDR tabs during streaming or after incomplete renders.

```javascript
function hasMeaningfulContent($elem) {
    if (!$elem || $elem.length === 0) return false;
    // Get text content, trim whitespace
    var textContent = ($elem.text() || '').trim();
    // Check if there's at least some meaningful text (more than just punctuation/whitespace)
    return textContent.length > 10; // Require at least 10 chars of actual content
}
```

**Used in:**
- Checking if TLDR wrapper has meaningful content (`hasTldrWrapper`)
- Validating preserved TLDR content before use
- Final validation of `tldrContentClone` before adding TLDR tab

### Helper Function: `restoreHiddenForClone()`

When cloning content from `<details>` blocks that were hidden, styles may be incorrect. This function cleans them:

```javascript
function restoreHiddenForClone($elem) {
    if (!$elem || $elem.length === 0) return;
    $elem.removeAttr('data-model-tabs-hidden');
    $elem.find('[data-model-tabs-hidden]').each(function() {
        $(this).removeAttr('data-model-tabs-hidden');
    });
    $elem.find('[style]').each(function() {
        var style = $(this).attr('style') || '';
        if (style.indexOf('display') !== -1) {
            var cleaned = style.replace(/display\s*:\s*none\s*;?/gi, '').trim();
            if (cleaned) {
                $(this).attr('style', cleaned);
            } else {
                $(this).removeAttr('style');
            }
        }
    });
    $elem.show();
}
```

### Unique ID Generation

Each tab group needs a unique ID to prevent conflicts:

```javascript
var rootId = 'model-tabs-root-' + Date.now().toString(36) + Math.random().toString(36).substr(2, 6);
```

### Event Handling

Bootstrap's native tab switching is used. No custom click handlers are needed - the `data-toggle="tab"` attribute handles everything.

---

## Files Modified

| File | Lines | Purpose |
|------|-------|---------|
| `interface/common.js` | 1686-2032 | `applyModelResponseTabs()` function |
| `interface/common.js` | 1793-1801 | `hasMeaningfulContent()` helper function |
| `interface/common.js` | 1739-1757 | `restoreHiddenForClone()` helper function |
| `interface/common.js` | 2210-2805 | `renderInnerContentAsMarkdown()` function |
| `common.py` | 291-500+ | `stream_multiple_models()` function |
| `Conversation.py` | 6815-6880 | TLDR generation in `chatbot_reply()` |
| `Conversation.py` | 2880-2960 | TLDR extraction for message storage |

---

## Testing Checklist

### Basic Functionality
- [ ] Select 2+ models in settings
- [ ] Send a message and verify tabs appear with each model's response
- [ ] Click each tab and verify content is correct
- [ ] Verify tab labels show model names (or "Main" for single model)

### TLDR Tab
- [ ] Send a message that generates a long response (>1000 words)
- [ ] Verify TLDR tab appears with summary content
- [ ] Verify Main tab contains the full response (without TLDR)

### Reload Handling
- [ ] After tabs are shown, reload the page
- [ ] Verify all tabs still have content
- [ ] Verify TLDR tab specifically has content (regression test)

### Edge Cases
- [ ] Single model without TLDR - no tabs should appear
- [ ] Single model with TLDR - tabs should appear (Main + TLDR)
- [ ] Multiple models without TLDR - tabs should appear (one per model)
- [ ] Switch between conversations and verify tabs render correctly

### Empty TLDR Tab Fix (Regression Tests)
- [ ] Multi-model response: TLDR tab should NOT appear (TLDR not generated for multi-model)
- [ ] Verify empty `<strong></strong>` content doesn't create TLDR tab
- [ ] During streaming: TLDR wrapper not removed until content is complete
- [ ] Preserved content validation: empty preserved content should be ignored

---

## Troubleshooting

### Empty TLDR Tab (Shows Only `<strong></strong>` or Empty)

**Causes** (Fixed in Feb 2026):
1. TLDR wrapper was removed during streaming before content was fully loaded
2. Empty tags like `<strong></strong>` from partial renders were incorrectly considered as content
3. `shouldBuildTabs` was evaluated before validating TLDR content meaningfulness
4. Incomplete preserved content was being re-used instead of waiting for complete content

**Solution**: The fix involves multiple changes:
1. **`hasMeaningfulContent()` helper** (lines ~1793-1801): Validates content has at least 10 characters of actual text
2. **Restructured validation flow**: TLDR content is now validated BEFORE deciding whether to build tabs
3. **Updated `shouldBuildTabs` logic**: Now uses `actuallyHasTldrContent` (validated flag) instead of simple existence checks
4. **Conditional wrapper removal**: TLDR wrapper is only removed after confirming meaningful content was captured

**Key Variable**: `actuallyHasTldrContent = tldrContentClone !== null && hasMeaningfulContent(tldrContentClone)`

See `EMPTY_TLDR_FIX_CONTEXT.md` for full details.

### Empty TLDR Tab After Reload

**Cause**: `$tldrWrapper` was removed from DOM after first render, and rebuild couldn't find source.

**Solution**: 
1. Lines 1803-1816 preserve TLDR content before clearing the container
2. Preservation now checks `hasMeaningfulContent()` to avoid preserving empty content
3. TLDR wrapper removal is conditional on `actuallyHasTldrContent`

### Tabs Not Appearing

**Check**:
1. Are there `<details>` blocks with "Response from" in the summary?
2. Is there a `[data-answer-tldr]` element with meaningful content (>10 chars)?
3. Is `shouldBuildTabs` evaluating to true?
4. Is `actuallyHasTldrContent` true (if expecting TLDR tab)?

### Wrong Tab Active After Reload

**Solution**: The active tab key is preserved via `data-tab-key` attribute and restored during rebuild.

### Content Not Visible in Tab

**Check**:
1. Is `restoreHiddenForClone()` being called on cloned content?
2. Are there lingering `display: none` styles?
3. Is the tab pane getting `.show.active` classes correctly?

### TLDR Tab Appearing When It Shouldn't

**Check**:
1. Is there a `<details>` block with "tldr" in its summary text? (Model responses mentioning TLDR can trigger this)
2. Is there preserved content from a previous session?
3. Clear the existing tab container and reload to reset state
