# Journal Extract Generator — Project Context

## What this is

A pipeline that automatically generates official "витяг" (extract) documents
from journal records for a specific
serviceman over a date range, sourced from per-day `.docx` files.

Source documents carry a restricted (internal-use) classification and
contain real personnel names, ranks, unit positions, and order numbers.
**This must stay fully local/offline — no cloud LLM calls, no telemetry, no
LLM of any kind.** The pipeline is 100% deterministic string/regex logic
(see "Core architectural principle" below).

## The one rule everything else follows

**The output text must be 100% verbatim from the source journal. Zero
paraphrasing, zero rewriting, zero "smoothing" of style.** This is an
official document — invented or reworded text is not an acceptable failure
mode, ever.

The only edits ever allowed:
1. Selecting *which* paragraphs to include (a person's mention doesn't have
   to be contiguous with its legal-basis order reference).
2. One mechanical punctuation fix: a trailing `;` → `.` if it ends up as the
   very last character after assembly (because the source item wasn't last
   in its original list).
3. Stripping MGRS-style grid coordinates (e.g. `37U CR 1234 5678`) wherever
   they appear, including cleanup of any parenthetical group that becomes
   empty once its coordinates are removed, and the introducing phrase "за
   координатами" (by/at coordinates) when it's left dangling with nothing
   left to refer to. Coordinates are tactical data with no place in a
   personnel extract — this is a blanket rule, not conditional on context.
   See `strip_coordinates()`.
4. Stripping the phrase "район зосередження" (concentration area) and its
   grammatical variants (районі, району, зосередженню, ...), including an
   immediately preceding preposition (у/в/на) so nothing dangles. Same
   rationale as coordinates — tactical location data, blanket rule. See
   `strip_location_labels()`.

If another person shares the exact same paragraph/sentence as the target,
their text is left in place, untouched — no redaction of other people's
names is performed.

Nothing else. If you're ever tempted to "clean up" or "reword" anything,
stop — that's the wrong direction for this project.

## Core architectural principle: fully deterministic pointer resolution

There is no text-generation model anywhere in this pipeline. Locating a
person's mention resolves to **pointers** into a numbered paragraph list:
which paragraphs are needed for context, and which single paragraph
contains the target person — computed entirely by deterministic
string/regex logic in `prefilter.py` (`build_pointer()`). All actual text
assembly is done by deterministic Python code that slices the original
source characters, so there is no channel through which wording drift
could ever be introduced — not because a model was constrained well, but
because there is no model.

```json
{
  "found": true,
  "context_paragraph_indices": [89],
  "target_paragraph_index": 97
}
```

- `context_paragraph_indices` — legal-basis / section-header paragraphs
  (order references, position headers). **Not necessarily contiguous** with
  the target — there can be a long run of *other people's own paragraphs*
  in between, and that gap is simply skipped, never included.
- `target_paragraph_index` — the single paragraph containing the person,
  found by `find_full_name_paragraph()` once full-name narrowing has
  already confirmed the name occurs verbatim in the candidate window.

## Pipeline (as currently implemented — entry point `generate_extract.py`,
run via `run.sh`)

1. **Parse** a day's `.docx` into an indexed paragraph list via
   `python-docx` (NOT `pandoc` — pandoc reflows/normalizes whitespace,
   which breaks verbatim-fidelity guarantees). Paragraphs live inside a
   single table cell in these documents.
2. **Surname prefilter** (deterministic): find all paragraphs containing
   the surname, build ±8-paragraph windows around each hit. If zero hits,
   return `found: false` immediately.
3. **Full-name narrowing** (deterministic): of the surname-based windows,
   keep only the one(s) that contain the full name (surname + first name +
   patronymic) verbatim. If this narrows to exactly one window, that's the
   only window pointer resolution ever looks at — this is what prevents
   context from two namesakes governed by different orders from ever being
   mixed (see bug log below). Zero matches means the full name isn't
   verbatim anywhere that day even though the surname is — this fails
   closed (`found: false`) rather than resolving from weaker surname-only
   context. Two or more matches is genuine ambiguity (e.g. two
   identically-named people); `select_ambiguous_window()` picks the first
   or last occurrence in the file per `FULL_NAME_AMBIGUITY_STRATEGY` in
   `config.py`.
