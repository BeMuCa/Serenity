"""
============================================================
Author:  Berk
Created: 2026-08-06
Purpose: Unit-test the model downloader (core.model_fetch) and its CLI
         (serenity.fetch_models) with a fake opener - no network, no real weights.
Role:    Headless guard for the first-run setup path: registry sanity, atomic writes,
         idempotent skips, size-mismatch refusal, dest routing, and CLI exit codes.

Test classes:
- TestRegistry - keys/assets_for/dest routing + the registry matches what the app looks for
- TestFetch - skip-when-present, atomic rename, no partial left behind, progress callback
- TestFetchAll - a key set lands in the right two dirs
- TestCli - default key set, --list, unknown key, failure exit code
- TestEntryFlag - `--fetch-models` short-circuits the app entry before Qt loads
- TestProgressLines - a piped run throttles progress to 10% steps
- TestNoStdout - the windowed exe (sys.stdout None) logs to a file instead of crashing
============================================================
"""
from pathlib import Path

import pytest

from serenity import fetch_models
from serenity.core.llm import DEFAULT_MODEL_FILE, QWEN3_0_6B_FILE
from serenity.core.model_fetch import (ASSETS, DEFAULT_KEYS, Asset, FetchError, assets_for,
                                       fetch, fetch_all, keys, target_dir)
from serenity.core.settings import Settings


class _FakeResponse:
    """Minimal urlopen stand-in: a context manager whose read(n) walks a byte payload."""

    def __init__(self, payload: bytes) -> None:
        self._buf = memoryview(payload)
        self._pos = 0

    def read(self, n: int) -> bytes:
        chunk = bytes(self._buf[self._pos:self._pos + n])
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(payload: bytes, calls: list | None = None):
    def open_url(url):
        if calls is not None:
            calls.append(url)
        return _FakeResponse(payload)
    return open_url


def _asset(size: int = 8, name: str = "m.gguf", dest: str = "models") -> Asset:
    return Asset("t", "https://example.invalid/m.gguf", name, dest, size)


class TestRegistry:
    def test_keys_are_deduped_in_registry_order(self):
        assert keys() == ["llm", "llm-small", "voice-de", "voice-en"]

    def test_assets_for_selects_sidecars_too(self):
        got = assets_for(["voice-de"])
        assert [a.filename for a in got] == ["de_DE-kerstin-low.onnx",
                                             "de_DE-kerstin-low.onnx.json"]

    def test_all_expands_and_unknown_key_raises(self):
        assert assets_for(["all"]) == list(ASSETS)
        with pytest.raises(KeyError):
            assets_for(["voice-fr"])

    def test_filenames_match_what_the_app_looks_for(self):
        """A download the app cannot find is worthless: the GGUF names must match
        core.llm's discovery order and the voice ids the Settings defaults ask for."""
        by_key = {a.key: a for a in ASSETS}
        assert by_key["llm"].filename == DEFAULT_MODEL_FILE
        assert by_key["llm-small"].filename == QWEN3_0_6B_FILE
        s = Settings()
        voices = {a.filename for a in ASSETS if a.dest == "voices"}
        assert f"{s.tts_voice_de}.onnx" in voices
        assert f"{s.tts_voice_en}.onnx" in voices

    def test_dest_routing(self, tmp_path):
        models, voices = tmp_path / "m", tmp_path / "v"
        gguf = next(a for a in ASSETS if a.dest == "models")
        onnx = next(a for a in ASSETS if a.dest == "voices")
        assert target_dir(gguf, models, voices) == models
        assert target_dir(onnx, models, voices) == voices

    def test_default_keys_are_real_keys(self):
        assert set(DEFAULT_KEYS) <= set(keys())


