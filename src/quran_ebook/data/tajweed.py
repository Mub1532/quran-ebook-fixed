"""Tajweed colouring for the IndoPak mushaf, mapped from QUL Hafs data.

QUL publishes tajweed rule spans marked on the QPC *Uthmani* spelling.
This module transfers them onto the *IndoPak* spelling the mushaf is set
in, and applies the Qudratullah publisher's own conventions on top.

Why it works at all: QUL's word-by-word tajweed file is keyed to the same
global word ids as the Qudratullah mushaf layout — verified 0 mismatches
across all 6,236 ayahs — so which WORD a rule belongs to is exact and free.
The only real problem is which LETTERS inside that word it covers, and
that is solved strictly: a rule transfers only when the two spellings
correspond letter-for-letter after the orthographic fold below. A word
that does not correspond is left black rather than coloured on a guess.

The publisher's rulings (rule set, palette, per-class carrier/trigger
narrowing, stop marks, qalqala precedence) are recorded as named
constants, each with the date it was settled, so the provenance of every
colouring decision stays readable.

Needs the QUL word-by-word tajweed export at
``docs/qpc-hafs-tajweed.json-word-by-word.zip`` (free QUL login; docs/ is
gitignored). Without it the build raises rather than silently producing
an uncoloured book.
"""
import json
import re
import unicodedata
import zipfile
from functools import lru_cache
from pathlib import Path

TAJWEED_ZIP = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "docs" / "qpc-hafs-tajweed.json-word-by-word.zip"
)

# The scheme name stamped on the page so CSS can pick a palette. The QPC
# Uthmani tajweed build keeps QUL's own colours; this one uses the
# Qudratullah publisher's.
SCHEME = "qudratullah"


@lru_cache(maxsize=1)
def load_tajweed_words() -> dict[int, str]:
    """QUL word-by-word tajweed text, keyed by global word id (1..83668)."""
    if not TAJWEED_ZIP.exists():
        raise FileNotFoundError(
            f"{TAJWEED_ZIP} missing — tajweed colouring needs the QUL "
            "word-by-word export (resource 58, "
            "qul.tarteel.ai/resources/quran-script/58; free login). "
            "Place it at that path, or build without layout.tajweed."
        )
    with zipfile.ZipFile(TAJWEED_ZIP) as zf:
        raw = json.load(zf.open(zf.namelist()[0]))
    words = {int(v["id"]): v["text"] for v in raw.values()}
    if len(words) != 83668:
        raise ValueError(
            f"tajweed export has {len(words)} words, expected 83,668 "
            "(must match the Qudratullah layout's word-id model)"
        )
    return words


RULE_OPEN = re.compile(r'<rule class=([a-z_]+)>')
RULE_CLOSE = '</rule>'
def PUA(ch: str) -> bool:
    """A Private Use Area codepoint — a font glyph, never a letter."""
    return 0xE000 <= ord(ch) <= 0xF8FF

# Uthmani writes these as spacing letters (لَهُۥ, بِهِۦ) though they carry no
# letter of their own; IndoPak writes the same sound as a combining mark
# (U+0657). Unicode gives them combining class 0, so without this they
# enter the letter sequence on one side only and every such word fails to
# match. Treated as marks on both sides (owner-approved 2026-09-19).
SUPERSCRIPT_LETTERS = {"\u06E5", "\u06E6"}


def _is_mark(ch: str) -> bool:
    return (unicodedata.combining(ch) != 0 or ch == "\u0640" or PUA(ch)
            or ch.isspace() or ch in SUPERSCRIPT_LETTERS)

