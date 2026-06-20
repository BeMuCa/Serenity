"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for deterministic tag consolidation (Job 5).
Role:    Guards core.tagsync: the normalize() folds (case / diacritic / German / separator /
         plural), the union-find clustering with its over-merge guards (cat/car must NOT merge),
         canonical selection + tiebreaks, singleton-drop, note_count, arsenal-only members,
         determinism + cap, and consolidate_tag on a real NoteStore (rewrite + case-insensitive
         dedup + order preservation + body-safety + idempotency + arsenal update + empty guard).

Test classes:
- TestNormalize        - the single deterministic clustering key
- TestSuggestGroups    - clustering, guards, canonical, note_count, determinism, cap
- TestConsolidate      - rewrite / dedup / idempotency / body-safety / arsenal on a real store
============================================================
"""

from datetime import datetime

from serenity.core.models import Note
from serenity.core.note_store import NoteStore
from serenity.core.settings import Settings
from serenity.core.tagsync import (
    MAX_GROUPS,
    TagGroup,
    consolidate_tag,
    normalize,
    suggest_tag_groups,
)


def mk(tags, deleted=False, body="body", title="N", nid=None):
    n = Note(title=title, body=body, tags=list(tags), deleted=deleted,
             updated=datetime(2026, 6, 19, 10, 0))
    if nid is not None:
        n.id = nid
    return n


class TestNormalize:
    def test_casefold(self):
        assert normalize("Work") == normalize("work") == normalize("WORK")

    def test_diacritic_and_german_fold(self):
        assert normalize("straße") == normalize("strasse")
        assert normalize("café") == normalize("cafe")
        # Documented German map: ä -> a (casefold-style), ö -> o, ü -> u, ß -> ss.
        assert normalize("Müller") == normalize("muller")
        assert normalize("projektä") == "projekta"
        assert normalize("projekt") == "projekt"

    def test_separator_collapse(self):
        assert normalize("co-op") == normalize("coop") == normalize("co op")
        assert normalize("co_op") == normalize("coop")

    def test_plural_fold(self):
        assert normalize("works") == normalize("work")
        assert normalize("categories") == normalize("category")
        assert normalize("boxes") == normalize("box")
        assert normalize("wishes") == normalize("wish")
        assert normalize("notes") == normalize("note")   # NOT "not"
        assert normalize("pages") == normalize("page")   # NOT "pag"

    def test_plural_guards(self):
        # ss / short-word guards prevent over-stemming.
        assert normalize("css") != normalize("cs")
        assert normalize("less") != normalize("les")
        assert normalize("css") == "css"

    def test_empty(self):
        assert normalize("") == ""
        assert normalize("   ") == ""
        assert normalize("  #  ") == ""   # punctuation-only -> dropped from clustering


class TestSuggestGroups:
    def test_case_variant_group(self):
        # "Work" twice, "work" once, "works" once -> one group; canonical = most frequent.
        notes = [mk(["Work"], nid="a"), mk(["Work"], nid="b"),
                 mk(["work"], nid="c"), mk(["works"], nid="d")]
        groups = suggest_tag_groups(notes)
        assert len(groups) == 1
        g = groups[0]
        assert g.canonical == "Work"                      # freq 2 beats work/works (freq 1)
        assert set(g.variants) == {"work", "works"}
        assert g.note_count == 4

    def test_spelling_group_clusters(self):
        notes = [mk(["proj"], nid="a"), mk(["projekt"], nid="b"),
                 mk(["project"], nid="c"), mk(["project"], nid="d")]
        groups = suggest_tag_groups(notes)
        assert len(groups) == 1
        assert set(groups[0].all_tags) == {"proj", "projekt", "project"}

    def test_over_merge_guard_short_tags(self):
        # cat/car ratio 0.667 < SHORT_SIM_RATIO; dog/cog share no prefix -> NO groups.
        assert suggest_tag_groups([mk(["cat"], nid="a"), mk(["car"], nid="b")]) == []
        assert suggest_tag_groups([mk(["dog"], nid="a"), mk(["cog"], nid="b")]) == []

    def test_over_merge_guard_prefix_abbrev(self):
        # idea/ideal: clean prefix but only +1 char -> below ABBREV_MIN_EXT -> NOT merged.
        assert suggest_tag_groups([mk(["idea"], nid="a"), mk(["ideal"], nid="b")]) == []

    def test_different_prefix_high_ratio_not_merged(self):
        # Same length, no shared leading chars -> shared-prefix guard blocks merge.
        assert suggest_tag_groups([mk(["abcd"], nid="a"), mk(["xbcd"], nid="b")]) == []

    def test_singletons_dropped(self):
        notes = [mk(["alpha"], nid="a"), mk(["beta"], nid="b"), mk(["gamma"], nid="c")]
        assert suggest_tag_groups(notes) == []

    def test_empty_and_one_tag_vault(self):
        assert suggest_tag_groups([]) == []
        assert suggest_tag_groups([mk(["only"], nid="x")]) == []
        assert suggest_tag_groups([mk([], nid="x")]) == []

    def test_deleted_excluded(self):
        # A deleted note's "work" does not count; only the active "Work" + "works" remain.
        notes = [mk(["Work"], nid="a"), mk(["works"], nid="b"),
                 mk(["work"], nid="c", deleted=True)]
        groups = suggest_tag_groups(notes)
        assert len(groups) == 1
        g = groups[0]
        assert set(g.all_tags) == {"Work", "works"}
        assert g.note_count == 2                          # the deleted note excluded

    def test_arsenal_only_variant_surfaces(self):
        # "projekt" lives only in the arsenal; notes use "project" -> they still group and
        # projekt joins even though no note uses it (note_count counts only note members).
        notes = [mk(["project"], nid="a"), mk(["project"], nid="b")]
        groups = suggest_tag_groups(notes, arsenal=["projekt", "Other"])
        assert len(groups) == 1
        g = groups[0]
        assert "projekt" in g.all_tags and "project" in g.all_tags
        assert g.note_count == 2                          # arsenal-only projekt adds 0

    def test_determinism(self):
        notes = [mk(["Work"], nid="a"), mk(["work"], nid="b"), mk(["works"], nid="c"),
                 mk(["proj"], nid="d"), mk(["project"], nid="e")]
        assert suggest_tag_groups(notes) == suggest_tag_groups(notes)

    def test_cap_at_max_groups(self):
        # Build > MAX_GROUPS distinct variant groups (each a stem + its plural). The stems are
        # mutually dissimilar (different leading chars / structure) so they never cross-merge,
        # while stem and stem+"s" share a normalized form and always group.
        stems = [f"{c}{v}qz{c}" for c in "bcdfghjklmnpqrstvwxyz" for v in "aeiou"]
        stems = stems[:MAX_GROUPS + 5]
        notes = []
        for i, stem in enumerate(stems):
            notes.append(mk([stem], nid=f"{i}a"))
            notes.append(mk([stem + "s"], nid=f"{i}b"))
        groups = suggest_tag_groups(notes)
        assert len(groups) == MAX_GROUPS

    def test_canonical_tiebreak_length(self):
        # Equal freq (1 each) -> the LONGER surface form wins as canonical.
        notes = [mk(["proj"], nid="a"), mk(["project"], nid="b")]
        groups = suggest_tag_groups(notes)
        assert len(groups) == 1
        assert groups[0].canonical == "project"

    def test_canonical_tiebreak_alpha(self):
        # Equal freq (1 each) AND equal length (4) -> alphabetically first wins. "WOrk" and
        # "Work" share a normalized form (always merge); sorted() puts uppercase 'O' before
        # lowercase 'o', so "WOrk" is the canonical.
        notes = [mk(["WOrk"], nid="a"), mk(["Work"], nid="b")]
        groups = suggest_tag_groups(notes)
        assert len(groups) == 1
        assert groups[0].canonical == "WOrk"
        assert groups[0].variants == ("Work",)


class TestConsolidate:
    def _store(self, tmp_path):
        return NoteStore(tmp_path)

    def _settings(self, tmp_path, tags):
        s = Settings()
        s._path = tmp_path / "settings.json"
        s.tags = list(tags)
        return s

    def test_basic_rewrite_and_order_preserved(self, tmp_path):
        store = self._store(tmp_path)
        store.create("A", tags=["proj"])
        store.create("B", tags=["alpha", "projekt", "beta"])
        store.create("C", tags=["projekt"])
        settings = self._settings(tmp_path, ["proj", "projekt"])
        n = consolidate_tag(store, settings, "project", ["proj", "projekt"])
        assert n == 3
        for note in store.all_active():
            assert "project" in note.tags
            assert "proj" not in note.tags and "projekt" not in note.tags
        # Unrelated tags survive IN ORDER.
        b = [x for x in store.all_active() if x.title == "B"][0]
        assert b.tags == ["alpha", "project", "beta"]

    def test_body_untouched(self, tmp_path):
        store = self._store(tmp_path)
        note = store.create("A", body="the original body text", tags=["proj"])
        settings = self._settings(tmp_path, ["proj"])
        consolidate_tag(store, settings, "project", ["proj"])
        reread = store.get(note.id)
        assert reread.body == "the original body text"
        # And the on-disk markdown body is unchanged.
        from pathlib import Path
        raw = Path(reread.path).read_text(encoding="utf-8")
        assert "the original body text" in raw

    def test_case_insensitive_dedup(self, tmp_path):
        store = self._store(tmp_path)
        note = store.create("A", tags=["Work", "work", "urgent"])
        settings = self._settings(tmp_path, ["Work", "work", "urgent"])
        n = consolidate_tag(store, settings, "Work", ["work"])
        assert n == 1
        assert store.get(note.id).tags == ["Work", "urgent"]

    def test_no_variant_note_skipped(self, tmp_path):
        store = self._store(tmp_path)
        target = store.create("A", tags=["proj"])
        bystander = store.create("B", tags=["unrelated"])
        before = bystander.updated
        settings = self._settings(tmp_path, ["proj", "unrelated"])
        n = consolidate_tag(store, settings, "project", ["proj"])
        assert n == 1                                     # only the proj note changed
        assert store.get(bystander.id).updated == before  # bystander not re-written
        assert store.get(bystander.id).tags == ["unrelated"]

    def test_idempotent(self, tmp_path):
        store = self._store(tmp_path)
        note = store.create("A", tags=["proj", "keep"])
        settings = self._settings(tmp_path, ["proj", "keep"])
        first = consolidate_tag(store, settings, "project", ["proj"])
        assert first == 1
        after_first = store.get(note.id).updated
        tags_after_first = list(store.get(note.id).tags)
        arsenal_after_first = list(settings.tags)
        second = consolidate_tag(store, settings, "project", ["proj"])
        assert second == 0                                # nothing left to map
        assert store.get(note.id).updated == after_first  # no write second time
        assert store.get(note.id).tags == tags_after_first
        assert settings.tags == arsenal_after_first

    def test_arsenal_update_and_persisted(self, tmp_path):
        store = self._store(tmp_path)
        store.create("A", tags=["proj"])
        settings = self._settings(tmp_path, ["proj", "projekt", "Other"])
        consolidate_tag(store, settings, "project", ["proj", "projekt"])
        assert "proj" not in settings.tags and "projekt" not in settings.tags
        assert "project" in settings.tags
        assert "Other" in settings.tags
        # save() persisted: reload from the same path.
        reloaded = Settings.load(settings._path)
        assert "project" in reloaded.tags
        assert "proj" not in reloaded.tags and "projekt" not in reloaded.tags
        assert "Other" in reloaded.tags

    def test_empty_canonical_guard(self, tmp_path):
        store = self._store(tmp_path)
        note = store.create("A", tags=["proj"])
        before = note.updated
        settings = self._settings(tmp_path, ["proj"])
        assert consolidate_tag(store, settings, "", ["proj"]) == 0
        assert consolidate_tag(store, settings, "   ", ["proj"]) == 0
        assert store.get(note.id).tags == ["proj"]        # untouched
        assert store.get(note.id).updated == before
        assert settings.tags == ["proj"]                  # arsenal untouched

    def test_case_only_canonical_normalization(self, tmp_path):
        store = self._store(tmp_path)
        note = store.create("A", tags=["work"])
        settings = self._settings(tmp_path, ["work"])
        # canonical differs only by case from the existing tag; variants empty.
        n = consolidate_tag(store, settings, "Work", [])
        assert n == 1
        assert store.get(note.id).tags == ["Work"]
        assert "Work" in settings.tags and "work" not in settings.tags


class TestTagGroup:
    def test_all_tags_canonical_first(self):
        g = TagGroup(canonical="project", variants=("proj", "projekt"), note_count=3)
        assert g.all_tags == ("project", "proj", "projekt")
