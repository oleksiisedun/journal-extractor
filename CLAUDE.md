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
    text spans more than one paragraph. Fixed by three corrections in
    `render.py` (`_equalize_leading_blanks()`, `_format_date_lines()`'s
    visual-line-count padding via `text_wrap.estimate_wrapped_line_count()`,
    and `_zero_space_after()`) — see
    [docs/decisions/0001-date-column-alignment.md](docs/decisions/0001-date-column-alignment.md)
    for the full rationale and consequences; re-check it before changing
    any of those three functions.
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
the daily journals). A recurring item collapses into one file with every
occurrence's date+time stacked, regardless of calendar gaps between
occurrences (a different person covering the same duty for a stretch of
days doesn't split the recurring item into separate files) — each
occurrence keeps its own dated entry rather than being folded into a
single "з ... по ..." span, so a gap day simply has no entry. Parsing
(`working_groups.py`'s `parse_working_group_blocks()`), grouping
(`group_consecutive_identical_blocks()`), date-range/filename construction
(`compute_date_ranges()`, `build_working_group_filename()`), the
year-boundary limitation, and a real fixed bug case (a recurring item with
a genuine coverage gap that used to split into near-duplicate files) are
documented in full in
[docs/working-groups.md](docs/working-groups.md).

## Time-of-day extraction

Real files use one of two mutually-exclusive-per-row formats for encoding
time: (a) inline — a content paragraph itself starts with the time (e.g.
`'00.00 на виконання ...'`), exact and always `"confident"`
(`extract_inline_time()`); (b) left-column — the narrow left column
carries times that are **not paragraph-aligned** with the content column,
handled by a snap-to-nearest-boundary heuristic
(`is_boundary_paragraph()`, `_assign_time_boundaries_left_column()`) that
marks a snap `"uncertain"` past a slack threshold. `assign_time_boundaries()`
tries (a) first, falls back to (b). Full heuristic rationale, the
empirical evidence behind it, and the caveat that it's derived from only
three sample files are in
[docs/time-extraction.md](docs/time-extraction.md) — re-check that before
touching either format's handling.

## Not yet built

- A real accuracy benchmark: ~15-20 hand-verified (person, day, expected
  pointer) cases **against real `journals/` `.docx` files**, tracked as a
  pass-rate. `tests/` (see "Unit tests" below) covers the same bug-log
  regression cases at the function level with synthetic paragraph lists —
  useful for catching a logic regression the moment it's introduced — but
  that's not a substitute for exercising the real parsing/prefilter chain
  end-to-end against actual source documents, which this item is still
  about.

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
  `domain_types.py` (shared type aliases/`TypedDict`s for the shapes
  passed between modules — e.g. `Paragraphs`, `Pointer`, `Fragment`,
  `MergedEntry` — kept in one place so a shape change touches a single
  definition instead of every module that names it),
  `docx_parsing.py`, `prefilter.py` (surname/full-name narrowing +
  `build_pointer()`), `time_extraction.py`, `assembly.py`, `pipeline.py`
  (`resolve_day_fragment()` — the per-day orchestration wrapper),
  `person_spec.py` (`parse_person_spec()` — optional per-person requested
  date range), `merge.py` (`merge_consecutive_entries()` — cross-day
  date-range merging), `date_formatting.py` (`format_date()`,
  `format_date_span()` — the `"DD.MM.YYYY"`/`"з ... по ..."` formatting
  shared between `render.py` and `working_groups.py`, kept in one place so
  the two output paths can't drift apart on wording), `render.py` (fills
  `templates/1.docx`),
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

## Static checks (lint / format / types)

Not to be confused with the pipeline's own domain guardrails (step 7
above, e.g. "target surname must appear in the final text") — this
section is generic code-quality tooling, checked via `pyproject.toml`.

Run `./check.sh` before committing a logic change (skip for a pure
docs/comment/sample-data change). It runs, in order:
- `uv run ruff check src/ tests/` — lint (`select = ["E", "F", "I", "B",
  "UP", "SIM"]` in `pyproject.toml`: pycodestyle, pyflakes, import
  sorting, bugbear, pyupgrade, simplify).
- `uv run ruff format --check src/ tests/` — formatting. Run `uv run ruff
  format src/ tests/` (no `--check`) to fix in place.
- `uv run pyright` — type checking, `standard` mode, over both `src/` and
  `tests/` (`[tool.pyright]`'s `include`). Every function signature
  carries real type hints (shared shapes live in `domain_types.py`) —
  `standard` mode has already caught real bugs from its own inference
  this way (e.g. a possibly-`None` `_Cell.width` in `render.py`, and an
  earlier `date | None` comparison bug) that a JSDoc comment convention
  wouldn't have.
- `uv run pytest` — `tests/` mirrors `src/`'s module split; see "Unit
  tests" below.
- `shellcheck run.sh check.sh` — shell lint.
- `shfmt -d run.sh check.sh` — shell formatting check. Run `shfmt -w
  run.sh check.sh` (no `-d`) to fix in place.

Dev dependencies (`ruff`, `pyright`, `pytest`) are declared in
`pyproject.toml`'s `[dependency-groups] dev` and pinned in the committed
`uv.lock`; `uv run <tool>` resolves and uses that exact pinned version
without needing anything installed globally — run `uv sync` once to
create `.venv/` (uv does this automatically on first `uv run` too).
`shellcheck`/`shfmt` aren't Python packages, so they still come from your
OS package manager. Not wired into a git hook or CI — run manually.

## Unit tests

`tests/` mirrors `src/`'s module split (`test_merge.py`, `test_assembly.py`,
etc.), one file per module that has real branching logic to test.
`pyproject.toml`'s `[tool.pytest.ini_options]` puts `src/` on
`pythonpath` so tests import modules directly (`from merge import ...`),
matching how the modules already import each other. Every test uses
synthetic paragraph lists/dicts, never a real `.docx` file — fast,
deterministic, no `journals/`/`templates/` dependency. Several tests
encode the exact regression cases from
[docs/bug-log.md](docs/bug-log.md) (items 1, 2, 3, 4, 5, 6) as
`pytest.raises`/assertion cases instead of prose, so a future change to
`prefilter.py`'s finder functions or `assembly.py`'s stripping/guardrail
logic that reintroduces one of those bugs fails loudly and immediately,
rather than waiting to be caught on the next production run. Not covered (deliberately — "skip tests that don't earn their keep", per
the global CLAUDE.md's unit-test doc): `render.py` (real docx-XML/template
orchestration, better verified manually against
`docs/decisions/0001-date-column-alignment.md`'s real case), and
`generate_extract.py` (thin CLI/glue wiring already-tested functions
together).