# For ALIGNMENT ONLY — never for display. IndoPak and Uthmani spell the
# same consonant with different codepoints in a handful of places.
_FOLD = {
    # Orthographic equivalences used ONLY to test whether two spellings
    # are the same word. IndoPak and Uthmani encode these at different
    # codepoints; folding them lets a genuine match be recognised. The
    # fold never decides WHICH letter a rule lands on — that still
    # requires a full 1:1 sequence correspondence.
    "\u06CC": "\u064A",   # farsi yeh      -> arabic yeh
    "\u0649": "\u064A",   # alef maksura   -> yeh
    "\u06A9": "\u0643",   # farsi kaf      -> arabic kaf
    "\u06C1": "\u0647",   # heh goal       -> heh
    "\u0671": "\u0627",   # alef wasla     -> alef
    "\u0622": "\u0627",   # alef madda     -> alef
    "\u0623": "\u0627",   # alef + hamza above -> alef   (approved 2026-09-19)
    "\u0625": "\u0627",   # alef + hamza below -> alef   (approved 2026-09-19)
    "\u06D5": "\u0629",   # ae             -> teh marbuta
}

def fold(ch: str) -> str:
    return _FOLD.get(ch, ch)


# --- Which rules this mushaf actually marks ------------------------------
# The Qudratullah IndoPak convention colours only the nasal/assimilation
# family plus qalqalah. Madd is left black because IndoPak orthography
# already notates it with the maddah sign over the letter, and the
# silent/wasl letters (ham_wasl, slnt, laam_shamsiyah) are not marked at
# all — together those are ~60% of QUL's marks, which is why the full
# scheme looks far busier than the printed page.
QUDRATULLAH_RULES = {
    "ikhafa",            # ikhfa
    "ikhafa_shafawi",    # ikhfa meem saakin
    "qalaqah",           # qalqala
    "iqlab",             # qalb
    "idgham_ghunnah",    # idghaam
    "idgham_shafawi",    # idghaam meem saakin
    "ghunnah",           # ghunna
}

# QUL's span covers the CARRIER plus the TRIGGER letter that follows (and
# the trigger may sit in the NEXT word). Which of those the mushaf colours
# is specified per class by the publisher's Colour Coded Details page:
#   ikhfa / qalb / ikhfa meem sakin  -> carrier only
#   idgham / idgham meem sakin       -> carrier AND trigger
# A carrier is the noon/meem itself, or whatever letter bears the tanween;
# the trigger is identified by its shaddah, since an assimilated trigger is
# always doubled while a carrier never is.
DROP_TRIGGER_RULES = {"ikhafa", "ikhafa_shafawi", "iqlab"}
_TANWEEN = "\u064B\u064C\u064D"
_SHADDA = "\u0651"
_NOON_MEEM = "\u0646\u0645"


def _is_carrier(base: str, cluster: str) -> bool:
    if any(t in cluster for t in _TANWEEN):
        return True
    return base in _NOON_MEEM and _SHADDA not in cluster


# --- Waqf qalqalah -------------------------------------------------------
# The Qudratullah contents page defines qalqalah as applying to these
# letters "in their sakin form OR you are stopping on them". QUL marks
# only the sakin half (2,829 mid-word + 904 word-final). The second clause
# is generated here, from the publisher's own stated rule.
#
# Which stops count is the owner's ruling (2026-09-19): end of ayah, plus
# lazim and jeem. The "don't stop" marks are excluded by definition, and
# qala / mu'anaqah are pending a check against the print.
# Pause symbols and other free-standing annotations. They ride in a
# letter's cluster (the loader rebases them on a NBSP after the word) but
# they are not part of the letter, so a colour span must stop before them.
WAQF_SYMBOLS = set("\u06D6\u06D7\u06D8\u06D9\u06DA\u06DB\u06DC\u06DD"
                   "\u06DE\u06E9\u06EA\u06EB\u06EC\u06ED\u06E2")

QALQALAH_LETTERS = set("\u0642\u0637\u0628\u062C\u062F")   # q t b j d
STOP_MARKS = {
    # Owner ruling 2026-09-19, made against the glyphs these codepoints
    # actually render as in the IndoPak Nastaleeq font (an earlier ruling
    # used Unicode names, which had 06D6/06D7 semantically reversed).
    "\u0615",   # ط    necessary stop (owner-identified 2026-09-19 from
                #      بِالْقِسْطِ / وَالْحِسَابَ; sits at U+0615, far below the
                #      06D6-06ED window an earlier census wrongly assumed)
    "\u06D6",   # صل   better to stop
    "\u06D8",   #      obligatory
    "\u06DA",   # ج    voluntary pause
    "\u06EB",   # قف   means to stop at it
    "\u06EA",   # ص    may pause if need
    "\u06DC",   # س    sakta - brief pause
}
# Explicitly NOT stops: U+06D7 ق (better not to stop), U+06D9 لا (don't
# stop), U+0617 ز (desirable to continue, ruled 2026-09-19), and U+06E5
# which is the لَهُۥ vowel rather than a pause mark. Unresolved, awaiting a ruling:
# U+06EC (+13 marks), U+06ED (+3), U+06DB mu'anaqah.


