"""
============================================================
Author:  Berk
Created: 2026-06-20
Purpose: On-demand tag consolidation: detect variant / near-spelling tags + rewrite them
         to one canonical tag across the whole vault.
Role:    Backs the Notes tab "Tidy tags" maintenance action (Job 5). Pure Python, no Qt.
         Scans the active note vault (and, optionally, the settings tag-arsenal) for GROUPS
         of tags that are spelling variants of each other (case differences, diacritics,
         separators, obvious plurals, small typos), then lets the UI CONSOLIDATE a group
         into one canonical tag - rewriting every affected note's .tags and the arsenal.

         This is a DETERMINISTIC, MODEL-FREE feature. Tag names are short strings; we cluster
         them by string similarity (normalize: casefold + diacritic-fold + separator-collapse
         + light singular/plural fold, then identical-normalized-form OR difflib ratio), NOT
         by embeddings (the Job-14 index embeds note BODIES, useless for tag-name similarity).
         stdlib only (difflib, unicodedata, collections.Counter); no new deps. Fully
         verifiable in this env (no "needs a machine" caveat).

         OVER-MERGE GUARDS: short tags (e.g. cat / car) must NOT merge, so the ratio path is
         gated by a minimum shared prefix, a stricter ratio for short tags, and a minimum tag
         length. Identical NORMALIZED forms (Work/work/WORK, proj/Proj) always merge - a
         casefold/diacritic/plural collision is unambiguous and bypasses the ratio guards.

         DATA SAFETY: consolidate_tag is a bulk mutation of many notes. It ONLY ever rewrites
         the .tags field - NEVER the body, title, color or pin. It preserves a note's
         unrelated tags and their order, does not crash on a note that holds none of the
         variants, and is IDEMPOTENT (safe to run twice; a second run is a no-op). There is
         NO trash-style undo for tag edits, so the UI MUST confirm before applying. The note's
         `updated` timestamp WILL change for notes that actually change (it is a real edit).

Functions:
- normalize(tag) -> str - the single deterministic clustering key
- suggest_tag_groups(notes, arsenal=None) -> list[TagGroup] - the scan
- consolidate_tag(store, settings, canonical, variants) -> int - rewrite affected notes

Classes:
- TagGroup - a suggested group: canonical tag + the variant tags to fold in + note count
============================================================
"""

from __future__ import annotations

import difflib
import unicodedata
from collections import Counter
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Named threshold constants (tuned + documented). Tag names are short, so the
# guards lean strict to avoid over-merging unrelated short words.
# --------------------------------------------------------------------------- #
SIM_RATIO = 0.82          # difflib ratio on NORMALIZED forms >= this -> same group (general)
SHORT_LEN = 4             # a normalized tag with len <= this is "short" -> strict gate
SHORT_SIM_RATIO = 0.90    # short tags must clear THIS higher ratio (cat/car @0.667, dog/cog never merge)
MIN_SHARED_PREFIX = 2     # two tags must share >= this many leading chars (normalized) to ratio-merge
MIN_TAG_LEN = 2           # ignore tags whose STRIPPED surface form is shorter than this (too noisy)
MAX_GROUPS = 50           # cap returned groups (sane top-N for the dialog)
# Identical-normalized-form ALWAYS merges - it bypasses the ratio + prefix guards because a
# casefold/diacritic/plural collision (Work/work, proj/Proj, cafe/cafe-with-accent) is unambiguous.

# Explicit German fold map applied BEFORE the NFKD combining-mark strip, so umlauts/ß fold
# predictably (ae->a style, matching casefold-style folding; ß->ss). The only locale nuance.
_FOLD_MAP = {"ä": "a", "ö": "o", "ü": "u", "ß": "ss"}


@dataclass(frozen=True)
class TagGroup:
    """A suggested group of variant tags to consolidate into one canonical tag.

    The full member set is ``{canonical} | set(variants)``; ``canonical`` is NOT in
    ``variants``. ``canonical`` and ``variants`` are ORIGINAL surface forms (not normalized).
    ``note_count`` is the number of distinct ACTIVE notes containing ANY member tag - an
    informational estimate for the whole group. The authoritative per-Apply changed-count is
    ``consolidate_tag``'s return value (the UI may edit the canonical before applying)."""

    canonical: str
    variants: tuple[str, ...]
    note_count: int

    @property
    def all_tags(self) -> tuple[str, ...]:
        """Full member list, canonical first then variants (convenience for the UI)."""
        return (self.canonical,) + self.variants


