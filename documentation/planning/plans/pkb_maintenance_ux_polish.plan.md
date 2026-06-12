---
name: PKB Maintenance Tab UX Polish — Visibility, Discoverability & Completeness
overview: "Focused backlog of UX gaps discovered during 2026-06-12 audit. The backend features (fading claims, archived, cleanup orchestrator, health stats, dedup, reinforce) all work correctly but the UI hides them, under-reports data, or doesn't surface information where users expect it. This plan makes what's already built actually discoverable and usable."
todos:
  - id: recently-archived-include-superseded
    content: "Recently Archived section shows only status='archived' — should also show 'superseded' and 'retracted' claims so users can find merged duplicates"
    status: pending
  - id: health-dashboard-enrich
    content: "Health dashboard only shows 'N claims (active, dormant) · domains'. Should show by_status breakdown, by_type, by_provenance (stated/extracted/inferred), activity this month, top entities"
    status: pending
  - id: dedup-highlight-in-cleanup
    content: "Dedup highlighting (highlightDiff) exists on proposal cards but NOT in maintenance cleanup cluster view — apply same highlighting to cluster member pairs"
    status: pending
  - id: stale-section-always-visible
    content: "Stale claims (from Analyze) are only visible after clicking Analyze. Consider showing stale count in the health stats or running a lightweight stale-check on tab open"
    status: pending
  - id: standalone-memory-ui
    content: "Full-page /memory/ route that renders PKBManager outside the modal. Plan in pkb_external_access_ui_mcp_rest_auth.plan.md WS1 (T1.1–T1.6). Required for external use and better UX than cramming everything in a modal"
    status: pending
---

# PKB Maintenance Tab UX Polish

## Motivation

The PKB has a complete maintenance backend — fading memories, archived claims, cleanup orchestrator, health stats, dedup clusters, LLM-assisted consolidation, reinforce/restore. But during usage testing (2026-06-12) several UX failures were discovered:

1. **Sections were invisible** — `display:none` + hide-when-empty meant users never knew these sections existed (FIXED in `a0b1ac08`)
2. **Status filter was broken** — "All Statuses" still returned only active claims (FIXED in `a0b1ac08`)
3. **No status badges** — non-active claims had no visual indicator of why they're non-active (FIXED in `3b423553`)
4. **All-or-nothing cleanup** — no per-item accept/reject (FIXED in `dd95055a`)
5. **Missing status options** in dropdown (FIXED in `a0b1ac08`)

This plan tracks the **remaining gaps** that were NOT fixed.

## Already Fixed (2026-06-12, for reference)

| Commit | Fix |
|--------|-----|
| `dd95055a` | Per-item checkboxes in cleanup, selective apply |
| `a0b1ac08` | Fading/Archived always visible, All Statuses works, all status options in dropdown |
| `3b423553` | Status badges (superseded/retracted/expired/dormant/historical/draft) on claim cards |

## Remaining Items

### 1. Recently Archived should include superseded & retracted (`recently-archived-include-superseded`)

**Problem:** The "Recently Archived" section queries `WHERE status = 'archived'` only. When claims are merged as duplicates they become `superseded`, not `archived`. Users looking for their merged claims find nothing in "Recently Archived."

**Fix:** Change `get_recently_archived()` to query `status IN ('archived', 'superseded', 'retracted')` and show the status as a badge on each item. Add a "Restore" option (sets back to `active`) and for superseded claims, show what superseded them (the link target).

**Files:** `truth_management_system/interface/structured_api.py` (query), `interface/pkb-manager.js` (badge).

---

### 2. Health Dashboard enrichment (`health-dashboard-enrich`)

**Problem:** Backend `get_health_stats()` returns `total_claims`, `by_status`, `by_type`, `by_domain`. UI only renders one line: `53 claims (38 active, 0 dormant) · 5 domains`. Plan called for provenance breakdown, activity this month, top entities, STM stats.

**Fix (incremental):**
- **Phase A (use existing data):** Render `by_status` as colored badges (green=active, grey=superseded, red=retracted, dark=expired, blue=dormant), `by_type` as a compact list, `by_domain` as a list.
- **Phase B (add provenance):** Add derivation breakdown to `get_health_stats()` (stated/extracted/inferred) — one more SQL group-by.
- **Phase C (activity):** Add claims added/modified this month count.