4. **Pointer resolution** (deterministic — `build_pointer()` in
   `prefilter.py`): `target_paragraph_index` is
   `find_full_name_paragraph()`'s result — guaranteed to match somewhere in
   the narrowed window. `context_paragraph_indices` is built by walking
   backward from that target paragraph for (a) the nearest preceding
   paragraph matching `ORDER_REF_PATTERN` — this can be dozens of
   paragraphs outside the ±8 window, e.g. one order heading a long
   composition list of many call-sign groups — and (b) the nearest
   preceding position/call-sign/group label (contains `«»` guillemets or
   ends in `:`, or — weaker, only trusted immediately adjacent — has no
   bare surname-like token at all), skipping over any of the target's
   fellow list members along the way since the target isn't always the
   first person listed under their label.
5. **Deterministic assembly**: slice the indicated paragraphs and join
   them. No redactions — other people's text sharing the target's
   paragraph is left as-is.
6. **Coordinate / location-label stripping**: `strip_coordinates()` removes
   MGRS-style grid coordinates (e.g. `37U CR 1234 5678`), and
   `strip_location_labels()` removes the phrase "район зосередження" and
   its grammatical variants — both applied per-paragraph, before the
   fragment is joined. Both run unconditionally, always, not just when the
   content looks out of place.
7. **Guardrails** (all added after observing real failures — see
   [docs/bug-log.md](docs/bug-log.md), do not remove without understanding
   why they exist):
   - Target's surname must appear in the final assembled text.
   - Context paragraphs must not reference more than one distinct order
     number (regex `№\S+`).
8. **Punctuation fix**: trailing `;` → `.`, mechanical, nothing else.
9. **Date + time metadata** (deterministic — see "Time-of-day extraction"
   below): `extract_date_from_filename()` parses the day's date from the
   `.docx` filename (separator between DD/MM/YYYY varies by file — `_`,
   `.`, or `-`, all seen in real filenames); `assign_time_boundaries()` +
   `time_for_paragraph()` resolve which time governs the target paragraph,
   trying the exact inline format first and falling back to the
   left-column heuristic. `assemble_fragment()` returns a dict
   (`{"text", "date", "time", "time_confidence"}`), not a bare string.
10. **Per-day resolution wrapper** (`pipeline.py`): `resolve_day_fragment()`
    wraps steps 2-9 (surname prefilter through `assemble_fragment()`) into
    one call returning `{"status": "found"|"not_found"|"rejected",
    "result", "pointer", "note"}` — called by `generate_extract.py` once
    per person per day, collecting each person's `"found"` days across all
    of `journals/`, so the not-found/ambiguous/guardrail branching lives
    in one place rather than being duplicated inline.
