"""
============================================================
Author:  Berk
Created: 2026-06-27
Purpose: Headless unit tests for core.note_draft — the Qt-free heart of Notes-expand.
Role:    Guards the 28 P1/P2 fail-safe guarantees without a display: draft
         serialization (P1-6), the strict commit-time validator (P1-1/5, P2-6/7),
         content-keyed write/discard/recover (P1-2/3, P2-1/4/11), the content-hash
         external-change detector (P2-8/9), and the promote() commit orchestration
         (P1-7/10, P2-16, P3-1) against a real tmp_path NoteStore.

Test classes:
- TestPrimitives        - draft_path / build_draft_text / content_hash / _norm (Task 1)
- TestValidate          - the strict commit gate (Task 2)
- TestWriteDiscardRecover - write_draft / discard / recover (Task 3)
- TestDetectExternal    - detect_external_change (Task 4)
- TestPromote           - promote orchestration (Task 5)
============================================================
"""

from datetime import datetime

import pytest

from serenity.core import note_draft as nd
from serenity.core.models import Note
from serenity.core.note_store import NoteStore, parse_markdown, serialize


def _note(**kw):
    base = dict(id="abc123def456", title="T", tags=["work"], color="violet", pinned=False)
    base.update(kw)
    return Note(**base)


# --------------------------------------------------------------------------- #
# Task 1 — serialization primitives
# --------------------------------------------------------------------------- #
class TestPrimitives:
    def test_draft_path_appends_draft(self):
        assert nd.draft_path("/v/n.md") == "/v/n.md.draft"

    def test_build_draft_text_sources_each_pane_independently(self):
        # fm from front_matter_text, body from body_text — never crossed (P1-6)
        fm = "title: Meeting\ntags:\n- work"
        out = nd.build_draft_text(fm, "## Agenda\n- x")
        assert out.startswith("---\n")
        assert "title: Meeting" in out and "## Agenda" in out

    def test_build_draft_text_roundtrips_both_panes(self):
        # a draft with BOTH an fm change and a body change parses back to both (P1-6)
        out = nd.build_draft_text("id: x1\ntitle: Meeting\ntags:\n- work", "## Agenda\n- x")
        got_fm, got_body = parse_markdown(out)
        assert got_fm["title"] == "Meeting" and "Agenda" in got_body

    def test_content_hash_differs_on_change(self):
        assert nd.content_hash("a") != nd.content_hash("b")
        assert nd.content_hash("a") == nd.content_hash("a")

    def test_norm_ignores_whitespace_and_key_order(self):
        # two semantically identical .md texts normalize equal (no false diff)
        n = _note(created=datetime(2026, 1, 1), updated=datetime(2026, 1, 2), body="hello")
        a = serialize(n)
        b = a + "\n\n   \n"            # trailing whitespace only
        assert nd._norm(a) == nd._norm(b)

    def test_norm_ignores_frontmatter_key_order(self):
        # same keys, different order -> normalize equal (kills a strip-only _norm; P1-2)
        a = "---\nid: x1\ntitle: T\n---\n\nbody\n"
        b = "---\ntitle: T\nid: x1\n---\n\nbody\n"
        assert nd._norm(a) == nd._norm(b)


# --------------------------------------------------------------------------- #
# Task 2 — the strict commit gate
# --------------------------------------------------------------------------- #
class TestValidate:
    def test_accepts_good_frontmatter(self):
        n = _note()
        fm = nd.validate("id: abc123def456\ntitle: T\ntags:\n- work\npinned: false", n)
        assert fm["id"] == "abc123def456"

    @pytest.mark.parametrize(
        "raw",
        [
            "id: abc123def456\ntitle: [unclosed",     # YAMLError
            "just a scalar",                           # non-dict
            "title: T",                                # id absent
            "id: DIFFERENT\ntitle: T",                 # id changed (P1-5)
            "id: abc123def456\ntags: work",            # scalar tags (P2-7)
            "id: abc123def456\ntags:\n- 1\n- 2",       # tags not list-of-str
            'id: abc123def456\npinned: "true"',        # pinned not bool
            'id: abc123def456\ndeleted: "no"',         # deleted not bool
            "id: abc123def456\ncreated: not-a-date",   # bad ISO created
            "id: abc123def456\nupdated: not-a-date",   # bad ISO updated
        ],
    )
    def test_rejects(self, raw):
        with pytest.raises(nd.NoteDraftInvalid):
            nd.validate(raw, _note())

    def test_restores_dropped_created(self):
        # created was present on the loaded note but dropped from the fm -> restore it
        n = _note(created=datetime(2026, 1, 1, 9, 0))
        fm = nd.validate("id: abc123def456\ntitle: T", n)
        assert fm["created"] == n.created.isoformat()

    def test_empty_created_does_not_trip_iso_check(self):
        # present-but-empty created is treated as absent, not as a bad ISO string
        n = _note(created=datetime(2026, 1, 1))
        fm = nd.validate("id: abc123def456\ncreated:", n)
        # restored from loaded note rather than rejected
        assert fm["created"] == n.created.isoformat()


