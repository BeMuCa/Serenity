"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: Unit tests for tag parsing (#tags) feeding the learning tag arsenal.
Role:    Guards the two halves of the tag feature together: the parser pulling #tags out
         of a capture (core.parser) and Settings.add_tags growing/persisting the arsenal
         (core.settings, decisions doc 4c). Covers cases the basic store test does not:
         umlaut tags, hyphenated tags, dedupe across parse+add, ordering, persistence.

Test classes:
- TestTagParsing - what the parser extracts as #tags (and strips from the title)
- TestArsenalGrowth - add_tags dedupe / whitespace / ordering / persistence
- TestParseFeedsArsenal - the end-to-end parse-then-grow flow
============================================================
"""

from datetime import datetime

from serenity.core.parser import BASIC_TAGS, parse_capture
from serenity.core.settings import Settings

NOW = datetime(2026, 6, 19, 10, 0, 0)


class TestTagParsing:
    def test_multiple_tags(self):
        cap = parse_capture("Todo ship release #work #urgent #q3", now=NOW)
        assert cap.tags == ["work", "urgent", "q3"]

    def test_tags_stripped_from_title(self):
        cap = parse_capture("Todo ship release #work #urgent", now=NOW)
        assert "#work" not in cap.title and "#urgent" not in cap.title
        assert "ship release" in cap.title

    def test_umlaut_tag(self):
        cap = parse_capture("Aufgabe Steuer #steuerklärung", now=NOW)
        assert "steuerklärung" in cap.tags

    def test_hyphenated_tag(self):
        cap = parse_capture("Todo plan #q3-launch", now=NOW)
        assert "q3-launch" in cap.tags

    def test_no_tags(self):
        cap = parse_capture("Todo just a plain task", now=NOW)
        assert cap.tags == []


class TestArsenalGrowth:
    def test_starts_with_eight_basics(self):
        s = Settings()
        assert s.tags == list(BASIC_TAGS)
        assert len(BASIC_TAGS) == 8

    def test_adds_new_tag(self):
        s = Settings()
        grew = s.add_tags(["Garden"])
        assert grew is True
        assert "Garden" in s.tags

    def test_case_insensitive_dedupe(self):
        s = Settings()
        grew = s.add_tags(["work", "WORK", "Work"])      # all dup of basic "Work"
        assert grew is False
        assert sum(1 for t in s.tags if t.lower() == "work") == 1

    def test_dedupe_within_one_call(self):
        s = Settings()
        s.add_tags(["Garden", "garden", "GARDEN"])
        assert sum(1 for t in s.tags if t.lower() == "garden") == 1

    def test_blank_and_whitespace_ignored(self):
        s = Settings()
        before = list(s.tags)
        grew = s.add_tags(["", "   ", None])
        assert grew is False
        assert s.tags == before

    def test_preserves_insertion_order(self):
        s = Settings()
        s.add_tags(["Alpha", "Beta"])
        assert s.tags[-2:] == ["Alpha", "Beta"]

    def test_growth_persists(self, tmp_path):
        path = tmp_path / "settings.json"
        s = Settings.load(path)
        s.add_tags(["Garden", "Drone"])
        s.save()
        reloaded = Settings.load(path)
        assert "Garden" in reloaded.tags and "Drone" in reloaded.tags


class TestParseFeedsArsenal:
    def test_capture_tags_grow_the_arsenal(self):
        s = Settings()
        cap = parse_capture("Todo water garden #garden #outdoor", now=NOW)
        grew = s.add_tags(cap.tags)
        assert grew is True
        assert "garden" in s.tags and "outdoor" in s.tags

    def test_capture_with_only_known_tags_does_not_grow(self):
        s = Settings()
        cap = parse_capture("Todo pay bills #finance", now=NOW)   # "Finance" is a basic
        grew = s.add_tags(cap.tags)
        assert grew is False
        assert sum(1 for t in s.tags if t.lower() == "finance") == 1
