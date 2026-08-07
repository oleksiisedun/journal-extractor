# Combat Log Extract Generator — Project Context

## What this is

A pipeline that automatically generates official "витяг" (extract) documents
from combat log records for a specific
serviceman over a date range, sourced from per-day `.docx` files.

Source documents carry a restricted (internal-use) classification and
contain real personnel names, ranks, unit positions, and order numbers.
**This must stay fully local/offline — no cloud LLM calls, no telemetry.**

## The one rule everything else follows

**The output text must be 100% verbatim from the source combat log. Zero
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
   empty once its coordinates are removed, and the introducing phrase "за
   координатами" (by/at coordinates) when it's left dangling with nothing
   left to refer to. Coordinates are tactical data with no place in a
   personnel extract — this is a blanket rule, not conditional on context.
   See `strip_coordinates()`.
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

## Pipeline (as currently implemented — entry point `run_demo.py`)

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
   (see bug log below). Zero matches means the full name isn't verbatim
   anywhere that day even though the surname is — this fails closed
   (`found: false`, no LLM call) rather than handing the LLM weaker
   surname-only context to guess from. Two or more matches is genuine
   ambiguity (e.g. two identically-named people); `select_ambiguous_window()`
   picks the first or last occurrence in the file per
   `FULL_NAME_AMBIGUITY_STRATEGY` in `config.py`.
4. **Forced deterministic context** (deterministic, no LLM — `run_demo.py`,
   `find_preceding_order_paragraph()` + `find_immediate_label_header()` in
   `prefilter.py`): before the LLM call, walk backward from the full-name
   anchor paragraph for (a) the nearest preceding paragraph matching
   `ORDER_REF_PATTERN` — this can be dozens of paragraphs outside the ±8
   window, e.g. one order heading a long composition list of many
   call-sign groups — and (b) the immediately preceding paragraph if it
   looks like a position/call-sign label (contains `«»` guillemets or ends
   in `:`, never seen in a bare personnel line across any sample file).
   Both are merged into `context_paragraph_indices` after the LLM call
   regardless of what the LLM itself returned — found empirically that the
   LLM would still drop the label paragraph even when it was already
   visible in-window and a prompt rule asked for it explicitly (see bug
   log). This mirrors the project's established pattern: prefer moving a
   recurring failure out of the model's hands entirely over asking it more
   firmly in the prompt.
5. **LLM call** (Ollama, local): given the (usually single, ~10-paragraph)
   candidate window, returns the pointer JSON above. See "LLM config"
   below for the non-obvious settings this depends on.