# --------------------------------------------------------------------------- #
# Task 3 — write_draft / discard / recover
# --------------------------------------------------------------------------- #
class TestWriteDiscardRecover:
    def test_write_draft_writes_and_reads_back(self, tmp_path):
        md = str(tmp_path / "n.md")
        assert nd.write_draft(md, "id: x1\ntitle: T", "body here") is True
        text = (tmp_path / "n.md.draft").read_text(encoding="utf-8")
        fm, body = parse_markdown(text)
        assert fm["title"] == "T" and "body here" in body

    def test_write_draft_never_raises_returns_false(self, tmp_path):
        # target dir does not exist -> atomic_write_text raises OSError -> caught -> False (P2-5)
        md = str(tmp_path / "nope" / "n.md")
        assert nd.write_draft(md, "id: x1", "b") is False

    def test_discard_removes_draft(self, tmp_path):
        md = str(tmp_path / "n.md")
        (tmp_path / "n.md.draft").write_text("x", encoding="utf-8")
        nd.discard(md)
        assert not (tmp_path / "n.md.draft").exists()

    def test_discard_missing_is_noop(self, tmp_path):
        nd.discard(str(tmp_path / "n.md"))  # no draft -> no raise (P2-4)

    def test_discard_real_oserror_propagates(self, tmp_path):
        # a real OSError (not FileNotFoundError) propagates so no false "discarded" (P2-4)
        import unittest.mock as mock

        md = str(tmp_path / "n.md")
        (tmp_path / "n.md.draft").write_text("x", encoding="utf-8")
        with mock.patch("pathlib.Path.unlink", side_effect=PermissionError("locked")):
            with pytest.raises(OSError):
                nd.discard(md)

    def test_recover_none_when_no_draft(self, tmp_path):
        md = str(tmp_path / "n.md")
        (tmp_path / "n.md").write_text("x", encoding="utf-8")
        assert nd.recover(md).status == "none"

    def test_recover_discards_orphan_when_md_absent(self, tmp_path):
        # .draft exists but .md gone -> discard orphan, none, never recreate .md (P1-3)
        md = str(tmp_path / "n.md")
        (tmp_path / "n.md.draft").write_text("x", encoding="utf-8")
        res = nd.recover(md)
        assert res.status == "none"
        assert not (tmp_path / "n.md.draft").exists()
        assert not (tmp_path / "n.md").exists()

    def test_recover_discards_identical_orphan(self, tmp_path):
        # crash-after-commit: draft == md (normalized) -> silent discard, none (P2-1)
        n = _note(created=datetime(2026, 1, 1), updated=datetime(2026, 1, 2), body="same")
        text = serialize(n)
        md = str(tmp_path / "n.md")
        (tmp_path / "n.md").write_text(text, encoding="utf-8")
        (tmp_path / "n.md.draft").write_text(text + "\n\n", encoding="utf-8")
        res = nd.recover(md)
        assert res.status == "none"
        assert not (tmp_path / "n.md.draft").exists()

    def test_recover_recoverable_when_draft_differs(self, tmp_path):
        n = _note(created=datetime(2026, 1, 1), updated=datetime(2026, 1, 2), body="orig")
        md = str(tmp_path / "n.md")
        (tmp_path / "n.md").write_text(serialize(n), encoding="utf-8")
        n.body = "edited in draft"
        (tmp_path / "n.md.draft").write_text(serialize(n), encoding="utf-8")
        res = nd.recover(md)
        assert res.status == "recoverable"
        assert "edited in draft" in res.draft_text

    def test_recover_is_content_keyed_not_mtime(self, tmp_path):
        # identical content but the draft is NEWER on disk -> still 'none' (content, not mtime).
        # This kills an mtime-based recover() that a timing-only test would let pass (P1-2/P2-1).
        import os

        n = _note(created=datetime(2026, 1, 1), updated=datetime(2026, 1, 2), body="same")
        text = serialize(n)
        md = tmp_path / "n.md"
        draft = tmp_path / "n.md.draft"
        md.write_text(text, encoding="utf-8")
        draft.write_text(text, encoding="utf-8")
        base = md.stat().st_mtime
        os.utime(md, (base, base))
        os.utime(draft, (base + 50, base + 50))     # draft strictly newer
        assert nd.recover(str(md)).status == "none"

    def test_recover_recoverable_even_when_draft_is_older(self, tmp_path):
        # different content but the draft is OLDER -> still 'recoverable' (content, not mtime).
        import os

        n = _note(created=datetime(2026, 1, 1), updated=datetime(2026, 1, 2), body="disk")
        md = tmp_path / "n.md"
        draft = tmp_path / "n.md.draft"
        md.write_text(serialize(n), encoding="utf-8")
        n.body = "older draft edit"
        draft.write_text(serialize(n), encoding="utf-8")
        base = md.stat().st_mtime
        os.utime(md, (base, base))
        os.utime(draft, (base - 50, base - 50))     # draft strictly older
        assert nd.recover(str(md)).status == "recoverable"