class TestFetch:
    def test_downloads_atomically_and_reports_progress(self, tmp_path):
        seen = []
        res = fetch(_asset(size=3 * 1024 * 1024), tmp_path,
                    opener=_opener(b"x" * (3 * 1024 * 1024)),
                    on_progress=lambda a, got, total: seen.append((got, total)))
        assert res.status == "downloaded"
        assert res.path.read_bytes() == b"x" * (3 * 1024 * 1024)
        assert list(tmp_path.iterdir()) == [res.path]        # no .part survives
        assert seen[-1] == (3 * 1024 * 1024, 3 * 1024 * 1024)  # progress ran to completion
        assert [g for g, _ in seen] == [1048576, 2097152, 3145728]

    def test_complete_file_is_skipped_without_a_network_call(self, tmp_path):
        (tmp_path / "m.gguf").write_bytes(b"12345678")
        calls = []
        res = fetch(_asset(size=8), tmp_path, opener=_opener(b"12345678", calls))
        assert res.status == "present" and calls == []

    def test_wrong_size_on_disk_is_redownloaded(self, tmp_path):
        (tmp_path / "m.gguf").write_bytes(b"trunc")          # an earlier failed attempt
        calls = []
        res = fetch(_asset(size=8), tmp_path, opener=_opener(b"12345678", calls))
        assert res.status == "downloaded" and len(calls) == 1
        assert res.path.read_bytes() == b"12345678"

    def test_short_download_raises_and_leaves_nothing(self, tmp_path):
        with pytest.raises(FetchError, match="expected 8 bytes, got 4"):
            fetch(_asset(size=8), tmp_path, opener=_opener(b"1234"))
        assert list(tmp_path.iterdir()) == []                # the .part was removed

    def test_opener_error_raises_and_leaves_nothing(self, tmp_path):
        def boom(url):
            raise OSError("no route to host")
        with pytest.raises(FetchError, match="download failed"):
            fetch(_asset(size=8), tmp_path, opener=boom)
        assert list(tmp_path.iterdir()) == []

    def test_creates_the_destination_dir(self, tmp_path):
        dest = tmp_path / "deep" / "models"
        res = fetch(_asset(size=8), dest, opener=_opener(b"12345678"))
        assert res.path == dest / "m.gguf" and res.path.exists()


class TestFetchAll:
    def test_voice_pair_lands_in_the_voices_dir_only(self, tmp_path):
        models, voices = tmp_path / "m", tmp_path / "v"
        payloads = {a.filename: b"y" * a.size for a in assets_for(["voice-de"])}

        def opener(url):
            name = url.rsplit("/", 1)[-1]
            return _FakeResponse(payloads[name])

        results = fetch_all(["voice-de"], models, voices, opener=opener)
        assert [r.status for r in results] == ["downloaded", "downloaded"]
        assert sorted(p.name for p in voices.iterdir()) == ["de_DE-kerstin-low.onnx",
                                                            "de_DE-kerstin-low.onnx.json"]
        assert not models.exists()


class TestCli:
    """Driven against a TINY stand-in registry: the real rows are ~1.2 GB, and the CLI's job
    is argv/routing/exit codes, not the weights themselves (TestRegistry pins those)."""

    TINY = (Asset("llm", "https://example.invalid/tiny.gguf", "tiny.gguf", "models", 8),
            Asset("voice-de", "https://example.invalid/v.onnx", "v.onnx", "voices", 4),
            Asset("voice-de", "https://example.invalid/v.onnx.json", "v.onnx.json", "voices", 2))

    @pytest.fixture(autouse=True)
    def _tiny_registry(self, monkeypatch):
        import serenity.core.model_fetch as mf
        monkeypatch.setattr(mf, "ASSETS", self.TINY)          # read by assets_for()/keys()
        monkeypatch.setattr(fetch_models, "ASSETS", self.TINY)  # printed by --list
        monkeypatch.setattr(fetch_models, "DEFAULT_KEYS", ("llm", "voice-de"))

    def _opener(self, url):
        sizes = {a.filename: a.size for a in self.TINY}
        return _FakeResponse(b"z" * sizes[url.rsplit("/", 1)[-1]])

    def test_default_run_fetches_the_default_key_set(self, tmp_path, capsys):
        models, voices = tmp_path / "m", tmp_path / "v"
        rc = fetch_models.main(["--models-dir", str(models), "--voices-dir", str(voices)],
                               opener=self._opener)
        assert rc == 0
        assert (models / "tiny.gguf").read_bytes() == b"z" * 8
        assert sorted(p.name for p in voices.iterdir()) == ["v.onnx", "v.onnx.json"]
        out = capsys.readouterr().out
        assert "Done." in out and "[ ok ]" in out

    def test_second_run_skips_everything(self, tmp_path, capsys):
        models, voices = tmp_path / "m", tmp_path / "v"
        argv = ["llm", "--models-dir", str(models), "--voices-dir", str(voices)]
        fetch_models.main(argv, opener=self._opener)
        capsys.readouterr()
        def refuse(url):                                      # a second call would be a bug
            raise AssertionError("re-downloaded an already complete file")
        assert fetch_models.main(argv, opener=refuse) == 0
        assert "[skip]" in capsys.readouterr().out

    def test_list_prints_every_asset_and_touches_nothing(self, tmp_path, capsys):
        rc = fetch_models.main(["--list"], opener=None)
        out = capsys.readouterr().out
        assert rc == 0
        for a in self.TINY:
            assert a.filename in out
        assert list(tmp_path.iterdir()) == []

    def test_unknown_key_exits_1(self, capsys):
        assert fetch_models.main(["voice-fr"], opener=None) == 1
        assert "unknown asset key" in capsys.readouterr().err

    def test_failed_download_exits_1(self, tmp_path, capsys):
        def short(url):
            return _FakeResponse(b"x")                        # 1 byte, 8 expected
        rc = fetch_models.main(["llm", "--models-dir", str(tmp_path / "m"),
                                "--voices-dir", str(tmp_path / "v")], opener=short)
        assert rc == 1
        assert "expected" in capsys.readouterr().err
        assert list((tmp_path / "m").iterdir()) == []          # no partial GGUF left


