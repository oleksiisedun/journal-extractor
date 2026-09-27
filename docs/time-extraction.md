# Time-of-day extraction

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
   writing but is no longer surfaced in the rendered `.docx` (see
   `CLAUDE.md`'s pipeline step 11) — it renders identically to a confident
   time.

`assign_time_boundaries()` is the dispatcher: it tries (a) first (via
`_assign_time_boundaries_inline()`) and only falls back to (b) if no
inline time tokens were found in that row's content paragraphs.

**Caveat**: only three real sample files have been checked
(`journals/ЖБД_02_04_2026.docx`, `ЖБД 10.07.2026.docx`,
`ЖБД_12-04-2026.docx`). The "column 0 = time, column 1 = content" layout,
the mutual-exclusivity-per-row assumption between formats (a) and (b), and
the boundary regexes above are derived from these — re-validate against
more files rather than assuming they generalize forever.
