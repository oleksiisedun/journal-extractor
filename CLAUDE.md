# ЖБД Extract Generator — Project Context

## What this is

A pipeline that automatically generates official "витяг" (extract) documents
from ЖБД (Ukrainian military combat log) records for a specific
serviceman over a date range, sourced from per-day `.docx` files.

Source documents carry a "ДСК" (restricted/internal-use) classification and
contain real personnel names, ranks, unit positions, and order numbers.
**This must stay fully local/offline — no cloud LLM calls, no telemetry.**

## The one rule everything else follows

**The output text must be 100% verbatim from the source ЖБД. Zero
paraphrasing, zero rewriting, zero "smoothing" of style.** This is an
official document — invented or reworded text is not an acceptable failure
mode, ever.

The only edits ever allowed:
1. Selecting *which* paragraphs to include (a person's mention doesn't have
   to be contiguous with its legal-basis order reference).
2. Removing *other people's* text when they share the exact same paragraph
   as the target person (never the target's own text).
3. One mechanical punctuation fix: a trailing `;` → `.` if it ends up as the
   very last character after assembly (because the source item wasn't last
   in its original list).
4. Stripping MGRS-style grid coordinates (e.g. `37U CR 1234 5678`) wherever
   they appear, including cleanup of any parenthetical group that becomes
   empty once its coordinates are removed. Coordinates are tactical data
   with no place in a personnel extract — this is a blanket rule, not
   conditional on context. See `strip_coordinates()`.
5. Stripping the phrase "район зосередження" (concentration area) and its
   grammatical variants (районі, району, зосередженню, ...), including an
   immediately preceding preposition (у/в/на) so nothing dangles. Same
   rationale as coordinates — tactical location data, blanket rule. See
   `strip_location_labels()`.

Nothing else. If you're tempted to have the LLM "clean up" or "reword"
anything, stop — that's the wrong direction for this project.

## Core architectural principle: the LLM never writes the final text

The LLM's only job is to return **pointers** into a numbered paragraph list:
which paragraphs are needed for context, which single paragraph contains the
target person, and (rarely) which substrings of *other* people to strip out
of that paragraph. All actual text assembly is done by deterministic Python
code that slices the original source characters — the LLM literally cannot
introduce wording drift, because it never gets a chance to output prose.

```json
{
  "found": true,
  "context_paragraph_indices": [89],
  "target_paragraph_index": 97,
  "redactions": []
}
```

- `context_paragraph_indices` — legal-basis / section-header paragraphs
  (order references, position headers). **Not necessarily contiguous** with
  the target — there can be a long run of *other people's own paragraphs*
  in between, and that gap is simply skipped, never included.
- `target_paragraph_index` — the single paragraph containing the person.
- `redactions` — verbatim substrings of *other* people to cut, used ONLY
  when someone else shares the exact same paragraph/sentence as the target
  (e.g. two names in one continuous sentence). Most of the time this is `[]`.

## Pipeline (as currently implemented in `test_vytyah_extraction.py`)

1. **Parse** a day's `.docx` into an indexed paragraph list via
   `python-docx` (NOT `pandoc` — pandoc reflows/normalizes whitespace,
   which breaks verbatim-fidelity guarantees). Paragraphs live inside a
   single table cell in these documents.
2. **Surname prefilter** (deterministic, no LLM): find all paragraphs
   containing the surname, build ±8-paragraph windows around each hit. If
   zero hits, return `found: false` immediately — no LLM call needed.
3. **Full-name narrowing** (deterministic, no LLM): of the surname-based
   windows, keep only the one(s) that contain the full name (surname +
   first name + patronymic) verbatim. If this narrows to exactly one
   window, that's all the LLM ever sees — this is what prevents the LLM
   from mixing context between two namesakes governed by different orders
   (see bug log below). Falls back to all surname-windows if 0 or 2+ match.
4. **LLM call** (Ollama, local): given the (usually single, ~10-paragraph)
   candidate window, returns the pointer JSON above. See "LLM config"
   below for the non-obvious settings this depends on.
5. **Deterministic assembly**: slice the indicated paragraphs, apply exact
   `str.replace()` for each redaction (raises `ValueError` — fail closed —
   if a redaction substring isn't found character-for-character).
6. **Coordinate / location-label stripping**: `strip_coordinates()` removes
   MGRS-style grid coordinates (e.g. `37U CR 1234 5678`), and
   `strip_location_labels()` removes the phrase "район зосередження" and
   its grammatical variants — both applied per-paragraph, after redactions
   (so redaction matching still runs against untouched source text) and
   before the fragment is joined. Both run unconditionally, always, not
   just when the content looks out of place.
7. **Guardrails** (all added after observing real model failures — see bug
   log, do not remove without understanding why they exist):
   - Target's surname must appear in the final assembled text.
   - Context paragraphs must not reference more than one distinct order
     number (regex `№\S+`).
8. **Punctuation fix**: trailing `;` → `.`, mechanical, nothing else.
9. **Date + time metadata** (deterministic, no LLM — see "Time-of-day
   extraction" below): `extract_date_from_filename()` parses the day's date
   from the `.docx` filename (separator between DD/MM/YYYY varies by file —
   `_`, `.`, or `-`, all seen in real filenames); `assign_time_boundaries()`
   + `time_for_paragraph()` resolve which time governs the target
   paragraph, trying the exact inline format first and falling back to the
   left-column heuristic. `assemble_fragment()` returns a dict
   (`{"text", "date", "time", "time_confidence"}`), not a bare string.

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
  fragments into a single "з ... по ..." date range (this is how the real
  вityah samples look for continuous multi-day presence — see the two
  original sample files if still available: `Витяг_з_ЖБД_на_100к_ЛИПЕНЬ_Клименко.docx`,
  `Витяг_ЖБД_Бондаренко_07_2026.docx`).
- Batch driver: iterate a folder of daily `.docx` files over a requested
  date range, run the per-day pipeline, merge, and flag gaps (a requested
  date with no match — genuinely absent vs. a matching failure — must
  always be surfaced explicitly, never silently dropped).
- Final rendering into the actual вityah `.docx` template (header/table/
  signature block matching the original samples).
- Handling for 0-match or multi-match full-name narrowing (currently falls
  back to giving the LLM everything and trusting the order-number
  guardrail — works, but untested at scale).
- A real accuracy benchmark: ~15-20 hand-verified (person, day, expected
  pointer) cases, tracked as a pass-rate, to catch regressions when the
  prompt or model changes instead of discovering bugs one production run
  at a time (which is how all the bugs below were actually found).

## LLM configuration — non-obvious things that matter

- **Model**: `qwen3:8b-q8_0` via Ollama. Apache 2.0. Q8_0 chosen
  deliberately over the default Q4_K_M — for this workload (short JSON
  output, longer prompt) prefill/prompt-processing dominates, not decode,
  and Q4_K's dequant overhead can cancel out its memory-bandwidth
  advantage on this CPU. Measure before assuming "smaller quant = faster"
  here; it wasn't true in practice.
- **`"think": false` MUST be a top-level field in the Ollama API request
  body, not inside `"options"`.** Qwen3 is a hybrid thinking model and
  defaults to thinking mode; the `/no_think` text trick in the prompt is
  an unreliable legacy method. Getting this wrong silently multiplies
  latency several-fold — this was the single biggest speed bug found.
- `"keep_alive": "30m"` — avoid reloading the model between calls in a
  test/dev session.
- `num_thread: 8` — physical cores of the target dev machine (Ryzen 7
  7840HS, 8C/16T). SMT did not help in testing; re-verify if hardware changes.
- Structured output enforced via Ollama's `format` (JSON schema) parameter
  — required, not optional, or JSON breakage is common at scale.

## Target dev hardware

AMD Ryzen 7 7840HS, Radeon 780M (CPU-only inference so far — Vulkan
offload to the iGPU is a possible future speed lever, not yet explored),
32GB RAM. Batch/offline processing, not real-time — a few seconds per
query is acceptable.

## Bug log (empirically found — read before touching the prompt or schema)

Each of these was found by running real queries against the real sample
ЖБД file, not by inspection. If you change the prompt or schema, re-run
against these exact cases before considering it done.

1. **Model redacted the target's own name.** Given a person who was the
   *only* name in their selected range, the model still put the target's
   own line into `redactions` (confusing "who am I looking for" with "who
   do I remove"). Fixed by: explicit prompt rule + the surname-presence
   guardrail (step 6 above), which fails loudly instead of silently
   producing an empty fragment.
2. **Model tried to hold one giant contiguous range over a list of many
   people and enumerate everyone else for redaction — and got it wrong**
   (missed several names, referenced one paragraph outside its own chosen
   range, crashed the fail-closed check). Root cause: asking a model to
   correctly enumerate N-1 items in a list without missing any doesn't
   scale. Fixed by changing the schema itself from a single contiguous
   `fragment_paragraph_range` to non-contiguous
   `context_paragraph_indices` + single `target_paragraph_index` — the
   model no longer needs to track or exclude anyone, it just never selects
   their paragraph.
3. **Model merged context from two different, unrelated orders** (two
   namesakes, each governed by a different БР number) into one answer.
   This one is dangerous because it passes every text-fidelity check —
   every character was verbatim, the target's name was present — but the
   *content* was wrong (a person cited under the wrong legal order). Fixed
   two ways: (a) root cause — the full-name narrowing step (pipeline step
   3) now usually prevents the LLM from ever seeing two unrelated windows
   at once; (b) defense in depth — the order-number-conflict guardrail
   (step 6) catches it if narrowing didn't apply.
4. **Prompt bloat caused a 300s request timeout.** Adding few-shot
   examples to fix the above bugs grew the system prompt to ~6200 chars,
   which fights directly against the prefill-bound CPU bottleneck. Fixed
   by trimming redundant example text and relying on full-name narrowing
   to keep the typical candidate window small (~10 paragraphs) rather than
   trying to cover every case with more prompt text.

**Pattern across all four**: the fixes that actually held up were the ones
that removed the need for the model to get something right, not the ones
that just asked it more firmly. Prefer restructuring the schema/pipeline
over adding another prompt paragraph when a bug recurs.

## Known test data

Main sample file used throughout development: `ЖБД_02_04_2026.docx` (date
2026-04-02, from the filename; left-column time format). Two useful real
test people in it:
- `солдат ОРЛЕНКО Олександр Сергійович` — ПВ «БЕРЕГ», paragraph 38,
  governed by order №БР42/Б3/7Р/ДСК (paragraph 36). Time resolves to
  `00.00`, `confident`.
- `солдат ОРЛЕНКО Павло Юрійович` — general reserve list, paragraph 97,
  governed by order №БР47/Б3/7Р/ДСК (paragraph 89). Time also resolves to
  `00.00`, `confident` (its order's own intro paragraph didn't get a direct
  boundary snap, but it falls in the same still-00:00 period before the
  day's first real time change).

Two more real sample files, added to exercise the other time format and
the filename-separator variants (see `journals/`, gitignored):
- `ЖБД 10.07.2026.docx` (date 2026-07-10, `.` separator) — **inline time
  format**: empty left column, 84 order-intro paragraphs each carrying its
  own inline time. Good regression file for `extract_inline_time()`.
- `ЖБД_12-04-2026.docx` (date 2026-04-12, `-` separator) — left-column
  format again, larger/messier than the main sample (includes MGRS
  coordinates in some boundary paragraphs) — useful for stress-testing
  `is_boundary_paragraph()` beyond the main sample's cleaner structure.

Same surname, different order — this pair is the namesake/disambiguation
regression test. Keep using it when touching the narrowing logic.

## Style/conventions in the existing code

- Deterministic logic and LLM prompt live in one file
  (`test_vytyah_extraction.py`) for now — fine for continued exploration,
  should probably split into modules (parsing / prefilter / llm client /
  assembly+guardrails / docx rendering) once the batch driver is added.
- Code comments (and docstrings) are English, matching the LLM system
  prompt — the actual document text/data (ЖБД source content, test names,
  runtime console output) stays Ukrainian since it's being extracted
  verbatim, not translated.
- Every new failure mode found through testing should get: (1) a guardrail
  that fails loudly (never silently produces a degraded result), and (2)
  an entry in the bug log above with the real example that triggered it.
