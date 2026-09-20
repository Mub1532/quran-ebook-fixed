"""Tajweed computed from the IndoPak text itself, driven by a rule file.

The other method (``tajweed.py``) transfers QUL's rule spans, marked on the
QPC *Uthmani* spelling, onto the IndoPak one. That works but costs an
alignment: roughly 2,300 words whose two spellings do not correspond
letter-for-letter are left black rather than coloured on a guess.

This method needs no alignment at all. Every carrier a Qudratullah rule
depends on — nun sakin, meem sakin, tanween, tashdeed — is written
explicitly in the IndoPak text (corpus-checked: not one bare nun or meem
in 6,236 ayahs), so the rules can be applied directly to the text being
typeset. No word is ever skipped.

The rules live in ``data/tajweed_qudratullah.json``, not in this file, so
the muṣḥaf's conventions can be corrected without touching code. This
module only knows how to *apply* whatever that file declares.

Its failure mode differs from the transfer method's, which is worth
stating plainly: a mapping error there is isolated (one word goes black),
whereas a missing exception here is systematic (every occurrence of a
pattern is coloured wrongly, confidently). The two methods are therefore
worth diffing against one another — where they agree, two independent
derivations agree.
"""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from .tajweed import WAQF_SYMBOLS, _TANWEEN, clusters

RULES_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "tajweed_qudratullah.json"
)

_SHADDA = "ّ"
# The qalb sign: a small meem printed over the nun or tanween to say the
# nun is pronounced as a meem. The IndoPak text does not always attach it
# to the carrier's own letter -- in shahidun it follows a private-use
# codepoint the font uses for placement, which starts a fresh cluster --
# so it has to be reattached to the rule after the fact.
# Two of them: the small meem rides above the letter, or below it when
# the tanween it belongs to is a kasratan and the space above is taken.
# Same sign, same rule, different codepoint.
_IQLAB_SIGNS = frozenset(("\u06E2", "\u06ED"))

# IndoPak spells a few letters at Persian/variant codepoints: the same
# letter, a different number. Matching a carrier or a trigger has to see
# through that, or a rule silently never fires (yaa written U+06CC was
# 35 words of missing idghaam, kaf written U+06A9/U+06AA 165 of missing
# ikhfa). Folded for *matching* only — the text is emitted untouched.
#
# Deliberately absent: U+0649 alef maksura and U+066E dotless beh. Both
# are vowel or hamza seats here, not consonants; folding them to yaa
# would invent triggers that the print does not colour.
_LETTER_FOLD = {
    "ی": "ي",   # farsi yeh   -> yeh
    "ے": "ي",   # yeh barree  -> yeh
    "ک": "ك",   # farsi kaf   -> kaf
    "ڪ": "ك",   # swash kaf   -> kaf
    "ہ": "ه",   # heh goal    -> heh
    "ھ": "ه",   # heh doachashmee -> heh
}


def _fold(ch: str) -> str:
    return _LETTER_FOLD.get(ch, ch)


_ARABIC_LETTER = re.compile(r"[ء-يٮ-ۓۺ-ۿ]")


@lru_cache(maxsize=1)
def load_rules(path: str | None = None) -> dict:
    """Read the rule file. Editing it changes the colouring, not the code."""
    p = Path(path) if path else RULES_PATH
    if not p.exists():
        raise FileNotFoundError(f"{p} missing — the tajweed rule file.")
    doc = json.loads(p.read_text(encoding="utf-8"))
    for key in ("rules", "carriers", "pause"):
        if key not in doc:
            raise ValueError(f"{p}: rule file has no {key!r} section")
    return doc


def _bare(text: str) -> str:
    """Letters only — for matching a word against the exception list."""
    text = re.sub(r"<[^>]*>", "", text)
    return "".join(
        _fold(ch) for ch in text
        if _ARABIC_LETTER.match(ch) and not unicodedata.combining(ch)
    )


class _Cluster:
    """One letter with its marks, plus where it sits in the text."""

    __slots__ = ("word", "idx", "base", "text", "rule")

    def __init__(self, word, idx, base, text):
        self.word = word
        self.idx = idx
        self.base = _fold(base)
        self.text = text
        self.rule = None

    def has(self, *marks) -> bool:
        return any(m in self.text for m in marks)