def normalize(tag: str) -> str:
    """The single deterministic clustering KEY for a tag (may be "").

    Steps, in order:
      1. strip surrounding whitespace
      2. casefold
      3. German fold map (ä->a, ö->o, ü->u, ß->ss), then NFKD + drop combining marks
         (so café -> cafe, straße -> strasse, projektä -> projekta)
      4. collapse separator runs [-_ \\t...] -> "" so co-op / coop / co op share a key
         (surface forms are preserved elsewhere; only the KEY collapses)
      5. light, conservative English-ish singular/plural fold (KEY only):
           - "ies" (len>4)            -> "y"   (categories -> category)
           - sibilant "es" (len>3)    -> ""    (boxes -> box, wishes -> wish, classes -> class)
                                                only after s/x/z or ch/sh, so the e is the plural
                                                "e" (NOT notes -> not / pages -> pag)
           - trailing "s", not "ss", (len>3), char-before-s not in "uiosywn" -> drop the s
                                                (works -> work, notes -> note; NOT css / less,
                                                NOT status / focus / axis / news / lens, so a
                                                singular noun ending in -s keeps a distinct key)
         Intentionally minimal (no stemmer, no deps); the len/ss/sibilant guards avoid
         over-stemming. A tag whose normalize() == "" is dropped from clustering."""
    s = (tag or "").strip()
    if not s:
        return ""
    s = s.casefold()
    # German fold first so the explicit map wins over NFKD's decomposition.
    for src, dst in _FOLD_MAP.items():
        if src in s:
            s = s.replace(src, dst)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # Keep alphanumerics only for the KEY: this collapses separators (co-op/co op -> coop) and
    # drops stray punctuation (a bare "#" or "@tag" prefix), so a "#"-only tag keys to "".
    s = "".join(c for c in s if c.isalnum())
    if not s:
        return ""
    # Light singular/plural fold (key only).
    if s.endswith("ies") and len(s) > 4:
        s = s[:-3] + "y"
    elif s.endswith("es") and len(s) > 3 and (s[-3] in "sxz" or s[-4:-2] in ("ch", "sh")):
        s = s[:-2]   # sibilant plural: boxes -> box, wishes -> wish, classes -> class
    elif s.endswith("s") and not s.endswith("ss") and len(s) > 3 and s[-2] not in "uiosywn":
        # simple plural: works -> work, notes -> note. The char-before-s guard (uiosywn) keeps
        # singular nouns ending in -s intact: NOT css/less (ss), NOT status/focus/bonus (us),
        # NOT axis/analysis (is), NOT news (ws), NOT lens (ns) - so news != new, lens != len and
        # they never form a bogus plural collision (identical-norm always merges, bypassing the
        # ratio + prefix guards, so the key MUST stay distinct).
        s = s[:-1]
    return s


class _DisjointSet:
    """Tiny pure-Python union-find for deterministic clustering of member tags."""

    def __init__(self, items):
        self._parent = {it: it for it in items}

    def find(self, x):
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        # Path compression keeps repeated find() cheap; order-independent.
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def _collect(notes, arsenal):
    """Walk active notes (+ optional arsenal) collecting EVERY surface-form tag.

    Returns (members, freq):
      - members: the set of distinct surface forms that qualify as cluster members
        (stripped len >= MIN_TAG_LEN and normalize() != "").
      - freq: Counter of how many NOTES contain each surface form. A note containing both
        "Work" and "work" counts each surface form once. Used for canonical selection.
    Surface forms differing only by case/diacritic ARE distinct members (so "Work" and "work"
    are two variants the group offers to merge). Arsenal tags are seeded as members with freq 0
    if `arsenal` is passed, so a variant living ONLY in the arsenal still surfaces for cleanup."""
    freq: Counter = Counter()
    members: set = set()

    def consider(tag, count_note):
        surface = (tag or "").strip()
        if len(surface) < MIN_TAG_LEN:
            return
        if not normalize(surface):
            return
        members.add(surface)
        if count_note:
            freq[surface] += 1

    for n in notes:
        if getattr(n, "deleted", False):
            continue
        seen_in_note: set = set()
        for t in (n.tags or []):
            surface = (t or "").strip()
            # Count each distinct surface form once per note.
            if surface in seen_in_note:
                consider(t, count_note=False)
                continue
            seen_in_note.add(surface)
            consider(t, count_note=True)

    if arsenal:
        for t in arsenal:
            consider(t, count_note=False)  # arsenal-only tags contribute 0 to freq

    return members, freq


