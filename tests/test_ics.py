from serenity.core import ics

def test_escape_unescape_roundtrip():
    s = 'Meet; plan A, B \\ done\nline2'
    esc = ics._escape_text(s)
    assert ";" not in esc.replace("\\;", "") and "\\n" in esc
    assert ics._unescape_text(esc) == s.replace("\r", "")

def test_fold_respects_75_octets_and_unfolds_clean():
    line = "SUMMARY:" + "x" * 200
    folded = ics._fold(line)
    assert all(len(seg.encode()) <= 75 for seg in folded.split("\r\n"))
    assert ics._unfold(folded) == line

def test_fold_never_splits_a_multibyte_char():
    line = "SUMMARY:" + "ü" * 60          # 2 bytes each
    folded = ics._fold(line)
    for seg in folded.split("\r\n "):
        seg.encode("utf-8")               # must not raise / be valid utf-8
    assert ics._unfold(folded) == line