def _is_seat(c: "_Cluster", row: list["_Cluster"] | None = None) -> bool:
    """A bare alef that carries no sound of its own.

    Tanween fath is written on its letter with a silent alef after it
    (nuran = raa + fathatan + alef), and hamzat al-wasl opens a word the
    same way. That alef is a seat, not a consonant, so it must not be
    taken for the trigger: without this, every `-an` + idghaam/ikhfa in
    the book went black because the engine looked at the alef instead of
    the letter beyond it. Skipping it is safe for every rule here, since
    alef is a trigger for none of them.

    Only a *bare* alef qualifies — alef madda and any alef with a hamza
    or a vowel on it are letters in their own right and are left alone.
    """
    # The qalb sign does not make the alef a letter: it is printed over
    # the seat for want of anywhere else to put it, and the seat is still
    # silent. Ignoring it here is what lets bushran bayna find its baa.
    bare = not any(unicodedata.combining(ch) for ch in c.text
                   if ch not in _IQLAB_SIGNS)
    if not bare:
        return False
    if c.base in ("\u0627", "\u0649"):
        return True
    # A word-final yaa or waw with nothing on it is a long vowel, or the
    # alef maksura, which this text spells with a Farsi yeh (hudan is
    # written daal + fathatan + U+06CC). Either way it is not pronounced
    # as a consonant, so it cannot be a trigger: hudam mir rabbihim has
    # to reach the meem of the next word.
    if row is not None and c.base in ("\u064A", "\u0648"):
        return all(not _ARABIC_LETTER.match(x.base) for x in row[c.idx + 1:])
    return False


def _build(words: list[str]) -> list[list[_Cluster]]:
    return [
        [_Cluster(w, i, b, t) for i, (b, t) in enumerate(clusters(text))]
        for w, text in enumerate(words)
    ]


def colour_words(words: list[str], stops: list[bool],
                 tanween_span: str = "letter",
                 rules_doc: dict | None = None) -> list[str]:
    """Colour a run of IndoPak words in reading order.

    ``stops[i]`` says a pause mark (or ayah end) follows word ``i``; a
    pause stops any cross-word rule from applying at all.
    """
    doc = rules_doc or load_rules()
    grid = apply_rules(words, stops, doc)
    colours = {r["id"]: r for r in doc["rules"]}
    return [_emit(row, colours, tanween_span) for row in grid]


def apply_rules(words: list[str], stops: list[bool],
                doc: dict | None = None) -> list[list["_Cluster"]]:
    """Tag each cluster with the rule that lands on it, and return the grid.

    Kept separate from rendering so the colouring can be audited against
    the rule file without going through HTML.
    """
    doc = doc or load_rules()
    rules = sorted(doc["rules"], key=lambda r: r["precedence"])
    sukun = set(doc["carriers"]["sukun_marks"])
    tanween = set(doc["carriers"]["tanween"]["marks"])
    exceptions = {e["id"]: e for e in doc.get("exceptions", [])}
    izhar_words = set(exceptions.get("same_word_izhar", {}).get("words", []))
    # No saktah exception: the saktah is a stop mark, so it already cancels
    # every cross-word rule through the ordinary pause path.

    grid = _build(words)
    flat = [c for row in grid for c in row]

    def next_letter(c: _Cluster):
        """The cluster after `c`, and whether a pause separates them."""
        pos = flat.index(c)
        for nxt in flat[pos + 1:]:
            if not _ARABIC_LETTER.match(nxt.base):
                continue
            if _is_seat(nxt, grid[nxt.word]):
                continue          # silent alef: not the trigger, look past it
            broken = any(stops[w] for w in range(c.word, nxt.word))
            return nxt, broken, nxt.word != c.word
        return None, False, False

    for rule in rules:
        carrier = rule["carrier"]
        triggers = set(rule.get("triggers", ()))
        for c in flat:
            if c.rule is not None and rule["precedence"] <= 0:
                continue

            if carrier == "shadda_on":
                if c.base in rule["carrier_letters"] and c.has(_SHADDA):
                    if c.rule is None:
                        c.rule = rule["id"]
                continue

            if carrier == "qalqalah_letter":
                if c.base not in rule["carrier_letters"]:
                    continue
                at_stop = (c is grid[c.word][-1] or
                           all(not _ARABIC_LETTER.match(x.base)
                               for x in grid[c.word][c.idx + 1:])) \
                    and stops[c.word]
                if c.has(*sukun) or at_stop:
                    c.rule = rule["id"]          # outranks everything
                continue

            # --- carriers that need a following trigger letter ---
            if carrier == "noon_sakin_or_tanween":
                ok = (c.base == doc["carriers"]["noon_sakin"]["letter"]
                      and c.has(*sukun)) or c.has(*tanween)
            elif carrier == "meem_sakin":
                ok = (c.base == doc["carriers"]["meem_sakin"]["letter"]
                      and c.has(*sukun))
            else:
                continue
            if not ok or c.rule is not None:
                continue

            trg, broken, cross = next_letter(c)
            if trg is None or trg.base not in triggers or broken:
                continue
            if rule.get("same_word") is False and not cross:
                continue
            if izhar_words and _bare(words[c.word]) in izhar_words:
                continue

            c.rule = rule["id"]
            if rule["colour_scope"] == "carrier_and_trigger":
                trg.rule = rule["id"]

    # The qalb sign belongs to the qalb, wherever the text happens to
    # have parked it. Without this it sits in a cluster of its own with
    # no rule on it and prints black beside a coloured carrier.
    for row in grid:
        if not any(c.rule == "iqlab" for c in row):
            continue
        for c in row:
            if c.rule is None and any(m in c.text for m in _IQLAB_SIGNS):
                c.rule = "iqlab"

    return grid