11. **Template rendering** (`render.py`): `render_extract()` fills
    `templates/1.docx` — the real extract template, two placeholders:
    `{дата}` / `{витяг}` inside the results table's single data row (the
    header no longer carries an issuance-date placeholder — it's static
    template text now). Every value written comes
    verbatim out of `assemble_fragment()`'s output; rendering is pure
    placeholder substitution, never text generation. Each person's
    `"found"` days are stacked as additional paragraphs inside that same
    single row (blank-paragraph separated) rather than cloning a new table
    row per day — matches the template's literal one-row structure.
    An uncertain time renders identically to a confident one — just the raw
    value, no inline warning — since `_format_time_line()` no longer
    branches on `time_confidence`; an entirely unresolved time (no value at
    all) is still left out of the rendered text, since inventing a
    placeholder value would violate the verbatim rule and the date line
    alone already makes that gap visible to whoever reviews the extract.
    `time_confidence` is still computed and threaded through
    `assemble_fragment()`/`merge_consecutive_entries()` even though nothing
    currently reads it for rendering — kept as domain data in case a future
    consumer (e.g. console output) needs it again. `generate_extract.py` is
    the entry point: one `.docx` per person, written to `OUTPUT_DIR`
    (`config.py`).

    **Keeping the {дата} column aligned with {витяг}**: the two cells are
    filled independently, so without compensation each entry's date would
    drift from its matching text as soon as any earlier entry's assembled
    text spans more than one paragraph. Three corrections, all in
    `render.py`:
    - `_equalize_leading_blanks()` trims whichever cell has more static
      leading paragraphs before its placeholder down to the other's count
      — the real template has 3 blank paragraphs before `{дата}` but only
      2 (a header line + blank) before `{витяг}`, a constant offset that
      would otherwise persist regardless of entry content. Only ever
      deletes blank paragraphs, never real template text.
    - `_format_date_lines()` pads each entry's date block — except the
      last entry, which is never padded, since that padding exists only to
      push a *later* entry's date down; padding it anyway just adds
      trailing blank paragraphs that make the {дата} cell (and so the
      whole row) taller than the content needs, leaving a visible empty
      gap at the bottom of the table — with blank paragraphs up to that
      entry's *measured visual line count* (`_entry_visual_line_count()`),
      not its raw paragraph count — a long order-reference paragraph is
      one docx paragraph but wraps to several visual lines in Word, so
      matching on paragraph count alone still left later dates landing
      early, inside an earlier entry's wrapped paragraph. Line counts come
      from `text_wrap.estimate_wrapped_line_count()`
      — a real greedy word-wrap simulation against actual glyph widths from
      the bundled font `assets/fonts/Carlito-Regular.ttf` (Carlito is
      metric-compatible with Calibri, `templates/1.docx`'s real but
      unembedded/uninstalled font, and is what LibreOffice — which this
      template's own fingerprints indicate produced/renders it — silently
      substitutes for a missing Calibri), measured against the `{витяг}`
      cell's actual width/margins/first-line-indent read straight from the
      template (`render.py`'s `_fragment_line_widths_pt()`,
      `_cell_margin_twips()`, `_run_font_size_pt()`) — not a guessed
      constant. Still a simulation, not Word's own layout engine, so
      occasional ±1 line drift is possible on unusual paragraph shapes
      (e.g. break opportunities around `/` or `-` that this word-based
      splitter doesn't model); re-validate if `templates/1.docx`'s column
      width or font ever change. Requires Pillow (for font glyph-width
      measurement) — not currently pinned in a requirements file, since
      this project doesn't have one yet.
    - `_zero_space_after()`, applied inside `_expand_multiline_placeholder()`:
      every paragraph in the template — including a blank filler one —
      carries a fixed 8pt `w:spacing w:after`, which Word charges once per
      *paragraph*, not once per *visual line*. A `{витяг}` paragraph that
      wraps to N lines only pays that 8pt once, but the old padding built N
      separate one-line filler paragraphs, each paying its own 8pt — so
      the `{дата}` column ended up taller than the `{витяг}` text it was
      supposed to track, drifting further with each earlier multi-line
      entry (see bug log item 12). Fixed by having `_format_date_lines()`
      emit `(text, suppress_space_after)` pairs: only as many filler
      paragraphs per entry as that entry's real `{витяг}` paragraph count
      keep normal space-after, the rest get it zeroed — matching the two
      columns' total charged space-after instances exactly, regardless of
      how many lines a paragraph wraps to.
12. **Requested date range** (`person_spec.py`): each person's CLI spec may
    carry an optional trailing `DD.MM.YYYY` or `DD.MM.YYYY-DD.MM.YYYY`
    (e.g. `"старший солдат БОНДАРЕНКО Олег Васильович
    02.04.2026-23.04.2026"`), parsed by `parse_person_spec()` and used in
    `generate_extract.py`'s per-person loop to filter which of
    `journals/`'s already-loaded days get searched for that person. When a
    range is given, every calendar date in it with no matching `.docx`
    file is printed as an explicit gap (`"ЖУРНАЛ ВІДСУТНІЙ"`) — distinct
    from the day-has-a-file-but-person-not-mentioned case (`"пропущено"`)
    — since the two are genuinely different failure modes and must never
    be conflated. No trailing date at all preserves the original
    behavior: every day in `journals/` is searched. A malformed spec
    (`date_from` after `date_to`, invalid calendar date) only skips that
    one person; the rest of the batch still runs.
13. **Cross-day merging** (`merge.py`): before rendering,
    `merge_consecutive_entries()` collapses a run of consecutive `"found"`
    days whose assembled text is byte-identical into a single entry
    carrying `date_from`/`date_to` instead of a single `date` — this is
    how real extract samples represent standing/recurring text (see
    `samples/Витяг з ЖБД на 100к ЛИПЕНЬ Сімоненков.docx`: nine identical
    days collapse into one `"з 01.07.2026 по 09.07.2026"` line instead of
    nine stacked copies). A run only merges across *exactly* consecutive
    calendar dates — a gap (person not found on an intervening day) always
    breaks it, even if identical text resumes afterward, since merging
    across a gap would misrepresent presence on the missing day(s). A
    merged (multi-day) entry drops its `time`/`time_confidence` — no
    single time correctly represents an entire range — while a single-day
    entry (`date_from == date_to`) keeps showing its date + time exactly
    as before. `render.py`'s `_format_date_lines()` renders a merged entry
    as one `"з ... по ..."` line and a single-day entry as its usual
    date-then-time pair.

## `--working-groups` mode (alternate entry path)

`generate_extract.py --working-groups <file.docx> [--year YYYY]` is a
structurally different mode from the per-person pipeline above: instead of
one extract per *person* across many days, it produces one extract per
*distinct reporting item ("block") text, once punctuation marks are
ignored* found in a single month-spanning "РОБОЧІ ГРУПИ" (working groups)
report — a `.docx` written as flowing body paragraphs (no table, unlike
the daily journals). A recurring item (same governing order, same body
text modulo incidental punctuation — e.g. a trailing `.` one day vs `;`
another, or a `,` vs `;` mid-sentence) collapses into one file with every
occurrence's date+time stacked, instead of one near-duplicate file per
day — **every occurrence of that same item goes into the same file
regardless of calendar gaps between occurrences** (e.g. a different person
covers the same duty for a stretch of days, then the original person's
identical-text entry resumes later in the month): each occurrence keeps
its own dated entry rather than being folded into a single "з ... по ..."
span, so a gap day simply has no entry and nothing is misrepresented — see
bug case below. Each block's own text still renders byte-verbatim in the
output — only the *grouping decision* ignores punctuation, per
`working_groups.py`'s `_normalize_for_grouping()`.

`working_groups.py`'s `parse_working_group_blocks()` walks the
document's paragraphs deterministically: a `DD.MM` line is a date-header
that supplies the fallback date for items that follow; each reporting
item is recognized by `ITEM_START_PATTERN` (an optional leading
`DD.MM.YYYY` override, then an `HH:MM-HH:MM`-shaped time range, both as
named regex groups) and carries its remaining text verbatim (the matched
date-override/time-range prefix is split off into the block's own `"time"`
field rather than left inline — it's structural item metadata, not
narrative content, and leaving it inline would (a) defeat byte-identical
text comparison between otherwise-identical days and (b) leave the
rendered `{дата}` column with nothing to show, since `time` used to be
discarded entirely) plus any order numbers found via
`WORKING_GROUP_ORDER_REF_PATTERN` (a working-groups-specific pattern —
deliberately not `patterns.ORDER_REF_PATTERN` — tolerant of `БР`-prefixed
and space-variant order tokens). A paragraph matching neither shape is
skipped with a loud warning, never silently dropped.

A header-derived date (no inline `DD.MM.YYYY` on the item itself) pairs
the header's day/month with `--year` if given, else the year the script
happens to be *run* in (`date.today().year`) — a fallback that's only
correct when running in the same year the report covers. **Known
limitation, left unfixed by design**: a report whose own date-header
sections straddle a year boundary (e.g. late December into early January
within one file) can't be represented by one flat `--year` value; this
wasn't judged worth solving since real working-groups reports each cover a
single calendar month and so never actually straddle a year boundary
themselves — `--year` only exists for the case where the report covers one
year but the script runs in a different one (e.g. processing a December
report in January).

`generate_extract.py`'s `generate_working_groups()` sorts blocks
chronologically, applies the same coordinate/location stripping and
trailing `;` → `.` fix as the main pipeline to each block's text, then
groups them via `working_groups.py`'s `group_consecutive_identical_blocks()`
— unlike `merge.merge_consecutive_entries()`'s adjacency-walk (which
requires exactly-consecutive calendar dates and always breaks a run on a
gap), this groups **every occurrence of a given normalized text into one
group, regardless of calendar gaps** between occurrences: it buckets all
blocks by `_normalize_for_grouping()`'s punctuation-insensitive key first,
then treats each bucket as one whole group, no further date-based
splitting. This is safe (unlike folding into a single "з ... по ..." span)
because every block stays its own dated entry within the group instead of
collapsing into one line — a gap date simply produces no entry, so nothing
implies continuous presence across it. Kept as a separate function from
`merge_consecutive_entries()` rather than adding a mode flag to it, since
the two output shapes are different enough (fold-into-a-range vs.
one-group-per-distinct-text-with-every-occurrence-kept-separate) that
sharing one function would trade a clear function for a branchy one. Each
group is rendered through the same multi-entry `render_extract()` template
path the per-person pipeline already uses to stack a person's multiple
found days in one document — no changes needed there. Output filenames
come from `build_working_group_filename()`, given the group's date ranges
from `compute_date_ranges()` (partitions the group's dates into runs of
chronologically-consecutive calendar days — since a group's occurrences
can now be non-contiguous, there can be more than one such run) —
`WORKING_GROUP_UNIT_PREFIX` in `config.py` (e.g. `"3 боп"`) + the date
part + every distinct order id across the group, unioned via
`union_order_ids()` in first-appearance order. The date part is `"за
DD.MM.YYYY"` for a single day or `"з DD.MM.YYYY по DD.MM.YYYY"` for one
contiguous run (same phrasing `render.py`'s `_format_date_lines()` uses
for a merged multi-day {дата} entry) when the group has exactly one date
range; when it has more than one (the gapped case), each range instead
renders compactly as `"DD.MM.YYYY-DD.MM.YYYY"` (or bare `"DD.MM.YYYY"` for
a lone day within the list), space-separated, e.g. `"02.07.2026-05.07.2026
10.07.2026-11.07.2026 20.07.2026-31.07.2026"` — so the filename itself
never implies a continuous span the source doesn't show.
`_dedupe_output_path()` appends `" (2)"`, `" (3)"`, ... if two groups would
otherwise collide on the same filename. Legacy binary `.doc` input is
rejected up front (checked by file signature, not extension).