6. **Deterministic assembly**: slice the indicated paragraphs, apply exact
   `str.replace()` for each redaction (raises `ValueError` — fail closed —
   if a redaction substring isn't found character-for-character).
7. **Coordinate / location-label stripping**: `strip_coordinates()` removes
   MGRS-style grid coordinates (e.g. `37U CR 1234 5678`), and
   `strip_location_labels()` removes the phrase "район зосередження" and
   its grammatical variants — both applied per-paragraph, after redactions
   (so redaction matching still runs against untouched source text) and
   before the fragment is joined. Both run unconditionally, always, not
   just when the content looks out of place.
8. **Guardrails** (all added after observing real model failures — see bug
   log, do not remove without understanding why they exist):
   - Target's surname must appear in the final assembled text.
   - Context paragraphs must not reference more than one distinct order
     number (regex `№\S+`).
9. **Punctuation fix**: trailing `;` → `.`, mechanical, nothing else.
10. **Date + time metadata** (deterministic, no LLM — see "Time-of-day
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
  extract samples look for continuous multi-day presence — see the two
  original sample files if still available: `Витяг_з_ЖБД_на_100к_ЛИПЕНЬ_Клименко.docx`,
  `Витяг_ЖБД_Бондаренко_07_2026.docx`).
- Batch driver: `run_demo.py` now iterates every `.docx` file found in
  `COMBAT_LOG_DIR` (`config.py`, default `journals/`), sorted chronologically
  by filename date, and runs the per-day pipeline independently for each —
  but it does not yet accept a requested date range, merge results across
  days, or flag gaps (a requested date with no matching file — genuinely
  absent vs. a matching failure — must always be surfaced explicitly, never
  silently dropped). Those three remain open work.
- Final rendering into the actual extract `.docx` template (header/table/
  signature block matching the original samples).
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
combat log file, not by inspection. If you change the prompt or schema, re-run
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
5. **Model redacted a neighboring paragraph it never selected.** Real case
   (see `local_test_data.py`, shape mirrors system-prompt Example 1): target
   on its own paragraph (e.g. ОРЛЕНКО at paragraph 38), immediately followed
   by a different, unselected person's paragraph (ПЕТРЕНКО at paragraph 39).
   `target_paragraph_index` and `context_paragraph_indices` were both
   correct, but `redactions` still contained the neighbor's text — even
   though paragraph 39 was in neither list, directly contradicting both the
   explicit prompt rule and Example 1's "no redaction needed" case.
   Reproduced deterministically (3/3 runs, temperature 0), and confirmed via
   A/B testing against both the real-name and fictional-name versions of the
   system prompt — identical failure either way, so this was not a
   prompt-wording regression. Fixed (tentatively) by shrinking the system
   prompt: dropped Example 4 (pure repetition of a rule already stated
   elsewhere, no new example data) and the duplicated NEVER/CRITICAL phrasing
   in the instructions, and trimmed the now-redundant `RESPONSE_SCHEMA`
   descriptions — 5073 → 3590 chars (-29%). Re-running the exact same real
   case afterward now returns the correct pointer with no hallucinated
   redaction. This is one manual rerun, not a regression suite — re-verify
   if this failure shape recurs, and treat the "real accuracy benchmark"
   item (see Not yet built) as the right way to confirm this holds at scale
   rather than trusting a single anecdotal pass. Defense in depth is still
   in place regardless: the fail-closed redaction-substring check in
   `assembly.py` would catch a recurrence (raises `ValueError`, no bad
   output emitted).
6. **Model picked a LATER, unrelated order paragraph as context because the
   TRUE governing order was outside the ±8 window entirely.** Real case
   (`ЖБД_12-04-2026.docx`, КРАВЧЕНКО Євгеній Геннадійович): the target sits
   at paragraph 108, inside a long composition list of ~15 call-sign groups
   (`ПВ «...»`, `СЗМ «...»`) all governed by one order header 43 paragraphs
   earlier (65, `№БН1/Б3/ДСК`). The ±8 window (100-109) never contained
   paragraph 65 — but it did contain paragraph 109, an unrelated order that
   actually starts the *next* section right after the target. The LLM had
   no way to pick correctly; it wasn't shown the right answer. This is not
   the same failure shape as item 3 (mixing two orders it *could* see) —
   here the correct paragraph was never in the candidate set at all, so no
   amount of prompt wording could have fixed it. A second, narrower gap
   surfaced once the window fix was in: paragraph 107 (`СЗМ «ФЛЕШ»`, the
   immediate call-sign sub-header right above the target) was already
   inside the original window, and the model *still* didn't select it as
   context — even after adding an explicit prompt rule about
   call-sign/position labels lacking trailing punctuation. Confirmed at
   temperature 0 across reruns: prompting alone did not change the output.
   Fixed both, deterministically, in `prefilter.py` —
   `find_preceding_order_paragraph()` and `find_immediate_label_header()`
   walk backward from the full-name anchor paragraph for (a) the nearest
   preceding `ORDER_REF_PATTERN` match regardless of distance, and (b) an
   immediately preceding line containing `«»` guillemets or ending in `:`
   (verified: never present in a bare personnel line across all three
   sample files) — both merged into `context_paragraph_indices` in
   `run_demo.py` after the LLM call, overriding whatever the LLM itself
   returned. See "Pipeline" step 4 above.
7. **`ORDER_REF_PATTERN` false-matched plain "№N" numbering as an order
   reference, breaking item 6's fix.** Real case (`ЖБД_12-04-2026.docx`,
   ХОМЕНКО Дмитро Юрійович): target at paragraph 125, inside "Група №2"
   (a numbered sub-group, not a call-sign), itself inside a list governed
   by an order at paragraph 112 — 13 paragraphs earlier, outside the ±8
   window, same shape as item 6. But `find_preceding_order_paragraph()`
   walked backward and immediately matched paragraph 124 ("Група №2 за
   координатами (...)") against the old `№\s?\S+` pattern, because "№2" on
   its own satisfies it — stopping the search one paragraph too early and
   never reaching the real order at 112. Every real order reference in all
   three sample files contains a `/` (e.g. `№БР59/Б3/РВП/ДСК`); plain "№N"
   numbering (group labels, the document's own header number) never does.
   Fixed by tightening `ORDER_REF_PATTERN` (`patterns.py`) to require a
   `/` in the matched token via a lookahead — this also fixes a latent
   false-positive risk in `assembly.py`'s multi-order guardrail, which
   used the same pattern. A second, narrower gap: paragraph 124 itself
   (the "Група №2" label) has neither of `find_immediate_label_header()`'s
   two signals (no `«»`, no trailing `:`), so it wasn't forced in either,
   and the LLM dropped it from context on its own — same shape as the
   `СЗМ «ФЛЕШ»` gap in item 6. Verified this "group label with neither
   signal" shape recurs across two different sample files (`Група №N`,
   lowercase `група N`, `Інженерно-саперна група №N`), so it's a real
   pattern, not a one-off. Fixed by adding a fallback signal to
   `find_immediate_label_header()`: a bare (non-quoted) run of 3+ uppercase
   Cyrillic letters is the shape every real surname has, so a preceding
   line WITHOUT one outside any `«»` quoting is safe to treat as a label
   rather than another person's own paragraph — worst case if this signal
   is ever too loose is a missed force-include (same as before this
   function existed), never a wrongly forced-in name.
8. **A stripped coordinate parenthetical left its introducing phrase
   dangling.** Same ХОМЕНКО case: `strip_coordinates()` correctly dropped
   `(37U CR 15093 59641)` and the now-empty parens, but left "Група №2 за
   координатами" — "за координатами" (by/at coordinates) is meaningless
   once the coordinates themselves are gone. Verified this exact phrase
   only ever appears immediately before a coordinate parenthetical (both
   occurrences in `ЖБД_12-04-2026.docx`), so stripping it unconditionally
   is safe — same rationale as the digits themselves (CLAUDE.md rule 4:
   tactical data with no place in a personnel extract). Fixed by adding
   `COORDINATE_LABEL_PATTERN` to `strip_coordinates()` (`assembly.py`),
   applied after the parenthetical cleanup, not as a separate rule.

**Pattern across items 1-8**: the fixes that actually held up were the ones
that removed the need for the model to get something right, not the ones
that just asked it more firmly. Prefer restructuring the schema/pipeline
over adding another prompt paragraph when a bug recurs.

## Known test data

Real person names, ranks, paragraph indices, and order numbers used for
local regression testing live in `local_test_data.py` (gitignored — never
commit this file; `run_demo.py` imports `TEST_CASES` from it when present
and falls back to fictional placeholder names otherwise). This keeps real
personnel data out of git while `journals/` (also gitignored) still holds
the source `.docx` files.

Main sample file used throughout development: `ЖБД_02_04_2026.docx` (date
2026-04-02, from the filename; left-column time format). It contains a
same-surname/different-order pair — two people sharing one surname, each
governed by a different order — which is the namesake/disambiguation
regression test; keep using it when touching the narrowing logic. See
`local_test_data.py` for the exact names/paragraph indices/order numbers.

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

- Code is split into small, single-purpose modules at the repo root (flat,
  no package directory — this project isn't distributed/packaged, so the
  extra nesting isn't worth it): `config.py` (settings), `patterns.py`
  (the one regex — `ORDER_REF_PATTERN` — shared between `assembly.py`,
  `time_extraction.py`, and `prefilter.py`; kept separate to avoid a
  circular import between `assembly.py` and `time_extraction.py`),
  `docx_parsing.py`, `prefilter.py`, `llm_client.py`
  (system prompt + schema + `ask_llm()`), `time_extraction.py`,
  `assembly.py`. `run_demo.py` is the entry point — it wires the modules
  together and prints results for a handful of hand-picked test people.
  It is intentionally *not* named `test_*.py`: it's a print-based demo, not
  a pytest suite, and that naming is reserved for the real accuracy
  benchmark still on the "not yet built" list. Docx-template rendering and
  the batch driver (also not yet built) should each get their own new
  module rather than growing an existing one.
- Code comments (and docstrings) are English, matching the LLM system
  prompt — the actual document text/data (combat log source content, test names,
  runtime console output) stays Ukrainian since it's being extracted
  verbatim, not translated.
- Every new failure mode found through testing should get: (1) a guardrail
  that fails loudly (never silently produces a degraded result), and (2)
  an entry in the bug log above with the real example that triggered it.
