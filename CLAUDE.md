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

The only three edits ever allowed:
1. Selecting *which* paragraphs to include (a person's mention doesn't have
   to be contiguous with its legal-basis order reference).
2. Removing *other people's* text when they share the exact same paragraph
   as the target person (never the target's own text).
3. One mechanical punctuation fix: a trailing `;` → `.` if it ends up as the
   very last character after assembly (because the source item wasn't last
   in its original list).

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
6. **Guardrails** (all added after observing real model failures — see bug
   log, do not remove without understanding why they exist):
   - Target's surname must appear in the final assembled text.
   - Context paragraphs must not reference more than one distinct order
     number (regex `№\S+`).
7. **Punctuation fix**: trailing `;` → `.`, mechanical, nothing else.

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

Sample file used throughout development: `ЖБД_02_04_2026.docx`. Two
useful real test people in it:
- `солдат ОРЛЕНКО Олександр Сергійович` — ПВ «БЕРЕГ», paragraph 38,
  governed by order №БР42/Б3/7Р/ДСК (paragraph 36).
- `солдат ОРЛЕНКО Павло Юрійович` — general reserve list, paragraph 97,
  governed by order №БР47/Б3/7Р/ДСК (paragraph 89).

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