def _shared_prefix_len(a: str, b: str) -> int:
    """Count of equal leading characters of two strings."""
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def _ratio_merge(a: str, b: str, norm: dict) -> bool:
    """True if two surface forms should be merged via the SIMILARITY path (with guards).

    SIMILARITY: the two normalized forms share >= MIN_SHARED_PREFIX leading chars AND their
    difflib ratio clears SIM_RATIO (or the stricter SHORT_SIM_RATIO when either form is short).
    The shared-prefix + strict-short-ratio guards keep cat/car (ratio 0.667) and dog/cog from
    ever merging. (There is deliberately NO prefix-abbreviation path: a complete short word that
    merely prefixes a longer, unrelated word - work/workspace, note/notebook, read/reading - is
    indistinguishable by any model-free measure from a true abbreviation like proj/project, so
    an abbreviation path over-merges distinct concepts on a no-undo bulk mutation. Data-safety
    and the over-merge guards outrank that one rare recall case. Identical-normalized-form
    collisions - Work/work, project/projekt via the ratio path - still group as before.)"""
    na, nb = norm[a], norm[b]
    if not na or not nb:
        return False
    # Similarity path.
    if _shared_prefix_len(na, nb) < MIN_SHARED_PREFIX:
        return False
    r = difflib.SequenceMatcher(None, na, nb).ratio()
    short = min(len(na), len(nb)) <= SHORT_LEN
    return r >= (SHORT_SIM_RATIO if short else SIM_RATIO)


def suggest_tag_groups(notes, arsenal=None) -> list[TagGroup]:
    """Scan tags for groups of spelling variants to consolidate.

    - notes: iterable of Note (uses .tags, .deleted). Deleted notes are excluded.
    - arsenal: optional list[str] (pass settings.tags) so arsenal-only variants surface.
    - Members are clustered by union-find: an edge joins two members when their NORMALIZED
      forms are IDENTICAL (always merge) OR they pass the guarded similarity path
      (_ratio_merge). Each cluster with >= 2 distinct surface forms becomes a TagGroup;
      SINGLETON clusters (nothing to consolidate) are dropped.
    - Canonical per group: most frequent across notes, tiebreak longest surface, tiebreak
      alphabetical. Variants are the remaining members in the same (freq desc, len desc, alpha)
      order, so the chip order is stable.
    - note_count: distinct active notes whose tags (matched by normalized key) include a member.
    - Returns [] cleanly for empty / one-tag vaults. Deterministic + stable; sorted by
      (note_count desc, canonical casefold, canonical) and capped at MAX_GROUPS."""
    notes = list(notes)
    active = [n for n in notes if not getattr(n, "deleted", False)]
    members_set, freq = _collect(active, arsenal)
    norm = {t: normalize(t) for t in members_set}

    # Deterministic iteration order: by (normalized key, surface form).
    members = sorted(members_set, key=lambda t: (norm[t], t))
    if len(members) < 2:
        return []

    ds = _DisjointSet(members)
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            a, b = members[i], members[j]
            if norm[a] == norm[b] or _ratio_merge(a, b, norm):
                ds.union(a, b)

    # Group members by their union-find root.
    clusters: dict[str, list[str]] = {}
    for m in members:
        clusters.setdefault(ds.find(m), []).append(m)

    def member_sort_key(t):
        # freq desc, len desc, alpha asc -> negate freq and len for ascending sort.
        return (-freq.get(t, 0), -len(t), t)

    # Precompute each active note's normalized key set ONCE (not once per surviving group):
    # note_count is then a cheap set intersection, removing the O(groups x notes x tags)
    # re-normalization blowup. Equivalent to the per-tag membership test (a note is counted iff
    # any of its normalized keys is in the group's keyset).
    note_keys = [{normalize(t) for t in (n.tags or [])} for n in active]

    groups: list[TagGroup] = []
    for root_members in clusters.values():
        if len(root_members) < 2:
            continue  # singleton: nothing to consolidate
        ordered = sorted(root_members, key=member_sort_key)
        canonical = ordered[0]
        variants = tuple(ordered[1:])
        keyset = {norm[t] for t in root_members}
        note_count = sum(1 for ks in note_keys if ks & keyset)
        groups.append(TagGroup(canonical=canonical, variants=variants, note_count=note_count))

    groups.sort(key=lambda g: (-g.note_count, g.canonical.casefold(), g.canonical))
    return groups[:MAX_GROUPS]


