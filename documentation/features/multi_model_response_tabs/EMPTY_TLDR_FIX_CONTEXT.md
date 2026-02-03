# Empty TLDR Tab Fix - Context Document

## Issue Description

The TLDR tab was appearing empty with only `<strong></strong>` content, even when multiple models were queried or when TLDR should have been populated.

Related symptom (encountered while improving TLDR persistence/reload behavior):
- In single-model + TLDR mode, the UI could show the full main answer *outside* the tabs (above/below the tab container) while multi-model mode looked correct.
  - Root cause: single-model answers often have no `Response from ...` model `<details>` sources to hide.
  - Fix: scope tab insertion + sibling hiding to the message body container so all render containers are hidden consistently.

### Root Causes Identified

1. **Premature TLDR wrapper removal**: The `$tldrWrapper.remove()` was called during streaming BEFORE content was fully loaded, causing loss of incomplete TLDR content.

2. **Non-validated content checks**: The `hasTldrWrapper` and `preservedTldrContent` checks only verified existence, not meaningful content. An element containing `<strong></strong>` (from an incomplete render) would pass these checks.

3. **Wrong ordering of validation**: The `shouldBuildTabs` decision was made BEFORE validating that TLDR content was meaningful, leading to empty TLDR tabs being created.

4. **Preservation of empty content**: When rebuilding tabs, empty/incomplete content (like `<strong></strong>`) was being preserved and re-used instead of waiting for complete content.

5. **Single-model duplicate sources**: For single-model + TLDR, the main answer is often plain rendered HTML (not model `<details>`). If we rebuild tabs inside one container but do not hide other render containers (e.g. `#message-render-space-md-render`, `showMore()` wrappers), the main answer appears outside the tabs.

---

## Changes Made

### File: `interface/common.js`

#### 1. Added `hasMeaningfulContent()` helper function (Lines ~1793-1801)

```javascript
function hasMeaningfulContent($elem) {
    if (!$elem || $elem.length === 0) return false;
    var textContent = ($elem.text() || '').trim();
    return textContent.length > 10; // Require at least 10 chars of actual content
}
```

**Purpose**: Validates that an element has actual text content, not just empty HTML tags.

#### 2. Updated TLDR wrapper existence check (Line ~1722)

**Before:**
```javascript
var hasTldrWrapper = $tldrWrapper.length > 0 && $tldrWrapper.contents().length > 0;
```

**After:**
```javascript
var hasTldrWrapper = $tldrWrapper.length > 0 && hasMeaningfulContent($tldrWrapper);
```

**Purpose**: Only consider TLDR wrapper as existing if it has meaningful content.

#### 3. Updated preserved content check (Lines ~1810-1814)

**Before:**
```javascript
if ($existingTldrBody.length > 0 && $existingTldrBody.contents().length > 0) {
    preservedTldrContent = $existingTldrBody.clone(true, true);
}
```

**After:**
```javascript
if ($existingTldrBody.length > 0 && hasMeaningfulContent($existingTldrBody)) {
    preservedTldrContent = $existingTldrBody.clone(true, true);
}
```

**Purpose**: Only preserve TLDR content if it's meaningful, not empty tags.

#### 4. Restructured code to validate TLDR BEFORE deciding on tabs (Lines ~1818-1866)

**New flow:**
1. STEP 1: Validate and clone TLDR content first
2. Set `actuallyHasTldrContent = tldrContentClone !== null && hasMeaningfulContent(tldrContentClone)`
3. STEP 2: Decide `shouldBuildTabs` using validated `actuallyHasTldrContent`
4. STEP 3: Create/update tab container
5. STEP 4: Build tab items

**Purpose**: Ensures tabs are only built when there's actual content to show.

#### 5. Updated `shouldBuildTabs` logic (Lines ~1856-1866)

**Before:**
```javascript
} else if (modelDetails.length === 1 && (tldrDetails.length > 0 || hasTldrWrapper || preservedTldrContent !== null)) {
    shouldBuildTabs = true;
} else if (modelDetails.length === 0 && (hasTldrWrapper || preservedTldrContent !== null)) {
```