_ZWJ = "\u200d"
# Letters that never join to the letter on their left. A ZWJ after one of
# these would ask for a joined form it does not have, so the seam is left
# alone there — it cannot carry a ligature across anyway.
_NO_LEFT_JOIN = set("اآأإٱدذرزوؤةءى")


def _seams(row: list[_Cluster]) -> set[int]:
    """Cluster positions after which a colour boundary needs a ZWJ.

    Where a rule ends in the middle of a word the two halves still join
    cursively, and the font may fuse the letters either side into a
    single ligature glyph. A glyph has one colour, so an engine that
    shapes across the span boundary paints the whole ligature with the
    first half's — the noon of inni drags the yaa blue with it. A ZWJ on
    each side shapes the halves separately while keeping them joined, so
    the ligature cannot form across the colour change.

    The positions are worked out once, from the colouring, and the same
    set is used for both layers of an overlay. They have to agree: the
    two layers are stacked glyph for glyph, and a ZWJ in one but not the
    other shifts the metrics apart and the black copy stops covering the
    coloured one.
    """
    out = set()
    for i in range(len(row) - 1):
        a, b = row[i], row[i + 1]
        if a.rule == b.rule:
            continue
        if not (_ARABIC_LETTER.match(a.base) and _ARABIC_LETTER.match(b.base)):
            continue
        if a.base in _NO_LEFT_JOIN:
            continue
        out.add(i)
    return out


def _emit(row: list[_Cluster], colours: dict, tanween_span: str) -> str:
    """Render one word, using the overlay when a tanween is coloured alone."""

    def render(rules, strip, seams):
        parts = []
        for i, c in enumerate(row):
            text = c.text
            drop = strip.get(id(c))
            if drop:
                text = "".join(ch for ch in text if ch not in drop)
            if i in seams:
                text += _ZWJ
            if i - 1 in seams:
                text = _ZWJ + text
            rule = rules[i]
            if rule is None:
                parts.append(text)
                continue
            # Trailing pause marks stay outside the colour. The qalb
            # sign is listed among them but is not one -- it is part of
            # the rule, so it stays inside.
            cut = len(text)
            while cut > 0 and text[cut - 1] not in _IQLAB_SIGNS and (
                    text[cut - 1] in WAQF_SYMBOLS or text[cut - 1].isspace()):
                cut -= 1
            head, tail = text[:cut], text[cut:]
            parts.append(f'<span class="tj-{rule}">{head}</span>{tail}'
                         if head else text)
        return "".join(parts)

    # Which carriers the print colours on the mark alone. Declared per
    # rule in the rule file (tanween_scope), not decided here.
    masked: dict[int, set[str]] = {}
    for c in row:
        if not c.rule:
            continue
        if colours[c.rule].get("tanween_scope") == "mark" and c.has(*_TANWEEN):
            masked.setdefault(id(c), set()).update(_TANWEEN)
        # The qalb sign is a mark too, and the print colours it whatever
        # the carrier is coloured -- so it goes in the hole in the top
        # sheet alongside the tanween.
        if c.rule == "iqlab" and any(m in c.text for m in _IQLAB_SIGNS):
            masked.setdefault(id(c), set()).update(_IQLAB_SIGNS)
    seams = _seams(row)
    rules = [c.rule for c in row]
    under = render(rules, {}, seams)
    if tanween_span != "mark" or not masked:
        return under
    over = render([None if id(c) in masked else c.rule for c in row],
                  masked, seams)
    return (f'<span class="tj-ov"><span class="tj-u">{under}</span>'
            f'<span class="tj-o" aria-hidden="true">{over}</span></span>')
