"""Page geometry for the TRUE fixed-layout 15-line IndoPak mushaf.

The reflowable ``indopak_fixed`` layout reproduces the Qudratullah line
BREAKS but leaves everything else to the reader: font size, spacing, and
therefore the measure, so lines never fill the width. This module sizes
an EPUB3 pre-paginated page instead — a real 1848x2772 canvas where every
box is in px and the reader changes nothing.

Sizing rule
-----------
A line has to fill the measure exactly, and the Nastaleeq font cannot
elongate strokes (kashida) the way the calligrapher did, so the deficit
lands in the word gaps. Natural line widths vary ~1.6x corpus-wide but
only ~1.24x WITHIN a page, and a reader only ever compares the lines in
front of them — so each page is sized to ITS OWN widest line (measured by
tools/build_indopak_fxl_metrics.py). That page's widest line then fills
the measure with no stretch at all, and the rest stretch by the
within-page spread.

Pages 1 and 2 fall out of the same rule rather than being special-cased:
their lines are genuinely narrow (the printed mushaf sets Al-Fatiha and
the opening of Al-Baqarah in a small centred block), so they hit
FONT_CAP_PX and get a narrower frame, centred — which is what the
printed page looks like.
"""

import json
from functools import lru_cache
from pathlib import Path

# --- Canvas (owner spec: 1848x2772 px, 2:3 portrait; a two-page spread
# is then 3696x2772 = 4:3 landscape) ---------------------------------------
PAGE_W = 1848
PAGE_H = 2772

# --- Text block ----------------------------------------------------------
# The outer margin is a real gutter, not slack: the ruku' and sajdah signs
# live out there, outside the gold rule, the way the printed mushaf sets
# them. Everything left over goes to the measure, which is what decides
# the font size.
OUTER_MARGIN = 87
FRAME_PAD = 34
FRAME_BORDER = 3     # the gold rule itself takes width in a border-box
# No vertical padding, deliberately: the frame's top border then sits above
# line 1 exactly as every line's own rule sits below it, so all 15 slots
# are optically identical. Any padding here would give the first line a
# gap no other line has.
FRAME_PAD_Y = 0
# The frame's horizontal padding belongs to each LINE, not to the frame:
# that way a line's bottom rule spans the full inner width of the frame
# instead of stopping at the text block. The text box is still
# MAX_BLOCK_W, so justification is unaffected.
MAX_BLOCK_W = PAGE_W - 2 * OUTER_MARGIN - 2 * FRAME_PAD - 2 * FRAME_BORDER
FONT_CAP_PX = 120    # a page whose lines are narrow stops here and keeps
                     # a narrower (centred) block instead of ballooning
LINE_RULE_PX = 1     # hairline ruled between lines, as a printed mushaf
LINE_H_MIN = 164     # constant leading, so the frame is the same height
LEADING = 1.76       # ...unless a big-font page needs more room
MAX_FRAME_H = 2490

# --- Header band (surah right, juz' left) and folio ----------------------
HEADER_H = 96
HEADER_GAP = 14
FOLIO_GAP = 22
FOLIO_H = 44

# Tajweed legend strip under the folio — the colour key a printed IndoPak
# mushaf carries in its bottom margin. Only reserved when asked for, so a
# book without tajweed colouring keeps its original proportions.
LEGEND_GAP = 16
LEGEND_H = 58

_METRICS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "indopak_15_fxl_metrics.json"
)


@lru_cache(maxsize=1)
def _metrics() -> tuple[float, dict[int, float]]:
    if not _METRICS_PATH.exists():
        raise FileNotFoundError(
            f"{_METRICS_PATH} missing — the fixed-layout mushaf needs the "
            "measured line widths (regenerate with "
            "tools/build_indopak_fxl_metrics.py)."
        )
    raw = json.loads(_METRICS_PATH.read_text())
    widths = {int(k): float(v) for k, v in raw["widest_line_px"].items()}
    if len(widths) != 610:
        raise ValueError(f"fxl metrics has {len(widths)} pages, expected 610")
    return float(raw["ref_font_px"]), widths


def page_geometry(page_number: int, n_lines: int, legend: bool = False) -> dict:
    """Every px the template needs for one mushaf page.

    The header band, the frame and the folio are centred on the canvas as
    ONE stack, so the gold rule sits visually centred with its furniture.
    """
    ref, widths = _metrics()
    widest = widths[page_number]

    font_px = min(FONT_CAP_PX, MAX_BLOCK_W * ref / widest)
    # Unless capped, this is exactly MAX_BLOCK_W; when capped the block
    # shrinks to the page's own widest line so that line still fills it.
    block_w = min(MAX_BLOCK_W, widest * font_px / ref)

    chrome_w = 2 * FRAME_PAD + 2 * FRAME_BORDER
    chrome_h = 2 * FRAME_PAD_Y + 2 * FRAME_BORDER
    extra = (LEGEND_GAP + LEGEND_H) if legend else 0
    max_frame = MAX_FRAME_H - extra
    line_h = max(LINE_H_MIN, font_px * LEADING)
    if n_lines * line_h + chrome_h > max_frame:
        line_h = (max_frame - chrome_h) / n_lines

    frame_w = block_w + chrome_w
    frame_h = n_lines * line_h + chrome_h
    total_h = HEADER_H + HEADER_GAP + frame_h + FOLIO_GAP + FOLIO_H + extra

    top = (PAGE_H - total_h) / 2
    frame_left = (PAGE_W - frame_w) / 2
    frame_top = top + HEADER_H + HEADER_GAP

    geo = {
        "font_px": round(font_px, 2),
        "block_w": round(block_w, 2),
        "line_h": round(line_h, 2),
        # The rule lives INSIDE the line's slot (border-box), so adding it
        # changes no other measurement: text gets line_h - rule, the slot
        # still occupies line_h, and the frame height is untouched.
        "text_line_h": round(line_h - LINE_RULE_PX, 2),
        "rule_px": LINE_RULE_PX,
        # Full inner width of the frame: the line box (and so its rule)
        # spans this, while its own side padding keeps the TEXT at block_w.
        "line_box_w": round(block_w + 2 * FRAME_PAD, 2),
        "line_pad_x": FRAME_PAD,
        "frame_pad_y": FRAME_PAD_Y,
        "frame_w": round(frame_w, 2),
        "frame_h": round(frame_h, 2),
        "frame_left": round(frame_left, 2),
        "frame_top": round(frame_top, 2),
        "header_top": round(top, 2),
        "header_left": round(frame_left, 2),
        "header_w": round(frame_w, 2),
        "header_h": HEADER_H,
        "folio_top": round(frame_top + frame_h + FOLIO_GAP, 2),
        "legend_top": round(frame_top + frame_h + FOLIO_GAP + FOLIO_H
                            + LEGEND_GAP, 2) if legend else None,
        "legend_h": LEGEND_H,
        # Margin signs sit in the LEFT gutter — the end of an RTL line,
        # which is where the printed mushaf puts them.
        "mark_left": 0,
        "mark_w": round(frame_left, 2),
        "text_top": round(frame_top + FRAME_BORDER + FRAME_PAD_Y, 2),
    }
    if top < 0 or frame_w > PAGE_W:
        raise ValueError(
            f"page {page_number}: frame {frame_w:.0f}x{frame_h:.0f} plus "
            f"furniture does not fit the {PAGE_W}x{PAGE_H} canvas "
            f"({n_lines} lines)"
        )
    return geo
