# 0001: Keeping the `{дата}` column aligned with `{витяг}`

## Context

`render.py`'s `render_extract()` fills two placeholders inside
`templates/1.docx`'s single results row: `{дата}` (date/time) and `{витяг}`
(the assembled fragment text). Each person's `"found"` days are stacked as
additional paragraphs inside that same row. The two cells are filled
independently, so without compensation each entry's date would drift from
its matching text as soon as any earlier entry's assembled text spans more
than one paragraph.

## Decision

Three corrections, all in `render.py`:

- `_equalize_leading_blanks()` trims whichever cell has more static
  leading paragraphs before its placeholder down to the other's count —
  the real template has 3 blank paragraphs before `{дата}` but only 2 (a
  header line + blank) before `{витяг}`, a constant offset that would
  otherwise persist regardless of entry content. Only ever deletes blank
  paragraphs, never real template text.
- `_format_date_lines()` pads each entry's date block — except the last
  entry, which is never padded, since that padding exists only to push a
  *later* entry's date down; padding it anyway just adds trailing blank
  paragraphs that make the `{дата}` cell (and so the whole row) taller
  than the content needs, leaving a visible empty gap at the bottom of the
  table — with blank paragraphs up to that entry's *measured visual line
  count* (`_entry_visual_line_count()`), not its raw paragraph count — a
  long order-reference paragraph is one docx paragraph but wraps to
  several visual lines in Word, so matching on paragraph count alone still
  left later dates landing early, inside an earlier entry's wrapped
  paragraph. Line counts come from
  `text_wrap.estimate_wrapped_line_count()` — a real greedy word-wrap
  simulation against actual glyph widths from the bundled font
  `assets/fonts/Carlito-Regular.ttf` (Carlito is metric-compatible with
  Calibri, `templates/1.docx`'s real but unembedded/uninstalled font, and
  is what LibreOffice — which this template's own fingerprints indicate
  produced/renders it — silently substitutes for a missing Calibri),
  measured against the `{витяг}` cell's actual width/margins/first-line
  indent read straight from the template (`render.py`'s
  `_fragment_line_widths_pt()`, `_cell_margin_twips()`,
  `_run_font_size_pt()`) — not a guessed constant. Still a simulation, not
  Word's own layout engine, so occasional ±1 line drift is possible on
  unusual paragraph shapes (e.g. break opportunities around `/` or `-`
  that this word-based splitter doesn't model); re-validate if
  `templates/1.docx`'s column width or font ever change. Requires Pillow
  (for font glyph-width measurement).
- `_zero_space_after()`, applied inside `_expand_multiline_placeholder()`:
  every paragraph in the template — including a blank filler one —
  carries a fixed 8pt `w:spacing w:after`, which Word charges once per
  *paragraph*, not once per *visual line*. A `{витяг}` paragraph that
  wraps to N lines only pays that 8pt once, but the old padding built N
  separate one-line filler paragraphs, each paying its own 8pt — so the
  `{дата}` column ended up taller than the `{витяг}` text it was supposed
  to track, drifting further with each earlier multi-line entry (see
  [bug-log.md](../bug-log.md) item 7). Fixed by having
  `_format_date_lines()` emit `(text, suppress_space_after)` pairs: only
  as many filler paragraphs per entry as that entry's real `{витяг}`
  paragraph count keep normal space-after, the rest get it zeroed —
  matching the two columns' total charged space-after instances exactly,
  regardless of how many lines a paragraph wraps to.

## Consequences

- The alignment math depends on reading real template geometry
  (`templates/1.docx`'s column width, margins, font size) rather than
  hardcoded constants, so it keeps working if the template's row content
  changes but breaks silently-wrong if the template's *column width or
  font* changes without re-validating this logic.
- `text_wrap.py`'s word-wrap simulation is an approximation of Word's
  real layout engine (no hyphenation modeling of break points around `/`
  or `-`), so occasional ±1 line drift is possible and expected on unusual
  paragraph shapes — not a bug to chase, a known limitation of simulating
  layout instead of rendering it.
- This logic has no automated regression test (see `CLAUDE.md`'s "Not yet
  built" section) — re-verify manually against
  [bug-log.md](../bug-log.md) item 7's real case
  (`output/Витяг_ТРОПІН_2026-08-08.docx`) before changing any of the three
  functions above.
