"""Qudratullah 15-line mushaf LINE map (QUL Mushaf Layout #12).

`data/qudratullah-indopak-15-lines.db` carries the full line table of the
standard subcontinent 15-line mushaf: every page's lines, each line's
type (`ayah` / `surah_name` / `basmallah`), its centring flag, and the
range of global word ids it holds. `indopak_pages` already distils that
down to one page number per ayah; this module keeps the LINE resolution,
which is what a fixed mushaf layout needs.

Word-id model
-------------
Identical to `tools/build_indopak_pagemap.py` (verified 2026-07-11,
re-asserted on every run here): the db's word ids are globally sequential
in reading order, each ayah spanning ``api_word_count + 1`` ids — the +1
being the end-of-ayah marker, which QUL stores as a word row — except
2:181, 8:6 and 13:37, where QUL splits the joined pair بَعْدَ مَا into two
words. 77,429 words + 6,236 markers + 3 splits = 83,668 ids.

Those 3 split words are the only place a single DISPLAY token spans two
QUL ids. All three sit comfortably inside one line (checked by
``_assert_model``), so no rendered word ever has to straddle a line break.

Pages 1, 2 and 610 hold 8, 8 and 10 lines; the other 607 hold 15. That
comes straight from the db — short pages are data, not a special case.
"""

import bisect
import sqlite3
from functools import lru_cache
from pathlib import Path

from ..models import Mushaf

TOTAL_PAGES = 610
TOTAL_WORD_IDS = 83668

# (surah, ayah) -> extra QUL word ids beyond api_word_count + 1.
_EXTRA_IDS = {(2, 181): 1, (8, 6): 1, (13, 37): 1}
# 1-based index of the display token that QUL splits in those 3 ayahs.
# Same positions as _INDOPAK_API_JOINS in quran_api (the joined pair).
_SPLIT_AT = {(2, 181): 3, (8, 6): 4, (13, 37): 8}

_DB_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "qudratullah-indopak-15-lines.db"
)


@lru_cache(maxsize=1)
def _load_layout() -> tuple[list[tuple], list[tuple]]:
    """Return (ayah_lines, all_lines) from the QUL layout db.

    ayah_lines: (first_id, last_id, page, line, centered) sorted by id.
    all_lines:  (page, line, type, centered, surah_number) in reading order.
    """
    if not _DB_PATH.exists():
        raise FileNotFoundError(
            f"{_DB_PATH} missing — the fixed IndoPak layout needs the QUL "
            "15-line mushaf export (qul.tarteel.ai/resources/mushaf-layout/12)."
        )
    con = sqlite3.connect(_DB_PATH)
    ayah_lines = [
        (int(f), int(last), p, ln, bool(c))
        for f, last, p, ln, c in con.execute(
            "SELECT first_word_id, last_word_id, page_number, line_number,"
            " is_centered FROM pages WHERE line_type='ayah'"
            " ORDER BY first_word_id"
        )
    ]
    all_lines = [
        (p, ln, t, bool(c), s)
        for p, ln, t, c, s in con.execute(
            "SELECT page_number, line_number, line_type, is_centered,"
            " surah_number FROM pages ORDER BY page_number, line_number"
        )
    ]
    con.close()

    # The ayah lines must tile 1..TOTAL_WORD_IDS with no gap or overlap.
    prev = 0
    for first, last, _, _, _ in ayah_lines:
        if first != prev + 1:
            raise ValueError(f"layout id gap: {prev} -> {first}")
        prev = last
    if prev != TOTAL_WORD_IDS:
        raise ValueError(f"layout ends at id {prev}, expected {TOTAL_WORD_IDS}")
    return ayah_lines, all_lines


def _first_ids(mushaf: Mushaf) -> dict[tuple[int, int], int]:
    """Global first word id per ayah, from this mushaf's own word counts."""
    first: dict[tuple[int, int], int] = {}
    g = 1
    for surah in mushaf.surahs:
        for ayah in surah.ayahs:
            key = (surah.number, ayah.ayah_number)
            first[key] = g
            g += len(ayah.words) + 1 + _EXTRA_IDS.get(key, 0)
    if g - 1 != TOTAL_WORD_IDS:
        raise ValueError(
            f"word-id model drift: {g - 1} ids from this mushaf, expected "
            f"{TOTAL_WORD_IDS}. The fixed layout needs word-level data for "
            "every ayah (build with the IndoPak word fetch enabled)."
        )
    return first