**Files:** `truth_management_system/interface/structured_api.py` (extend query), `interface/pkb-manager.js` (render richer dashboard).

---

### 3. Dedup highlighting in cleanup clusters (`dedup-highlight-in-cleanup`)

**Problem:** `highlightDiff()` function exists and is used on extraction proposal cards to show overlap. But in the Maintenance cleanup report, cluster members are shown as plain text side-by-side with no highlighting.

**Fix:** In `renderCleanupReport()`, when rendering cluster members, pass adjacent pairs through `highlightDiff()` to mark the differing words.

**Files:** `interface/pkb-manager.js` — modify the cluster rendering in `renderCleanupReport()`.

---

### 4. Stale claims visibility without Analyze (`stale-section-always-visible`)

**Problem:** Stale claims only appear after clicking "Analyze" (which calls `POST /pkb/cleanup {apply: false}`). There's no indication before clicking that stale claims exist. The health dashboard doesn't mention them either.

**Options:**
- **A) Lightweight stale count on tab open:** Add a fast SQL count of claims with `confidence < threshold AND last_accessed_at < X days ago AND status = 'active'` — surface as "N claims approaching staleness" in the health stats.
- **B) Auto-run analyze on tab open:** Too slow for tab open (runs embedding clustering).
- **C) Cache last analyze results:** Store cleanup report in a lightweight cache; show "Last analysis (2h ago): N stale, M clusters" with "Re-analyze" button.

**Recommendation:** Option A for now (fast count in health stats), option C later.

**Files:** `truth_management_system/interface/structured_api.py` (add stale count to health), `interface/pkb-manager.js` (render).

---

### 5. Standalone `/memory/` page (`standalone-memory-ui`)

**Problem:** All PKB management is crammed into a modal. The 9-tab UI (Claims, Entities, Tags, Contexts, STM, NL, Notifications, Import, Maintenance) outgrew the modal format. Keyboard shortcuts, deep linking, browser back/forward, and screen real estate are all lost.

**Plan:** Already detailed in `pkb_external_access_ui_mcp_rest_auth.plan.md` Workstream 1 (T1.1–T1.6):
- T1.1: Refactor `PKBManager` to accept a container selector (`init('#memory-root')`)
- T1.2: Create `interface/memory.html` thin shell page
- T1.3: Flask route `/memory` + `/memory/<path>` for deep links
- T1.4: `openByReference(ref)` for deep-link resolution
- T1.5: No backend changes (reuses session-authenticated `/pkb/*` endpoints)
- T1.6: nginx already proxies

**Key UX benefits:**
- Full-page layout — claims list gets proper table/grid instead of cramped modal
- URL-addressable tabs: `/memory/maintenance`, `/memory/claims?status=superseded`
- Browser back/forward works
- Can be opened in a separate browser tab
- Foundation for the standalone-hostable PKB (external access plan WS0)

**Dependencies:** Requires extracting shared CSS/JS deps used by `pkb-manager.js` (jQuery, Bootstrap, showToast, escapeHtml) into a reusable bundle or standalone include.

---

## Implementation Order

1. **Item 1** (recently-archived-include-superseded) — 15min, high impact, fixes the "where are my merged claims?" question immediately
2. **Item 2 Phase A** (health-dashboard-enrich with existing data) — 30min, uses data the backend already returns
3. **Item 3** (dedup-highlight-in-cleanup) — 20min, function already exists, just wire it in
4. **Item 4 Option A** (stale count in health stats) — 20min, one SQL + one line of UI
5. **Item 5** (standalone memory UI) — 4–6h, larger effort, separate work session

## Relationship to Other Plans

- `pkb_ux_improvements.plan.md` — all items marked done; this plan picks up the UX gaps those items didn't fully cover
- `pkb_provenance_and_cleanup.plan.md` — W9 (cleanup orchestrator) + W11 (UI) are done; this plan polishes W11.4
- `pkb_external_access_ui_mcp_rest_auth.plan.md` — WS1 (standalone UI) is tracked here as item 5 for continuity; the full auth/extraction/MCP work remains in that plan
