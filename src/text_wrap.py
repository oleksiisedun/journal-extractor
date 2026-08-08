"""Estimates how many visual lines a paragraph of text will wrap to inside
a fixed-width docx table cell, by measuring real glyph widths from a bundled
font file (assets/fonts/Carlito-Regular.ttf) instead of guessing an average
characters-per-line constant.

Carlito is metric-compatible with Calibri (identical character advance
widths) -- and Calibri is templates/1.docx's actual font (its
docDefaults/Normal style both specify it explicitly), but it isn't embedded
in the .docx and isn't installed on this machine. Carlito is also what
LibreOffice silently substitutes for a missing Calibri, and this template's
own fingerprints (Liberation Serif/Sans alt-font entries in its
fontTable.xml, the LibreOffice-style ".~lock.*" files seen in journals/)
indicate LibreOffice is what actually renders it, so Carlito should closely
match what's really on screen.
"""

import os

from PIL import ImageFont

_FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts", "Carlito-Regular.ttf")
_MEASURE_SIZE = 1000  # arbitrary large nominal size for measurement precision; scaled to the real font size afterward
_font_cache = {}


def _measurement_font():
    """Loads (and caches) the bundled Carlito font at a large nominal size
    for precise, scale-independent width measurement."""
    if _MEASURE_SIZE not in _font_cache:
        _font_cache[_MEASURE_SIZE] = ImageFont.truetype(_FONT_PATH, _MEASURE_SIZE)
    return _font_cache[_MEASURE_SIZE]


def _text_width_pt(text, font_size_pt):
    """Real width of `text` in points at `font_size_pt`, from Carlito's
    actual glyph advance widths rather than an average-character guess."""
    if text == "":
        return 0.0
    raw_width = _measurement_font().getlength(text)
    return raw_width * (font_size_pt / _MEASURE_SIZE)


def estimate_wrapped_line_count(text, font_size_pt, first_line_width_pt, continuation_width_pt):
    """Simulates greedy word-wrap of `text` (split on spaces, no
    hyphenation -- matching templates/1.docx's
    `<w:suppressAutoHyphens w:val="true"/>` docDefault) into lines no wider
    than `first_line_width_pt` for the first line (reduced by the
    paragraph's first-line indent) then `continuation_width_pt` for every
    line after. Returns the number of lines produced; an empty string is
    always 1 (blank) line. A single word wider than its line's available
    width is still placed alone on that line -- Word doesn't break
    mid-word without hyphenation -- rather than looping forever."""
    if text == "":
        return 1

    space_width = _text_width_pt(" ", font_size_pt)
    lines = 1
    available = first_line_width_pt
    current_width = 0.0

    for word in text.split(" "):
        word_width = _text_width_pt(word, font_size_pt)
        if current_width == 0.0:
            current_width = word_width
            continue
        needed = current_width + space_width + word_width
        if needed <= available:
            current_width = needed
        else:
            lines += 1
            available = continuation_width_pt
            current_width = word_width

    return lines
