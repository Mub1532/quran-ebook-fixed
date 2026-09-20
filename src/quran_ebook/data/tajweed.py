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


# QUL's export is not uniform: most spans write class=X bare, but 2,661
# of them (1,373 words, 3.8% of the data) quote it as class='X'. A regex
# that only matches the bare form drops those rules silently. The repo's
# qul_tajweed.py already allows for this; match it.
RULE_OPEN = re.compile(r"""<rule\s+class=['"]?([a-z_]+)['"]?[^>]*>""")
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

# Rules whose carrier and trigger sit in DIFFERENT words. None of them can
# occur across a pause: if a stop mark separates the two, the reciter stops
# and no assimilation happens, so neither half is coloured (owner,
# 2026-09-20, from جَمِيعًا ؕ وَعْدَ).
CROSSWORD_RULES = {
    "ikhafa", "ikhafa_shafawi", "iqlab",
    "idgham_ghunnah", "idgham_shafawi",
}
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
WAQF_SYMBOLS = set("\u0615"                                    # tah - necessary stop
                   "\u0617"                                    # zain
                   "\u06D6\u06D7\u06D8\u06D9\u06DA\u06DB\u06DC\u06DD"
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


DAGGER = "\u0670"


def _compare_seq(items):
    """Folded letter sequence for matching, plus each position's owner.

    Uthmani writes long aa as U+0670 (a mark on the previous letter) where
    IndoPak often writes a full alef — same letter, two conventions
    (owner-approved 2026-09-19). BOTH sides are normalised the same way: a
    dagger yields an extra virtual alef. Applying it to one side only makes
    matters worse, because IndoPak uses U+0670 in plenty of words too, and
    the sides then disagree where they previously matched.

    `owner[p]` is the index of the real cluster position p belongs to, so
    a rule landing on a virtual alef lands on the letter carrying it.
    """
    seq, owner = [], []
    for idx, item in enumerate(items):
        base, text = item[0], item[1]
        seq.append(fold(base))
        owner.append(idx)
        if DAGGER in text:
            seq.append("\u0627")
            owner.append(idx)
    return seq, owner


def map_word(uth_marked: str, indopak: str, allowed=None, stop: bool = False,
             tanween_span: str = "letter", break_after: bool = False,
             break_before: bool = False):
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
        seq_u, own_u = _compare_seq(u)
        seq_i, own_i = _compare_seq(ip)
        if seq_u != seq_i:
            status = "skipped"
        else:
            status = "exact"
            # map each matched position back onto its real IndoPak cluster
            for pos, src in enumerate(own_u):
                rule = u[src][2]
                if rule is not None:
                    rules[own_i[pos]] = rule

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

    # A pause between carrier and trigger cancels the rule outright. The
    # carrier is the last ruled cluster (anything after it is a silent
    # seat); the trigger is the first. Only cross-word rules are affected —
    # a rule wholly inside one word is untouched by what follows it.
    # Position tells carrier from trigger: QUL marks a trigger at the START
    # of its word and a carrier at the END. Without that test, a word whose
    # only ruled cluster is its word-initial trigger (مُّبِيْنٌ, يَّعْلَمُوْنَ)
    # gets that trigger dropped by break_after as though it were a carrier.
    if break_after:
        for i in range(len(rules) - 1, -1, -1):
            if rules[i] is not None:
                if i > 0 and rules[i] in CROSSWORD_RULES:
                    rules[i] = None
                break
    if break_before:
        for i, r in enumerate(rules):
            if r is not None:
                if i == 0 and r in CROSSWORD_RULES:
                    rules[i] = None
                break

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

    # --- emit -----------------------------------------------------------
    # The print colours a tanween carrier on the MARK ALONE. Most engines
    # refuse to paint a lone combining mark in its own colour, using the
    # base letter's instead -- black in Thorium (Chromium/Readium) and
    # Google Play Books, though Gecko obliges. So tanween_span="mark" never
    # asks them to: it draws the whole cluster coloured, then covers the
    # LETTER with an identical black copy that omits the tanween, leaving
    # only the coloured mark showing. Verified in Thorium, 2026-09-20.
    #
    # The overlay wraps the WHOLE WORD, never a single cluster: Arabic
    # joins inside a word but not across spaces, so isolating a word costs
    # no cursive joining where isolating a cluster would break it.
    def _emit(idx, rule, drop_tanween=False):
        txt = ip[idx][1]
        if drop_tanween:          # must precede the rule check: the masked
            return "".join(       # cluster is emitted plain AND stripped
                c for c in txt if c not in _TANWEEN
            )
        if rule is None:
            return txt
        cut = len(txt)                      # trailing pause symbols stay
        while cut > 0 and (txt[cut - 1] in WAQF_SYMBOLS
                           or txt[cut - 1].isspace()):
            cut -= 1
        head, tail = txt[:cut], txt[cut:]
        return f'<span class="tj-{rule}">{head}</span>{tail}' if head else txt

    # Tanween carriers the print colours mark-only. Qalqala is excluded --
    # it takes its tanween with it (owner ruling 2026-09-19).
    masked = [
        i for i, r in enumerate(rules)
        if r is not None and r != "qalaqah"
        and any(t in ip[i][1] for t in _TANWEEN)
    ]

    under = "".join(_emit(i, rules[i]) for i in range(len(ip)))
    if tanween_span != "mark" or not masked:
        return under, status

    over = "".join(
        _emit(i, None if i in masked else rules[i], drop_tanween=(i in masked))
        for i in range(len(ip))
    )
    return (f'<span class="tj-ov"><span class="tj-u">{under}</span>'
            f'<span class="tj-o" aria-hidden="true">{over}</span></span>'), status


def is_stop_word(word_text: str, is_last_in_ayah: bool) -> bool:
    """Does the reciter stop on this word? (owner's ruling, see STOP_MARKS)"""
    return is_last_in_ayah or any(c in word_text for c in STOP_MARKS)