# --------------------------------------------------------------------------- #
# Task 4 — detect_external_change
# --------------------------------------------------------------------------- #
class TestDetectExternal:
    def test_unchanged_when_hash_matches(self, tmp_path):
        md = tmp_path / "n.md"
        md.write_text("hello", encoding="utf-8")
        base = nd.content_hash("hello")
        assert nd.detect_external_change(str(md), base) == "unchanged"

    def test_changed_when_content_differs(self, tmp_path):
        md = tmp_path / "n.md"
        md.write_text("changed externally", encoding="utf-8")
        base = nd.content_hash("the original")
        assert nd.detect_external_change(str(md), base) == "changed"

    def test_source_missing_when_deleted(self, tmp_path):
        md = tmp_path / "gone.md"
        assert nd.detect_external_change(str(md), nd.content_hash("x")) == "source_missing"


# --------------------------------------------------------------------------- #
# Task 5 — promote orchestration
# --------------------------------------------------------------------------- #
class TestPromote:
    def test_promote_commits_body_and_emits_note(self, tmp_path):
        store = NoteStore(tmp_path)
        n = store.create("Title", body="orig body")
        fm_text = serialize(n).split("---")[1].strip()
        nd.write_draft(n.path, fm_text, "new body")
        out = nd.promote(store, n.id, fm_text, "new body", fm_edited=False)
        assert out.body == "new body"
        from pathlib import Path

        _, body = parse_markdown(Path(n.path).read_text(encoding="utf-8"))
        assert "new body" in body

    def test_promote_purged_id_raises_and_does_not_recreate(self, tmp_path):
        store = NoteStore(tmp_path)
        n = store.create("Title", body="b")
        path = n.path
        store.purge(n.id)
        with pytest.raises(nd.NoteSourceMissing):
            nd.promote(store, n.id, "id: %s" % n.id, "b", fm_edited=False)
        from pathlib import Path

        assert not Path(path).exists()

    def test_promote_fm_not_edited_carries_live_metadata(self, tmp_path):
        # fm_edited=False -> pin/color/tags come from the live note, not a stale draft (P2-16)
        store = NoteStore(tmp_path)
        n = store.create("Title", body="b", tags=["alpha"], color="violet")
        store.set_pinned(n.id, True)
        store.set_color(n.id, "sky")
        # a stale fm that would clobber if applied
        stale_fm = "id: %s\ntitle: Title\ntags:\n- WRONG\npinned: false\ncolor: rose" % n.id
        out = nd.promote(store, n.id, stale_fm, "new body", fm_edited=False)
        assert out.pinned is True
        assert out.color == "sky"
        assert out.tags == ["alpha"]
        assert out.body == "new body"

    def test_promote_fm_edited_applies_edited_keys(self, tmp_path):
        store = NoteStore(tmp_path)
        n = store.create("Title", body="b", tags=["alpha"])
        fm = "id: %s\ntitle: Renamed\ntags:\n- beta\npinned: true" % n.id
        out = nd.promote(store, n.id, fm, "body2", fm_edited=True)
        assert out.title == "Renamed"
        assert out.tags == ["beta"]
        assert out.pinned is True

    def test_promote_preserves_live_deleted(self, tmp_path):
        # the store's deleted flag is never silently un-trashed (P2-16)
        store = NoteStore(tmp_path)
        n = store.create("Title", body="b")
        store.soft_delete(n.id)
        out = nd.promote(store, n.id, "id: %s\ntitle: Title" % n.id, "edited", fm_edited=False)
        assert out.deleted is True

    def test_promote_deletes_draft_only_after_success(self, tmp_path):
        store = NoteStore(tmp_path)
        n = store.create("Title", body="b")
        fm_text = serialize(n).split("---")[1].strip()
        nd.write_draft(n.path, fm_text, "new body")
        assert nd.draft_path(n.path)
        from pathlib import Path

        assert Path(nd.draft_path(n.path)).exists()
        nd.promote(store, n.id, fm_text, "new body", fm_edited=False)
        assert not Path(nd.draft_path(n.path)).exists()

    def test_promote_applies_edited_created(self, tmp_path):
        # a deliberate raw-YAML created edit reaches disk (P2-6); not silently dropped
        store = NoteStore(tmp_path)
        n = store.create("Title", body="b")
        fm = "id: %s\ntitle: Title\ncreated: 2020-05-04T00:00:00" % n.id
        out = nd.promote(store, n.id, fm, "body2", fm_edited=True)
        assert out.created == datetime(2020, 5, 4, 0, 0, 0)

    def test_promote_backs_up_corrupt_original(self, tmp_path):
        # on-disk .md has a fence but no usable id -> preserve original bytes before overwrite (P1-7)
        from pathlib import Path

        store = NoteStore(tmp_path)
        n = store.create("Title", body="b")
        orig_bytes = "---\ntitle: x\n---\n\nold body\n"
        Path(n.path).write_text(orig_bytes, encoding="utf-8")
        nd.promote(store, n.id, "id: %s\ntitle: Title" % n.id, "new body", fm_edited=False)
        sibs = list(Path(n.path).parent.glob(Path(n.path).name + ".corrupt-*"))
        assert len(sibs) == 1 and sibs[0].read_text(encoding="utf-8") == orig_bytes
        fm, body = parse_markdown(Path(n.path).read_text(encoding="utf-8"))
        assert fm["id"] == n.id and "new body" in body

    def test_promote_invalid_yaml_raises_and_keeps_md(self, tmp_path):
        store = NoteStore(tmp_path)
        n = store.create("Title", body="orig")
        from pathlib import Path

        before = Path(n.path).read_text(encoding="utf-8")
        with pytest.raises(nd.NoteDraftInvalid):
            nd.promote(store, n.id, "id: [unclosed", "x", fm_edited=True)
        assert Path(n.path).read_text(encoding="utf-8") == before

    def test_promote_write_failure_raises_note_write_failed(self, tmp_path):
        import unittest.mock as mock

        store = NoteStore(tmp_path)
        n = store.create("Title", body="b")
        fm_text = serialize(n).split("---")[1].strip()
        nd.write_draft(n.path, fm_text, "new body")
        with mock.patch(
            "serenity.core.note_store.atomic_write_text", side_effect=PermissionError("locked")
        ):
            with pytest.raises(nd.NoteWriteFailed):
                nd.promote(store, n.id, fm_text, "new body", fm_edited=False)
        # draft kept on failure
        from pathlib import Path

        assert Path(nd.draft_path(n.path)).exists()

    def test_promote_index_failure_non_fatal(self, tmp_path):
        # the disposable index step failing must NOT fail the commit (P3-1)
        import unittest.mock as mock

        store = NoteStore(tmp_path)
        n = store.create("Title", body="b")
        fm_text = serialize(n).split("---")[1].strip()
        with mock.patch.object(store, "_index_note", side_effect=Exception("db boom")):
            out = nd.promote(store, n.id, fm_text, "new body", fm_edited=False)
        assert out.body == "new body"
        from pathlib import Path

        _, body = parse_markdown(Path(n.path).read_text(encoding="utf-8"))
        assert "new body" in body
