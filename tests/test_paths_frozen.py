"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for the PyInstaller frozen-path fix in core.paths.
Role:    Guards the bundle-layout contract: when sys.frozen + sys._MEIPASS are
         set (as in a PyInstaller exe), the read-only assets_dir()/data_dir()/
         poses_dir()/voice_lines_path() resolve UNDER sys._MEIPASS, while the
         per-user config_dir()/voices_dir() stay put (%APPDATA%/Serenity, not the
         bundle). Non-frozen (dev/pip) behavior must be unchanged. Also py_compiles
         serenity.spec so a syntax error in the build spec is caught here, on
         Linux/WSL, without running PyInstaller.

Test classes:
- TestFrozenPaths    - frozen branch resolves assets/data under _MEIPASS;
                       config stays per-user; falls back without _MEIPASS
- TestNonFrozenPaths - dev/pip path unchanged; shipped files still on disk
- TestSpecCompiles   - serenity.spec is valid Python
- TestEntryLauncher  - serenity_launch.py compiles, imports main with full package
                       context, and is the script the spec points Analysis at
                       (so the frozen exe never hits __main__.py's relative import)
============================================================
"""

import py_compile
import sys
from pathlib import Path

from serenity.core import paths

_REPO_ROOT = Path(__file__).resolve().parents[1]


class TestFrozenPaths:
    def test_assets_dir_under_meipass(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert paths.assets_dir() == tmp_path / "assets"

    def test_data_and_voice_lines_under_meipass(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert paths.data_dir() == tmp_path / "data"
        assert paths.voice_lines_path() == tmp_path / "data" / "voice_lines.json"

    def test_poses_dir_under_meipass(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert paths.poses_dir() == tmp_path / "assets" / "poses"

    def test_config_dir_unchanged_when_frozen(self, tmp_path, monkeypatch):
        # config_dir() / voices_dir() must stay per-user, NEVER under the bundle.
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        cfg = paths.config_dir()
        assert str(tmp_path) not in str(cfg)
        # resolves to the per-user Serenity location regardless of platform
        assert "serenity" in str(cfg).lower()
        # voices live under config_dir(), not under _MEIPASS
        voices = paths.voices_dir()
        assert str(tmp_path) not in str(voices)
        assert voices == cfg / "voices"

    def test_frozen_without_meipass_falls_back(self, monkeypatch):
        # frozen but no _MEIPASS -> fall back to the source package root.
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        assert paths.assets_dir() == paths._PKG_ROOT / "assets"
        assert paths.data_dir() == paths._PKG_ROOT / "data"


class TestNonFrozenPaths:
    def test_non_frozen_unchanged(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert paths.assets_dir() == paths._PKG_ROOT / "assets"
        assert paths.data_dir() == paths._PKG_ROOT / "data"
        # the shipped files still exist on disk (guards dev/pip mode)
        assert paths.poses_dir().exists()
        assert paths.voice_lines_path().exists()


class TestSpecCompiles:
    def test_spec_py_compiles(self):
        spec = _REPO_ROOT / "serenity.spec"
        assert spec.exists(), f"missing build spec at {spec}"
        # doraise -> py_compile raises PyCompileError on a syntax error
        py_compile.compile(str(spec), doraise=True)

    def test_spec_entry_is_launcher_not_main(self):
        # PKG-1: Analysis must point at the top-level launcher, never __main__.py
        # directly (PyInstaller runs the entry script with no package context, so
        # __main__.py's relative import would crash the exe on launch).
        spec_src = (_REPO_ROOT / "serenity.spec").read_text(encoding="utf-8")
        assert "'serenity_launch.py'" in spec_src
        assert "['serenity/__main__.py']" not in spec_src


class TestEntryLauncher:
    def test_launcher_exists_and_compiles(self):
        launcher = _REPO_ROOT / "serenity_launch.py"
        assert launcher.exists(), f"missing launcher at {launcher}"
        py_compile.compile(str(launcher), doraise=True)

    def test_launcher_imports_main_with_package_context(self):
        # The launcher must reach main() via an ABSOLUTE import so it works when
        # run as the top-level __main__ (the frozen-exe condition).
        launcher = _REPO_ROOT / "serenity_launch.py"
        src = launcher.read_text(encoding="utf-8")
        assert "from serenity.__main__ import main" in src
        # importing it must not raise (full package context intact)
        from serenity.__main__ import main

        assert callable(main)

    def test_main_uses_relative_import_so_needs_a_package_runner(self):
        # Proves WHY the launcher is needed: __main__.py reaches Shell via a
        # RELATIVE import, which only resolves with package context. PyInstaller
        # runs the entry script as top-level __main__ (no parent package), so the
        # spec must NOT point at __main__.py. We reproduce the failure in-process
        # without booting Qt or the single-instance shared memory: exec the exact
        # offending statement in a namespace with no package context.
        main_src = (_REPO_ROOT / "serenity" / "__main__.py").read_text(encoding="utf-8")
        assert "from .ui.shell import Shell" in main_src  # the relative import
        ns: dict = {"__name__": "__main__", "__package__": None}
        try:
            exec("from .ui.shell import Shell", ns)
        except ImportError as e:
            assert "no known parent package" in str(e)
        else:  # pragma: no cover - would mean the relative import unexpectedly resolved
            raise AssertionError("relative import unexpectedly resolved without a package")
