"""Measure the natural width of every 15-line mushaf line, per page.

Input:  the IndoPak Nastaleeq font + the Qudratullah line map
        (quran_ebook.data.indopak_lines), so this needs a warm cache —
        run any IndoPak build first.
Output: data/indopak_15_fxl_metrics.json — for each of the 610 pages, the
        widest line's natural advance width at a REFERENCE font size, in
        px. Tracked in git; consumed by quran_ebook.data.indopak_fxl to
        size each fixed-layout page.

Why per page: a fixed-layout mushaf page has to fill its measure exactly,
and the Nastaleeq font cannot elongate strokes (kashida) the way the
calligrapher did, so the deficit has to land in the word gaps. Sizing
each page to ITS widest line keeps that stretch down to the within-page
spread (~1.24x median) instead of the corpus-wide spread (~1.6x), and a
reader only ever compares lines on the page in front of them.

Measurement uses WeasyPrint's own line breaker with white-space:nowrap
and reads the resulting line box width, so the number is exactly what
the renderer will produce for that markup.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "indopak_15_fxl_metrics.json"
REF_FONT_PX = 100
CHUNK = 500
# base.css .hizb-marker for a non-glyph script: primary font at 0.6em,
# inline-block, 0.06em side margins.
HIZB_HTML = (
    '<span style="display:inline-block;font-size:0.6em;margin:0 0.06em">'
    "\u06de</span>"
)


def main() -> None:
    from weasyprint import HTML
    from weasyprint.formatting_structure import boxes

    sys.path.insert(0, str(ROOT / "src"))
    from quran_ebook.data.cache import set_stale_policy
    set_stale_policy("reuse")
    from quran_ebook.data.indopak_lines import build_whole_pages
    from quran_ebook.data.quran_api import load_quran
    from quran_ebook.fonts.manager import get_font_path

    font = get_font_path("indopak_nastaleeq")
    mushaf = load_quran("text_indopak_nastaleeq", wbw_language="en")
    # Whole pages, exactly as the fixed-layout template renders them —
    # including the stripped trailing nbsp on a line-final ayah marker,
    # which changes the width this measurement has to report.
    pages = build_whole_pages(mushaf)

    rows = []
    for page in pages.values():
        if True:
            for line in page["lines"]:
                if line["type"] != "ayah":
                    continue
                # Must mirror the template's markup exactly, or the
                # measurement lies. The rub al-hizb marker is the one
                # piece that is NOT part of the verse text but does take
                # width on the ~240 lines that carry it.
                parts = []
                for i, tok in enumerate(line["tokens"]):
                    if tok["kind"] == "end":
                        parts.append(tok["text"])
                        continue
                    if i:
                        parts.append(" ")
                    if tok["hizb"]:
                        parts.append(HIZB_HTML)
                    parts.append(tok["text"])
                rows.append({
                    "page": page["page_number"],
                    "html": "".join(parts),
                    "centered": line["centered"],
                })

    def line_boxes(box):
        if isinstance(box, boxes.LineBox):
            yield box
        for child in getattr(box, "children", ()) or ():
            yield from line_boxes(child)

    widths = []
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i + CHUNK]
        body = "".join(f'<div class="m">{r["html"]}</div>' for r in chunk)
        html = (
            f'<html dir="rtl"><head><meta charset="utf-8"/><style>'
            f"@font-face {{ font-family:IPK; src:url('file://{font}'); }}"
            f"@page {{ size: 40000px 200000px; margin:0 }} body {{ margin:0 }}"
            f".m {{ font-family:IPK; font-size:{REF_FONT_PX}px;"
            f" white-space:nowrap; width:39000px; text-align:right; }}"
            f"</style></head><body>{body}</body></html>"
        )
        doc = HTML(string=html).render()
        got = [lb.width for pg in doc.pages for lb in line_boxes(pg._page_box)]
        if len(got) != len(chunk):
            sys.exit(f"measured {len(got)} boxes for {len(chunk)} lines at {i}")
        widths.extend(got)
        print(f"  measured {i + len(chunk)}/{len(rows)}", flush=True)

    # Per page: the widest line decides that page's font size. Centred
    # lines are deliberately short (end of a surah) and must never drive
    # it — a page of nothing but centred lines falls back to them.
    full: dict[int, float] = {}
    any_line: dict[int, float] = {}
    for row, width in zip(rows, widths, strict=True):
        page = row["page"]
        any_line[page] = max(any_line.get(page, 0.0), width)
        if not row["centered"]:
            full[page] = max(full.get(page, 0.0), width)
    per_page = {p: full.get(p, w) for p, w in any_line.items()}

    if len(per_page) != 610:
        sys.exit(f"got {len(per_page)} pages, expected 610")

    OUT_PATH.write_text(json.dumps({
        "ref_font_px": REF_FONT_PX,
        "widest_line_px": {str(p): round(w, 2) for p, w in sorted(per_page.items())},
    }, indent=0) + "\n")
    vals = sorted(per_page.values())
    print(f"OK: wrote {OUT_PATH} (610 pages)")
    print(f"    widest line per page: min {vals[0]:.0f}px, "
          f"median {vals[len(vals) // 2]:.0f}px, max {vals[-1]:.0f}px "
          f"@ {REF_FONT_PX}px font")


if __name__ == "__main__":
    main()
