# Combat Log Extract Generator — Project Context

## What this is

A pipeline that automatically generates official "витяг" (extract) documents
from combat log records for a specific
serviceman over a date range, sourced from per-day `.docx` files.

Source documents carry a restricted (internal-use) classification and
contain real personnel names, ranks, unit positions, and order numbers.
**This must stay fully local/offline — no cloud LLM calls, no telemetry, no
LLM of any kind.** The pipeline is 100% deterministic string/regex logic
(see "Core architectural principle" below); an earlier version used a
local LLM and it was removed once every field it produced turned out to be
already derivable deterministically.

## The one rule everything else follows

**The output text must be 100% verbatim from the source combat log. Zero
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
names is performed (project decision; an earlier version of this pipeline
did redact them, see "Core architectural principle" below).

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

**History**: an earlier version of this pipeline used a local LLM (Ollama,
`qwen3:8b-q8_0`) to produce this same pointer, plus a third field
(`redactions`) for stripping other people's text out of a shared paragraph.
It was removed once it became clear every field it returned was already
derivable deterministically: `found` and `target_paragraph_index` come
straight out of full-name narrowing, and `context_paragraph_indices` was
already being force-overridden with `find_preceding_order_paragraph()` /
`find_preceding_label_header()`'s output regardless of what the LLM
answered (see [docs/bug-log.md](docs/bug-log.md) items 6, 7, 9).
Separately, the project decided `redactions` is no longer needed at all —
other people sharing the target's paragraph are now left in the text
as-is. The bug log is kept because it documents *why* the deterministic
finder functions look the way they do — every entry describes a real
failure that shaped `prefilter.py`, not a hypothetical one.

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
   first person listed under their label. This used to run *before* an LLM
   call and then get force-merged into the pointer regardless of what the
   LLM itself returned — found empirically that the LLM would still drop
   the label paragraph even when it was already visible in-window and a
   prompt rule asked for it explicitly (see
   [docs/bug-log.md](docs/bug-log.md)). It's now simply the
   entire answer, since nothing else was ever contributing a correct
   answer the LLM was actually needed for.
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
    `templates/1.docx` — the real extract template, three placeholders:
    `{дата витягу}` (issuance date, in the header) and `{дата}` / `{витяг}`
    inside the results table's single data row. Every value written comes
    verbatim out of `assemble_fragment()`'s output; rendering is pure
    placeholder substitution, never text generation. Each person's
    `"found"` days are stacked as additional paragraphs inside that same
    single row (blank-paragraph separated) rather than cloning a new table
    row per day — matches both the template's literal one-row structure
    and one of the two real sample layouts observed; the other real sample
    clones a row per day, which was deliberately not chosen (see git
    history / the plan behind this feature for the two layouts compared).
    Uncertain or entirely unresolved times are flagged inline in the
    rendered text itself (e.g. `"05.00 (час приблизний — перевірити)"`),
    never silently presented as fact. `generate_extract.py` is the entry
    point: one `.docx` per person, written to `OUTPUT_DIR`
    (`config.py`).

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
time to real people. Confirmed with the user: this alignment is purely
visual/eyeballed by whoever typed the document — there is no textual
convention that recovers it exactly, short of rendering the page
(LibreOffice → PDF/coordinates), which was deliberately ruled out as too
heavy for now. Instead, a snap-to-nearest-boundary heuristic is used
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
   governs it — the later, more specific time is kept). `"uncertain"`
   results must be surfaced to the user, never silently presented as fact
   — same posture as the surname/order-number guardrails.

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

- Cross-day merging: collapsing consecutive days with byte-identical
  fragments into a single "з ... по ..." date range (this is how one of
  the real extract samples looks for continuous multi-day presence — see
  the two original sample files if still available:
  `Витяг_з_ЖБД_на_100к_ЛИПЕНЬ_Клименко.docx`,
  `Витяг_ЖБД_Бондаренко_07_2026.docx`). `render.py` currently stacks every
  `"found"` day as its own separate block in the output `.docx` rather
  than collapsing repeats — the natural next step once this is built.
- Batch driver / requested date range: `generate_extract.py` iterates
  every `.docx` file found in `COMBAT_LOG_DIR` (`config.py`, default
  `journals/`), sorted chronologically by filename date, and runs the
  per-day pipeline independently for each — but doesn't yet accept a
  requested date range or flag gaps (a requested date with no matching
  file — genuinely absent vs. a matching failure — must always be
  surfaced explicitly, never silently dropped). Remains open work.
- A real accuracy benchmark: ~15-20 hand-verified (person, day, expected
  pointer) cases, tracked as a pass-rate, to catch regressions when
  `prefilter.py`'s finder functions change instead of discovering bugs one
  production run at a time (which is how every entry in
  [docs/bug-log.md](docs/bug-log.md) was actually found).

Since the pipeline is now pure string/regex logic over an already-parsed
paragraph list (no model inference), it runs in well under a second per
person/day — no particular hardware requirements, and the LLM configuration
notes that used to live here no longer apply.

## Bug log

Every empirically-found failure that shaped `prefilter.py`'s finder
functions and `assembly.py`'s stripping logic — 10 entries so far — lives
in [docs/bug-log.md](docs/bug-log.md), not here. Read it before touching
`build_pointer()`, its finder functions, or coordinate/label stripping;
each entry is a real regression case to re-check, not a hypothetical one.

## Known test data

Person names are passed to `run.sh` directly at run time — either as
inline arguments or via a `.txt` file (one `"rank SURNAME Firstname
Patronymic"` string per line; see `load_people()` in
`generate_extract.py`). There's no committed or gitignored fixture file
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
  `render.py` (fills `templates/1.docx`). One entry point,
  `generate_extract.py` — run via `run.sh` at the repo root, which just
  forwards its CLI arguments through — wires the modules together,
  resolves each requested person's `"found"` days across `journals/`, and
  writes a real extract `.docx` per person via `render.py`. The batch
  date-range/gap-flagging driver (still not yet built) should get its own
  new module rather than growing an existing one, consistent with how
  rendering got its own (`render.py`) instead of being bolted onto
  `assembly.py`.
- Code comments (and docstrings) are English — the actual document
  text/data (combat log source content, test names, runtime console
  output) stays Ukrainian since it's being extracted verbatim, not
  translated.
- Every new failure mode found through testing should get: (1) a guardrail
  that fails loudly (never silently produces a degraded result), and (2)
  an entry in [docs/bug-log.md](docs/bug-log.md) with the real example
  that triggered it.
