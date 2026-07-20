"""
============================================================
Author:  Berk
Created: 2026-07-19
Purpose: Shared pytest fixtures. Autouse teardown that stops any LlmWorker QThread a
         test left running (tests build Shell() directly and never call Shell._quit).
Role:    Keeps the suite clean of "QThread: Destroyed while thread is still running"
         warnings and stray polling threads from the LLM job queue (Infra A).

Functions:
- _stop_llm_workers() — autouse fixture: after each test, stop+join any live LlmWorker
============================================================
"""
import pytest


@pytest.fixture(autouse=True)
def _stop_llm_workers():
    yield
    try:
        from serenity.ui.llm_worker import stop_all_workers
    except Exception:
        return  # PySide6 not installed (base-only run): no workers to stop
    stop_all_workers(timeout_ms=2000)