# Owner-supplied Qudratullah palette (2026-09-19), in legend order.
QUDRATULLAH_PALETTE = [
    ("ikhafa",         "#438851", "إخفاء"),
    ("ikhafa_shafawi", "#C9C856", "إخفاء ميم ساكن"),
    ("qalaqah",        "#E7570C", "قلقلة"),
    ("iqlab",          "#7F4669", "قلب"),
    ("idgham_ghunnah", "#EC520F", "إدغام"),
    ("idgham_shafawi", "#F3A3B2", "إدغام ميم ساكن"),
    ("ghunnah",        "#289FEA", "غنة"),
]

def clusters(text: str):
    """Split into (base_letter, full_cluster) — a letter plus its marks.

    IndoPak display text is not plain text: the loader wraps PUA glyph
    runs in <span dir="rtl"> for bidi isolation. Those tags must ride
    along with the cluster they sit in, never be tokenised as letters —
    otherwise '<', 's', 'p', 'a', 'n', '>' enter the letter sequence and
    the word can never match its Uthmani counterpart.
    """
    out = []
    i = 0
    pending = ""
    while i < len(text):
        ch = text[i]
        if ch == "<":                      # an HTML tag, not Arabic
            j = text.find(">", i)
            if j == -1:
                j = len(text) - 1
            tag = text[i:j + 1]
            if out:
                out[-1][1] += tag
            else:
                pending += tag
            i = j + 1
            continue
        if _is_mark(ch):
            if out:
                out[-1][1] += ch
            else:
                pending += ch
            i += 1
            continue
        out.append([ch, pending + ch])
        pending = ""
        i += 1
    if pending and out:
        out[-1][1] += pending
    return [(b, s) for b, s in out]


def uthmani_clusters_with_rules(marked: str):
    """Clusters of the rule-marked Uthmani word, each tagged with its rule.

    A rule span may open on a COMBINING MARK that belongs to the previous
    letter, e.g. madda_permissible over "\u0650\u064A" (kasra + yeh): the kasra is
    the previous letter's vowel, the yeh is the madd letter. Letting that
    leading mark drag the rule onto the previous cluster colours one letter
    too many and shifts every such rule left — the systematic error in the
    first Yunus proof.

    So: if a rule span contains any BASE letter, only those base letters
    take the rule. A span made purely of marks (e.g. "\u0640\u0670", tatweel +
    dagger alif) has no letter of its own and does belong to the letter it
    sits on, so it attaches to the preceding cluster as before.
    """
    pos, cur, plain, tags = 0, None, [], []
    occ = 0
    while pos < len(marked):
        m = RULE_OPEN.match(marked, pos)
        if m:
            occ += 1
            cur = (m.group(1), occ)
            pos = m.end()
            continue
        if marked.startswith(RULE_CLOSE, pos):
            cur = None
            pos += len(RULE_CLOSE)
            continue
        plain.append(marked[pos])
        tags.append(cur)
        pos += 1

    is_mark = _is_mark

    # which rule occurrences actually contain a base letter?
    has_base = set()
    for ch, tag in zip(plain, tags):
        if tag and not is_mark(ch):
            has_base.add(tag[1])

    out = []
    for ch, tag in zip(plain, tags):
        if is_mark(ch):
            if out:
                base, txt, rule = out[-1]
                # a marks-only rule span belongs to the letter it sits on
                if rule is None and tag is not None and tag[1] not in has_base:
                    rule = tag[0]
                out[-1] = (base, txt + ch, rule)
            continue
        out.append((ch, ch, tag[0] if tag else None))
    return out


