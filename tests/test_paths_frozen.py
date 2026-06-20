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
============================================================
"""

import py_compile
import sys
from pathlib import Path

from serenity.core import paths


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
        spec = Path(__file__).resolve().parents[1] / "serenity.spec"
        assert spec.exists(), f"missing build spec at {spec}"
        # doraise -> py_compile raises PyCompileError on a syntax error
        py_compile.compile(str(spec), doraise=True)