def _token_ids(surah_num: int, ayah_num: int, n_words: int, base: int) -> list[int]:
    """Global ids for an ayah's display tokens: n_words, then the marker.

    A split ayah's joined token owns two consecutive ids; it is listed
    under the first, and everything after it shifts up by one.
    """
    key = (surah_num, ayah_num)
    split_at = _SPLIT_AT.get(key) if key in _EXTRA_IDS else None
    ids = []
    for j in range(n_words):
        shift = 1 if split_at is not None and j >= split_at else 0
        ids.append(base + j + shift)
    ids.append(base + n_words + _EXTRA_IDS.get(key, 0))  # end marker
    return ids



def _bucket_tokens(mushaf: Mushaf, ayah_lines: list[tuple],
                   starts: list[int]) -> dict[tuple[int, int], list[dict]]:
    """Every display token of the mushaf, bucketed by the line it sits on.

    Shared by both layout builders so there is exactly one place where a
    global word id turns into "this token, on this page, on this line".
    """
    first_ids = _first_ids(mushaf)

    def line_of(gid: int) -> tuple[int, int]:
        first, last, page, line, _ = ayah_lines[bisect.bisect_right(starts, gid) - 1]
        if not first <= gid <= last:
            raise ValueError(f"word id {gid} outside every layout line")
        return page, line

    buckets: dict[tuple[int, int], list[dict]] = {}
    for surah in mushaf.surahs:
        for ayah in surah.ayahs:
            base = first_ids[(surah.number, ayah.ayah_number)]
            ids = _token_ids(
                surah.number, ayah.ayah_number, len(ayah.words), base
            )
            tokens = [
                {"kind": "word", "text": w.text, "surah": surah.number,
                 "ayah": ayah.ayah_number,
                 "hizb": ayah.hizb_marker and w.position == 1,
                 # Needed by the margin signs: a manzil opens on the
                 # line that carries its first word, not its last.
                 "position": w.position,
                 "translation": False}
                for w in ayah.words
            ]
            tokens.append({
                "kind": "end", "text": ayah.ayah_marker,
                "surah": surah.number, "ayah": ayah.ayah_number,
                "hizb": False, "position": 0,
                # The popup variant turns a marker into a noteref only
                # where a translation note actually exists.
                "translation": bool(ayah.translation),
            })
            for gid, tok in zip(ids, tokens, strict=True):
                buckets.setdefault(line_of(gid), []).append(tok)

    _assert_model(buckets, ayah_lines)
    return buckets


def build_pages(mushaf: Mushaf) -> dict[int, list[dict]]:
    """Lay every surah out on the 15-line Qudratullah grid.

    Returns {surah_number: [page, ...]}, each page::

        {"page_number": int,
         "lines": [{"type": "surah_name"|"basmallah"|"ayah",
                    "centered": bool,
                    "tokens": [{"kind": "word"|"end", "text": str,
                                "surah": int, "ayah": int,
                                "hizb": bool, "translation": bool}, ...]}]}

    A page shared by two surahs appears in BOTH surahs' lists, each
    holding only the lines that belong to that surah.
    """
    ayah_lines, all_lines = _load_layout()
    starts = [row[0] for row in ayah_lines]
    buckets = _bucket_tokens(mushaf, ayah_lines, starts)

    # Walk the layout in reading order, attributing each line to a surah.
    pages: dict[int, list[dict]] = {s.number: [] for s in mushaf.surahs}
    open_page: dict[int, dict] = {}   # surah -> its page dict on this page
    current_page = None
    pending_surah = None              # surah whose header we just emitted

    def page_for(surah_num: int, page_num: int) -> dict:
        got = open_page.get(surah_num)
        if got is None or got["page_number"] != page_num:
            got = {"page_number": page_num, "lines": []}
            pages[surah_num].append(got)
            open_page[surah_num] = got
        return got

    for page_num, line_num, ltype, centered, surah_num in all_lines:
        if page_num != current_page:
            current_page, open_page = page_num, {}
        if ltype == "surah_name":
            pending_surah = int(surah_num)
            page_for(pending_surah, page_num)["lines"].append(
                {"type": "surah_name", "centered": centered, "tokens": [],
                 "surah": pending_surah}
            )
        elif ltype == "basmallah":
            owner = pending_surah
            page_for(owner, page_num)["lines"].append(
                {"type": "basmallah", "centered": centered, "tokens": [],
                 "surah": owner}
            )
        else:
            tokens = buckets.get((page_num, line_num), [])
            owner = tokens[0]["surah"]
            pending_surah = None
            page_for(owner, page_num)["lines"].append(
                {"type": "ayah", "centered": centered, "tokens": tokens,
                 "surah": owner}
            )
    return pages