def consolidate_tag(store, settings, canonical: str, variants) -> int:
    """Rewrite every active note's variant tags to `canonical`; update the arsenal. Returns the
    count of NOTES actually changed.

    Rewrite rule per note tag `t`:
      - if t == canonical (exact): keep as-is;
      - elif t.lower() in the variant set OR t.lower() == canonical.lower() (a case-only variant
        of the canonical itself): map to the exact `canonical`;
      - else: keep t.
    Only the EXTRA copies that the consolidation itself produces are collapsed (so a note
    holding both a variant and the canonical, e.g. [Work, work, urgent] -> [Work, urgent], does
    not gain a duplicate canonical). Tags NOT mapped to the canonical are preserved exactly,
    including a pre-existing case-duplicate pair unrelated to this group (so an externally
    hand-edited [Foo, foo] survives untouched). store.update is called ONLY for notes that
    actually change (no spurious writes / timestamp churn), which makes a re-run a no-op ==
    IDEMPOTENT. The note body, title, color and pin are NEVER touched. update() bumps the
    changed note's `updated` (expected).

    Arsenal: drop the variants (and any case-variant of the canonical) from settings.tags, then
    add_tags([canonical]) to guarantee the exact canonical is present, then settings.save().
    `settings` is OPTIONAL (None): NotesView documents a settings=None contract, so when settings
    is None the note rewrite still runs and only the arsenal update is skipped - never a crash
    mid-mutation. Defensive: an empty/blank canonical returns 0 and makes no writes (the UI
    prevents this)."""
    canonical = (canonical or "").strip()
    if not canonical:
        return 0

    var_lower = {(v or "").strip().lower() for v in variants if (v or "").strip()}
    canon_lower = canonical.lower()

    def maps_to_canonical(t: str) -> bool:
        tl = t.lower()
        return tl in var_lower or tl == canon_lower

    count = 0
    for note in store.all_active():
        new_tags: list[str] = []
        seen_canon = False
        changed = False
        for t in note.tags:
            if maps_to_canonical(t):
                if t != canonical:
                    changed = True   # a variant (or case-variant) rewritten to canonical
                if seen_canon:
                    changed = True   # drop only the EXTRA mapped copy we just produced
                    continue
                new_tags.append(canonical)
                seen_canon = True
            else:
                new_tags.append(t)   # unrelated tag: preserved exactly (even a case-dup pair)
        if changed:
            note.tags = new_tags
            store.update(note)  # writes .md + reindexes (bumps note.updated); body untouched
            count += 1

    # Arsenal: drop variants + case-variants of the canonical, then ensure canonical present.
    # settings is OPTIONAL (NotesView documents settings=None): when absent we still perform the
    # data-safe note rewrite above and simply skip the arsenal update, instead of crashing
    # mid-mutation (which would leave notes rewritten on disk but the arsenal stale).
    if settings is not None:
        settings.tags = [
            t for t in settings.tags
            if t.lower() not in var_lower and not (t.lower() == canon_lower and t != canonical)
        ]
        settings.add_tags([canonical])  # case-insensitive; canonical guaranteed present
        settings.save()

    return count