**After:**
```javascript
} else if (modelDetails.length === 1 && actuallyHasTldrContent) {
    shouldBuildTabs = true;
} else if (modelDetails.length === 0 && actuallyHasTldrContent) {
```

**Purpose**: Only show tabs when TLDR content is validated as meaningful.

#### 6. Updated TLDR cloning logic (Lines ~1822-1848)

Added `hasMeaningfulContent()` checks at each cloning point:
- When cloning from `$tldrInnerDetails`
- When cloning from `$tldrWrapper`
- When cloning from `$tldrDetailsElem`
- When cloning from fallback details

**Purpose**: Ensures we only clone content that's actually meaningful.

#### 7. Updated TLDR wrapper removal logic (Lines ~2017-2027)

**Before:**
```javascript
if (hasTldrWrapper) {
    $tldrWrapper.remove();
}
tldrDetails.forEach(function(item) {
    item.element.remove();
});
```

**After:**
```javascript
if (actuallyHasTldrContent) {
    if (hasTldrWrapper && $tldrWrapper.length > 0) {
        $tldrWrapper.remove();
    }
    tldrDetails.forEach(function(item) {
        item.element.remove();
    });
}
```

**Purpose**: Only remove TLDR sources AFTER confirming we have captured meaningful content. This prevents data loss during streaming.

#### 8. Hide sources at the message-body scope (single-model parity)

To make single-model + TLDR match multi-model behavior, `applyModelResponseTabs()` scopes to the message body container (the card's `.chat-card-body`) and hides sibling render containers, leaving only:
- `.model-tabs-container`
- `.message-toc-container`

This prevents the main answer from showing above/below the tabs in single-model mode.

---

## Testing Scenarios

1. **Multi-model response without TLDR** (agent is not None):
   - Expected: No TLDR tab should appear
   - Verified: `actuallyHasTldrContent` will be false, no TLDR tab added

2. **Single model with long response (>1000 words)**:
   - Expected: Main + TLDR tabs appear
   - TLDR should have actual content

3. **Page reload with tabs**:
   - Expected: Preserved content should only be used if meaningful
   - Empty `<strong></strong>` should NOT be preserved

4. **Streaming in progress**:
   - Expected: TLDR wrapper not removed until content is complete
   - Subsequent renders should find complete content

---

## Key Variables

| Variable | Purpose |
|----------|---------|
| `hasTldrWrapper` | Now checks for meaningful content, not just existence |
| `actuallyHasTldrContent` | Final validated flag - true only if TLDR has 10+ chars of text |
| `preservedTldrContent` | Only set if existing TLDR has meaningful content |
| `tldrContentClone` | The cloned TLDR content to put in the tab |
| `shouldBuildTabs` | Depends on `actuallyHasTldrContent` for TLDR scenarios |

---

## Root Cause Analysis

The `<strong></strong>` in the empty TLDR tab came from the TLDR summary header format:

```html
<summary><strong>📝 TLDR Summary (Quick Read)</strong></summary>
```

During incomplete streaming:
1. The `[data-answer-tldr]` wrapper existed with partial content
2. The code detected it as having content (`.contents().length > 0`)
3. The wrapper was removed prematurely
4. Only the `<strong>` from the summary was captured
5. On rebuilds, this empty content was preserved and re-used

The fix ensures:
1. Content must have at least 10 characters of actual text
2. Wrapper is only removed after meaningful content is captured
3. Empty/incomplete content is not preserved or used

---

## Files Changed

| File | Lines Modified | Summary |
|------|----------------|---------|
| `interface/common.js` | ~1720-2030 | Core `applyModelResponseTabs()` function |

---

## Future Considerations

1. The 10-character threshold is somewhat arbitrary. Could be made configurable.
2. Consider adding a "loading" state for TLDR tab during streaming.
3. Could add explicit streaming state detection to be more precise about when to capture content.
