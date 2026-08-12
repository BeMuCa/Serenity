"""
============================================================
Author:  Berk
Created: 2026-07-19
Purpose: Shared pytest fixtures. Autouse teardown that stops any LlmWorker QThread a
         test left running (tests build Shell() directly and never call Shell._quit),
         plus an autouse redirect of the per-user config dir away from the real one.
Role:    Keeps the suite clean of "QThread: Destroyed while thread is still running"
         warnings and stray polling threads from the LLM job queue (Infra A), and stops
         the suite from writing over the running user's own settings.json.

Functions:
- _isolate_user_config() — autouse fixture: point config_dir() at a temp dir for the run
- _stop_llm_workers() — autouse fixture: after each test, stop+join any live LlmWorker
============================================================
"""
import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolate_user_config(tmp_path_factory):
    """Redirect config_dir() for the whole run.

    A bare Settings() carries no _path, so save() falls back to
    config_dir()/settings.json - the REAL user file. A UI test doing exactly that
    wiped the user's activity_states and repointed their vault at a pytest tmpdir."""
    base = tmp_path_factory.mktemp("user-config")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("XDG_CONFIG_HOME", str(base))   # POSIX
        mp.setenv("APPDATA", str(base))           # Windows
        yield


@pytest.fixture(autouse=True)
def _stop_llm_workers():
    yield
    try:
        from serenity.ui.llm_worker import stop_all_workers
    except Exception:
        return  # PySide6 not installed (base-only run): no workers to stop
    stop_all_workers(timeout_ms=2000)