**Bug case (fixed): a recurring item with a real coverage gap used to
split into multiple near-duplicate files instead of one.** Real case
(`journals/РОБОЧІ ГРУПИ 01.07-31.07.docx`, order `№БР1927/(S-3) ВКП/ДСК`,
БАЙЛИМ Іван Сергійович's identical-text entry): he covered this duty
02.07–05.07, someone else covered it 06.07–19.07, then he resumed
20.07–31.07 with byte-identical (post-normalization) text. Before the fix,
`group_consecutive_identical_blocks()` split same-text occurrences into a
new group every time a date gap appeared — same "gap breaks a run" rule as
`merge.merge_consecutive_entries()` — producing three separate,
near-duplicate output files for what a human reviewer would recognize as
one recurring assignment. Verified against the real source file that the
gap dates (06.07–19.07) genuinely have no matching-text block (a different
person's paragraph covers those dates instead), ruling out a parsing miss.
Fixed by removing the date-gap split entirely for this mode: grouping is
now purely by normalized text, and `compute_date_ranges()` +
`build_working_group_filename()`'s multi-range format make the resulting
single file's filename correctly show the three separate spans instead of
falsely claiming one continuous run.

## Time-of-day extraction

Real files use one of two formats for encoding time — never mixed within a
single day, in every file seen so far:

**(a) Inline / "easy case"** — a content paragraph itself starts with the
time (e.g. `'00.00 на виконання БОЙОВОГО РОЗПОРЯДЖЕННЯ ...'`), and the
left time column is empty. `extract_inline_time()` matches this exactly —
no guessing, always `"confident"`. This is the common case in
`journals/ЖБД 10.07.2026.docx` (84 order-intro paragraphs, each with its
own inline time).

**(b) Left-column / "hard case"** — the narrow left column carries the
times, and **the two columns are not paragraph-aligned.** Verified
empirically: in one sample the left column had 217 raw paragraphs (11
non-empty time labels), the right had 155, and the gaps between
consecutive time labels (57, 41, 11, 6, 10, 2, 2, 2, 17, 3 paragraph-slots)
don't track the right column's structure proportionally. A naive
linear-interpolation mapping from left-column position to right-column
position landed correctly on real section/list headers for only some
labels — for the rest it landed **inside a single, homogeneous ~30-person
list governed by one order**, which would have silently mis-assigned a
time to real people. The alignment is purely visual/eyeballed by whoever
typed the document — there is no textual convention that recovers it
exactly. Instead, a snap-to-nearest-boundary heuristic is used
(`is_boundary_paragraph()`, `_assign_time_boundaries_left_column()`):
1. Only paragraphs that look like a genuine section/list boundary — Roman-
   numeral headers, lines ending in `:`, or order-reference sentences
   (`№\S+`) — are ever eligible to receive a time assignment. Ordinary list
   entries (a single person's line) never qualify. This is what stops a
   time label from being snapped into the middle of a person list.
2. Each time label's raw column-0 position is mapped to a proportional cut
   point in column-1, then **snapped forward** to the nearest eligible
   boundary paragraph.
3. A snap is marked `"uncertain"` if it traveled more than a slack
   threshold (15 raw paragraphs) from its predicted cut point, or if two
   labels collided on the same boundary (ambiguous which one really
   governs it — the later, more specific time is kept). This confidence
   value is still computed and threaded through the pipeline as of this
   writing but is no longer surfaced in the rendered `.docx` (see step 11
   above) — it renders identically to a confident time.

`assign_time_boundaries()` is the dispatcher: it tries (a) first (via
`_assign_time_boundaries_inline()`) and only falls back to (b) if no
inline time tokens were found in that row's content paragraphs.

**Caveat**: only three real sample files have been checked
(`journals/ЖБД_02_04_2026.docx`, `ЖБД 10.07.2026.docx`,
`ЖБД_12-04-2026.docx`). The "column 0 = time, column 1 = content" layout,
the mutual-exclusivity-per-row assumption between formats (a) and (b), and
the boundary regexes above are derived from these — re-validate against
more files rather than assuming they generalize forever.

## Not yet built

- A real accuracy benchmark: ~15-20 hand-verified (person, day, expected
  pointer) cases, tracked as a pass-rate, to catch regressions when
  `prefilter.py`'s finder functions change instead of discovering bugs one
  production run at a time (which is how every entry in
  [docs/bug-log.md](docs/bug-log.md) was actually found).

The pipeline is pure string/regex logic over an already-parsed paragraph
list (no model inference), so it runs in well under a second per
person/day — no particular hardware requirements.

## Bug log

Every empirically-found failure that shaped `prefilter.py`'s finder
functions and `assembly.py`'s stripping logic — 7 entries so far — lives
in [docs/bug-log.md](docs/bug-log.md), not here. Read it before touching
`build_pointer()`, its finder functions, or coordinate/label stripping;
each entry is a real regression case to re-check, not a hypothetical one.

## Known test data

Person names are passed to `run.sh` directly at run time — either as
inline arguments or via a `.txt` file (one `"rank SURNAME Firstname
Patronymic"` string per line, optionally followed by a requested
`DD.MM.YYYY` or `DD.MM.YYYY-DD.MM.YYYY`; see `load_people()` in
`generate_extract.py` and `parse_person_spec()` in `person_spec.py`).
There's no committed or gitignored fixture file
for real names anymore; keep any local names file you use for regression
testing out of version control yourself. `journals/` (gitignored) still
holds the source `.docx` files.

Main sample file used throughout development: `ЖБД_02_04_2026.docx` (date
2026-04-02, from the filename; left-column time format). It contains a
same-surname/different-order pair — two people sharing one surname, each
governed by a different order — which is the namesake/disambiguation
regression test; keep using it when touching the narrowing logic.

Two more real sample files, added to exercise the other time format and
the filename-separator variants (see `journals/`, gitignored):
- `ЖБД 10.07.2026.docx` (date 2026-07-10, `.` separator) — **inline time
  format**: empty left column, 84 order-intro paragraphs each carrying its
  own inline time. Good regression file for `extract_inline_time()`.
- `ЖБД_12-04-2026.docx` (date 2026-04-12, `-` separator) — left-column
  format again, larger/messier than the main sample (includes MGRS
  coordinates in some boundary paragraphs) — useful for stress-testing
  `is_boundary_paragraph()` beyond the main sample's cleaner structure.

## Style/conventions in the existing code

- Code is split into small, single-purpose modules under `src/` (flat within
  that folder, no further package nesting — this project isn't
  distributed/packaged, so deeper nesting isn't worth it): `config.py`
  (settings), `patterns.py`
  (the one regex — `ORDER_REF_PATTERN` — shared between `assembly.py`,
  `time_extraction.py`, and `prefilter.py`; kept separate to avoid a
  circular import between `assembly.py` and `time_extraction.py`),
  `docx_parsing.py`, `prefilter.py` (surname/full-name narrowing +
  `build_pointer()`), `time_extraction.py`, `assembly.py`, `pipeline.py`
  (`resolve_day_fragment()` — the per-day orchestration wrapper),
  `person_spec.py` (`parse_person_spec()` — optional per-person requested
  date range), `merge.py` (`merge_consecutive_entries()` — cross-day
  date-range merging), `render.py` (fills `templates/1.docx`),
  `text_wrap.py` (`estimate_wrapped_line_count()` — real glyph-width-based
  word-wrap simulation used only to keep `render.py`'s `{дата}`/`{витяг}`
  columns aligned; kept separate since it's pure text-measurement geometry,
  unrelated to `render.py`'s template/XML orchestration), and
  `working_groups.py` (`parse_working_group_blocks()`,
  `group_consecutive_identical_blocks()`, `compute_date_ranges()`,
  `build_working_group_filename()` — the alternate `--working-groups`
  entry path, see above; kept separate since it parses a structurally
  different source document, not the daily per-table journals). One entry
  point, `generate_extract.py` — run via `run.sh` at the repo root, which
  just forwards its CLI arguments through — wires the modules together,
  resolves each requested person's `"found"` days across `journals/`
  (optionally narrowed to a requested date range), merges consecutive
  identical days, and writes a real extract `.docx` per person via
  `render.py`. New standalone concerns (`person_spec.py` is the precedent)
  get their own module rather than growing an existing one, consistent
  with how rendering got its own (`render.py`) instead of being bolted
  onto `assembly.py`.
- Code comments (and docstrings) are English. Console log/status/error
  messages (`print()` text, exception messages, `pipeline.py`'s `"note"`
  strings) are also English — only the actual document text/data (journal
  source content flowing into rendered output, person names, test
  fixture names) stays Ukrainian since it's being extracted verbatim, not
  translated.
- Every new failure mode found through testing should get: (1) a guardrail
  that fails loudly (never silently produces a degraded result), and (2)
  an entry in [docs/bug-log.md](docs/bug-log.md) with the real example
  that triggered it.
