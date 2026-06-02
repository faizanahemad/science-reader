# Message Card Header — Actions & Menus

## Overview

Every message card (`.message-card`) has a **card header** (`.card-header`) containing per-message controls split into two sides:

- **Left side**: checkbox, sender label with reference badge, "Message Actions" dropdown
- **Right side**: copy button, "More Options" dropdown

The header layout uses `d-flex justify-content-between align-items-center` to pin the two groups to opposite edges.

## Structure

```
.card-header
├── Left: .d-flex.align-items-center
│   ├── Checkbox (.history-message-checkbox)
│   ├── Sender label + reference badge (.message-ref-badge)
│   └── "Message Actions" dropdown (⋮)
│       ├── Show Doubts
│       ├── Ask New Doubt
│       ├── ── divider ──
│       ├── Move Up
│       ├── Move Down
│       ├── ── divider ──
│       ├── Artefacts
│       ├── Delete Message
│       └── Delete Pair
└── Right: .d-flex.align-items-center
    ├── Copy button (.copy-btn-header)
    └── "More Options" dropdown (⋮, .vote-menu-toggle)
        ├── Short TTS
        ├── Full TTS
        ├── Short Podcast (desktop only)
        ├── Full Podcast (desktop only)
        ├── ── divider ──
        ├── Table of Contents
        ├── ── divider ──
        ├── Edit Message
        ├── Edit as Artefact
        └── Save to Memory
```

## How Each Side Is Populated

### Left — "Message Actions" dropdown

Built **statically** in an HTML template string (`actionDropdown` variable) inside `common-chat.js` ~line 2414. Each item is an `<a class="dropdown-item ...">` with a descriptive class (e.g. `.show-doubts-button`, `.move-message-up-button`) and `message-index` / `message-id` attributes.

Event handlers are wired via **delegated jQuery** at ~line 2674:

```javascript
$(".delete-message-button").off().on("click", function(event) { ... });
$(".move-message-up-button").off().on("click", function(event) { ... });
$(".show-doubts-button").off().on("click", function(event) { ... });
$(".ask-doubt-button").off().on("click", function(event) { ... });
$(".open-artefacts-button").off().on("click", function(event) { ... });
```

`delete-pair-button` uses a document-level delegated handler in `common.js` (~line 2216).

### Right — "More Options" dropdown

The template only creates an **empty** `<div class="dropdown-menu dropdown-menu-right vote-dropdown-menu">`. It is populated **dynamically** by `initialiseVoteBank(cardElem, text, contentId, activeDocId, disable_voting)` in `common.js` (~line 1489).

`initialiseVoteBank` is called:
- For each message during conversation load (~line 2506/2512 in `common-chat.js`)
- For streaming assistant responses once complete (~line 1802)
- During snapshot restore (~line 347, 772)

It empties `.vote-dropdown-menu` then appends items with inline click handlers:

```javascript
voteDropdown.empty();
voteDropdown.append(shortTtsItem, ttsItem);
if (window.innerWidth > 768) voteDropdown.append(shortPodcastItem, podcastItem);
voteDropdown.append(divider, tocItem);
voteDropdown.append(divider, editItem, editAsArtefactItem, saveToMemoryItem);
```

### Copy button (`.copy-btn-header`)

Standalone button on the right side. Its click handler is wired inside `initialiseVoteBank()` (~line 1795) — it delegates to the internal `copyBtn.click()` which calls `copyToClipboard(cardElem, text)`.

### Reference badge (`.message-ref-badge`)

Displays `#<index> · <hash>`. Click handler attached via delegated event at ~line 2722 in `common-chat.js`; copies `@conversation_<fid>_message_<hash>` to clipboard.

## How to Add New Buttons

### Add an item to "Message Actions" (left dropdown)

1. Add the `<a>` in the `actionDropdown` template (~line 2414 in `common-chat.js`):

```javascript
<a class="dropdown-item my-new-action" href="#" message-index="${index}" message-id="${message.message_id}">
    <i class="bi bi-star mr-2"></i>My Action
</a>
```

2. Wire a delegated handler (~line 2674):

```javascript
$(".my-new-action").off().on("click", function(event) {
    event.preventDefault();
    event.stopPropagation();
    var messageId = $(this).attr('message-id');
    // your logic
});
```

