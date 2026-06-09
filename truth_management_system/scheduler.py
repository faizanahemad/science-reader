"""
Periodic lifecycle-sweep scheduler (Workstream F1).

Moves the hard-TTL expiry + soft-TTL dormancy sweep off the lazy on-search path
and onto a periodic background daemon thread, so lifecycle transitions happen on
a predictable cadence rather than being traffic-dependent. The lazy
``utils.maybe_expire_claims`` path remains as a fallback.

Design notes:
- Uses a plain ``threading.Thread`` daemon + ``threading.Event`` (matching the
  existing ``server.py`` background-thread convention), so no new dependency.
- ``Event.wait(interval)`` is used instead of ``sleep`` so the thread stops
  promptly when ``stop_lifecycle_sweep_scheduler`` is called (and is testable).
- Config-gated: ``sweep_interval_seconds <= 0`` disables the scheduler entirely.
- Idempotent: starting twice while a thread is alive is a no-op.
- The sweep runs globally (``user_email=None``) over the shared PKB database.
"""

import threading
from typing import Optional

from .utils import run_lifecycle_sweep

import logging

logger = logging.getLogger(__name__)


_sweep_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_lock = threading.Lock()


def start_lifecycle_sweep_scheduler(db, config, interval_seconds: Optional[int] = None):
    """
    Start the background lifecycle sweep daemon (Workstream F1).

    Args:
        db: PKBDatabase instance (shared, multi-user).
        config: PKBConfig — supplies ``sweep_interval_seconds`` and the dormancy
            knobs the sweep reads.
        interval_seconds: Optional override; defaults to
            ``config.sweep_interval_seconds``.

    Returns:
        The running ``Thread``, or ``None`` when disabled (interval <= 0).
    """
    global _sweep_thread

    interval = (
        interval_seconds
        if interval_seconds is not None
        else getattr(config, "sweep_interval_seconds", 0)
    )
    if not interval or interval <= 0:
        logger.info(
            "PKB lifecycle sweep scheduler disabled (sweep_interval_seconds=%s)",
            interval,
        )
        return None

    with _lock:
        if _sweep_thread is not None and _sweep_thread.is_alive():
            logger.info("PKB lifecycle sweep scheduler already running")
            return _sweep_thread

        _stop_event.clear()

        def _loop():
            # Wait first so we never sweep synchronously at startup (the lazy
            # path / startup expiry already handles the initial pass).
            while not _stop_event.wait(interval):
                try:
                    counts = run_lifecycle_sweep(db, config)
                    if counts["expired"] or counts["dormant"]:
                        logger.info(
                            "PKB lifecycle sweep: expired=%d dormant=%d",
                            counts["expired"],
                            counts["dormant"],
                        )
                except Exception:
                    logger.exception("PKB lifecycle sweep failed")

        thread = threading.Thread(
            target=_loop, daemon=True, name="pkb-lifecycle-sweep"
        )
        thread.start()
        _sweep_thread = thread
        logger.info(
            "PKB lifecycle sweep scheduler started (interval=%ds)", interval
        )
        return thread


def stop_lifecycle_sweep_scheduler() -> None:
    """Signal the sweep daemon to stop (best-effort; thread is a daemon)."""
    _stop_event.set()


def is_running() -> bool:
    """True when the sweep daemon thread is alive."""
    return _sweep_thread is not None and _sweep_thread.is_alive()
