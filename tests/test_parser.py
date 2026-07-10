"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Unit tests for the deterministic capture parser (intent/date/entities).
Role:    Guards the Phase-1 voice grammar: intent keywords, NL dates (DE/EN),
         #tag / @category / mit-with-Person, recurring flags, confidence and the
         missing-slot signal that drives conversational slot-filling.

Test classes:
- TestIntent / TestEntities / TestDates / TestRecurring / TestConfidence
============================================================
"""

from datetime import datetime

from serenity.core.parser import parse_capture, parse_natural_date

NOW = datetime(2026, 6, 19, 10, 0, 0)  # a Friday


class TestIntent:
    def test_todo_keyword(self):
        cap = parse_capture("Todo: buy milk", now=NOW)
        assert cap.intent == "todo"
        assert cap.title.lower().startswith("buy milk")
        assert cap.kind == "todo"

    def test_german_aufgabe(self):
        cap = parse_capture("Aufgabe Milch kaufen", now=NOW)
        assert cap.intent == "todo"
        assert "Milch kaufen" in cap.title

    def test_note_default_when_no_keyword(self):
        cap = parse_capture("random thought about cyberpunk", now=NOW)
        assert cap.intent == "note"
        assert cap.kind == "note"

    def test_idea_intent(self):
        cap = parse_capture("Idee: onboarding flow", now=NOW)
        assert cap.intent == "note_idea"
        assert cap.kind == "note"

    def test_reminder_sets_flag(self):
        cap = parse_capture("Reminder call Tom tomorrow 9am", now=NOW)
        assert cap.intent == "reminder"
        assert cap.reminder is True
        assert cap.kind == "todo"

    def test_meeting_intent(self):
        cap = parse_capture("Meeting with Lena tomorrow 14:00", now=NOW)
        assert cap.intent == "meeting"


class TestEntities:
    def test_hashtag(self):
        cap = parse_capture("Todo finish report #work #urgent", now=NOW)
        assert "work" in cap.tags and "urgent" in cap.tags
        assert "#work" not in cap.title

    def test_category(self):
        cap = parse_capture("Note ideas @ideas", now=NOW)
        assert cap.category == "ideas"
        assert "@ideas" not in cap.title

    def test_person_with(self):
        cap = parse_capture("Meeting with Lena tomorrow", now=NOW)
        assert cap.person == "Lena"

    def test_person_mit(self):
        cap = parse_capture("Termin mit Berk morgen", now=NOW)
        assert cap.person == "Berk"


class TestDates:
    def test_tomorrow(self):
        dt = parse_natural_date("tomorrow", now=NOW)
        assert dt is not None and dt.date() == datetime(2026, 6, 20).date()

    def test_german_morgen(self):
        dt = parse_natural_date("morgen", now=NOW)
        assert dt is not None and dt.date() == datetime(2026, 6, 20).date()

    def test_in_30_min(self):
        dt = parse_natural_date("in 30 minutes", now=NOW)
        assert dt is not None
        assert 25 <= (dt - NOW).total_seconds() / 60 <= 35

    def test_capture_extracts_date_and_time(self):
        cap = parse_capture("Todo call dentist tomorrow 9:00", now=NOW)
        assert cap.date is not None
        assert cap.date.date() == datetime(2026, 6, 20).date()
        assert cap.has_time is True

    def test_no_date_phrase_no_date(self):
        cap = parse_capture("Todo think about the architecture", now=NOW)
        assert cap.date is None

    def test_morgen_uhr_applies_time(self):
        # decisions doc 6.5 example 1: "morgen 17 Uhr" -> tomorrow 17:00
        cap = parse_capture("Erledige Steuerunterlagen sortieren morgen 17 Uhr", now=NOW)
        assert cap.date is not None
        assert cap.date.date() == datetime(2026, 6, 20).date()
        assert cap.date.hour == 17
        assert cap.has_time is True
        # the time should not leak into the title
        assert "uhr" not in cap.title.lower()
        assert "17" not in cap.title

    def test_heute_uhr_applies_time(self):
        cap = parse_capture("Meeting heute 14 Uhr Standup", now=NOW)
        assert cap.date is not None
        assert cap.date.hour == 14
        assert cap.has_time is True
        assert cap.title == "Standup"

    def test_um_uhr_form(self):
        cap = parse_capture("Termin morgen um 8 Uhr Review", now=NOW)
        assert cap.date is not None
        assert cap.date.date() == datetime(2026, 6, 20).date()
        assert cap.date.hour == 8
        assert cap.has_time is True
        assert cap.title == "Review"

    def test_uhr_with_minutes(self):
        cap = parse_capture("Todo call morgen 17:30 Uhr", now=NOW)
        assert cap.date is not None
        assert cap.date.hour == 17 and cap.date.minute == 30
        assert cap.has_time is True


class TestRecurring:
    def test_every_weekday(self):
        cap = parse_capture("Todo standup every weekday 9am", now=NOW)
        assert cap.recurring == "every weekday"

    def test_german_taeglich(self):
        cap = parse_capture("Aufgabe Wasser trinken taeglich", now=NOW)
        assert cap.recurring == "daily"


class TestConfidence:
    def test_keyword_plus_title_is_confident(self):
        cap = parse_capture("Todo buy milk tomorrow", now=NOW)
        assert cap.confidence >= 0.55
        assert "title" not in cap.missing

    def test_empty_input_missing_title(self):
        cap = parse_capture("", now=NOW)
        assert "title" in cap.missing
        assert cap.confidence < 0.55

    def test_meeting_without_date_missing_date(self):
        cap = parse_capture("Meeting standup", now=NOW)
        assert "date" in cap.missing


class TestReminderOffset:
    def test_offset_1_day_before_title_only_en(self):
        cap = parse_capture("remind me 1 day before dentist", now=NOW)
        assert cap.intent == "reminder"
        assert cap.reminder is True
        assert cap.reminder_offset == 1440
        assert cap.title == "dentist"
        assert cap.date is None
        assert "date" in cap.missing

    def test_offset_1_tag_vorher_de(self):
        cap = parse_capture("Erinnerung Zahnarzt morgen 1 Tag vorher", now=NOW)
        assert cap.intent == "reminder"
        assert cap.reminder_offset == 1440
        assert cap.title == "Zahnarzt"
        assert cap.date is not None
        assert cap.date.date() == datetime(2026, 6, 20).date()

    def test_offset_30_minutes_before_with_date_time_en(self):
        cap = parse_capture("remind me 30 minutes before standup tomorrow 9:00", now=NOW)
        assert cap.reminder_offset == 30
        assert "standup" in cap.title
        assert cap.date is not None

    def test_no_offset_when_no_lead_word_en(self):
        cap = parse_capture("reminder call mom tomorrow", now=NOW)
        assert cap.reminder_offset is None
        assert "call mom" in cap.title

    def test_offset_2_weeks_vorher_de(self):
        cap = parse_capture("erinnere mich 2 Wochen vorher", now=NOW)
        assert cap.reminder_offset == 20160
        assert cap.title == ""  # no title, but offset is extracted

    def test_offset_unit_minute_en(self):
        cap = parse_capture("todo call 5 minute before meeting tomorrow 3pm", now=NOW)
        assert cap.reminder_offset == 5
        assert "call" in cap.title.lower()

    def test_offset_unit_hour_en(self):
        cap = parse_capture("remind 1 hour before event", now=NOW)
        assert cap.reminder_offset == 60

    def test_offset_unit_stunde_de(self):
        cap = parse_capture("Erinnerung 2 Stunden vor Termin morgen", now=NOW)
        assert cap.reminder_offset == 120

    def test_offset_unit_minuten_de(self):
        cap = parse_capture("Termin 10 minuten davor", now=NOW)
        assert cap.reminder_offset == 10

    def test_offset_unit_woche_de(self):
        cap = parse_capture("Erinnerung 1 Woche vorher", now=NOW)
        assert cap.reminder_offset == 10080

    def test_offset_unit_day_en(self):
        cap = parse_capture("remind 2 days before event", now=NOW)
        assert cap.reminder_offset == 2880

    def test_offset_phrase_stripped_from_title(self):
        cap = parse_capture("Todo call 3 hours before dentist appointment tomorrow", now=NOW)
        assert cap.reminder_offset == 180
        assert "3 hours before" not in cap.title
        assert "dentist appointment" in cap.title

    def test_offset_in_advance_en(self):
        # "in advance" lead word (English) — the regex supports it but no case drove it.
        cap = parse_capture("remind me 1 day in advance dentist", now=NOW)
        assert cap.reminder_offset == 1440
        assert "dentist" in cap.title