3. Add the class to the **click-guard exclusion lists** (lines 1257, 1267, 1283, 2610, 2620, 2636) so card-click doesn't fire when the button is clicked:

```javascript
if ($(e.target).closest('..., .my-new-action, ...').length > 0) {
```

### Add an item to "More Options" (right dropdown)

In `initialiseVoteBank()` in `common.js` (~line 1871-1915):

```javascript
var myItem = $('<a class="dropdown-item" href="#"><i class="bi bi-star mr-2"></i>My Action</a>');
myItem.click(function(e) {
    e.preventDefault();
    // cardElem, text, contentId available via closure
});
voteDropdown.append(myItem);
```

### Add a standalone button beside the ⋮ dots

**Right side** — add in the `cardHeader` template (~line 2449), before or after the copy button:

```javascript
<button class="btn btn-sm p-1 my-btn" title="My Action">
    <i class="bi bi-star"></i>
</button>
```

Wire handler in `initialiseVoteBank()`:
```javascript
cardElem.find('.my-btn').click(function(e) { ... });
```

**Left side** — add after `${actionDropdown}` in the template.

In either case, add the new class to the click-guard exclusion lists.

## Doubts Indicator Button (`.has-doubts-btn`)

A standalone button (`<i class="bi bi-chat-left-text"></i>`) placed immediately after the left ⋮ dropdown. Hidden by default (`display:none`), revealed only when the message has existing doubts.

**How it works:**
1. On conversation load, `revealDoubtsButtons(conversationId)` fetches `GET /get_messages_with_doubts/<conversation_id>` which returns message IDs that have at least one root doubt.
2. Matching `.has-doubts-btn[message-id="X"]` elements are shown.
3. When a new doubt finishes streaming (both `part.completed` and reader `done` paths in `doubt-manager.js`), the button for that message is revealed immediately.
4. After a streamed assistant response completes, a 5-second delayed `revealDoubtsButtons()` call catches backend-only doubt creation (e.g. auto-takeaways).

**Streaming card note:** During streaming, cards are created without a `message_id`. When the backend returns `message_ids`, all action buttons (including `.has-doubts-btn`) get their `message-id` attribute updated — both on the assistant card and the user card.

**Click action:** Opens the doubts overview modal via `DoubtManager.showDoubtsOverview(conversationId, messageId)` — same as the "Show Doubts" dropdown item.

**Backend:**
- `database/doubts.py` → `get_message_ids_with_doubts(conversation_id=...)` — returns distinct message_ids with root doubts
- `endpoints/doubts.py` → `GET /get_messages_with_doubts/<conversation_id>` — returns `{success, message_ids[]}`

## Key Files

| File | What |
|------|------|
| `interface/common-chat.js` ~L2414-2468 | Card header template (both dropdowns + `.has-doubts-btn`) |
| `interface/common.js` ~L1489 | `initialiseVoteBank()` — populates right dropdown, copy handler |
| `interface/common-chat.js` ~L2674-2740 | Delegated handlers for left dropdown items + `.has-doubts-btn` |
| `interface/common.js` ~L2216 | Delete Pair handler (document-level delegated) |
| `interface/common-chat.js` ~L1257,2610 | Click-guard exclusion lists |
| `interface/common-chat.js` ~L1580-1590 | Streaming response: updates `message-id` on action buttons + `.has-doubts-btn` |
| `interface/common-chat.js` `revealDoubtsButtons()` | Fetches and shows doubts indicator buttons |
| `interface/doubt-manager.js` ~L770,601 | Reveals button on doubt stream completion |
| `database/doubts.py` | `get_message_ids_with_doubts()` |
| `endpoints/doubts.py` | `GET /get_messages_with_doubts/<conversation_id>` |

## Notes

- Bootstrap 4.6 dropdowns are used (`data-toggle="dropdown"`). They are re-initialized via `$('[data-toggle="dropdown"]').dropdown()` after cards are appended.
- The left dropdown uses `dropdown-menu-left`, the right uses `dropdown-menu-right` for alignment.
- `initialiseVoteBank` also creates internal `copyBtn` and `editBtn` jQuery elements (not appended to DOM) whose click handlers are reused by the dropdown items and the header copy button.
- The Podcast items are only shown when `window.innerWidth > 768`.