def _assert_model(buckets: dict, ayah_lines: list[tuple]) -> None:
    """Every layout line must be filled, and hold exactly its id span."""
    placed = sum(len(v) for v in buckets.values())
    if placed != TOTAL_WORD_IDS - sum(_EXTRA_IDS.values()):
        raise ValueError(
            f"{placed} display tokens placed, expected "
            f"{TOTAL_WORD_IDS - sum(_EXTRA_IDS.values())}"
        )
    empty = [(pg, ln) for _, _, pg, ln, _ in ayah_lines if not buckets.get((pg, ln))]
    if empty:
        raise ValueError(f"{len(empty)} mushaf lines came out empty: {empty[:5]}")


def surah_page_span(pages: list[dict]) -> tuple[int, int]:
    """(first, last) mushaf page a surah occupies."""
    return pages[0]["page_number"], pages[-1]["page_number"]



# The ayah-marker cluster is NBSP + marks + medallion + NBSP: the trailing
# NBSP gives the gap before whatever follows. When the marker ends a line
# there IS nothing following, and that NBSP becomes a fixed blob of space
# between the medallion and the margin which justification cannot absorb
# (NBSP does not stretch or collapse). Stripped per line, never in the
# token data itself, so every other layout keeps the invariant.
_NBSP = "\u00A0"


def _ayah_meta(mushaf: Mushaf) -> dict:
    """Per-ayah facts the mushaf margins and headers need.

    ruku_end maps an ayah to its ruku' index WITHIN its surah, but only
    for the ayah that CLOSES that ruku' — which is where the printed
    mushaf puts the margin sign.
    """
    juz: dict[tuple[int, int], int | None] = {}
    sajdah: set[tuple[int, int]] = set()
    ruku_end: dict[tuple[int, int], int] = {}
    # The ayah that OPENS each para — the printed mushaf tints the line it
    # falls on.
    juz_first: dict[int, tuple[int, int]] = {}
    # The ayah that OPENS each manzil. Unlike the ruku' sign this belongs
    # to where the division BEGINS, which is how the printed mushaf sets
    # it.
    #
    # No quarter-hizb sign: the owner checked page 7 line 9 (the nisf of
    # hizb 1, at 2:44) against the print on 2026-09-20 and the margin
    # there is empty -- this mushaf puts the rub' marks under the ayah
    # medallion, in the text itself, and nowhere else.
    manzil_first: dict[int, tuple[int, int]] = {}
    for surah in mushaf.surahs:
        seen: list[int] = []
        for i, ayah in enumerate(surah.ayahs):
            key = (surah.number, ayah.ayah_number)
            juz[key] = ayah.juz_number
            if ayah.juz_number is not None and ayah.juz_number not in juz_first:
                juz_first[ayah.juz_number] = key
            if (ayah.manzil_number is not None
                    and ayah.manzil_number not in manzil_first):
                manzil_first[ayah.manzil_number] = key
            if ayah.sajdah:
                sajdah.add(key)
            if ayah.ruku_number is None:
                continue
            if ayah.ruku_number not in seen:
                seen.append(ayah.ruku_number)
            nxt = surah.ayahs[i + 1] if i + 1 < len(surah.ayahs) else None
            closes = nxt is None or nxt.ruku_number != ayah.ruku_number
            if closes:
                ruku_end[key] = len(seen)
    return {"juz": juz, "sajdah": sajdah, "ruku_end": ruku_end,
            "juz_start": set(juz_first.values()),
            "manzil_start": {key: n for n, key in manzil_first.items()}}


_ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def _line_marks(tokens: list[dict], meta: dict) -> dict:
    """Margin signs and header facts for one line of the grid."""
    juz = None
    sajdah = False
    ruku = None
    manzil = None
    for tok in tokens:
        key = (tok["surah"], tok["ayah"])
        if juz is None:
            juz = meta["juz"].get(key)
        # The manzil OPENS on this line if its first ayah starts here.
        if tok["kind"] == "word" and tok.get("position") == 1:
            if manzil is None and key in meta["manzil_start"]:
                manzil = meta["manzil_start"][key]
        if tok["kind"] == "end":
            # Both signs belong to the line where the ayah CLOSES — a
            # sajdah ayah can span four lines, and the printed mushaf
            # marks it once.
            if key in meta["sajdah"]:
                sajdah = True
            if key in meta["ruku_end"]:
                ruku = meta["ruku_end"][key]
    return {
        "juz": juz, "sajdah": sajdah, "ruku": ruku,
        "manzil": ("منزل " + str(manzil).translate(_ARABIC_DIGITS)
                   if manzil is not None else None),
    }

def build_whole_pages(mushaf: Mushaf) -> dict[int, dict]:
    """Lay the mushaf out as 610 WHOLE pages, ignoring surah boundaries.

    ``build_pages`` splits a shared page between the two surahs that meet
    on it, because the reflowable layout writes one file per surah. A
    fixed-layout book writes one file per PAGE, so it needs the page
    intact — header line, basmallah line and every ayah line in layout
    order, whichever surah each belongs to.

    Returns {page_number: {"page_number": int, "lines": [...]}} with lines
    shaped exactly as ``build_pages`` produces them.
    """
    ayah_lines, all_lines = _load_layout()
    starts = [row[0] for row in ayah_lines]
    buckets = _bucket_tokens(mushaf, ayah_lines, starts)
    meta = _ayah_meta(mushaf)

    pages: dict[int, dict] = {}
    pending_surah = None
    seen_juz_starts: set[tuple[int, int]] = set()
    for page_num, line_num, ltype, centered, surah_num in all_lines:
        page = pages.setdefault(
            page_num, {"page_number": page_num, "lines": []}
        )
        if ltype == "surah_name":
            pending_surah = int(surah_num)
            page["lines"].append({"type": "surah_name", "centered": centered,
                                  "tokens": [], "surah": pending_surah,
                                  "juz": None, "sajdah": False, "ruku": None,
                                  "juz_start": False})
        elif ltype == "basmallah":
            page["lines"].append({"type": "basmallah", "centered": centered,
                                  "tokens": [], "surah": pending_surah,
                                  "juz": None, "sajdah": False, "ruku": None,
                                  "juz_start": False})
        else:
            tokens = [dict(t) for t in buckets.get((page_num, line_num), [])]
            if tokens and tokens[-1]["kind"] == "end":
                tokens[-1]["text"] = tokens[-1]["text"].rstrip(_NBSP)
            pending_surah = None
            line = {"type": "ayah", "centered": centered,
                    "tokens": tokens, "surah": tokens[0]["surah"]}
            line.update(_line_marks(tokens, meta))
            # A para opens on the FIRST line carrying any part of its
            # opening ayah — marked once, even though that ayah may run
            # across several lines.
            line["juz_start"] = False
            for tok in tokens:
                key = (tok["surah"], tok["ayah"])
                if key in meta["juz_start"] and key not in seen_juz_starts:
                    seen_juz_starts.add(key)
                    line["juz_start"] = True
            page["lines"].append(line)
    if len(pages) != TOTAL_PAGES:
        raise ValueError(f"laid out {len(pages)} pages, expected {TOTAL_PAGES}")
    return pages