class TestEntryFlag:
    """The frozen exe has no python CLI - `Serenity.exe --fetch-models` is the only way an
    installed copy can pull its models, so the flag must short-circuit BEFORE Qt boots."""

    def test_flag_delegates_to_the_downloader_before_importing_qt(self, monkeypatch):
        import sys
        import serenity.__main__ as entry
        seen = []

        def fake_main(argv):
            seen.append(argv)
            return 7                                  # a distinctive code to prove pass-through

        monkeypatch.setattr(fetch_models, "main", fake_main)
        # Sabotage the Qt import: taking the normal boot path would now raise, so a passing
        # test proves the flag branch returned before any Qt import.
        monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", None)
        monkeypatch.setattr(sys, "argv", ["serenity", "--fetch-models", "voice-de", "--list"])
        assert entry.main() == 7
        assert seen == [["voice-de", "--list"]]


class TestProgressLines:
    def test_piped_progress_is_throttled_to_ten_percent_steps(self, tmp_path, capsys):
        """A 1.1 GB fetch calls on_progress once per MB chunk; unthrottled that is >1000
        lines in an install log, so a non-TTY run must print at most one line per 10%."""
        fetch_models._printed.clear()
        size = 30 * 1024 * 1024                                # 30 chunks
        asset = Asset("t", "https://example.invalid/big.bin", "big.bin", "models", size)
        fetch(asset, tmp_path, opener=_opener(b"q" * size), on_progress=fetch_models._progress)
        lines = [l for l in capsys.readouterr().out.splitlines() if "big.bin" in l]
        assert 2 <= len(lines) <= 11                            # buckets 0,10,...,100
        assert lines[-1].strip().startswith("big.bin: 100%")


class TestNoStdout:
    """The installer's post-install step runs the WINDOWED exe, where sys.stdout is None:
    print() is a silent no-op and isatty() would raise, so output goes to a log file."""

    def test_reports_into_a_log_file_and_does_not_crash(self, tmp_path, monkeypatch):
        import sys
        from serenity.core import paths
        monkeypatch.setattr(paths, "config_dir", lambda: tmp_path)
        monkeypatch.setattr(sys, "stdout", None)
        models, voices = tmp_path / "m", tmp_path / "v"
        asset = Asset("only", "https://example.invalid/f.bin", "f.bin", "models", 8)
        monkeypatch.setattr("serenity.core.model_fetch.ASSETS", (asset,))
        rc = fetch_models.main(["only", "--models-dir", str(models), "--voices-dir", str(voices)],
                               opener=_opener(b"12345678"))
        assert rc == 0
        log = (tmp_path / fetch_models.LOG_NAME).read_text()
        assert "f.bin" in log and "Done." in log
        assert (models / "f.bin").exists()