def map_word(uth_marked: str, indopak: str, allowed=None, stop: bool = False):
    """Return (html, status) — IndoPak text with tj- spans applied.

    STRICT: a QUL rule transfers only when the two spellings have the same
    letter sequence (after the fold), so every transferred colour is a 1:1
    correspondence. `stop` says this word sits at a stopping place, which
    enables waqf qalqalah — computed from the IndoPak text alone, so it
    does not depend on the alignment and still applies to skipped words.
    """
    ip = clusters(indopak)
    rules = [None] * len(ip)
    status = "norule"

    u = uthmani_clusters_with_rules(uth_marked)
    if allowed is not None:
        u = [(b, t, (r if r in allowed else None)) for b, t, r in u]
    if any(r for _, _, r in u):
        a = [fold(b) for b, _, _ in u]
        b = [fold(x) for x, _ in ip]
        if a != b:
            status = "skipped"
        else:
            status = "exact"
            rules = [r for _, _, r in u]

            # P2: drop the trigger, only where it stays a separate sound.
            k = 0
            while k < len(rules):
                r = rules[k]
                if r not in DROP_TRIGGER_RULES:
                    k += 1
                    continue
                j = k
                while j < len(rules) and rules[j] == r:
                    j += 1
                kept = False
                for i in range(k, j):
                    if not kept and _is_carrier(ip[i][0], ip[i][1]):
                        kept = True
                    else:
                        rules[i] = None
                k = j

            # A tanween fath is written with an alef seat; the seat is
            # silent, so the tanween is the only coloured cluster of its run.
            k = 0
            while k < len(rules):
                r = rules[k]
                if r is None:
                    k += 1
                    continue
                j = k
                while j < len(rules) and rules[j] == r:
                    j += 1
                tw = next((i for i in range(k, j)
                           if any(t in ip[i][1] for t in _TANWEEN)), None)
                if tw is not None:
                    for i in range(k, j):
                        if i != tw:
                            rules[i] = None
                k = j

    # Waqf qalqalah on the word's final letter, when nothing already
    # colours it and the reciter stops there.
    if stop and ip and (allowed is None or "qalaqah" in allowed):
        last = len(ip) - 1
        if ip[last][0] in QALQALAH_LETTERS:
            # Owner verified all 6 conflicts against the print (2026-09-19):
            # the mushaf shows qalqala, not the assimilation rule QUL put
            # there. So at a stop the final letter is qalqala outright —
            # it does not defer to an existing mark. Only the FINAL letter
            # is affected; other letters keep their own rules (35:32 keeps
            # idgham meem sakin on its meem).
            if rules[last] != "qalaqah" and status == "norule":
                status = "waqf"
            rules[last] = "qalaqah"

    if not any(rules):
        return indopak, status

    # P1: a tanween carrier colours the MARK alone; the letter under it is
    # a different letter and stays black.
    html = []
    for idx, (base, txt) in enumerate(ip):
        r = rules[idx]
        if r is None:
            html.append(txt)
            continue
        # Qalqala takes the letter AND its tanween together — unlike the
        # noon rules, where only the tanween mark is coloured (owner,
        # 2026-09-19, from وَبَرْقٌ / حَقٍّ / أُجَاجٌ).
        if r != "qalaqah" and any(t in txt for t in _TANWEEN):
            out = []
            for ch in txt:
                out.append(f'<span class="tj-{r}">{ch}</span>'
                           if ch in _TANWEEN else ch)
            html.append("".join(out))
        else:
            # keep any trailing pause symbols OUTSIDE the colour
            cut = len(txt)
            while cut > 0 and (txt[cut - 1] in WAQF_SYMBOLS
                               or txt[cut - 1].isspace()):
                cut -= 1
            head, tail = txt[:cut], txt[cut:]
            html.append(f'<span class="tj-{r}">{head}</span>{tail}'
                        if head else txt)
    return "".join(html), status


def is_stop_word(word_text: str, is_last_in_ayah: bool) -> bool:
    """Does the reciter stop on this word? (owner's ruling, see STOP_MARKS)"""
    return is_last_in_ayah or any(c in word_text for c in STOP_MARKS)
