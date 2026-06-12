# A0 Audit: PKBConfig per-user resolution bypass check

**Date:** 2026-06-12  
**Status:** Complete — no critical bypasses found; two known items to address in A3/D1.

## Summary

Traced all readers/consumers of `PKBConfig` to determine whether per-user effective-config resolution (planned for A3's `for_user` overlay) will propagate correctly. No module-level globals inside TMS hold config. All instances are rebuilt per-request/per-user call. Two items need attention:

## Findings

### 1. Config instantiation sites (shared/cached)

| Location | Pattern | Per-user risk |
|---|---|---|
| `endpoints/pkb.py:128` | `_pkb_config = PKBConfig(db_path=...)` cached globally | None — callers pass it to `StructuredAPI`; `for_user` will overlay |
| `extension_server.py:665` | Same global-cache pattern | Same — `get_pkb_api_for_user` builds StructuredAPI per-call |
| `Conversation.py:205` | `_pkb_config_instance` cached once | Same — passed to StructuredAPI per-user |
| `text_orchestration.py:73`, `conversation_distillation.py:102`, `text_ingestion.py:160` | `self.config = config or PKBConfig()` | Receive config from caller (StructuredAPI) — inherits effective config once A3 lands |
| `notes_search.py:70` | `self.config = config or PKBConfig()` | Same |

### 2. for_user (the A3 fix point)

```python
def for_user(self, user_email: str) -> "StructuredAPI":
    return StructuredAPI(db=self.db, keys=self.keys, config=self.config, user_email=user_email)
```

Currently passes the shared config unchanged. **A3 will:** read `pkb_user_settings` for `user_email`, call `derive_policy(autonomy, overrides)`, build an effective config, and pass *that* to the new instance. All downstream consumers (`EmbeddingStore`, `ConversationDistiller`, etc.) are rebuilt per-call from `api.config` so they'll inherit automatically.

### 3. Scheduler (deferred — D1/D2)

```python
start_lifecycle_sweep_scheduler(db, config)  # holds shared config ref
# in loop:
    run_lifecycle_sweep(db, config)  # reads config.dormancy_threshold
```

The sweep is global (user_email=None → sweeps all). For per-user autonomy it should iterate users and apply their effective policy. **Acceptable for v1:** `dormancy_threshold=0.0` (inert) means the sweep is a no-op unless explicitly configured. The per-user sweep iteration is planned for Phase D (D1/D2).

### 4. EmbeddingStore

Built fresh in each `StructuredAPI.__init__`: `EmbeddingStore(self.db, self.keys, self.config)`. Since `for_user` constructs a new StructuredAPI, the store gets the effective config. ✅

### 5. No module-level config singletons in TMS

`grep -rnE "^[a-z_]*config\b|^CONFIG" truth_management_system/` — empty (excluding tests/comments). ✅

## Conclusion

- **No blocking bypasses.** All config readers are instance-level, rebuilt per-request or per-user.
- **A3 fix** (`for_user` overlay) is the single point of change needed to propagate per-user policy.
- **D1/D2 fix** (scheduler per-user iteration) is deferred; safe because lifecycle automation is inert at `dormancy_threshold=0`.
