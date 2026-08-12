"""
============================================================
Author:  Berk
Created: 2026-08-12
Purpose: Verify the suite can never write into the REAL per-user config dir - a bare
         Settings() has no _path, so save() falls back to config_dir()/settings.json and
         a UI test really did overwrite the user's own settings (custom activity_states
         wiped to [], vault_path repointed at a deleted pytest tmpdir).
Role:    Headless guard for the conftest config-isolation fixture. Without it the states
         a user configures in the app vanish the next time the test suite is run.

Test classes:
- TestConfigIsolation — config_dir() is redirected, and a bare save() lands there
============================================================
"""
import os
import sys
from pathlib import Path

from serenity.core import paths
from serenity.core.settings import Settings

# Captured at import (collection time), BEFORE the session fixture redirects the env,
# so this is genuinely where the running user's settings live.
_ORIG_XDG = os.environ.get("XDG_CONFIG_HOME")
_ORIG_APPDATA = os.environ.get("APPDATA")


def _real_user_config_dir() -> Path:
    """Where config_dir() would point with no test isolation in place."""
    if sys.platform.startswith("win"):
        base = _ORIG_APPDATA or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Serenity"
    base = Path(_ORIG_XDG) if _ORIG_XDG else Path.home() / ".config"
    return base / "serenity"


class TestConfigIsolation:
    def test_config_dir_is_not_the_real_user_config(self):
        assert paths.config_dir() != _real_user_config_dir()

    def test_a_bare_settings_save_cannot_reach_the_real_user_file(self):
        """QuickNoteDialog._save() calls settings.save() on the fixtures' bare Settings;
        that write must land in the redirected dir, never on the user's own file."""
        Settings().save()
        assert (paths.config_dir() / "settings.json").exists()
        assert not str(paths.config_dir()).startswith(str(_real_user_config_dir()))
