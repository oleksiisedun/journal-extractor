# Bug log (empirically found — read before touching `prefilter.py`)

Each of these was found by running real queries against the real sample
combat log file, not by inspection. Items 1-5 were found back when this
pipeline used a local LLM to produce the pointer, before it was replaced
by pure deterministic logic (see "Core architectural principle" in
[CLAUDE.md](../CLAUDE.md)) — they're kept because they're *why* the schema
is shaped the way it is (non-contiguous `context_paragraph_indices` +
single `target_paragraph_index`, no `redactions`). Items 6-9 are about
`prefilter.py`'s finder functions directly and remain fully live
regression cases. Item 10 is about `assembly.py`'s `strip_coordinates()`
instead, item 11 about the multi-order guardrail in
`assembly.py`'s `assemble_fragment()`, and item 12 about `render.py`'s
`{дата}`/`{витяг}` column-alignment padding. If you touch `build_pointer()`
or its finder functions, the coordinate/label stripping, the multi-order
guardrail in `assembly.py`, or `render.py`'s date-padding logic, re-run
against these exact cases before considering it done.

1. **Model redacted the target's own name.** Given a person who was the
   *only* name in their selected range, the model still put the target's
   own line into `redactions` (confusing "who am I looking for" with "who
   do I remove"). Fixed by: explicit prompt rule + the surname-presence
   guardrail (pipeline step 7), which fails loudly instead of
   silently producing an empty fragment. The guardrail is what survived —
   redactions themselves are gone now (see "Core architectural principle").
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
   (pipeline step 7) catches it if narrowing didn't apply.
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
   redaction. This whole failure class is now moot: `redactions` was
   removed from the schema entirely once the project decided other
   people's text sharing the target's paragraph doesn't need to be
   redacted (see "Core architectural principle" above).
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
   `find_preceding_order_paragraph()` and `find_preceding_label_header()`
   walk backward from the full-name anchor paragraph for (a) the nearest
   preceding `ORDER_REF_PATTERN` match regardless of distance, and (b) an
   immediately preceding line containing `«»` guillemets or ending in `:`
   (verified: never present in a bare personnel line across all three
   sample files) — both merged into `context_paragraph_indices`, at the
   time in `run_demo.py` after the LLM call (overriding whatever the LLM
   itself returned), now directly inside `build_pointer()` since there's
   no LLM answer left to override. See "Pipeline" step 4 in
   [CLAUDE.md](../CLAUDE.md).
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
   (the "Група №2" label) has neither of `find_preceding_label_header()`'s
   two signals (no `«»`, no trailing `:`), so it wasn't forced in either,
   and the LLM dropped it from context on its own — same shape as the
   `СЗМ «ФЛЕШ»` gap in item 6. Verified this "group label with neither
   signal" shape recurs across two different sample files (`Група №N`,
   lowercase `група N`, `Інженерно-саперна група №N`), so it's a real
   pattern, not a one-off. Fixed by adding a fallback signal to
   `find_preceding_label_header()`: a bare (non-quoted) run of 3+ uppercase
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
9. **Label header separated from the target by another person's own
   paragraph.** Real case (`ЖБД_12-04-2026.docx`, ЧЕРЕДНІЧЕНКО Олександр
   Іванович): target at paragraph 168, but the governing label — "Пост
   повітряного прикриття № 2 (37U CR 15021 60370):" at paragraph 166 — is
   two paragraphs back, not one, because paragraph 167 is a DIFFERENT
   person (ОГУЛА) listed first under the same label. The original
   `find_immediate_label_header()` only ever checked the single
   immediately preceding paragraph, so it never found 166 at all — item 6
   and 7's fix worked when the target was the FIRST person under their
   label, not otherwise. Fixed by generalizing it into
   `find_preceding_label_header()`: it now walks backward from the target,
   skipping over any paragraph that looks like another person's own (has a
   bare surname-like token), down to `find_preceding_order_paragraph()`'s
   result as a lower bound — mirroring context_paragraph_indices' own
   documented semantics ("Not necessarily contiguous with the target --
   there can be a long run of other people's own paragraphs in between").
   The weaker no-surname fallback signal (item 6) is intentionally NOT
   extended across this walk — it only fires when directly adjacent to the
   target, to avoid guessing on some distant, ambiguous line; only the
   strong guillemet/colon signal is trusted across the skip.
10. **A trailing colon plus its now-dangling comma survived coordinate
    stripping and collided into stray punctuation.** Real case: `"...
    Харківської області, за координатами: (37U CR 1234 5678; 37U CR 1234
    5678; 37U CR 1234 5678; 37U CR 1234 5678)."` stripped down to `"...
    Харківської області,:."` instead of `"... Харківської області."`. Two
    compounding gaps: (a) `COORDINATE_LABEL_PATTERN` only matched `"за
    координат\w*"`, not the `":"` some real occurrences carry right after
    (item 8's fix case had no colon, so it was never exercised), leaving a
    bare `":"` behind once the phrase itself was removed; (b) the comma
    that used to separate the preceding clause from "за координатами" had
    nothing left to introduce once both the phrase and its parenthetical
    were gone, but nothing removed it — it collided with the trailing `"."`
    via the existing whitespace-before-punctuation collapse regex,
    producing `",:."` instead of a clean `"."`. Fixed by (a) extending
    `COORDINATE_LABEL_PATTERN` to swallow an optional trailing `:` plus
    whitespace, and (b) adding a rule to `strip_coordinates()` that drops a
    comma immediately preceding a now-adjacent `.`/`;` (`r",\s*([.;])"` ->
    `r"\1"`) — both still scoped to artifacts of coordinate stripping
    specifically (CLAUDE.md rule 3), not a general punctuation rule.

11. **Multi-order guardrail (item 3) false-positived on a legitimate joint
    legal basis.** Real case: a single order-reference paragraph reading
    "на виконання БОЙОВОГО НАКАЗУ ... №БН5/Б3/ДСК від 22.06.2026 та
    БОЙОВОГО РОЗПОРЯДЖЕННЯ ... №БР63/Б3/9Р/ДСК від 30.06.26, з метою..." —
    ONE paragraph citing two orders together as a single combined legal
    basis for the same action, which is real and correct, not a sign of
    two unrelated bases getting merged. The old guardrail counted distinct
    order *numbers* across all context paragraphs, so this single
    paragraph alone tripped `len(order_refs) > 1` and got rejected. Fixed
    by counting order-*bearing context paragraphs* instead of distinct
    order numbers (`assembly.py`, `assemble_fragment()`): still rejects
    the original item-3 shape (two different context paragraphs, each
    citing its own order — a real cross-order merge), but no longer trips
    when multiple order numbers appear together inside one paragraph.
    Consistent with `build_pointer()` only ever walking back to a single
    preceding order paragraph (see pipeline step 4 in CLAUDE.md) — more
    than one order-bearing *paragraph* in context is still the real signal
    of a wrongly-merged foreign order.

12. **A later entry's `{дата}` line rendered several lines below the
    matching `{витяг}` text it was supposed to line up with, drifting
    further with each earlier entry.** Real case
    (`output/Витяг_ТРОПІН_2026-08-08.docx`, ТРОПІН Юрій Анатолійович,
    three merged entries: 02.07.2026, 03.07-19.07.2026, 20.07-29.07.2026):
    the third entry's date ("з 20.07.2026 по 29.07.2026") rendered next to
    the *last* line of its own text block instead of the first. Root
    cause: `_format_date_lines()` pads the `{дата}` cell up to each
    entry's *measured visual line count* (`_entry_visual_line_count()`) by
    inserting one blank docx paragraph per line — but every paragraph in
    `templates/1.docx`, including a blank filler one, carries the
    template's `w:spacing w:after="160"` (8pt space-after,
    confirmed straight from the template's `Normal`-derived pPr, no
    `contextualSpacing` override). Word/LibreOffice only charges that 8pt
    once per real paragraph — a `{витяг}` paragraph that wraps to 13
    visual lines still pays space-after once, after its 13th line — but
    the old padding built 13 separate one-line filler paragraphs, each
    paying its own 8pt. Measured on the real file: entry 1 (3 real
    paragraphs, 12 visual lines) overpaid space-after by 9 extra
    instances (+72pt), entry 2 (3 real paragraphs, 15 visual lines) by 12
    more (+96pt) — 168pt (~5.9cm) of compounded drift by the time entry
    3's date line was placed, which is why it visibly sank to the bottom
    of its block. Fixed by having `_format_date_lines()` emit
    `(text, suppress_space_after)` pairs instead of bare strings: only as
    many filler paragraphs per entry as that entry's real `{витяг}`
    paragraph count (`len(_entry_fragment_lines(entry))`) keep normal
    space-after — the rest get it zeroed via the new `_zero_space_after()`
    helper in `_expand_multiline_placeholder()` — so the `{дата}` column's
    total charged space-after instances match the `{витяг}` column's
    exactly, regardless of how many lines a paragraph wraps to. Which
    specific filler paragraphs keep it doesn't matter for total block
    height (a fixed 8pt is charged once per kept paragraph regardless of
    its position in the block), only the count does.

**Pattern across items 1-12**: the fixes that actually held up were the ones
that removed the need for a model to get something right, not the ones
that just asked it more firmly — and that pattern is *why* an LLM ended up
fully removable: every one of its jobs eventually got moved into
deterministic code. Prefer restructuring the schema/pipeline over adding
prompting/heuristic guesswork when a bug recurs.
